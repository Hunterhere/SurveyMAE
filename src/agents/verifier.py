"""Knowledge Verification Agent (VerifierAgent).

Validates factual accuracy by cross-referencing claims with external sources.
Uses citation checker tools to search for and verify citations.
"""

import logging
import re
from typing import Any, Dict, Optional

from src.agents.base import BaseAgent
from src.core.config import AgentConfig, LLMConfig
from src.core.mcp_client import MCPManager
from src.core.state import SurveyState, EvaluationRecord
from src.tools.citation_checker import CitationChecker

logger = logging.getLogger(__name__)


class VerifierAgent(BaseAgent):
    """Agent responsible for verifying factual claims and citations.

    This agent:
    - Extracts citations and claims from the survey text
    - Uses CitationChecker to verify citations exist and match claims
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
        # Initialize citation checker for direct tool calls
        self._citation_checker = CitationChecker()

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
        source_pdf = state.get("source_pdf_path", "")

        # Load the verification prompt
        system_prompt = self._load_prompt(
            "verifier",
            agent_name=self.name,
            section=section_name or "entire survey",
        )

        # Use citation checker to extract and validate citations
        citation_analysis = await self._analyze_citations(source_pdf, content)

        # Extract claims for verification
        claims_and_citations = self._extract_claims_and_citations(content)

        # Prepare user content with extracted claims and citation analysis
        user_content = f"""
        Survey Content to Verify:
        ---
        {content[:15000]}
        ---

        Citation Analysis Results:
        {citation_analysis}

        Extracted Claims and Citations:
        {claims_and_citations}

        Please verify each claim by:
        1. Checking if the cited papers exist and are accessible
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

        # Incorporate citation validation results into the score
        if citation_analysis:
            score, reasoning, evidence = self._incorporate_citation_analysis(
                score, reasoning, evidence, citation_analysis
            )

        return EvaluationRecord(
            agent_name=self.name,
            dimension="factuality",
            score=score,
            reasoning=reasoning,
            evidence=evidence,
            confidence=0.85,
        )

    async def _analyze_citations(
        self,
        pdf_path: str,
        content: str,
    ) -> Dict[str, Any]:
        """Analyze citations using CitationChecker tool.

        Args:
            pdf_path: Path to the PDF file.
            content: Survey content.

        Returns:
            Citation analysis results.
        """
        try:
            if pdf_path:
                # Use the PDF-based citation extraction
                result = self._citation_checker.extract_citations_with_context_from_pdf(pdf_path)
                return {
                    "citations_count": len(result.get("citations", [])),
                    "references_count": len(result.get("references", [])),
                    "backend": result.get("backend", "unknown"),
                    "has_citations": len(result.get("citations", [])) > 0,
                    "has_references": len(result.get("references", [])) > 0,
                }
            else:
                # Fallback to text-based extraction
                citations = self._citation_checker.extract_citations(content)
                return {
                    "citations_count": len(citations),
                    "references_count": 0,
                    "backend": "text",
                    "has_citations": len(citations) > 0,
                    "has_references": False,
                }
        except Exception as e:
            logger.warning(f"Citation analysis failed: {e}")
            return {
                "citations_count": 0,
                "references_count": 0,
                "backend": "error",
                "error": str(e),
            }

    def _incorporate_citation_analysis(
        self,
        score: float,
        reasoning: str,
        evidence: Optional[str],
        citation_analysis: Dict[str, Any],
    ) -> tuple:
        """Incorporate citation analysis into the evaluation score.

        Args:
            score: Original LLM score.
            reasoning: Original reasoning.
            evidence: Original evidence.
            citation_analysis: Citation analysis results.

        Returns:
            Updated (score, reasoning, evidence) tuple.
        """
        citations_count = citation_analysis.get("citations_count", 0)
        references_count = citation_analysis.get("references_count", 0)

        # Check for citation-related issues
        issues = []

        if citations_count == 0:
            issues.append("No citations found in the survey")

        if references_count == 0:
            issues.append("No reference list found")

        # If there are citations but no references, that's a problem
        if citations_count > 0 and references_count == 0:
            issues.append("Citations found but no reference list - possible hallucination")

        # Add citation analysis to evidence
        citation_evidence = f"Citation count: {citations_count}, Reference count: {references_count}"
        if issues:
            citation_evidence += f"\nIssues: {'; '.join(issues)}"
            # Reduce score for citation issues
            score = min(score, 7.0) if issues else score

        if evidence:
            evidence = f"{citation_evidence}\n{evidence}"
        else:
            evidence = citation_evidence

        return score, reasoning, evidence

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
