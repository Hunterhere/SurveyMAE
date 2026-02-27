"""Citation analysis tool for PDF papers.

Provides basic statistics over extracted references, such as counts by year.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from src.tools.citation_checker import CitationChecker
from src.tools.result_store import ResultStore
from src.tools.pdf_parser import PDFParser

logger = logging.getLogger(__name__)


@dataclass
class YearCount:
    """Year/count entry."""

    year: str
    count: int


@dataclass
class YearBucket:
    """Year window bucket."""

    start_year: int
    end_year: int
    count: int


class CitationAnalyzer:
    """Analyze citations and references from papers."""

    def __init__(
        self,
        pdf_parser: Optional[PDFParser] = None,
        citation_checker: Optional[CitationChecker] = None,
        result_store: Optional[ResultStore] = None,
    ) -> None:
        self.pdf_parser = pdf_parser or PDFParser()
        self.citation_checker = citation_checker or CitationChecker()
        self.result_store = result_store

    def analyze_pdf(self, pdf_path: str) -> dict[str, Any]:
        """Analyze references in a PDF paper.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            A summary dictionary containing basic reference statistics.
        """
        references = self.citation_checker.extract_references_from_pdf(pdf_path)
        summary = self.analyze_references(references)

        if self.result_store:
            try:
                paper_id = self.result_store.register_paper(pdf_path)
                payload = {"paper_id": paper_id, "summary": summary}
                self.result_store.save_analysis(paper_id, payload)
                self.result_store.update_index(paper_id, status="analyzed", source_path=pdf_path)
            except Exception as exc:
                logger.warning("Failed to persist analysis result: %s", exc)

        return summary

    def analyze_references(self, references: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze a list of reference entries.

        Args:
            references: List of reference dictionaries.

        Returns:
            A summary dictionary containing basic reference statistics.
        """
        year_counts = self.count_by_year(references)
        numeric_years = [int(y.year) for y in year_counts if y.year.isdigit()]

        summary = {
            "total_references": len(references),
            "year_counts": [yc.__dict__ for yc in year_counts],
            "unique_years": sorted(set(numeric_years)),
            "earliest_year": min(numeric_years) if numeric_years else None,
            "latest_year": max(numeric_years) if numeric_years else None,
            "unknown_years": self._count_unknown_years(year_counts),
        }

        return summary

    def analyze_references_with_validation(
        self,
        references: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Analyze references using validation metadata to fill missing fields."""
        normalized = self._merge_validation_metadata(references)
        return self.analyze_references(normalized)

    def count_by_year(self, references: list[dict[str, Any]]) -> list[YearCount]:
        """Count references by year and sort by year ascending.

        Args:
            references: List of reference dictionaries.

        Returns:
            List of YearCount entries sorted by year.
        """
        counts: dict[str, int] = {}
        unknown_count = 0

        for ref in references:
            year = str(ref.get("year", "")).strip()
            if year and year.isdigit():
                counts[year] = counts.get(year, 0) + 1
            else:
                unknown_count += 1

        result: list[YearCount] = [
            YearCount(year=year, count=count)
            for year, count in sorted(counts.items(), key=lambda item: int(item[0]))
        ]

        if unknown_count:
            result.append(YearCount(year="unknown", count=unknown_count))

        return result

    def _merge_validation_metadata(
        self,
        references: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        for ref in references:
            ref_copy = dict(ref)
            validation = ref.get("validation") or {}
            metadata = validation.get("metadata") if isinstance(validation, dict) else None
            if isinstance(metadata, dict):
                if not ref_copy.get("title") and metadata.get("title"):
                    ref_copy["title"] = metadata.get("title")
                if not ref_copy.get("year") and metadata.get("year"):
                    ref_copy["year"] = str(metadata.get("year"))
                if not ref_copy.get("doi") and metadata.get("doi"):
                    ref_copy["doi"] = metadata.get("doi")
                if not ref_copy.get("arxiv_id") and metadata.get("arxiv_id"):
                    ref_copy["arxiv_id"] = metadata.get("arxiv_id")
                if not ref_copy.get("author") and metadata.get("authors"):
                    authors = metadata.get("authors")
                    if isinstance(authors, list):
                        ref_copy["author"] = " and ".join(a for a in authors if a)
                    elif isinstance(authors, str):
                        ref_copy["author"] = authors
            merged.append(ref_copy)
        return merged

    def _count_unknown_years(self, year_counts: list[YearCount]) -> int:
        for entry in year_counts:
            if entry.year == "unknown":
                return entry.count
        return 0

    def bucket_by_year_window(
        self,
        references: list[dict[str, Any]],
        window: int = 5,
    ) -> list[YearBucket]:
        """Group references into fixed-size year windows.

        Args:
            references: List of reference dictionaries.
            window: Window size (years).

        Returns:
            List of YearBucket entries sorted by start_year.
        """
        if window <= 0:
            raise ValueError("window must be positive")

        years = self._collect_numeric_years(references)
        if not years:
            return []

        min_year = min(years)
        max_year = max(years)
        bucket_count = ((max_year - min_year) // window) + 1

        counts = [0] * bucket_count
        for year in years:
            bucket_index = (year - min_year) // window
            counts[bucket_index] += 1

        buckets = []
        for index, count in enumerate(counts):
            start = min_year + index * window
            end = start + window - 1
            buckets.append(YearBucket(start_year=start, end_year=end, count=count))

        return buckets

    def year_over_year_trend(self, references: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute year-over-year trends for references.

        Returns:
            Dictionary with yearly counts, growth rates, and moving averages.
        """
        counts = self._count_years(references)
        years = sorted(counts.keys())

        yearly_counts = [{"year": year, "count": counts[year]} for year in years]

        growth = []
        prev_count: Optional[int] = None
        for year in years:
            count = counts[year]
            if prev_count is None:
                growth.append({"year": year, "delta": None, "pct": None})
            else:
                delta = count - prev_count
                pct = (delta / prev_count) * 100 if prev_count else None
                growth.append({"year": year, "delta": delta, "pct": pct})
            prev_count = count

        window = 3
        moving_average = []
        for idx, year in enumerate(years):
            if idx + 1 < window:
                moving_average.append({"year": year, "window": window, "value": None})
                continue
            window_years = years[idx + 1 - window : idx + 1]
            window_sum = sum(counts[y] for y in window_years)
            moving_average.append(
                {"year": year, "window": window, "value": window_sum / window}
            )

        return {
            "year_counts": yearly_counts,
            "growth": growth,
            "moving_average": moving_average,
        }

    def citation_age_distribution(
        self,
        references: list[dict[str, Any]],
        paper_year: int,
        bins: Optional[list[int]] = None,
    ) -> dict[str, int]:
        """Compute citation age distribution relative to a paper year.

        Args:
            references: List of reference dictionaries.
            paper_year: Year of the target paper.
            bins: Optional age bins in years (e.g., [0, 5, 10, 20]).

        Returns:
            Mapping from age-bin labels to counts.
        """
        if bins is None:
            bins = [0, 5, 10, 20]

        bins = sorted(set(bins))
        if bins[0] != 0:
            bins = [0] + bins

        counts: dict[str, int] = {}

        for ref in references:
            year_raw = str(ref.get("year", "")).strip()
            if not year_raw.isdigit():
                counts["unknown"] = counts.get("unknown", 0) + 1
                continue

            year = int(year_raw)
            age = paper_year - year
            if age < 0:
                counts["future"] = counts.get("future", 0) + 1
                continue

            label = self._age_bucket_label(age, bins)
            counts[label] = counts.get(label, 0) + 1

        return counts

    def concentration_top_years(
        self,
        references: list[dict[str, Any]],
        top_k: int = 3,
    ) -> dict[str, Any]:
        """Compute concentration over top-k years.

        Returns:
            Dictionary with top-year counts and concentration ratios.
        """
        if top_k <= 0:
            raise ValueError("top_k must be positive")

        counts = self._count_years(references)
        total = sum(counts.values())

        top_years = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:top_k]
        top_list = []
        top_sum = 0
        for year, count in top_years:
            top_sum += count
            share = (count / total) if total else 0.0
            top_list.append({"year": year, "count": count, "share": share})

        top_k_share = (top_sum / total) if total else 0.0

        return {
            "top_years": top_list,
            "top_k_share": top_k_share,
            "total_known_years": total,
            "unknown_years": self._count_unknown_years(self.count_by_year(references)),
        }

    def author_statistics(self, references: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute basic author statistics from references.

        Returns:
            Dictionary with author counts and summary stats.
        """
        raise NotImplementedError("TODO: implement author-level statistics")

    def annotate_high_impact(
        self,
        references: list[dict[str, Any]],
        citation_metrics: dict[str, Any],
        min_citations: int = 100,
    ) -> list[dict[str, Any]]:
        """Annotate references with high-impact flags.

        Args:
            references: List of reference dictionaries.
            citation_metrics: Mapping keyed by DOI/arXiv/title to metrics.
            min_citations: Threshold for high-impact labeling.

        Returns:
            Updated list of references with impact annotations.
        """
        raise NotImplementedError("TODO: implement high-impact annotation")

    def _collect_numeric_years(self, references: list[dict[str, Any]]) -> list[int]:
        years = []
        for ref in references:
            year = str(ref.get("year", "")).strip()
            if year.isdigit():
                years.append(int(year))
        return years

    def _count_years(self, references: list[dict[str, Any]]) -> dict[int, int]:
        counts: dict[int, int] = {}
        for year in self._collect_numeric_years(references):
            counts[year] = counts.get(year, 0) + 1
        return counts

    def _age_bucket_label(self, age: int, bins: list[int]) -> str:
        for idx in range(len(bins) - 1):
            start = bins[idx]
            end = bins[idx + 1]
            if start <= age < end:
                return f"{start}-{end - 1}"
        return f"{bins[-1]}+"


def create_citation_analysis_mcp_server():
    """Create an MCP server for citation analysis."""
    from mcp.server import Server
    from mcp.types import Tool, TextContent
    import json

    app = Server("citation-analysis")
    analyzer = CitationAnalyzer()

    @app.list_tools()
    async def list_tools():
        return [
            Tool(
                name="analyze_pdf_citations",
                description="Analyze references in a PDF paper",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pdf_path": {
                            "type": "string",
                            "description": "Path to the PDF file",
                        },
                    },
                    "required": ["pdf_path"],
                },
            ),
            Tool(
                name="analyze_references",
                description="Analyze a list of reference entries",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "references": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Reference list",
                        },
                    },
                    "required": ["references"],
                },
            ),
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
            if name == "analyze_pdf_citations":
                report = analyzer.analyze_pdf(arguments["pdf_path"])
                return [TextContent(type="text", text=json.dumps(report))]
            if name == "analyze_references":
                report = analyzer.analyze_references(arguments["references"])
                return [TextContent(type="text", text=json.dumps(report))]

            return [TextContent(type="text", text=f"Unknown tool: {name}", isError=True)]
        except Exception as exc:
            return [TextContent(type="text", text=str(exc), isError=True)]

    return app
