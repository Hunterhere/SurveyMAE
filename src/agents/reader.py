"""Reader Simulation Agent (ReaderAgent).

This agent evaluates the readability and information quality of a survey.
It assesses timeliness, information distribution, structural clarity, and writing quality.

Dimensions evaluated:
- R1: Timeliness - coverage of historical and recent developments
- R2: Information Balance - balance of information across sections
- R3: Structural Clarity - clarity of hierarchical structure
- R4: Writing Quality - language quality and consistency

Extension point: This agent can be extended to override evaluate() to add
tool-augmented scoring for specific sub-dimensions.
"""

import logging
from typing import Optional

from src.agents.base import BaseAgent
from src.core.config import AgentConfig
from src.core.mcp_client import MCPManager
from src.core.state import SurveyState, EvaluationRecord

logger = logging.getLogger("surveymae.agents.reader")


class ReaderAgent(BaseAgent):
    """Agent that simulates a reader's experience with the survey.

    This agent uses the base class evaluate() implementation which:
    1. Reads dispatch_specs["reader"] from state
    2. Evaluates each sub-dimension (R1-R4) using the provided evidence context
    3. Returns structured AgentOutput with per-sub-dimension scores
    """

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        mcp: Optional[MCPManager] = None,
    ):
        """Initialize the ReaderAgent.

        Args:
            config: Agent configuration.
            mcp: Optional MCP manager for retrieval tools.

        Note:
            This agent does NOT instantiate CitationChecker or CitationAnalyzer
            in __init__() because evidence_collection has already performed
            these analyses. The evaluation uses dispatch_specs from evidence_dispatch.
        """
        super().__init__(
            name="reader",
            config=config or AgentConfig(name="reader"),
            mcp=mcp,
        )
        # Extension point: If you override evaluate() to add tool-augmented scoring,
        # you can instantiate tools here. Example:
        # self._citation_checker = CitationChecker()
        # self._citation_analyzer = CitationAnalyzer()

    # Extension point: Override evaluate() to add tool-augmented scoring for specific sub-dimensions.
    # The base class evaluate() will be used if not overridden.
    #
    # Example:
    # async def evaluate(self, state, section_name=None):
    #     # Call base class evaluate
    #     record = await super().evaluate(state, section_name)
    #     # Add tool-augmented refinement
    #     ...
