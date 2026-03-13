"""Citation analysis tool for PDF papers.

Provides basic statistics over extracted references, such as counts by year.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional
from datetime import datetime, timezone

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
        self.citation_checker = citation_checker or CitationChecker(result_store=result_store)
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

    def analyze_paragraph_distribution(
        self,
        citations: list[dict[str, Any]],
        references: list[dict[str, Any]],
        sections: Optional[list[dict[str, Any]]] = None,
        exclude_section_kinds: Optional[set[str]] = None,
        exclude_paragraph_section_kinds: Optional[set[str]] = None,
        max_examples_per_paragraph: int = 2,
        max_paragraphs: Optional[int] = None,
    ) -> dict[str, Any]:
        """Analyze citation distribution across paragraphs."""
        ref_by_key = {ref.get("key"): ref for ref in references if ref.get("key")}
        ref_by_number = {
            ref.get("reference_number"): ref for ref in references if ref.get("reference_number")
        }

        paragraph_map: dict[int, list[dict[str, Any]]] = {}
        for citation in citations:
            paragraph_index = citation.get("paragraph_index")
            if not paragraph_index:
                continue
            paragraph_map.setdefault(int(paragraph_index), []).append(citation)

        paragraph_indices = sorted(paragraph_map.keys())
        if max_paragraphs is not None:
            paragraph_indices = paragraph_indices[:max_paragraphs]

        paragraph_entries = []
        paragraph_ref_sets: dict[int, set[str]] = {}
        total_citations = 0
        total_linked = 0
        total_missing = 0
        unique_refs: set[str] = set()
        if exclude_section_kinds is None:
            exclude_section_kinds = {"title", "abstract"}
        if exclude_paragraph_section_kinds is None:
            exclude_paragraph_section_kinds = {"references"}

        section_kind_map: dict[tuple[Optional[int], str], str] = {}
        section_kind_by_index: dict[int, str] = {}
        section_root_map: dict[Optional[int], Optional[int]] = {}
        section_title_map: dict[Optional[int], str] = {}
        section_level_map: dict[Optional[int], int] = {}
        section_number_map: dict[int, str] = {}
        section_info: dict[int, dict[str, Any]] = {}
        section_stats: dict[int, dict[str, Any]] = {}
        # TODO: Paragraph table sometimes falls back to parent section titles when child
        # headings are not reliably detected or are duplicated. Improve heading detection
        # and section dedup/mapping so Section labels consistently show "number + subsection title".

        if sections:
            ordered_sections = sorted(
                sections,
                key=lambda sec: sec.get("section_index") or 0,
            )
            stack: list[tuple[int, Optional[int]]] = []
            counters: list[int] = []
            last_appendix_level: Optional[int] = None

            for sec in ordered_sections:
                sec_index = sec.get("section_index")
                if sec_index is None:
                    continue
                raw_title = sec.get("section_title") or "Unknown"
                level = sec.get("level") or 1
                try:
                    level = int(level)
                except (TypeError, ValueError):
                    level = 1
                if level < 1:
                    level = 1
                explicit_number, _ = self._split_section_prefix(raw_title)
                kind = sec.get("kind") or "main"
                if (
                    explicit_number
                    and re.match(r"^[A-Z]$", explicit_number)
                    and last_appendix_level is not None
                    and level <= last_appendix_level
                ):
                    level = last_appendix_level + 1
                if explicit_number and re.match(r"^\d+(?:\.\d+)*$", explicit_number):
                    counters = [int(p) for p in explicit_number.split(".")]
                    section_number_map[sec_index] = explicit_number
                elif explicit_number and re.match(r"^[A-Z]$", explicit_number):
                    section_number_map[sec_index] = explicit_number
                else:
                    if level > len(counters):
                        while len(counters) < level:
                            counters.append(1)
                    else:
                        counters = counters[:level]
                        counters[-1] += 1
                    section_number_map[sec_index] = ".".join(str(c) for c in counters)
                while stack and stack[-1][0] >= level:
                    stack.pop()
                parent_index = stack[-1][1] if stack else None
                section_root_map[sec_index] = parent_index
                section_title_map[sec_index] = raw_title
                section_level_map[sec_index] = level
                section_kind_by_index[sec_index] = kind
                section_info[sec_index] = {
                    "section_index": sec_index,
                    "section_number": section_number_map.get(sec_index),
                    "section_title": raw_title,
                    "level": level,
                    "kind": kind,
                }
                if kind == "appendix":
                    last_appendix_level = level
                stack.append((level, sec_index))

            def _find_root(index: Optional[int]) -> Optional[int]:
                current = index
                while current is not None and current in section_root_map:
                    parent = section_root_map[current]
                    if parent is None:
                        break
                    current = parent
                return current

            for sec in ordered_sections:
                sec_index = sec.get("section_index")
                if sec_index is None:
                    continue
                root_index = _find_root(sec_index) or sec_index
                root_title = section_title_map.get(
                    root_index, sec.get("section_title") or "Unknown"
                )
                root_kind = section_kind_by_index.get(root_index, "main")
                section_kind_map.setdefault((root_index, root_title), root_kind)

        def _infer_kind_from_title(title: Optional[str]) -> Optional[str]:
            if not title:
                return None
            lowered = str(title).lower()
            if "abstract" in lowered:
                return "abstract"
            if "introduction" in lowered:
                return "introduction"
            if "conclusion" in lowered:
                return "conclusion"
            if any(key in lowered for key in ("references", "bibliography")):
                return "references"
            if any(key in lowered for key in ("appendix", "appendices")):
                return "appendix"
            return None

        for paragraph_index in paragraph_indices:
            items = paragraph_map.get(paragraph_index, [])
            page_values = [c.get("page") for c in items if c.get("page")]
            line_values = [c.get("line_in_paragraph") for c in items if c.get("line_in_paragraph")]
            raw_section_title = next(
                (c.get("section_title") for c in items if c.get("section_title")),
                None,
            )
            raw_section_index = next(
                (c.get("section_index") for c in items if c.get("section_index")),
                None,
            )
            leaf_index = raw_section_index
            leaf_title = raw_section_title
            if leaf_index is not None and not leaf_title:
                leaf_title = section_title_map.get(leaf_index)
            root_index = leaf_index
            if leaf_index in section_root_map:
                root_index = leaf_index
                while section_root_map.get(root_index) is not None:
                    root_index = section_root_map[root_index]
            root_title = section_title_map.get(root_index, leaf_title or "Unknown")
            root_number = section_number_map.get(root_index)
            section_key = (root_index, root_title or "Unknown")
            section_kind = section_kind_map.get(section_key)
            if not section_kind:
                section_kind = section_kind_by_index.get(root_index)
            if not section_kind:
                section_kind = _infer_kind_from_title(root_title) or _infer_kind_from_title(
                    leaf_title
                )
            leaf_kind = (
                section_kind_by_index.get(leaf_index)
                or _infer_kind_from_title(leaf_title)
                or section_kind
            )
            leaf_number = section_number_map.get(leaf_index)
            leaf_level = section_level_map.get(leaf_index)

            ref_counts: dict[str, int] = {}
            valid_counts = 0
            invalid_counts = 0
            unknown_counts = 0
            ref_set: set[str] = set()
            paragraph_linked = 0
            paragraph_missing = 0

            for citation in items:
                if leaf_kind in exclude_section_kinds:
                    continue
                if leaf_kind in exclude_paragraph_section_kinds:
                    continue
                total_citations += 1
                ref_key = citation.get("ref_key")
                if not ref_key and citation.get("reference_number"):
                    ref = ref_by_number.get(citation.get("reference_number"))
                    ref_key = ref.get("key") if ref else None

                if ref_key:
                    ref_counts[ref_key] = ref_counts.get(ref_key, 0) + 1
                    ref_set.add(ref_key)
                    unique_refs.add(ref_key)
                    paragraph_linked += 1

                    ref = ref_by_key.get(ref_key) or ref_by_number.get(
                        citation.get("reference_number")
                    )
                    validation = ref.get("validation") if ref else None
                    if isinstance(validation, dict):
                        if validation.get("is_valid") is True:
                            valid_counts += 1
                        elif validation.get("is_valid") is False:
                            invalid_counts += 1
                        else:
                            unknown_counts += 1
                    else:
                        unknown_counts += 1
                else:
                    paragraph_missing += 1

            if leaf_kind in exclude_section_kinds:
                continue
            if leaf_kind in exclude_paragraph_section_kinds:
                continue

            paragraph_ref_sets[paragraph_index] = ref_set
            total_linked += paragraph_linked
            total_missing += paragraph_missing

            top_refs = sorted(ref_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
            ref_summary = []
            for key, count in top_refs:
                ref = ref_by_key.get(key) or {}
                validation = ref.get("validation") if isinstance(ref, dict) else None
                is_valid = validation.get("is_valid") if isinstance(validation, dict) else None
                ref_summary.append(
                    {
                        "key": key,
                        "count": count,
                        "title": ref.get("title", ""),
                        "year": ref.get("year", ""),
                        "is_valid": is_valid,
                    }
                )

            examples = []
            if max_examples_per_paragraph > 0:
                for citation in items:
                    if leaf_kind in exclude_section_kinds:
                        continue
                    examples.append(
                        {
                            "marker": citation.get("marker"),
                            "marker_raw": citation.get("marker_raw"),
                            "sentence": citation.get("sentence", ""),
                            "page": citation.get("page"),
                            "line_in_paragraph": citation.get("line_in_paragraph"),
                        }
                    )
                    if len(examples) >= max_examples_per_paragraph:
                        break

            citation_count = paragraph_linked + paragraph_missing

            paragraph_entries.append(
                {
                    "paragraph_index": paragraph_index,
                    "section_index": leaf_index,
                    "section_number": leaf_number,
                    "section_level": leaf_level,
                    "section_title": leaf_title or "Unknown",
                    "section_kind": leaf_kind,
                    "root_section_index": root_index,
                    "root_section_number": root_number,
                    "root_section_title": root_title,
                    "page_start": min(page_values) if page_values else None,
                    "page_end": max(page_values) if page_values else None,
                    "line_start": min(line_values) if line_values else None,
                    "line_end": max(line_values) if line_values else None,
                    "citation_count": citation_count,
                    "unique_references": len(ref_set),
                    "linked_citations": paragraph_linked,
                    "missing_reference_links": paragraph_missing,
                    "validation_counts": {
                        "valid": valid_counts,
                        "invalid": invalid_counts,
                        "unknown": unknown_counts,
                    },
                    "top_references": ref_summary,
                    "examples": examples,
                }
            )
            if leaf_index is not None:
                stats = section_stats.setdefault(
                    leaf_index,
                    {"paragraphs": set(), "citation_count": 0, "unique_refs": set()},
                )
                stats["paragraphs"].add(paragraph_index)
                stats["citation_count"] += citation_count
                stats["unique_refs"].update(ref_set)

        filtered_indices = sorted(paragraph_ref_sets.keys())
        adjacent_similarity = []
        for left, right in zip(filtered_indices, filtered_indices[1:]):
            left_set = paragraph_ref_sets.get(left, set())
            right_set = paragraph_ref_sets.get(right, set())
            union = left_set | right_set
            if not union:
                score = 0.0
            else:
                score = len(left_set & right_set) / len(union)
            adjacent_similarity.append(
                {
                    "left_paragraph": left,
                    "right_paragraph": right,
                    "jaccard": round(score, 4),
                    "shared_refs": len(left_set & right_set),
                    "left_unique": len(left_set),
                    "right_unique": len(right_set),
                }
            )

        dispersion = []
        per_ref_paragraphs: dict[str, set[int]] = {}
        per_ref_counts: dict[str, int] = {}
        for paragraph_index, items in paragraph_map.items():
            for citation in items:
                leaf_index = citation.get("section_index")
                leaf_title = citation.get("section_title")
                if leaf_index is not None and not leaf_title:
                    leaf_title = section_title_map.get(leaf_index)
                leaf_kind = section_kind_by_index.get(leaf_index) or _infer_kind_from_title(
                    leaf_title
                )
                if not leaf_kind:
                    root_index = leaf_index
                    if leaf_index in section_root_map:
                        root_index = leaf_index
                        while section_root_map.get(root_index) is not None:
                            root_index = section_root_map[root_index]
                    root_title = section_title_map.get(root_index, leaf_title or "Unknown")
                    leaf_kind = section_kind_by_index.get(root_index) or _infer_kind_from_title(
                        root_title
                    )
                if leaf_kind in exclude_section_kinds:
                    continue
                if leaf_kind in exclude_paragraph_section_kinds:
                    continue
                ref_key = citation.get("ref_key")
                if not ref_key and citation.get("reference_number"):
                    ref = ref_by_number.get(citation.get("reference_number"))
                    ref_key = ref.get("key") if ref else None
                if not ref_key:
                    continue
                per_ref_counts[ref_key] = per_ref_counts.get(ref_key, 0) + 1
                per_ref_paragraphs.setdefault(ref_key, set()).add(paragraph_index)

        total_paragraphs = len(filtered_indices)
        for key, para_set in per_ref_paragraphs.items():
            ref = ref_by_key.get(key) or {}
            validation = ref.get("validation") if isinstance(ref, dict) else None
            is_valid = validation.get("is_valid") if isinstance(validation, dict) else None
            paragraph_count = len(para_set)
            dispersion.append(
                {
                    "key": key,
                    "title": ref.get("title", ""),
                    "year": ref.get("year", ""),
                    "paragraph_count": paragraph_count,
                    "total_citations": per_ref_counts.get(key, 0),
                    "dispersion": round(
                        (paragraph_count / total_paragraphs) if total_paragraphs else 0.0,
                        4,
                    ),
                    "is_valid": is_valid,
                }
            )

        dispersion.sort(key=lambda item: (-item["paragraph_count"], item["key"]))

        section_agg: dict[int, dict[str, Any]] = {}
        for sec_index in section_info:
            stats = section_stats.get(
                sec_index,
                {"paragraphs": set(), "citation_count": 0, "unique_refs": set()},
            )
            section_agg[sec_index] = {
                "paragraphs": set(stats["paragraphs"]),
                "citation_count": stats["citation_count"],
                "unique_refs": set(stats["unique_refs"]),
            }

        ordered_by_level = sorted(
            section_info.values(),
            key=lambda item: (item.get("level") or 1, item.get("section_index") or 0),
            reverse=True,
        )
        for entry in ordered_by_level:
            sec_index = entry["section_index"]
            parent_index = section_root_map.get(sec_index)
            if parent_index is None:
                continue
            parent_stats = section_agg.setdefault(
                parent_index,
                {"paragraphs": set(), "citation_count": 0, "unique_refs": set()},
            )
            child_stats = section_agg.get(
                sec_index, {"paragraphs": set(), "citation_count": 0, "unique_refs": set()}
            )
            parent_stats["paragraphs"].update(child_stats["paragraphs"])
            parent_stats["citation_count"] += child_stats["citation_count"]
            parent_stats["unique_refs"].update(child_stats["unique_refs"])

        section_entries = []
        ordered_sections = sorted(
            section_info.values(),
            key=lambda item: (item.get("section_index") or 0),
        )
        for entry in ordered_sections:
            if entry.get("kind") in exclude_section_kinds:
                continue
            stats = section_agg.get(
                entry["section_index"],
                {"paragraphs": set(), "citation_count": 0, "unique_refs": set()},
            )
            section_entries.append(
                {
                    "section_index": entry["section_index"],
                    "section_number": entry.get("section_number"),
                    "section_title": entry.get("section_title"),
                    "paragraph_count": len(stats["paragraphs"]),
                    "citation_count": stats["citation_count"],
                    "unique_references": len(stats["unique_refs"]),
                    "paragraph_indices": sorted(stats["paragraphs"]),
                    "level": entry.get("level"),
                    "kind": entry.get("kind"),
                }
            )

        filtered_paragraphs = [p for p in paragraph_entries if p.get("citation_count")]

        sections_with_citations = len(
            [entry for entry in section_entries if entry.get("citation_count", 0) > 0]
        )

        summary = {
            "total_citations": total_citations,
            "paragraphs_with_citations": len(filtered_paragraphs),
            "unique_references": len(unique_refs),
            "linked_citations": total_linked,
            "missing_reference_links": total_missing,
            "avg_citations_per_paragraph": round(
                (total_citations / len(filtered_paragraphs)) if filtered_paragraphs else 0.0, 2
            ),
            "avg_adjacent_similarity": round(
                sum(edge["jaccard"] for edge in adjacent_similarity) / len(adjacent_similarity)
                if adjacent_similarity
                else 0.0,
                4,
            ),
            "sections_with_citations": sections_with_citations,
            "avg_citations_per_section": round(
                (total_citations / len(section_entries)) if section_entries else 0.0, 2
            ),
        }

        result = {
            "format_version": "paragraph_distribution_v1",
            "generated_at": datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            "summary": summary,
            "excluded_section_kinds": sorted(exclude_section_kinds),
            "excluded_paragraph_section_kinds": sorted(exclude_paragraph_section_kinds),
            "paragraphs": paragraph_entries,
            "sections": section_entries,
            "reference_dispersion": dispersion,
            "adjacent_similarity": adjacent_similarity,
        }

        result["render"] = {
            "markdown": self._render_paragraph_distribution_markdown(result),
            "text": self._render_paragraph_distribution_text(result),
        }

        return result

    async def analyze_pdf_paragraph_distribution(
        self,
        pdf_path: str,
        verify_references: bool = True,
        sources: Optional[list[str]] = None,
        verify_limit: Optional[int] = None,
    ) -> dict[str, Any]:
        extraction = await self.citation_checker.extract_citations_with_context_from_pdf_async(
            pdf_path,
            verify_references=verify_references,
            sources=sources,
            verify_limit=verify_limit,
        )
        result = self.analyze_paragraph_distribution(
            extraction.get("citations", []),
            extraction.get("references", []),
            sections=extraction.get("sections"),
        )
        if self.result_store:
            try:
                paper_id = self.result_store.register_paper(pdf_path)
                payload = {
                    "paper_id": paper_id,
                    "analysis_type": "paragraph_distribution",
                    "summary": result["summary"],
                    "render": result.get("render"),
                    "paragraph_distribution": result,
                }
                self.result_store.save_analysis(paper_id, payload)
                self.result_store.update_index(paper_id, status="analyzed", source_path=pdf_path)
            except Exception as exc:
                logger.warning("Failed to persist paragraph analysis: %s", exc)

        return result

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

    def compute_temporal_metrics(
        self,
        references: list[dict[str, Any]],
        field_trend_baseline: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Compute T-series temporal metrics (T1-T5).

        This method computes:
        - T1: year_span
        - T2: foundational_retrieval_gap (requires field_trend_baseline)
        - T3: peak_year_ratio
        - T4: temporal_continuity
        - T5: trend_alignment (requires field_trend_baseline)

        Args:
            references: List of reference dictionaries.
            field_trend_baseline: Field trend baseline from LiteratureSearch.

        Returns:
            Dict with T1-T5 metrics.
        """
        # Extract years
        numeric_years: list[int] = []
        for ref in references:
            year = ref.get("year")
            if year:
                try:
                    numeric_years.append(int(year))
                except (ValueError, TypeError):
                    continue

        if not numeric_years:
            return {
                "T1_year_span": None,
                "T2_foundational_retrieval_gap": None,
                "T3_peak_year_ratio": None,
                "T4_temporal_continuity": None,
                "T5_trend_alignment": None,
                "status": "no_valid_years",
            }

        # T1: year_span
        min_year = min(numeric_years)
        max_year = max(numeric_years)
        year_span = max_year - min_year

        # T2: foundational_retrieval_gap
        foundational_gap = None
        if field_trend_baseline:
            baseline_years = field_trend_baseline.get("yearly_counts", {})
            # Find earliest year with significant publications
            significant_years = [
                int(y)
                for y, c in baseline_years.items()
                if c and isinstance(c, (int, float)) and c > 0
            ]
            if significant_years:
                earliest_foundation_year = min(significant_years)
                foundational_gap = min_year - earliest_foundation_year

        # T3: peak_year_ratio (ratio of citations in last 3 years)
        import datetime as _dt

        current_year = _dt.datetime.now().year
        recent_years = [y for y in numeric_years if y >= current_year - 2]
        peak_year_ratio = len(recent_years) / len(numeric_years) if numeric_years else 0

        # T4: temporal_continuity (longest gap in years with no citations)
        unique_years = sorted(set(numeric_years))
        max_gap = 0
        for i in range(len(unique_years) - 1):
            gap = unique_years[i + 1] - unique_years[i]
            if gap > max_gap:
                max_gap = gap

        # T5: trend_alignment (Pearson correlation)
        trend_alignment = None
        if field_trend_baseline:
            baseline_counts = field_trend_baseline.get("yearly_counts", {})
            # Build aligned year-count pairs
            survey_counts: dict[int, int] = {}
            for y in numeric_years:
                survey_counts[y] = survey_counts.get(y, 0) + 1

            # Find overlapping years
            common_years = []
            survey_values = []
            baseline_values = []

            for year_str, baseline_count in baseline_counts.items():
                if year_str.isdigit():
                    year = int(year_str)
                    if year in survey_counts and baseline_count:
                        common_years.append(year)
                        survey_values.append(survey_counts[year])
                        baseline_values.append(baseline_count)

            if len(common_years) >= 3:
                try:
                    from scipy.stats import pearsonr

                    correlation, _ = pearsonr(survey_values, baseline_values)
                    trend_alignment = correlation
                except ImportError:
                    # Fallback: simple correlation calculation
                    trend_alignment = self._simple_correlation(survey_values, baseline_values)

        # Build year distribution for report
        year_distribution = {}
        for year in numeric_years:
            year_distribution[year] = year_distribution.get(year, 0) + 1

        return {
            "T1_year_span": year_span,
            "T2_foundational_retrieval_gap": foundational_gap,
            "T3_peak_year_ratio": round(peak_year_ratio, 3),
            "T4_temporal_continuity": max_gap,
            "T5_trend_alignment": round(trend_alignment, 3)
            if trend_alignment is not None
            else None,
            "year_distribution": year_distribution,
            "earliest_year": min_year,
            "latest_year": max_year,
            "status": "success" if numeric_years else "no_data",
        }

    def _simple_correlation(self, x: list[float], y: list[float]) -> float:
        """Calculate simple Pearson correlation without scipy."""
        if len(x) != len(y) or len(x) < 2:
            return 0.0

        n = len(x)
        mean_x = sum(x) / n
        mean_y = sum(y) / n

        numerator = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
        denominator_x = sum((x[i] - mean_x) ** 2 for i in range(n))
        denominator_y = sum((y[i] - mean_y) ** 2 for i in range(n))

        denominator = (denominator_x * denominator_y) ** 0.5
        if denominator == 0:
            return 0.0

        return numerator / denominator

    def compute_structural_metrics(
        self,
        section_ref_counts: dict[str, dict[str, int]],
        total_paragraphs: int = 0,
    ) -> dict[str, Any]:
        """Compute S-series structural metrics (S1-S5).

        This method computes:
        - S1: section_count
        - S2: citation_density
        - S3: citation_gini
        - S4: zero_citation_section_rate

        Args:
            section_ref_counts: Dict mapping section titles to {ref_key: count}.
            total_paragraphs: Total number of paragraphs (for density calculation).

        Returns:
            Dict with S1-S4 metrics.
        """
        # S1: section_count
        section_count = len(section_ref_counts)

        # S2: citation_density
        total_citations = sum(
            sum(ref_counts.values()) for ref_counts in section_ref_counts.values()
        )
        citation_density = total_citations / total_paragraphs if total_paragraphs > 0 else 0

        # S3: citation_gini
        citation_counts = [sum(ref_counts.values()) for ref_counts in section_ref_counts.values()]
        gini = self._compute_gini(citation_counts)

        # S4: zero_citation_section_rate
        zero_citation_sections = sum(1 for count in citation_counts if count == 0)
        zero_citation_rate = zero_citation_sections / section_count if section_count > 0 else 0

        return {
            "S1_section_count": section_count,
            "S2_citation_density": round(citation_density, 3),
            "S3_citation_gini": round(gini, 3),
            "S4_zero_citation_section_rate": round(zero_citation_rate, 3),
            "total_citations": total_citations,
            "total_paragraphs": total_paragraphs,
        }

    def _compute_gini(self, values: list[float]) -> float:
        """Compute Gini coefficient for a list of values."""
        if not values:
            return 0.0

        # Remove zeros and sort
        values = sorted([v for v in values if v > 0])
        if not values:
            return 0.0

        n = len(values)
        cumsum = 0
        for i, v in enumerate(values):
            cumsum += (i + 1) * v

        total = sum(values)
        if total == 0:
            return 0.0

        gini = (2 * cumsum) / (n * total) - (n + 1) / n
        return max(0.0, min(1.0, gini))

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

    def _render_paragraph_distribution_markdown(self, data: dict[str, Any]) -> str:
        summary = data.get("summary", {})
        paragraphs = data.get("paragraphs", [])
        sections = data.get("sections", [])
        ordered_paragraphs = sorted(paragraphs, key=lambda item: (item.get("paragraph_index") or 0))

        lines = [
            "### Paragraph Citation Distribution",
            f"- Total citations: {summary.get('total_citations')}",
            f"- Paragraphs with citations: {summary.get('paragraphs_with_citations')}",
            f"- Unique references: {summary.get('unique_references')}",
            f"- Avg citations/paragraph: {summary.get('avg_citations_per_paragraph')}",
            f"- Avg adjacent similarity: {summary.get('avg_adjacent_similarity')}",
            f"- Sections with citations: {summary.get('sections_with_citations')}",
            f"- Avg citations/section: {summary.get('avg_citations_per_section')}",
            "",
            "#### Sections",
            "| Section | Paragraphs | Citations | Unique Refs |",
            "|---|---|---|---|",
        ]

        for item in sections:
            section_label = self._format_section_label(
                item.get("section_title"),
                item.get("section_number"),
                item.get("level"),
                for_markdown=True,
            )
            lines.append(
                f"| {section_label} | {item.get('paragraph_count')} | "
                f"{item.get('citation_count')} | {item.get('unique_references')} |"
            )

        lines += [
            "",
            "| Paragraph | Section | Page Range | Citations | Unique Refs | Top Refs |",
            "|---|---|---|---|---|---|",
        ]

        for item in ordered_paragraphs:
            page_range = "-"
            if item.get("page_start") is not None:
                if item.get("page_end") and item.get("page_end") != item.get("page_start"):
                    page_range = f"{item.get('page_start')}-{item.get('page_end')}"
                else:
                    page_range = str(item.get("page_start"))
            top_refs = ", ".join(
                f"{ref.get('key')}({ref.get('count')})" for ref in item.get("top_references", [])
            )
            section_label = self._format_section_label(
                item.get("section_title"),
                item.get("section_number"),
                item.get("section_level"),
                for_markdown=True,
            )
            lines.append(
                f"| {item.get('paragraph_index')} | {section_label} | {page_range} | "
                f"{item.get('citation_count')} | {item.get('unique_references')} | {top_refs} |"
            )

        return "\n".join(lines)

    def _render_paragraph_distribution_text(self, data: dict[str, Any]) -> str:
        summary = data.get("summary", {})
        paragraphs = data.get("paragraphs", [])
        sections = data.get("sections", [])
        ordered_paragraphs = sorted(paragraphs, key=lambda item: (item.get("paragraph_index") or 0))

        lines = [
            "Paragraph Citation Distribution",
            f"Total citations: {summary.get('total_citations')}",
            f"Paragraphs with citations: {summary.get('paragraphs_with_citations')}",
            f"Unique references: {summary.get('unique_references')}",
            f"Avg citations/paragraph: {summary.get('avg_citations_per_paragraph')}",
            f"Avg adjacent similarity: {summary.get('avg_adjacent_similarity')}",
            f"Sections with citations: {summary.get('sections_with_citations')}",
            f"Avg citations/section: {summary.get('avg_citations_per_section')}",
            "",
            "Sections:",
        ]

        for item in sections:
            section_label = self._format_section_label(
                item.get("section_title"),
                item.get("section_number"),
                item.get("level"),
                for_markdown=False,
            )
            lines.append(
                f"- {section_label}: paragraphs={item.get('paragraph_count')} "
                f"citations={item.get('citation_count')} unique_refs={item.get('unique_references')}"
            )

        lines.append("")

        for item in ordered_paragraphs:
            page_range = "-"
            if item.get("page_start") is not None:
                if item.get("page_end") and item.get("page_end") != item.get("page_start"):
                    page_range = f"{item.get('page_start')}-{item.get('page_end')}"
                else:
                    page_range = str(item.get("page_start"))
            top_refs = ", ".join(
                f"{ref.get('key')}({ref.get('count')})" for ref in item.get("top_references", [])
            )
            section_label = self._format_section_label(
                item.get("section_title"),
                item.get("section_number"),
                item.get("section_level"),
                for_markdown=False,
            )
            lines.append(
                f"[P{item.get('paragraph_index')}] section={section_label} pages={page_range} "
                f"citations={item.get('citation_count')} "
                f"unique_refs={item.get('unique_references')} "
                f"top_refs={top_refs}"
            )

        return "\n".join(lines)

    def _normalize_section_label(self, label: Optional[str]) -> str:
        if not label:
            return "Unknown"
        return " ".join(str(label).split())

    def _split_section_prefix(self, title: Optional[str]) -> tuple[Optional[str], str]:
        if not title:
            return None, "Unknown"
        text = self._normalize_section_label(title)
        match = re.match(r"^(\d+(?:\.\d+)*)\s+(.+)$", text)
        if match:
            return match.group(1), match.group(2)
        match = re.match(r"^([A-Z])\s+(.+)$", text)
        if match:
            return match.group(1), match.group(2)
        return None, text

    def _format_section_label(
        self,
        title: Optional[str],
        number: Optional[str],
        level: Optional[int],
        *,
        for_markdown: bool,
    ) -> str:
        label = self._normalize_section_label(title)
        prefix, remainder = self._split_section_prefix(label)
        if number and prefix == number and remainder:
            label = remainder
        if number:
            label = f"{number} {label}"
        return label

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
            moving_average.append({"year": year, "window": window, "value": window_sum / window})

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
            Tool(
                name="analyze_paragraph_distribution",
                description="Analyze citation distribution across paragraphs",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "citations": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Citations with paragraph indices",
                        },
                        "references": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Reference entries with metadata/validation",
                        },
                        "sections": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Section headings extracted from the PDF",
                        },
                        "max_examples_per_paragraph": {
                            "type": "integer",
                            "description": "Max example sentences per paragraph",
                        },
                    },
                    "required": ["citations", "references"],
                },
            ),
            Tool(
                name="analyze_pdf_paragraph_distribution",
                description="Extract, validate, and analyze citation distribution for a PDF",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pdf_path": {
                            "type": "string",
                            "description": "Path to the PDF file",
                        },
                        "verify_references": {
                            "type": "boolean",
                            "description": "Verify references via external sources",
                        },
                        "verify_sources": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Ordered list of sources to query",
                        },
                        "verify_limit": {
                            "type": "integer",
                            "description": "Max number of references to verify",
                        },
                    },
                    "required": ["pdf_path"],
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

            if name == "analyze_paragraph_distribution":
                report = analyzer.analyze_paragraph_distribution(
                    arguments["citations"],
                    arguments["references"],
                    sections=arguments.get("sections"),
                    max_examples_per_paragraph=arguments.get("max_examples_per_paragraph", 2),
                )
                return [TextContent(type="text", text=json.dumps(report))]

            if name == "analyze_pdf_paragraph_distribution":
                report = await analyzer.analyze_pdf_paragraph_distribution(
                    arguments["pdf_path"],
                    verify_references=arguments.get("verify_references", True),
                    sources=arguments.get("verify_sources"),
                    verify_limit=arguments.get("verify_limit"),
                )
                return [TextContent(type="text", text=json.dumps(report))]

            return [TextContent(type="text", text=f"Unknown tool: {name}", isError=True)]
        except Exception as exc:
            return [TextContent(type="text", text=str(exc), isError=True)]

    return app
