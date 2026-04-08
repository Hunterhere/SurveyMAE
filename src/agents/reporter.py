"""Report Generation Agent (ReportAgent).

This agent generates the final evaluation report with variance-aware display.

According to Plan v3:
- Aggregator: Pure mathematical aggregation (in src/graph/nodes/aggregator.py)
- Reporter: Report generation with variance display (this file)
- Also generates run_summary.json for batch experiment comparison

The reporter:
- Calls aggregate_scores to compute weighted scores
- Generates markdown with variance visualization
- Generates run_summary.json
"""

import logging
from datetime import UTC, datetime
from typing import Any

from src.agents.base import BaseAgent
from src.core.config import AgentConfig
from src.core.mcp_client import MCPManager
from src.core.state import EvaluationRecord, SurveyState
from src.graph.builder import _get_result_store
from src.graph.nodes.aggregator import aggregate_scores, generate_report

logger = logging.getLogger(__name__)


class ReportAgent(BaseAgent):
    """Agent responsible for final report generation.

    This agent:
    - Calls aggregate_scores for mathematical aggregation
    - Generates markdown report with variance-aware display
    - Generates run_summary.json
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        mcp: MCPManager | None = None,
    ) -> None:
        super().__init__(
            name="reporter",
            config=config or AgentConfig(name="reporter"),
            mcp=mcp,
        )

    async def evaluate(
        self,
        state: SurveyState,
        section_name: str | None = None,
    ) -> EvaluationRecord:
        """Return a placeholder evaluation record.

        Report generation uses :meth:`process` directly to emit the final report.
        """
        return EvaluationRecord(
            agent_name=self.name,
            dimension="report_generation",
            score=10.0,
            reasoning="Final report is generated in reporter.process.",
            evidence=None,
            confidence=1.0,
        )

    async def process(  # FIXME: add LLM judgement for more datails
        self,
        state: SurveyState,
    ) -> dict[str, Any]:
        """Generate final report from accumulated evaluations.

        This method:
        1. Calls aggregate_scores for mathematical aggregation
        2. Generates markdown report with variance display
        3. Generates run_summary.json
        4. Returns final state with report and scores
        """
        # Step 1: Aggregate scores (pure calculation)
        aggregation_result = await aggregate_scores(state)

        # Step 2: Generate markdown report with variance display
        final_report = generate_report(aggregation_result, state)

        # Step 3: Generate run_summary.json (v3)
        run_summary = self._generate_run_summary(state, aggregation_result)

        # Save run_summary.json to papers/{paper_id}/ (primary) or run_dir (fallback)
        try:
            from pathlib import Path as _Path
            store = _get_result_store(state.get("source_pdf_path", ""))
            source_pdf = state.get("source_pdf_path", "")
            paper_id = None
            if source_pdf:
                resolved = str(_Path(source_pdf).resolve())
                paper_id = store._paper_cache.get(resolved)
            if paper_id:
                store._write_json(store.papers_dir / paper_id / "run_summary.json", run_summary)
                logger.info("Saved run_summary.json to papers/%s/", paper_id)
            else:
                store._write_json(store.run_dir / "run_summary.json", run_summary)
                logger.info("Saved run_summary.json to run directory (paper_id unknown)")
        except Exception as e:
            logger.warning(f"Failed to save run_summary.json: {e}")

        # Return combined result (deterministic_metrics is inside run_summary)
        return {
            "final_report_md": final_report,
            "aggregated_scores": aggregation_result.get("dimension_scores", {}),
            "overall_score": aggregation_result.get("overall_score", 0.0),
            "grade": aggregation_result.get("grade", "F"),
            "total_weight": aggregation_result.get("total_weight", 0.0),
            "run_summary": run_summary,
        }

    def _generate_run_summary(
        self,
        state: SurveyState,
        aggregation_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate run_summary.json content."""
        from src.graph.builder import _result_store

        run_id = "unknown"
        if _result_store:
            run_id = _result_store.run_id

        # Get source file
        source_pdf = state.get("source_pdf_path", "")

        # Build agent scores from dimension_scores
        agent_scores = {}
        dimension_scores = aggregation_result.get("dimension_scores", {})
        for dim_id, dim_data in dimension_scores.items():
            agent_scores[dim_id] = dim_data.get("final_score", 5.0)

        # Build corrected scores
        corrected_scores = {}
        corrector_output = state.get("corrector_output")
        if corrector_output:
            for dim_id, correction in corrector_output.get("corrections", {}).items():
                corrected_scores[dim_id] = {
                    "original": correction.get("original_score"),
                    "corrected": correction.get("corrected_score"),
                    "std": correction.get("variance", {}).get("std", 0.0),
                }

        # Extract deterministic metrics from tool_evidence
        deterministic_metrics = self._extract_deterministic_metrics(state)

        return {
            "run_id": run_id,
            "source": source_pdf,
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "schema_version": "v3",
            "deterministic_metrics": deterministic_metrics,
            "dimension_scores": dimension_scores,
            "agent_scores": agent_scores,
            "corrected_scores": corrected_scores,
            "overall_score": aggregation_result.get("overall_score", 0.0),
            "grade": aggregation_result.get("grade", "F"),
        }

    def _extract_deterministic_metrics(self, state: SurveyState) -> dict[str, Any]:
        """Extract deterministic metrics from tool_evidence."""
        tool_evidence = state.get("tool_evidence", {})
        metrics = {}

        # Citation validation metrics (C3, C5)
        if validation := tool_evidence.get("validation", {}):
            metrics["C3"] = validation.get("C3_orphan_ref_rate")
            metrics["C5"] = validation.get("C5_metadata_verify_rate")

        # C6 alignment metrics
        if c6 := tool_evidence.get("c6_alignment", {}):
            metrics["C6_contradiction_rate"] = c6.get("contradiction_rate")

        # Temporal and structural metrics (T1-T5, S1-S5)
        if analysis := tool_evidence.get("analysis", {}):
            temporal = analysis.get("temporal", {})
            structural = analysis.get("structural", {})

            metrics["T1"] = temporal.get("T1_year_span")
            metrics["T2"] = temporal.get("T2_foundational_retrieval_gap")
            metrics["T3"] = temporal.get("T3_peak_year_ratio")
            metrics["T4"] = temporal.get("T4_temporal_continuity")
            metrics["T5"] = temporal.get("T5_trend_alignment")

            metrics["S1"] = structural.get("S1_section_count")
            metrics["S2"] = structural.get("S2_citation_density")
            metrics["S3"] = structural.get("S3_citation_gini")
            metrics["S4"] = structural.get("S4_zero_citation_section_rate")

        # Graph metrics (G1-G6, S5) - data is flat under graph key
        if graph := tool_evidence.get("graph_analysis", {}):
            total_refs = max(tool_evidence.get("validation", {}).get("total_refs", 1), 1)
            g6_isolates = graph.get("G6_isolates", 0)

            metrics["G1"] = graph.get("G1_density")
            metrics["G2"] = graph.get("G2_components")
            metrics["G3"] = graph.get("G3_lcc_frac")
            metrics["G4"] = graph.get("G4_coverage_rate")
            metrics["G5"] = graph.get("G5_clusters")
            metrics["G6"] = g6_isolates / total_refs if total_refs > 0 else 0

            # S5 from graph analysis
            metrics["S5"] = graph.get("S5_nmi")

        # Remove None values
        return {k: v for k, v in metrics.items() if v is not None}
