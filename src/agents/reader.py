"""Reader Simulation Agent (ReaderAgent).

Simulates a reader's experience by generating QA pairs and measuring coverage.
Uses retrieval-based evaluation to assess information completeness.
Uses citation analysis tools for temporal analysis and section-level distribution.
"""

import logging
import re
from typing import Any, Dict, Optional

from src.agents.base import BaseAgent
from src.core.config import AgentConfig, LLMConfig
from src.core.mcp_client import MCPManager
from src.core.state import SurveyState, EvaluationRecord
from src.tools.citation_checker import CitationChecker
from src.tools.citation_analysis import CitationAnalyzer

logger = logging.getLogger(__name__)


class ReaderAgent(BaseAgent):
    """Agent that simulates a reader's experience with the survey.

    This agent:
    - Generates questions a reader might have about the topic
    - Uses RAG-style retrieval to find answers in the survey
    - Calculates coverage metrics based on answer quality
    - Identifies information gaps from a reader perspective
    - Uses citation temporal analysis and section-level distribution

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
        # Initialize citation analysis tools
        self._citation_checker = CitationChecker()
        self._citation_analyzer = CitationAnalyzer()

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
        source_pdf = state.get("source_pdf_path", "")

        # Get evidence report from state
        evidence_reports = state.get("evidence_reports", {})
        evidence_report = evidence_reports.get("reader", "No evidence report available.")

        # Load the reader simulation prompt
        system_prompt = self._load_prompt(
            "reader",
            agent_name=self.name,
            section=section_name or "entire survey",
            evidence_report=evidence_report,
        )

        # Get citation temporal and section-level analysis
        citation_analysis = await self._analyze_citations(source_pdf, content)

        user_content = f"""
        Survey Content:
        ---
        {content[:15000]}
        ---

        Citation Temporal Analysis Results:
        {citation_analysis.get("temporal", "N/A")}

        Section-level Citation Distribution:
        {citation_analysis.get("section_distribution", "N/A")}

        Please simulate a reader's experience with this survey:
        1. Generate 3-5 key questions a reader might ask about this topic
        2. Retrieve and assess answers from the survey content
        3. Calculate coverage: what % of questions are well-answered?
        4. Assess balance between classical and recent works
        5. Evaluate distribution of references across sections
        6. Rate clarity, readability and structural clarity (0-10)
        7. Identify any confusing or unclear sections

        Format your response with the questions, answers, and coverage score.
        """

        response = await self._call_llm(self._create_messages(system_prompt, user_content))

        score, reasoning, evidence = self._parse_reader_response(response)

        # Incorporate citation analysis into evaluation
        if citation_analysis:
            score, reasoning, evidence = self._incorporate_citation_analysis(
                score, reasoning, evidence, citation_analysis
            )

        return EvaluationRecord(
            agent_name=self.name,
            dimension="coverage",
            score=score,
            reasoning=reasoning,
            evidence=evidence,
            confidence=0.8,
        )

    async def _analyze_citations(
        self,
        pdf_path: str,
        content: str,
    ) -> Dict[str, Any]:
        """Analyze citations for temporal and section-level distribution.

        Args:
            pdf_path: Path to the PDF file.
            content: Survey content.

        Returns:
            Citation analysis results.
        """
        try:
            if not pdf_path:
                return {"error": "No PDF path provided"}

            # Extract citations and references from PDF (async)
            extraction = await self._citation_checker.extract_citations_with_context_from_pdf(pdf_path)
            references = extraction.get("references", [])
            citations = extraction.get("citations", [])

            if not references:
                return {"error": "No references found"}

            # Get temporal analysis
            temporal = self._citation_analyzer.analyze_references(references)

            # Get section-level distribution (paragraph distribution)
            section_dist = self._citation_analyzer.analyze_paragraph_distribution(
                citations=citations,
                references=references,
            )

            return {
                "temporal": temporal,
                "section_distribution": section_dist,
                "has_references": len(references) > 0,
            }
        except Exception as e:
            logger.warning(f"Citation analysis failed: {e}")
            return {"error": str(e)}

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
        if "error" in citation_analysis:
            return score, reasoning, evidence

        # Build evidence string
        analysis_evidence = "Citation Analysis: "

        temporal = citation_analysis.get("temporal", {})
        if temporal:
            year_dist = temporal.get("year_distribution", {})
            if year_dist:
                recent_count = sum(1 for y in year_dist.keys() if int(y) >= 2020)
                classical_count = sum(1 for y in year_dist.keys() if int(y) < 2015)
                total = sum(year_dist.values())
                analysis_evidence += f"Recent (2020+): {recent_count}, Classical (<2015): {classical_count}, Total: {total}. "

        section_dist = citation_analysis.get("section_distribution", {})
        if section_dist:
            sections = section_dist.get("sections", {})
            if sections:
                analysis_evidence += f"References across {len(sections)} sections. "

        if evidence:
            evidence = f"{analysis_evidence}\n{evidence}"
        else:
            evidence = analysis_evidence

        return score, reasoning, evidence

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
                        # Try to extract percentage or score
                        pct_match = re.search(r"(\d+(?:\.\d+)?)%?", line)
                        if pct_match:
                            pct = float(pct_match.group(1))
                            # Only divide by 10 if there's an actual % sign
                            if "%" in pct_match.group(0):
                                score = pct / 10.0  # Convert percentage to 0-10 scale
                            else:
                                score = max(0.0, min(10.0, pct))
                        else:
                            score = float(line.split(":")[-1].strip())
                            score = max(0.0, min(10.0, score))
                    except ValueError:
                        pass

            if any(kw in line_lower for kw in ["unanswered", "gap", "missing"]):
                if evidence is None:
                    evidence = line

        return score, reasoning, evidence
