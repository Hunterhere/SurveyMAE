"""Domain Expert Agent (ExpertAgent).

This agent evaluates the academic depth and domain-specific quality of a survey.
It assesses core literature coverage, method classification, technical accuracy, and critical analysis.

Dimensions evaluated:
- E1: Core Literature Coverage - coverage of foundational works
- E2: Method Classification - reasonableness of method classification
- E3: Technical Accuracy - technical correctness of descriptions
- E4: Critical Analysis Depth - depth of critical analysis and comparison

Extension point: This agent can be extended to override evaluate() to add
tool-augmented scoring for specific sub-dimensions.
"""

import logging
from typing import Optional

from src.agents.base import BaseAgent
from src.core.config import AgentConfig
from src.core.mcp_client import MCPManager
from src.core.state import SurveyState, EvaluationRecord

logger = logging.getLogger("surveymae.agents.expert")


class ExpertAgent(BaseAgent):
    """Agent that evaluates survey quality from a domain expert perspective.

    This agent uses the base class evaluate() implementation which:
    1. Reads dispatch_specs["expert"] from state
    2. Evaluates each sub-dimension (E1-E4) using the provided evidence context
    3. Returns structured AgentOutput with per-sub-dimension scores
    """

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        mcp: Optional[MCPManager] = None,
    ):
        """Initialize the ExpertAgent.

        Args:
            config: Agent configuration.
            mcp: Optional MCP manager for domain-specific tools.

        Note:
            This agent does NOT instantiate CitationChecker or CitationGraphAnalyzer
            in __init__() because evidence_collection has already performed
            these analyses. The evaluation uses dispatch_specs from evidence_dispatch.
        """
        super().__init__(
            name="expert",
            config=config or AgentConfig(name="expert"),
            mcp=mcp,
        )
        # Extension point: If you override evaluate() to add tool-augmented scoring,
        # you can instantiate tools here. Example:
        # self._citation_checker = CitationChecker()
        # self._graph_analyzer = CitationGraphAnalyzer()

    # Extension point: Override evaluate() to add tool-augmented scoring for specific sub-dimensions.
    # The base class evaluate() will be used if not overridden.
    #
    # Example:
    # async def evaluate(self, state, section_name=None):
    #     # Call base class evaluate
    #     record = await super().evaluate(state, section_name)
    #     # Add tool-augmented refinement
    #     ...
