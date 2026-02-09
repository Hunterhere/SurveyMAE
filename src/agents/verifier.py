"""Knowledge Verification Agent (VerifierAgent).

Validates factual accuracy by cross-referencing claims with external sources.
Uses MCP tools to search for and verify citations.
"""

import re
from typing import Optional

from src.agents.base import BaseAgent
from src.core.config import AgentConfig, LLMConfig
from src.core.mcp_client import MCPManager
from src.core.state import SurveyState, EvaluationRecord


class VerifierAgent(BaseAgent):
    """Agent responsible for verifying factual claims and citations.

    This agent:
    - Extracts citations and claims from the survey text
    - Searches external databases for verification
    - Checks if cited papers actually exist and match the claims
    - Identifies potential hallucinations

    Dimensions evaluated:
    - factuality: Are the claims factually accurate?
    - citation_accuracy: Do citations match the content?
    - hallucination_score: Rate of potentially false claims
    """

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        mcp: Optional[MCPManager] = None,
    ):
        """Initialize the VerifierAgent.

        Args:
            config: Agent configuration.
            mcp: MCP manager for search tool access.
        """
        super().__init__(
            name="verifier",
            config=config or AgentConfig(name="verifier"),
            mcp=mcp,
        )

    async def evaluate(
        self,
        state: SurveyState,
        section_name: Optional[str] = None,
    ) -> EvaluationRecord:
        """Evaluate the factuality and citation accuracy of survey content.

        Args:
            state: The current workflow state.
            section_name: Optional section to focus on.

        Returns:
            EvaluationRecord with factuality scores.
        """
        content = state.get("parsed_content", "")

        # Load the verification prompt
        system_prompt = self._load_prompt(
            "verifier",
            agent_name=self.name,
            section=section_name or "entire survey",
        )

        # Extract claims and citations for verification
        claims_and_citations = self._extract_claims_and_citations(content)

        # Prepare user content with extracted claims
        user_content = f"""
        Survey Content to Verify:
        ---
        {content[:10000]}  # Truncate for context limit
        ---

        Extracted Claims and Citations:
        {claims_and_citations}

        Please verify each claim by:
        1. Checking if the cited papers exist
        2. Verifying if the claims match the actual paper content
        3. Identifying any potential hallucinations
        4. Providing a factuality score from 0-10

        Return your evaluation with evidence for each claim.
        """

        # Call LLM for verification
        response = await self._call_llm(
            self._create_messages(system_prompt, user_content)
        )

        # Parse the response to extract scores
        score, reasoning, evidence = self._parse_verification_response(response)

        return EvaluationRecord(
            agent_name=self.name,
            dimension="factuality",
            score=score,
            reasoning=reasoning,
            evidence=evidence,
            confidence=0.85,  # Base confidence, can be adjusted
        )

    def _extract_claims_and_citations(self, content: str) -> str:
        """Extract claims and their citations from content.

        Args:
            content: The survey text content.

        Returns:
            A formatted string of claims with citations.
        """
        # Pattern to find citations like [1], [1-3], [1, 2, 3]
        citation_pattern = r"\[(?:[0-9]+(?:[-,]\s*[0-9]+)*)\]"

        # Find all citations
        citations = re.findall(citation_pattern, content)

        # Get unique citations
        unique_citations = list(dict.fromkeys(citations))

        return f"Found citations: {', '.join(unique_citations)}"

    def _parse_verification_response(self, response: str) -> tuple:
        """Parse the LLM verification response.

        Args:
            response: The raw response from the verification LLM.

        Returns:
            Tuple of (score, reasoning, evidence).
        """
        # Simple parsing - in production, use structured output parsing
        lines = response.strip().split("\n")

        score = 5.0  # Default score
        reasoning = response
        evidence = None

        for line in lines:
            line_lower = line.lower()
            if "score" in line_lower and ":" in line:
                try:
                    score = float(line.split(":")[-1].strip())
                    score = max(0.0, min(10.0, score))  # Clamp to [0, 10]
                except ValueError:
                    pass

            if "evidence:" in line_lower:
                evidence = line.split(":", 1)[-1].strip()

        return score, reasoning, evidence
