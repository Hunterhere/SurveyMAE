"""Reader Simulation Agent (ReaderAgent).

Simulates a reader's experience by generating QA pairs and measuring coverage.
Uses retrieval-based evaluation to assess information completeness.
"""

from typing import Optional, List

from src.agents.base import BaseAgent
from src.core.config import AgentConfig, LLMConfig
from src.core.mcp_client import MCPManager
from src.core.state import SurveyState, EvaluationRecord


class ReaderAgent(BaseAgent):
    """Agent that simulates a reader's experience with the survey.

    This agent:
    - Generates questions a reader might have about the topic
    - Uses RAG-style retrieval to find answers in the survey
    - Calculates coverage metrics based on answer quality
    - Identifies information gaps from a reader perspective

    Dimensions evaluated:
    - coverage: What fraction of important topics are addressed?
    - clarity: How clear and understandable is the content?
    - coherence: How well does the content flow for a reader?
    - question_answering: Can the survey answer key questions?
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
        """
        super().__init__(
            name="reader",
            config=config or AgentConfig(name="reader"),
            mcp=mcp,
        )

    async def evaluate(
        self,
        state: SurveyState,
        section_name: Optional[str] = None,
    ) -> EvaluationRecord:
        """Evaluate reader experience and information coverage.

        Args:
            state: The current workflow state.
            section_name: Optional specific section to evaluate.

        Returns:
            EvaluationRecord with coverage and clarity scores.
        """
        content = state.get("parsed_content", "")

        # Load the reader simulation prompt
        system_prompt = self._load_prompt(
            "reader",
            agent_name=self.name,
            section=section_name or "entire survey",
        )

        user_content = f"""
        Survey Content:
        ---
        {content[:10000]}
        ---

        Please simulate a reader's experience with this survey:
        1. Generate 3-5 key questions a reader might ask about this topic
        2. Retrieve and assess answers from the survey content
        3. Calculate coverage: what % of questions are well-answered?
        4. Rate clarity and coherence (0-10)
        5. Identify any confusing or unclear sections

        Format your response with the questions, answers, and coverage score.
        """

        response = await self._call_llm(
            self._create_messages(system_prompt, user_content)
        )

        score, reasoning, evidence = self._parse_reader_response(response)

        return EvaluationRecord(
            agent_name=self.name,
            dimension="coverage",
            score=score,
            reasoning=reasoning,
            evidence=evidence,
            confidence=0.8,
        )

    def _parse_reader_response(self, response: str) -> tuple:
        """Parse the reader simulation response.

        Args:
            response: The raw response from the reader LLM.

        Returns:
            Tuple of (score, reasoning, evidence).
        """
        lines = response.strip().split("\n")

        score = 5.0
        reasoning = response
        evidence = None

        coverage_keywords = ["coverage", "answer rate", "answered"]

        for line in lines:
            line_lower = line.lower()
            if any(keyword in line_lower for keyword in coverage_keywords):
                if ":" in line or "%" in line:
                    try:
                        # Try to extract percentage
                        import re
                        pct_match = re.search(r"(\d+(?:\.\d+)?)%?", line)
                        if pct_match:
                            pct = float(pct_match.group(1))
                            score = pct / 10.0  # Convert percentage to 0-10 scale
                        else:
                            score = float(line.split(":")[-1].strip())
                            score = max(0.0, min(10.0, score))
                    except ValueError:
                        pass

            if any(kw in line_lower for kw in ["unanswered", "gap", "missing"]):
                if evidence is None:
                    evidence = line

        return score, reasoning, evidence
