"""Foundational coverage analysis tool for survey evaluation.

This tool implements G4 (foundational_coverage_rate) metric:
- Retrieve top-K highly-cited papers using topic keywords
- LLM-assisted filtering to remove irrelevant papers
- Match with survey's reference list
- Output coverage rate and missing key papers
"""

import json
import logging
from dataclasses import dataclass, asdict
from typing import Any, Optional

from src.tools.literature_search import LiteratureSearch

logger = logging.getLogger("surveymae.tools.foundational_coverage")


def _convert_numpy_types(obj: Any) -> Any:
    """Recursively convert numpy types to Python native types for JSON serialization.

    Args:
        obj: Any object that might contain numpy types

    Returns:
        Object with numpy types converted to Python native types
    """
    try:
        import numpy as np
    except ImportError:
        return obj

    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {key: _convert_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_convert_numpy_types(item) for item in obj]
    return obj


@dataclass
class FoundationalCoverageResult:
    """Result of foundational coverage analysis."""

    coverage_rate: float
    matched_papers: list[dict[str, Any]]
    missing_key_papers: list[dict[str, Any]]
    suspicious_centrality: list[dict[str, Any]]
    llm_involved: bool
    hallucination_risk: str


class FoundationalCoverageAnalyzer:
    """Analyze foundational paper coverage for surveys.

    This implements the G4 metric from Plan v2:
    - Retrieve candidate key papers via academic API search
    - Filter with LLM to remove irrelevant papers
    - Match with survey references
    - Identify suspicious centrality (high in-graph but low external citations)
    """

    def __init__(
        self,
        literature_search: Optional[LiteratureSearch] = None,
        top_k: int = 30,
        match_threshold: float = 0.85,
    ):
        """Initialize the analyzer.

        Args:
            literature_search: Literature search instance.
            top_k: Number of top-cited papers to retrieve per query.
            match_threshold: Title matching threshold (0-1).
        """
        self.literature_search = literature_search or LiteratureSearch()
        self.top_k = top_k
        self.match_threshold = match_threshold

    async def analyze(
        self,
        topic_keywords: list[str],
        survey_references: list[dict[str, Any]],
        ref_metadata_cache: dict[str, dict],
        llm_filter=None,
    ) -> FoundationalCoverageResult:
        """Analyze foundational paper coverage.

        Args:
            topic_keywords: Keywords extracted from survey.
            survey_references: Survey's reference list.
            ref_metadata_cache: Metadata cache from CitationChecker.
            llm_filter: Optional LLM for filtering irrelevant papers.

        Returns:
            FoundationalCoverageResult with coverage metrics.
        """
        # Step 1: Search for candidate key papers
        all_candidates = []
        for keyword in topic_keywords[:5]:  # Limit queries
            try:
                results = self.literature_search.search_by_keywords(
                    keywords=keyword,
                    max_results=self.top_k,
                    sort_by="citation_count",
                )
                all_candidates.extend(results)
            except Exception as e:
                logger.warning(f"Failed to search for keyword '{keyword}': {e}")
                continue

        # Deduplicate by title
        seen_titles = set()
        unique_candidates = []
        for r in all_candidates:
            title_lower = r.title.lower().strip()
            if title_lower not in seen_titles:
                seen_titles.add(title_lower)
                unique_candidates.append(r)

        # Step 2: LLM filtering (if provided)
        if llm_filter:
            filtered_candidates = await self._llm_filter(
                unique_candidates, topic_keywords, llm_filter
            )
        else:
            filtered_candidates = unique_candidates

        # Step 3: Match with survey references
        matched, missing = self._match_references(filtered_candidates, survey_references)

        # Step 4: Identify suspicious centrality
        suspicious = self._find_suspicious_centrality(matched, ref_metadata_cache)

        # Calculate coverage rate
        coverage_rate = len(matched) / len(filtered_candidates) if filtered_candidates else 0

        return FoundationalCoverageResult(
            coverage_rate=coverage_rate,
            matched_papers=matched,
            missing_key_papers=missing,
            suspicious_centrality=suspicious,
            llm_involved=llm_filter is not None,
            hallucination_risk="low" if llm_filter else "none",
        )

    async def _llm_filter(
        self,
        candidates: list,
        topic_keywords: list[str],
        llm,
    ) -> list:
        """Filter irrelevant papers using LLM."""
        from langchain_core.messages import HumanMessage

        filtered = []

        for candidate in candidates:
            prompt = f"""You are evaluating whether a candidate paper is relevant to a survey's topic.

Survey Topic Keywords: {", ".join(topic_keywords)}

Candidate Paper:
- Title: {candidate.title}
- Abstract: {candidate.abstract[:500] if candidate.abstract else "N/A"}
- Citation Count: {candidate.citation_count}

Is this paper relevant to the survey's topic? Answer only "yes" or "no"."""

            try:
                response = await llm.ainvoke([HumanMessage(content=prompt)])
                content = response.content if hasattr(response, "content") else str(response)
                content = content.strip().lower()

                if content.startswith("yes"):
                    filtered.append(candidate)
            except Exception as e:
                logger.warning(f"LLM filter failed for '{candidate.title}': {e}")
                # Include if filter fails
                filtered.append(candidate)

        return filtered

    def _match_references(
        self,
        candidates: list,
        survey_references: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Match candidates with survey references."""
        try:
            from rapidfuzz import fuzz
        except ImportError:
            # Fallback to simple matching
            fuzz = None

        matched = []
        unmatched_candidates = []

        # Build reference lookup
        ref_lookup: dict[str, dict] = {}
        for ref in survey_references:
            key = ref.get("key", "")
            title = ref.get("title", "").lower().strip()
            doi = ref.get("doi", "").lower().strip()
            if key:
                ref_lookup[key] = ref
            if title:
                ref_lookup[f"title:{title}"] = ref
            if doi:
                ref_lookup[f"doi:{doi}"] = ref

        for candidate in candidates:
            is_matched = False

            # Convert candidate to JSON-serializable dict to avoid numpy type issues
            paper_dict = _convert_numpy_types({
                "title": candidate.title,
                "year": candidate.year,
                "authors": candidate.authors,
                "doi": candidate.doi,
                "venue": getattr(candidate, "venue", None),
                "citation_count": candidate.citation_count,
            })

            # Check DOI first
            if candidate.doi:
                doi_key = f"doi:{candidate.doi.lower().strip()}"
                if doi_key in ref_lookup:
                    matched.append(
                        {
                            "paper": paper_dict,
                            "matched_ref": ref_lookup[doi_key],
                            "match_type": "doi",
                        }
                    )
                    is_matched = True

            # Check title
            if not is_matched and candidate.title:
                candidate_title = candidate.title.lower().strip()
                for ref_key, ref in ref_lookup.items():
                    if ref_key.startswith("title:"):
                        ref_title = ref_key[6:].lower().strip()
                        if fuzz:
                            score = fuzz.token_sort_ratio(candidate_title, ref_title)
                            if score >= self.match_threshold * 100:
                                matched.append(
                                    {
                                        "paper": paper_dict,
                                        "matched_ref": ref,
                                        "match_type": "title",
                                        "match_score": score / 100,
                                    }
                                )
                                is_matched = True
                                break
                        else:
                            # Simple substring match
                            if candidate_title in ref_title or ref_title in candidate_title:
                                matched.append(
                                    {
                                        "paper": paper_dict,
                                        "matched_ref": ref,
                                        "match_type": "title",
                                    }
                                )
                                is_matched = True
                                break

            if not is_matched:
                unmatched_candidates.append(candidate)

        # Missing = candidates that weren't matched
        missing = [
            _convert_numpy_types({
                "title": c.title,
                "year": c.year,
                "citation_count": c.citation_count,
                "venue": getattr(c, "venue", ""),
            })
            for c in unmatched_candidates
        ]

        return matched, missing

    def _find_suspicious_centrality(
        self,
        matched: list[dict[str, Any]],
        ref_metadata_cache: dict[str, dict],
    ) -> list[dict[str, Any]]:
        """Find papers with suspicious centrality.

        These are papers that have high centrality in the survey's citation graph
        but low external citation counts.
        """
        suspicious = []

        for match in matched:
            ref = match.get("matched_ref", {})
            ref_key = ref.get("key", "")

            # Get external citation count from metadata cache
            cache_entry = ref_metadata_cache.get(ref_key, {})
            external_citations = cache_entry.get("citation_count", 0)

            # If external citations are very low but paper is heavily cited in survey
            # (we don't have graph centrality here, so just flag low external citations)
            if external_citations is not None and external_citations < 10:
                # Handle both dict and object access for paper
                paper = match.get("paper", {})
                if isinstance(paper, dict):
                    title = paper.get("title", "")
                    year = paper.get("year", "")
                else:
                    title = getattr(paper, "title", "")
                    year = getattr(paper, "year", "")
                suspicious.append(
                    {
                        "title": title,
                        "year": year,
                        "external_citations": external_citations,
                        "reason": "Low external citations",
                    }
                )

        return suspicious


def create_foundational_coverage_mcp_server():
    """Create MCP server for foundational coverage analysis."""
    from mcp.server import Server
    from mcp.types import Tool, TextContent

    app = Server("foundational-coverage")
    analyzer = FoundationalCoverageAnalyzer()

    @app.list_tools()
    async def list_tools():
        return [
            Tool(
                name="analyze_foundational_coverage",
                description="Analyze foundational paper coverage (G4 metric)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "topic_keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Keywords extracted from survey",
                        },
                        "survey_references": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Survey reference list",
                        },
                        "ref_metadata_cache": {
                            "type": "object",
                            "description": "Metadata cache from CitationChecker",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of top-cited papers to retrieve",
                            "default": 30,
                        },
                    },
                    "required": ["topic_keywords", "survey_references"],
                },
            )
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict):
        if name != "analyze_foundational_coverage":
            return [TextContent(type="text", text=f"Unknown tool: {name}", isError=True)]

        try:
            result = await analyzer.analyze(
                topic_keywords=arguments["topic_keywords"],
                survey_references=arguments["survey_references"],
                ref_metadata_cache=arguments.get("ref_metadata_cache", {}),
            )
            output = {
                "coverage_rate": result.coverage_rate,
                "matched_papers": result.matched_papers,
                "missing_key_papers": result.missing_key_papers,
                "suspicious_centrality": result.suspicious_centrality,
                "llm_involved": result.llm_involved,
                "hallucination_risk": result.hallucination_risk,
            }
            return [TextContent(type="text", text=json.dumps(output, ensure_ascii=False))]
        except Exception as exc:
            return [TextContent(type="text", text=str(exc), isError=True)]

    return app
