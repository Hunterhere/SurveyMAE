"""Report Generation Agent (ReportAgent).

Aggregates multi-agent evaluation records and generates structured JSON report.

# TODO: 重构职责
# - 收集来自 Verifier/Expert/Reader/Corrector 的异构评估数据
# - 分析数据质量和一致性
# - 生成结构化 JSON 报告（包含维度评分、文本摘要）
# - JSON 输出给 Aggregator 节点进行统计渲染
#
# 结构化输出格式:
# {
#     "dimension_scores": {
#         "factuality": {"agent": "...", "score": 8.5, "confidence": 0.9, "reasoning": "..."},
#         ...
#     },
#     "text_summary": "综合评估摘要...",
#     "metadata": {...}
# }
"""

from typing import Any, Dict, Optional

from src.agents.base import BaseAgent
from src.core.config import AgentConfig
from src.core.mcp_client import MCPManager
from src.core.state import EvaluationRecord, SurveyState
from src.graph.nodes.aggregator import aggregate_scores


class ReportAgent(BaseAgent):
    """Agent responsible for final report generation.

    This agent:
    - Collects all evaluation records from other agents
    - Aggregates scores with confidence-aware weighting
    - Produces the final markdown report
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
        """Generate final report from accumulated evaluations."""
        return await aggregate_scores(state)

