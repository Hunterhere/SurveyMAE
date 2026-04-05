"""Knowledge Verification Agent (VerifierAgent).

This agent validates factual accuracy and citation quality of a survey.
It assesses citation existence, claim alignment, and internal consistency.

Dimensions evaluated (v3):
- V1: Citation Existence - whether references are real and verifiable
- V2: Citation-Claim Alignment - whether survey correctly understands cited papers
- V4: Internal Consistency - whether the survey has internal contradictions

Note: V2 scoring is handled by the short-circuit mechanism in evidence_dispatch.
When C6.auto_fail=True, V2 is auto-scored as 1 without calling the agent.

Extension point: This agent can be extended to override evaluate() to add
tool-augmented scoring for specific sub-dimensions.
"""

import logging
from typing import Optional

from src.agents.base import BaseAgent
from src.core.config import AgentConfig
from src.core.mcp_client import MCPManager
from src.core.state import SurveyState, EvaluationRecord

logger = logging.getLogger("surveymae.agents.verifier")


class VerifierAgent(BaseAgent):
    """Agent responsible for verifying factual claims and citations.

    This agent uses the base class evaluate() implementation which:
    1. Reads dispatch_specs["verifier"] from state
    2. Evaluates each sub-dimension (V1, V4) using the provided evidence context
    3. V2 is pre-filled by evidence_dispatch when C6.auto_fail=True
    4. Returns structured AgentOutput with per-sub-dimension scores
    """

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        mcp: Optional[MCPManager] = None,
    ):
        """Initialize the VerifierAgent.

        Args:
            config: Agent configuration.
            mcp: Optional MCP manager for search tool access.

        Note:
            This agent does NOT instantiate CitationChecker in __init__() because
            evidence_collection has already performed citation extraction and validation.
            The evaluation uses dispatch_specs from evidence_dispatch.
        """
        super().__init__(
            name="verifier",
            config=config or AgentConfig(name="verifier"),
            mcp=mcp,
        )
        # Extension point: If you override evaluate() to add tool-augmented scoring,
        # you can instantiate tools here. Example:
        # self._citation_checker = CitationChecker()

    # Extension point: Override evaluate() to add tool-augmented scoring for specific sub-dimensions.
    # The base class evaluate() will be used if not overridden.
    #
    # Example:
    # async def evaluate(self, state, section_name=None):
    #     # Call base class evaluate
    #     record = await super().evaluate(state, section_name)
    #     # Add tool-augmented refinement
    #     ...
