"""Bias Correction Agent (CorrectorAgent).

Analyzes and detects systematic biases in the survey.
Evaluates balance, fairness, and potential viewpoints being over/under-represented.
"""

from typing import Optional

from src.agents.base import BaseAgent
from src.core.config import AgentConfig, LLMConfig
from src.core.mcp_client import MCPManager
from src.core.state import SurveyState, EvaluationRecord


class CorrectorAgent(BaseAgent):
    """Agent that detects and evaluates systematic biases in the survey.

    This agent:
    - Analyzes citation distribution and balance
    - Detects potential viewpoint biases
    - Identifies over-represented or under-represented perspectives
    - Evaluates fairness in presenting conflicting views

    Dimensions evaluated:
    - bias: Overall bias score (lower is more balanced)
    - balance: Balance in presenting different viewpoints
    - representation: Fair representation of different works/perspectives
    - objectivity: Objectivity in presenting facts vs. opinions
    """

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        mcp: Optional[MCPManager] = None,
    ):
        """Initialize the CorrectorAgent.

        Args:
            config: Agent configuration.
            mcp: Optional MCP manager for reference check tools.
        """
        super().__init__(
            name="corrector",
            config=config or AgentConfig(name="corrector"),
            mcp=mcp,
        )

    async def evaluate(
        self,
        state: SurveyState,
        section_name: Optional[str] = None,
    ) -> EvaluationRecord:
        """Evaluate bias and balance in the survey content.

        Args:
            state: The current workflow state.
            section_name: Optional specific section to evaluate.

        Returns:
            EvaluationRecord with bias and balance scores.
        """
        content = state.get("parsed_content", "")

        # Load the bias correction prompt
        system_prompt = self._load_prompt(
            "corrector",
            agent_name=self.name,
            section=section_name or "entire survey",
        )

        user_content = f"""
        Survey Content:
        ---
        {content[:10000]}
        ---

        Please analyze this survey for potential biases:
        1. Examine citation distribution - are some works over-represented?
        2. Check for balance in presenting different viewpoints
        3. Identify any systematic biases (geographic, temporal, methodological)
        4. Evaluate objectivity vs. opinion
        5. Rate the overall bias/balance (0-10, where 10 = perfectly balanced)

        Provide specific examples of bias or imbalance if found.
        """

        response = await self._call_llm(
            self._create_messages(system_prompt, user_content)
        )

        score, reasoning, evidence = self._parse_corrector_response(response)

        # Invert score: higher balance = higher score
        # The LLM returns balance score directly
        return EvaluationRecord(
            agent_name=self.name,
            dimension="bias",
            score=score,
            reasoning=reasoning,
            evidence=evidence,
            confidence=0.75,  # Bias detection has inherent uncertainty
        )

    def _parse_corrector_response(self, response: str) -> tuple:
        """Parse the bias correction response.

        Args:
            response: The raw response from the corrector LLM.

        Returns:
            Tuple of (score, reasoning, evidence).
        """
        lines = response.strip().split("\n")

        score = 5.0
        reasoning = response
        evidence = None

        for line in lines:
            line_lower = line.lower()
            if any(keyword in line_lower for keyword in ["balance", "bias score", "rating"]):
                if ":" in line:
                    try:
                        score = float(line.split(":")[-1].strip())
                        score = max(0.0, min(10.0, score))
                    except ValueError:
                        pass

            if any(kw in line_lower for kw in ["over-represented", "under-represented", "bias", "imbalance"]):
                if evidence is None:
                    evidence = line

        return score, reasoning, evidence
