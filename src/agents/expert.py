"""Domain Expert Agent (ExpertAgent).

Evaluates the logical depth and domain-specific quality of the survey.
Acts as a domain expert to assess technical accuracy and completeness.
"""

from typing import Optional

from src.agents.base import BaseAgent
from src.core.config import AgentConfig, LLMConfig
from src.core.mcp_client import MCPManager
from src.core.state import SurveyState, EvaluationRecord


class ExpertAgent(BaseAgent):
    """Agent that evaluates survey quality from a domain expert perspective.

    This agent:
    - Analyzes technical depth and accuracy
    - Evaluates logical structure and reasoning
    - Assesses completeness of topic coverage
    - Identifies gaps in the literature review

    Dimensions evaluated:
    - depth: Technical depth and sophistication
    - logical_coherence: Organization and logical flow
    - completeness: Coverage of important works/topics
    - accuracy: Technical correctness
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
        """
        super().__init__(
            name="expert",
            config=config or AgentConfig(name="expert"),
            mcp=mcp,
        )

    async def evaluate(
        self,
        state: SurveyState,
        section_name: Optional[str] = None,
    ) -> EvaluationRecord:
        """Evaluate the domain expertise and depth of the survey.

        Args:
            state: The current workflow state.
            section_name: Optional specific section to evaluate.

        Returns:
            EvaluationRecord with depth and expertise scores.
        """
        content = state.get("parsed_content", "")

        # Load the expert evaluation prompt
        system_prompt = self._load_prompt(
            "expert",
            agent_name=self.name,
            section=section_name or "entire survey",
        )

        # Get domain context from metadata if available
        domain_context = state.get("metadata", {}).get("domain", "general")

        user_content = f"""
        Survey Content to Evaluate:
        ---
        {content[:10000]}
        ---

        Domain Context: {domain_context}

        Please evaluate this survey from a domain expert perspective:
        1. Assess the technical depth and accuracy
        2. Evaluate logical structure and reasoning quality
        3. Identify any gaps in topic coverage
        4. Rate the overall expertise demonstrated (0-10)

        Provide specific examples and evidence for your assessment.
        """

        response = await self._call_llm(
            self._create_messages(system_prompt, user_content)
        )

        score, reasoning, evidence = self._parse_expert_response(response)

        return EvaluationRecord(
            agent_name=self.name,
            dimension="depth",
            score=score,
            reasoning=reasoning,
            evidence=evidence,
            confidence=0.9,  # Expert agents typically have high confidence
        )

    def _parse_expert_response(self, response: str) -> tuple:
        """Parse the expert evaluation response.

        Args:
            response: The raw response from the expert LLM.

        Returns:
            Tuple of (score, reasoning, evidence).
        """
        lines = response.strip().split("\n")

        score = 5.0
        reasoning = response
        evidence = None

        for line in lines:
            line_lower = line.lower()
            if any(keyword in line_lower for keyword in ["score", "rating", "grade"]):
                if ":" in line:
                    try:
                        score = float(line.split(":")[-1].strip())
                        score = max(0.0, min(10.0, score))
                    except ValueError:
                        pass

            if "evidence:" in line_lower or "example:" in line_lower:
                evidence = line.split(":", 1)[-1].strip()

        return score, reasoning, evidence
