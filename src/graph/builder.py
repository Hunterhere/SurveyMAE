"""LangGraph Workflow Builder.

Constructs and compiles the SurveyMAE evaluation workflow.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

# Import agents lazily to avoid circular imports
if TYPE_CHECKING:
    from src.agents import (
        BaseAgent,
        CorrectorAgent,
        ExpertAgent,
        ReaderAgent,
        ReportAgent,
        VerifierAgent,
    )

from src.core.config import SurveyMAEConfig
from src.core.state import SurveyState
from src.graph.edges import should_continue_debate, should_end
from src.graph.nodes import run_debate
from src.tools.pdf_parser import PDFParser

logger = logging.getLogger(__name__)

# Shared PDF parser instance for workflow
_pdf_parser: Optional[PDFParser] = None


def _get_pdf_parser() -> PDFParser:
    """Get or create the shared PDF parser instance."""
    global _pdf_parser
    if _pdf_parser is None:
        _pdf_parser = PDFParser()
    return _pdf_parser


def _get_agent_classes():
    """Lazy load agent classes to avoid circular imports."""
    from src.agents import (
        CorrectorAgent,
        ExpertAgent,
        ReaderAgent,
        ReportAgent,
        VerifierAgent,
    )
    return {
        "verifier": VerifierAgent,
        "expert": ExpertAgent,
        "reader": ReaderAgent,
        "corrector": CorrectorAgent,
        "reporter": ReportAgent,
    }


def create_workflow(
    config: Optional[SurveyMAEConfig] = None,
) -> StateGraph:
    """Create the SurveyMAE evaluation workflow graph.

    The workflow follows this structure:
    1. Parse PDF -> Extract content and citations
    2. Parallel Agent Evaluation -> All 4 agents evaluate the survey
    3. Check for Debate -> If score variance is high, enter debate
    4. Report Generation -> Aggregate results and generate final report

    Args:
        config: Optional configuration for customization.

    Returns:
        Compiled StateGraph ready for execution.
    """
    # Create the state graph
    workflow = StateGraph(SurveyState)

    # Get agent classes
    agent_classes = _get_agent_classes()

    # Create evaluation agents
    agents = _create_agents(config, agent_classes)

    # Add nodes for each agent
    for agent in agents:
        workflow.add_node(
            agent.name,
            agent.process,
        )

    # Add PDF parsing node
    workflow.add_node("parse_pdf", _parse_pdf_node)

    # Add debate node
    workflow.add_node("debate", run_debate)

    # Add a "gather" node to wait for all agents to complete
    workflow.add_node("gather", _gather_evaluations)

    # Define the workflow flow
    # 1. Start -> Parse PDF
    workflow.add_edge(START, "parse_pdf")

    # 2. Parse PDF -> Parallel agent evaluations (all 4 agents)
    workflow.add_edge("parse_pdf", "verifier")
    workflow.add_edge("parse_pdf", "expert")
    workflow.add_edge("parse_pdf", "reader")
    workflow.add_edge("parse_pdf", "corrector")

    # 3. All agents -> gather (wait for all to complete)
    workflow.add_edge("verifier", "gather")
    workflow.add_edge("expert", "gather")
    workflow.add_edge("reader", "gather")
    workflow.add_edge("corrector", "gather")

    # 4. gather -> Check if debate needed -> debate or reporter
    workflow.add_conditional_edges(
        "gather",
        should_end,
        {
            "END": "reporter",
            "debate": "debate",
        },
    )

    # 5. Debate -> Continue or Reporter
    workflow.add_conditional_edges(
        "debate",
        should_continue_debate,
        {
            "continue": "debate",  # Another round
            "reporter": "reporter",
        },
    )

    # 6. Reporter -> END
    workflow.add_edge("reporter", END)

    return workflow


def compile_workflow(
    workflow: Optional[StateGraph] = None,
    config: Optional[SurveyMAEConfig] = None,
    checkpointer: Optional[MemorySaver] = None,
):
    """Compile the workflow with optional configuration.

    Args:
        workflow: Optional pre-created StateGraph.
        config: Optional configuration.
        checkpointer: Optional checkpointer for state persistence.

    Returns:
        Compiled graph ready for invocation.
    """
    if workflow is None:
        workflow = create_workflow(config)

    # Use memory checkpointer by default
    checkpointer = checkpointer or MemorySaver()

    compiled = workflow.compile(checkpointer=checkpointer)

    logger.info("SurveyMAE workflow compiled successfully")
    return compiled


def _create_agents(config, agent_classes):
    """Create evaluation agents with optional configuration.

    Args:
        config: Optional configuration.
        agent_classes: Dict of agent name to class.

    Returns:
        List of agent instances.
    """
    # In a full implementation, agents would be configured from config
    agents = [
        agent_classes["verifier"](),
        agent_classes["expert"](),
        agent_classes["reader"](),
        agent_classes["corrector"](),
        agent_classes["reporter"](),
    ]

    return agents


async def _parse_pdf_node(state: SurveyState) -> dict:
    """Parse the input PDF file using PDFParser.

    Uses the shared PDFParser instance which supports pymupdf4llm
    with fallback to pypdf.

    Args:
        state: The current workflow state.

    Returns:
        Updated state with parsed content.
    """
    source_path = state.get("source_pdf_path", "")

    if not source_path:
        logger.warning("No source PDF path provided")
        return {"parsed_content": "", "metadata": {"error": "no_pdf_path"}}

    if not Path(source_path).exists():
        logger.error(f"PDF file not found: {source_path}")
        return {"parsed_content": "", "metadata": {"error": "file_not_found", "path": source_path}}

    try:
        logger.info(f"Parsing PDF: {source_path}")
        # Use PDFParser (which uses pymupdf4llm with fallback)
        parser = _get_pdf_parser()
        parsed_content = parser.parse(source_path)

        return {
            "parsed_content": parsed_content,
            "metadata": {
                "source": source_path,
                "parsed": "true",
                "parser": "PDFParser",
            },
        }

    except Exception as e:
        logger.error(f"Failed to parse PDF: {e}")
        return {
            "parsed_content": "",
            "metadata": {"error": str(e)},
        }


async def _gather_evaluations(state: SurveyState) -> dict:
    """Gather all evaluations and check if we have all results.

    This is a pass-through node that ensures all parallel agents
    have completed before making the debate decision.

    Args:
        state: The current workflow state.

    Returns:
        Empty dict - state already contains evaluations.
    """
    evaluations = state.get("evaluations", [])
    logger.info(f"Gathered {len(evaluations)} evaluations")

    # Return empty dict - the state already has all evaluations
    return {}
