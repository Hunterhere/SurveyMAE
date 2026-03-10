"""Domain Expert Agent (ExpertAgent).

Evaluates the logical depth and domain-specific quality of the survey.
Acts as a domain expert to assess technical accuracy and completeness.
Uses citation graph analysis tools.
"""

import logging
from typing import Any, Dict, Optional

from src.agents.base import BaseAgent
from src.core.config import AgentConfig, LLMConfig
from src.core.mcp_client import MCPManager
from src.core.state import SurveyState, EvaluationRecord
from src.tools.citation_checker import CitationChecker
from src.tools.citation_graph_analysis import CitationGraphAnalyzer

logger = logging.getLogger(__name__)


class ExpertAgent(BaseAgent):
    """Agent that evaluates survey quality from a domain expert perspective.

    This agent:
    - Analyzes technical depth and accuracy
    - Evaluates logical structure and reasoning
    - Assesses completeness of topic coverage
    - Identifies gaps in the literature review
    - Uses citation graph data to evaluate authority and representativeness

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
        # Initialize tools for citation graph analysis
        self._citation_checker = CitationChecker()
        self._graph_analyzer = CitationGraphAnalyzer()

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
        source_pdf = state.get("source_pdf_path", "")

        # Load the expert evaluation prompt
        system_prompt = self._load_prompt(
            "expert",
            agent_name=self.name,
            section=section_name or "entire survey",
        )

        # Get citation graph analysis results
        graph_analysis = await self._analyze_citation_graph(source_pdf, content)

        # Get domain context from metadata if available
        domain_context = state.get("metadata", {}).get("domain", "general")

        user_content = f"""
        Survey Content to Evaluate:
        ---
        {content[:15000]}
        ---

        Domain Context: {domain_context}

        Citation Graph Analysis Results:
        {graph_analysis}

        Please evaluate this survey from a domain expert perspective:
        1. Assess the technical depth and accuracy
        2. Evaluate logical structure and reasoning quality
        3. Assess authority and representativeness of cited literature
        4. Check for structural coherence of the citation graph
        5. Identify presence of core or foundational works
        6. Identify any gaps in topic coverage
        7. Rate the overall expertise demonstrated (0-10)

        Provide specific examples and evidence for your assessment.
        """

        response = await self._call_llm(
            self._create_messages(system_prompt, user_content)
        )

        score, reasoning, evidence = self._parse_expert_response(response)

        # Incorporate citation graph analysis into evaluation
        if graph_analysis:
            score, reasoning, evidence = self._incorporate_graph_analysis(
                score, reasoning, evidence, graph_analysis
            )

        return EvaluationRecord(
            agent_name=self.name,
            dimension="depth",
            score=score,
            reasoning=reasoning,
            evidence=evidence,
            confidence=0.9,  # Expert agents typically have high confidence
        )

    async def _analyze_citation_graph(
        self,
        pdf_path: str,
        content: str,
    ) -> Dict[str, Any]:
        """Analyze citation graph using CitationGraphAnalyzer.

        Args:
            pdf_path: Path to the PDF file.
            content: Survey content.

        Returns:
            Citation graph analysis results.
        """
        try:
            if not pdf_path:
                return {"error": "No PDF path provided"}

            # Extract citations and references from PDF
            extraction = self._citation_checker.extract_citations_with_context_from_pdf(pdf_path)
            references = extraction.get("references", [])

            if not references:
                return {"error": "No references found in PDF"}

            # Analyze citation graph
            graph_result = self._graph_analyzer.analyze(references)

            # Extract key metrics for the agent
            return {
                "node_count": graph_result.get("node_count", 0),
                "edge_count": graph_result.get("edge_count", 0),
                "density": graph_result.get("density_connectivity", {}).get("density", 0),
                "centrality": graph_result.get("centrality", {}),
                "clustering": graph_result.get("cocitation_clustering", {}),
                "has_graph": graph_result.get("node_count", 0) > 0,
            }
        except Exception as e:
            logger.warning(f"Citation graph analysis failed: {e}")
            return {"error": str(e)}

    def _incorporate_graph_analysis(
        self,
        score: float,
        reasoning: str,
        evidence: Optional[str],
        graph_analysis: Dict[str, Any],
    ) -> tuple:
        """Incorporate citation graph analysis into the evaluation score.

        Args:
            score: Original LLM score.
            reasoning: Original reasoning.
            evidence: Original evidence.
            graph_analysis: Citation graph analysis results.

        Returns:
            Updated (score, reasoning, evidence) tuple.
        """
        if "error" in graph_analysis:
            return score, reasoning, evidence

        # Extract key metrics
        node_count = graph_analysis.get("node_count", 0)
        edge_count = graph_analysis.get("edge_count", 0)
        density = graph_analysis.get("density", 0)

        # Build evidence string
        graph_evidence = f"Citation Graph: {node_count} nodes, {edge_count} edges, density: {density:.3f}"

        # Add centrality info if available
        centrality = graph_analysis.get("centrality", {})
        if centrality:
            top_central = centrality.get("top_nodes", [])[:3]
            if top_central:
                graph_evidence += f"\nTop centrality nodes: {top_central}"

        if evidence:
            evidence = f"{graph_evidence}\n{evidence}"
        else:
            evidence = graph_evidence

        return score, reasoning, evidence

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
