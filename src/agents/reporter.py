"""Report Generation Agent (ReportAgent).

This agent generates the final evaluation report with variance-aware display.

According to Plan v2:
- Aggregator: Pure mathematical aggregation (in src/graph/nodes/aggregator.py)
- Reporter: Report generation with variance display (this file)

The reporter:
- Calls aggregate_scores to compute weighted scores
- Separates deterministic vs LLM-involved metrics
- Generates markdown with variance visualization
"""

from typing import Any, Dict, Optional

from src.agents.base import BaseAgent
from src.core.config import AgentConfig
from src.core.mcp_client import MCPManager
from src.core.state import EvaluationRecord, SurveyState
from src.graph.nodes.aggregator import aggregate_scores, generate_report


class ReportAgent(BaseAgent):
    """Agent responsible for final report generation.

    This agent:
    - Calls aggregate_scores for mathematical aggregation
    - Generates markdown report with variance-aware display
    - Deterministic metrics shown with solid values
    - LLM metrics shown with error bars/variance
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
        3. Returns final state with report and scores
        """
        # Step 1: Aggregate scores (pure calculation)
        aggregation_result = await aggregate_scores(state)

        # Step 2: Generate markdown report with variance display
        final_report = generate_report(aggregation_result, state)

        # Return combined result
        return {
            "final_report_md": final_report,
            "aggregated_scores": aggregation_result.get("aggregated_scores", {}),
            "deterministic_score": aggregation_result.get("deterministic_score"),
            "llm_score": aggregation_result.get("llm_score"),
            "llm_variance": aggregation_result.get("llm_variance"),
            "overall_score": aggregation_result.get("overall_score", 0.0),
            "consensus_reached": aggregation_result.get("consensus_reached", True),
        }
