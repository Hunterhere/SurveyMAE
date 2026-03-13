"""LangGraph Workflow Builder.

Constructs and compiles the SurveyMAE evaluation workflow.

According to Plan v2, the workflow structure is:
1. parse_pdf -> Extract content and citations
2. evidence_collection -> Execute all tools, build ref_metadata_cache
3. evidence_dispatch -> Assemble Evidence Report for each agent
4. Parallel agent evaluation -> verifier, expert, reader evaluate with evidence
5. corrector -> Multi-model voting + variance computation
6. Check for Debate -> If score variance is high, enter debate
7. reporter -> Generate final report with variance display
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
from src.graph.nodes.evidence_collection import run_evidence_collection
from src.graph.nodes.evidence_dispatch import run_evidence_dispatch
from src.tools.pdf_parser import PDFParser
from src.tools.result_store import ResultStore

logger = logging.getLogger(__name__)

# Shared PDF parser instance for workflow
_pdf_parser: Optional[PDFParser] = None

# Shared ResultStore instance for workflow
_result_store: Optional[ResultStore] = None


def _get_result_store(source_pdf_path: str = "") -> ResultStore:
    """Get or create the shared ResultStore instance."""
    global _result_store
    if _result_store is None:
        # Generate run_id based on source PDF
        run_id = None
        if source_pdf_path:
            import hashlib
            pdf_hash = hashlib.md5(source_pdf_path.encode()).hexdigest()[:8]
            from datetime import datetime, timezone
            run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{pdf_hash}"
        _result_store = ResultStore(base_dir="./output/runs", run_id=run_id)
    return _result_store


def _save_workflow_step(
    step_name: str,
    state: SurveyState,
    data: dict,
    input_state: Optional[SurveyState] = None,
    run_params: Optional[dict] = None,
) -> None:
    """Save workflow step data with full input/output/params to ResultStore.

    Args:
        step_name: Name of the workflow step
        state: Current workflow state
        data: Output data from the step
        input_state: Input state before the step (optional)
        run_params: Run parameters used (optional)
    """
    try:
        import json
        from datetime import datetime, timezone

        store = _get_result_store(state.get("source_pdf_path", ""))
        source_path = state.get("source_pdf_path", "")
        if source_path:
            paper_id = store.register_paper(source_path)

            # Build comprehensive step record
            step_record = {
                "step": step_name,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source_pdf": source_path,
            }

            # Add input state (sanitized - remove large content)
            if input_state:
                sanitized_input = _sanitize_state_for_logging(input_state)
                step_record["input"] = sanitized_input

            # Add output data
            step_record["output"] = _sanitize_output_for_logging(data)

            # Add run parameters
            if run_params:
                step_record["run_params"] = run_params

            # Save step data
            step_file = store.papers_dir / paper_id / f"{step_name}.json"
            step_file.parent.mkdir(parents=True, exist_ok=True)
            step_file.write_text(json.dumps(step_record, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"Saved {step_name} to {step_file}")
    except Exception as e:
        logger.warning(f"Failed to save workflow step {step_name}: {e}")


def _sanitize_state_for_logging(state: SurveyState) -> dict:
    """Sanitize state for logging - truncate large content but keep structure."""
    result = {}
    for key, value in state.items():
        if value is None:
            result[key] = None
        elif isinstance(value, str):
            # Truncate long strings
            result[key] = value[:2000] + "..." if len(value) > 2000 else value
        elif isinstance(value, (list, tuple)):
            # For lists, show length and first few items
            if len(value) > 5:
                result[key] = {
                    "_type": "list",
                    "_length": len(value),
                    "_preview": value[:3],
                }
            else:
                result[key] = value
        elif isinstance(value, dict):
            # For dicts, sanitize each key
            sanitized = {}
            for k, v in value.items():
                if isinstance(v, str) and len(v) > 500:
                    sanitized[k] = v[:500] + "..."
                else:
                    sanitized[k] = v
            result[key] = sanitized
        else:
            # Other types - convert to string
            result[key] = str(value)[:500] if str(value) else None
    return result


def _sanitize_output_for_logging(data: dict) -> dict:
    """Sanitize output data for logging - truncate long content."""
    result = {}
    for key, value in data.items():
        if value is None:
            result[key] = None
        elif isinstance(value, str):
            # Truncate long strings
            result[key] = value[:5000] + "..." if len(value) > 5000 else value
        elif isinstance(value, (list, dict)):
            # Convert to JSON-serializable form
            try:
                import json
                json_str = json.dumps(value, ensure_ascii=False, default=str)
                if len(json_str) > 10000:
                    result[key] = json_str[:10000] + "...[truncated]"
                else:
                    result[key] = json.loads(json_str)  # Parse back to dict
            except:
                result[key] = str(value)[:1000]
        else:
            result[key] = value
    return result


# Wrapper functions for workflow nodes to save intermediate results
async def _wrap_parse_pdf(state: SurveyState) -> dict:
    """Wrapper for parse_pdf node with result saving."""
    # Capture input state
    input_state = dict(state)
    result = await _parse_pdf_node(state)
    _save_workflow_step(
        "01_parse_pdf", state,
        {"parsed_content": result.get("parsed_content", ""), "metadata": result.get("metadata", {})},
        input_state=input_state,
        run_params={"node": "parse_pdf"}
    )
    return result


async def _wrap_evidence_collection(state: SurveyState) -> dict:
    """Wrapper for evidence_collection node with result saving."""
    input_state = dict(state)
    result = await run_evidence_collection(state)
    _save_workflow_step(
        "02_evidence_collection", state, result,
        input_state=input_state,
        run_params={"node": "evidence_collection"}
    )
    return result


async def _wrap_evidence_dispatch(state: SurveyState) -> dict:
    """Wrapper for evidence_dispatch node with result saving."""
    input_state = dict(state)
    result = await run_evidence_dispatch(state)
    _save_workflow_step(
        "03_evidence_dispatch", state, result,
        input_state=input_state,
        run_params={"node": "evidence_dispatch"}
    )
    return result


async def _wrap_agent(agent_name: str, agent, state: SurveyState) -> dict:
    """Wrapper for agent evaluation nodes with result saving."""
    input_state = dict(state)
    result = await agent.process(state)
    _save_workflow_step(
        f"04_{agent_name}", state, result,
        input_state=input_state,
        run_params={"node": agent_name, "agent_class": agent.__class__.__name__}
    )
    return result
    return result


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

    According to Plan v2, the workflow structure is:
    1. parse_pdf -> Extract content and citations
    2. evidence_collection -> Execute all tools, build ref_metadata_cache
    3. evidence_dispatch -> Assemble Evidence Report for each agent
    4. Parallel agent evaluation -> verifier, expert, reader evaluate with evidence
    5. corrector -> Multi-model voting + variance computation
    6. Check for Debate -> If score variance is high, enter debate
    7. reporter -> Generate final report with variance display

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

    # Add nodes for each agent (with wrapper for saving results)
    for agent in agents:
        # Create a partial wrapper for this agent
        async def agent_node_wrapper(state: SurveyState, a=agent):
            return await _wrap_agent(a.name, a, state)
        workflow.add_node(agent.name, agent_node_wrapper)

    # Add PDF parsing node
    workflow.add_node("parse_pdf", _wrap_parse_pdf)

    # Add evidence collection node (Phase 2 new)
    workflow.add_node("evidence_collection", _wrap_evidence_collection)

    # Add evidence dispatch node (Phase 2 new)
    workflow.add_node("evidence_dispatch", _wrap_evidence_dispatch)

    # Add debate node
    workflow.add_node("debate", run_debate)

    # Add a "gather" node to wait for all agents to complete
    workflow.add_node("gather", _gather_evaluations)

    # Define the workflow flow
    # 1. Start -> Parse PDF
    workflow.add_edge(START, "parse_pdf")

    # 2. Parse PDF -> Evidence Collection (unified tool execution)
    workflow.add_edge("parse_pdf", "evidence_collection")

    # 3. Evidence Collection -> Evidence Dispatch
    workflow.add_edge("evidence_collection", "evidence_dispatch")

    # 4. Evidence Dispatch -> Parallel agent evaluations (verifier, expert, reader)
    workflow.add_edge("evidence_dispatch", "verifier")
    workflow.add_edge("evidence_dispatch", "expert")
    workflow.add_edge("evidence_dispatch", "reader")

    # Note: corrector runs after other agents, gets their outputs
    # 5. After verifier/expert/reader complete -> corrector for variance computation
    workflow.add_edge("verifier", "corrector")
    workflow.add_edge("expert", "corrector")
    workflow.add_edge("reader", "corrector")

    # 6. Corrector -> gather (wait for all to complete)
    workflow.add_edge("corrector", "gather")

    # 7. gather -> Check if debate needed -> debate or reporter
    workflow.add_conditional_edges(
        "gather",
        should_end,
        {
            "END": "reporter",
            "debate": "debate",
        },
    )

    # 8. Debate -> Continue or Reporter
    workflow.add_conditional_edges(
        "debate",
        should_continue_debate,
        {
            "continue": "debate",  # Another round
            "reporter": "reporter",
        },
    )

    # 9. Reporter -> END
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
    from src.core.config import AgentConfig, LLMConfig, SurveyMAEConfig, load_model_config

    # Load config if not provided
    if config is None:
        # Use default config path
        import os
        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "config", "main.yaml")
        config = SurveyMAEConfig.from_yaml(config_path)

    # Get LLM config from config
    llm_config = config.llm if config else None

    # Load model config from models.yaml for multi-model settings
    model_config = load_model_config()

    # Create agent configs with LLM settings
    agent_configs = {
        name: AgentConfig(name=name, llm=llm_config)
        for name in ["verifier", "expert", "reader", "corrector", "reporter"]
    }

    # Get multi_model config for corrector from models.yaml and set in agent_config
    if model_config.agents:
        corrector_cfg = model_config.agents.get("corrector")
        if corrector_cfg and corrector_cfg.multi_model:
            agent_configs["corrector"].multi_model = corrector_cfg.multi_model

    # Create agents with configuration
    agents = [
        agent_classes["verifier"](config=agent_configs["verifier"]),
        agent_classes["expert"](config=agent_configs["expert"]),
        agent_classes["reader"](config=agent_configs["reader"]),
        agent_classes["corrector"](config=agent_configs["corrector"]),
        agent_classes["reporter"](config=agent_configs["reporter"]),
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
