"""LangGraph Workflow Builder.

Constructs and compiles the SurveyMAE evaluation workflow.
"""

import logging
from typing import Optional

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.core.config import SurveyMAEConfig
from src.core.state import SurveyState
from src.agents import (
    BaseAgent,
    CorrectorAgent,
    ExpertAgent,
    ReaderAgent,
    ReportAgent,
    VerifierAgent,
)
from src.graph.edges import should_continue_debate, should_end
from src.graph.nodes import run_debate

logger = logging.getLogger(__name__)


def create_workflow(
    config: Optional[SurveyMAEConfig] = None,
) -> StateGraph:
    """Create the SurveyMAE evaluation workflow graph.

    Args:
        config: Optional configuration for customization.

    Returns:
        Compiled StateGraph ready for execution.
    """
    # Create the state graph
    workflow = StateGraph(SurveyState)

    # Create evaluation agents
    agents = _create_agents(config)

    # Add nodes for each agent
    for agent in agents:
        workflow.add_node(
            agent.name,
            agent.process,
        )

    # Add PDF parsing node (placeholder)
    workflow.add_node("parse_pdf", _parse_pdf_node)

    # Add debate node
    workflow.add_node("debate", run_debate)

    # Define the workflow flow
    # 1. Start -> Parse PDF
    workflow.add_edge(START, "parse_pdf")

    # 2. Parse PDF -> Parallel agent evaluations
    workflow.add_edge("parse_pdf", "verifier")
    workflow.add_edge("parse_pdf", "expert")
    workflow.add_edge("parse_pdf", "reader")
    workflow.add_edge("parse_pdf", "corrector")

    # 3. Agent evaluations -> Check if debate needed
    workflow.add_conditional_edges(
        "verifier",
        should_end,
        {
            "END": "reporter",
            "debate": "debate",
        },
    )
    workflow.add_conditional_edges(
        "expert",
        should_end,
        {
            "END": "reporter",
            "debate": "debate",
        },
    )
    workflow.add_conditional_edges(
        "reader",
        should_end,
        {
            "END": "reporter",
            "debate": "debate",
        },
    )
    workflow.add_conditional_edges(
        "corrector",
        should_end,
        {
            "END": "reporter",
            "debate": "debate",
        },
    )

    # 4. Debate -> Continue or Reporter
    workflow.add_conditional_edges(
        "debate",
        should_continue_debate,
        {
            "continue": "debate",  # Another round
            "reporter": "reporter",
        },
    )

    # 5. Reporter -> END
    workflow.add_edge("reporter", END)

    return workflow


def compile_workflow(
    workflow: Optional[StateGraph] = None,
    config: Optional[SurveyMAEConfig] = None,
    checkpointer: Optional = None,
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


def _create_agents(config: Optional[SurveyMAEConfig] = None):
    """Create evaluation agents with optional configuration.

    Args:
        config: Optional configuration.

    Returns:
        List of agent instances.
    """
    # In a full implementation, agents would be configured from config
    agents = [
        VerifierAgent(),
        ExpertAgent(),
        ReaderAgent(),
        CorrectorAgent(),
        ReportAgent(),
    ]

    return agents


async def _parse_pdf_node(state: SurveyState) -> dict:
    """Parse the input PDF file.

    This is a placeholder that should be replaced with actual PDF parsing
    using tools like pymupdf4llm.

    Args:
        state: The current workflow state.

    Returns:
        Updated state with parsed content.
    """
    import logging

    logger = logging.getLogger(__name__)
    source_path = state.get("source_pdf_path", "")

    if not source_path:
        logger.warning("No source PDF path provided")
        return {"parsed_content": "", "metadata": {"error": "no_pdf_path"}}

    try:
        # Placeholder: In production, use pymupdf4llm or similar
        # Example:
        # import pymupdf4llm
        # content = pymupdf4llm.to_markdown(source_path)

        # For now, return empty content
        logger.info(f"Parsing PDF: {source_path}")
        parsed_content = f"[Parsed content from {source_path}]"

        return {
            "parsed_content": parsed_content,
            "metadata": {
                "source": source_path,
                "parsed": "true",
            },
        }

    except Exception as e:
        logger.error(f"Failed to parse PDF: {e}")
        return {
            "parsed_content": "",
            "metadata": {"error": str(e)},
        }
