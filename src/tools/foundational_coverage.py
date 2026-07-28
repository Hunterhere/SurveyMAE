"""Foundational coverage analysis tool for survey evaluation.

This tool implements G4 (foundational_coverage_rate) metric.

Cluster-Centric approach (v2):
  1. Extract cluster centers from co-citation clustering (computed by
     CitationGraphAnalyzer → graph_analysis.json). For each cluster, the
     paper with the highest PageRank is the "cluster center".
  2. For each cluster center, compute a citation_norm score:
       citation_norm = citation_count / CITATION_THRESHOLD
     where CITATION_THRESHOLD = 50 (fixed threshold, empirically chosen).
     A cluster center with citation_norm >= 1.0 is a "foundational center".
  3. G4 = fraction of clusters that have a foundational center.
  4. Topic relevance judgment is deferred to ExpertAgent.E1 scoring phase.
     The ExpertAgent LLM receives the cluster_centers list and judges whether
     each center is genuinely a foundational paper for the survey's domain.

Future enhancement:
  Use field- and year-normalized baselines instead of a fixed threshold:
    citation_norm = citation_count / (field_avg_citation_per_year × log₂(year_diff + 1))
  This requires a new LiteratureSearch.search_field_citation_baseline() method.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("surveymae.tools.foundational_coverage")

# Fixed citation threshold — a paper with >= 50 external citations is
# considered a candidate foundational paper for its sub-field.
CITATION_THRESHOLD = 50


def _convert_numpy_types(obj: Any) -> Any:
    """Recursively convert numpy types to Python native types for JSON serialization."""
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
    """Result of foundational coverage analysis (cluster-centric)."""

    coverage_rate: float
    cluster_centers: list[dict[str, Any]]
    matched_papers: list[dict[str, Any]]
    missing_key_papers: list[dict[str, Any]]
    suspicious_centrality: list[dict[str, Any]]
    llm_involved: bool
    hallucination_risk: str
    citation_threshold: int = CITATION_THRESHOLD


class FoundationalCoverageAnalyzer:
    """Analyze foundational paper coverage for surveys.

    Cluster-centric approach:
      - For each co-citation cluster, identify the center paper (highest PageRank).
      - Cross-reference its external citation count from ref_metadata_cache.
      - A center with citation_count >= citation_threshold is a "foundational center".
      - G4 = fraction of clusters that have at least one foundational center.
      - Topic relevance is deferred to ExpertAgent.E1 LLM scoring.
    """

    def __init__(
        self,
        citation_threshold: int = CITATION_THRESHOLD,
    ):
        """Initialize the analyzer.

        Args:
            citation_threshold: Minimum external citation count for a paper
                to be considered a foundational center. Default 50.
        """
        self.citation_threshold = citation_threshold

    async def analyze(
        self,
        *,
        cluster_evidence: list[dict[str, Any]],
        ref_metadata_cache: dict[str, dict],
        survey_references: list[dict[str, Any]],
    ) -> FoundationalCoverageResult:
        """Analyze foundational paper coverage using co-citation clusters.

        Args:
            cluster_evidence: Co-citation cluster evidence from graph analysis.
                Each cluster has: cluster_id, size, top_papers (list of
                {paper_id, score} sorted by PageRank descending).
            ref_metadata_cache: Metadata cache from CitationChecker.
                Maps reference key → {title, year, citation_count, ...}.
            survey_references: Survey's reference list.
                Each ref has: key, title, year.

        Returns:
            FoundationalCoverageResult with coverage rate and cluster-center data.
        """
        # Build a lookup for reference metadata: try ref_metadata_cache first,
        # fall back to survey_references for basic fields.
        ref_lookup: dict[str, dict] = {}

        for ref in survey_references:
            key = ref.get("key", "")
            if not key:
                continue
            ref_lookup[key] = {
                "title": ref.get("title", ""),
                "year": ref.get("year", ""),
                "citation_count": 0,
            }

        # Overlay verified metadata from CitationChecker
        for key, meta in ref_metadata_cache.items():
            if key in ref_lookup:
                ref_lookup[key].update({
                    "title": meta.get("title") or ref_lookup[key].get("title", ""),
                    "year": meta.get("year") or ref_lookup[key].get("year", ""),
                    "citation_count": meta.get("citation_count", 0) or 0,
                })

        # Step 1: Extract cluster centers and compute citation_norm
        cluster_centers: list[dict[str, Any]] = []
        for cluster in cluster_evidence:
            cluster_id = cluster.get("cluster_id", -1)
            cluster_size = cluster.get("size", 0)
            top_papers = cluster.get("top_papers", [])

            if not top_papers:
                # Cluster with no papers — shouldn't happen, but handle gracefully
                cluster_centers.append({
                    "cluster_id": cluster_id,
                    "cluster_size": cluster_size,
                    "center_paper_id": "",
                    "center_title": "(empty cluster)",
                    "center_year": "",
                    "citation_count": 0,
                    "citation_norm": 0.0,
                    "pagerank_score": 0.0,
                    "is_foundational_anchor": False,
                })
                continue

            # Center is the paper with highest PageRank in this cluster
            center = top_papers[0]
            paper_id = center.get("paper_id", "")
            pagerank_score = center.get("score", 0.0)

            meta = ref_lookup.get(paper_id, {})
            title = meta.get("title", paper_id)
            year = meta.get("year", "")
            citation_count = meta.get("citation_count", 0)
            if citation_count is None:
                citation_count = 0

            citation_norm = citation_count / self.citation_threshold if self.citation_threshold > 0 else 0.0
            is_anchor = citation_norm >= 1.0

            cluster_centers.append({
                "cluster_id": cluster_id,
                "cluster_size": cluster_size,
                "center_paper_id": paper_id,
                "center_title": title,
                "center_year": str(year) if year else "",
                "citation_count": citation_count,
                "citation_norm": round(citation_norm, 2),
                "pagerank_score": round(pagerank_score, 6),
                "is_foundational_anchor": is_anchor,
            })

        # Step 2: Classify into centers and non-centers
        centers = [c for c in cluster_centers if c["is_foundational_anchor"]]
        non_centers = [c for c in cluster_centers if not c["is_foundational_anchor"]]
        coverage_rate = len(centers) / len(cluster_centers) if cluster_centers else 0.0

        logger.info(
            "G4 cluster-centric: %d/%d clusters have foundational centers (rate=%.2f)",
            len(centers), len(cluster_centers), coverage_rate,
        )

        return FoundationalCoverageResult(
            coverage_rate=coverage_rate,
            cluster_centers=cluster_centers,
            matched_papers=centers,
            missing_key_papers=non_centers,
            suspicious_centrality=[],
            llm_involved=False,
            hallucination_risk="none",
            citation_threshold=self.citation_threshold,
        )


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
                description="Analyze foundational paper coverage (G4 metric, cluster-centric)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "cluster_evidence": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Co-citation cluster evidence from CitationGraphAnalyzer",
                        },
                        "ref_metadata_cache": {
                            "type": "object",
                            "description": "Metadata cache from CitationChecker (key → metadata)",
                        },
                        "survey_references": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Survey reference list with key, title, year",
                        },
                        "citation_threshold": {
                            "type": "integer",
                            "description": "Minimum citation count for foundational anchor",
                            "default": CITATION_THRESHOLD,
                        },
                    },
                    "required": ["cluster_evidence", "survey_references"],
                },
            )
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict):
        if name != "analyze_foundational_coverage":
            return [TextContent(type="text", text=f"Unknown tool: {name}", isError=True)]

        try:
            result = await analyzer.analyze(
                cluster_evidence=arguments["cluster_evidence"],
                ref_metadata_cache=arguments.get("ref_metadata_cache", {}),
                survey_references=arguments.get("survey_references", []),
            )
            output = {
                "coverage_rate": result.coverage_rate,
                "cluster_centers": result.cluster_centers,
                "matched_papers": result.matched_papers,
                "missing_key_papers": result.missing_key_papers,
                "suspicious_centrality": result.suspicious_centrality,
                "llm_involved": result.llm_involved,
                "hallucination_risk": result.hallucination_risk,
                "citation_threshold": result.citation_threshold,
            }
            return [TextContent(type="text", text=json.dumps(output, ensure_ascii=False))]
        except Exception as exc:
            return [TextContent(type="text", text=str(exc), isError=True)]

    return app
