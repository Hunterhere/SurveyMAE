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
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.agents.base import BaseAgent
from src.core.config import AgentConfig
from src.core.mcp_client import MCPManager
from src.core.state import EvaluationRecord, SurveyState
from src.graph.nodes.aggregator import aggregate_scores, generate_report
from src.graph.builder import _get_result_store

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
        config: Optional[AgentConfig] = None,
        mcp: Optional[MCPManager] = None,
    ) -> None:
        super().__init__(
            name="reporter",
            config=config or AgentConfig(name="reporter"),
            mcp=mcp,
        )

    async def evaluate(
        self,
        state: SurveyState,
        section_name: Optional[str] = None,
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

    async def process(
        self,
        state: SurveyState,
    ) -> Dict[str, Any]:
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

        # Save run_summary.json
        try:
            store = _get_result_store(state.get("source_pdf_path", ""))
            source_path = state.get("source_pdf_path", "")
            if source_path:
                paper_id = store.register_paper(source_path)
                store._write_json(store.papers_dir / paper_id / "run_summary.json", run_summary)
                logger.info("Saved run_summary.json")
        except Exception as e:
            logger.warning(f"Failed to save run_summary.json: {e}")

        # Return combined result
        return {
            "final_report_md": final_report,
            "aggregated_scores": aggregation_result.get("dimension_scores", {}),
            "deterministic_metrics": aggregation_result.get("deterministic_metrics", {}),
            "overall_score": aggregation_result.get("overall_score", 0.0),
            "grade": aggregation_result.get("grade", "F"),
            "total_weight": aggregation_result.get("total_weight", 0.0),
            "run_summary": run_summary,
        }

    def _generate_run_summary(
        self,
        state: SurveyState,
        aggregation_result: Dict[str, Any],
    ) -> Dict[str, Any]:
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

        return {
            "run_id": run_id,
            "source": source_pdf,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "agent_scores": agent_scores,
            "corrected_scores": corrected_scores,
            "overall_score": aggregation_result.get("overall_score", 0.0),
            "grade": aggregation_result.get("grade", "F"),
        }
