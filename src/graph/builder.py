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
from typing import TYPE_CHECKING, Optional, Any

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
from src.core.log import log_pipeline_step
from src.core.state import SurveyState
from src.graph.edges import should_continue_debate, should_end
from src.graph.nodes import run_debate
from src.graph.nodes.evidence_collection import run_evidence_collection
from src.graph.nodes.evidence_dispatch import run_evidence_dispatch
from src.tools.pdf_parser import PDFParser, create_pdf_parser
from src.tools.result_store import ResultStore

logger = logging.getLogger("surveymae.graph")

# Shared PDF parser instance for workflow
_pdf_parser: Optional[PDFParser] = None

# Shared ResultStore instance for workflow
_result_store: Optional[ResultStore] = None


def _get_result_store(source_pdf_path: str = "", run_dir: str = "./output/runs") -> ResultStore:
    """Get or create the shared ResultStore instance.

    Args:
        source_pdf_path: Used to derive run_id if run_dir is not provided.
        run_dir: Explicit run directory (run_dir/run_id/). Takes precedence.
    """
    global _result_store
    if _result_store is None:
        run_id = None
        if source_pdf_path:
            import hashlib
            pdf_hash = hashlib.md5(source_pdf_path.encode()).hexdigest()[:8]
            from datetime import datetime, timezone
            run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{pdf_hash}"
        _result_store = ResultStore(base_dir=run_dir, run_id=run_id)
    return _result_store


def _init_metrics_index(config: Any = None) -> dict:
    """Initialize metrics_index for run.json.

    Returns the metrics_index structure recording指标血缘.
    """
    # Build metrics_index based on Plan v3 §3.4.3
    metrics_index = {
        "metrics": {
            # C Series (Citation integrity)
            "C3": {
                "name": "orphan_ref_rate",
                "computed_by": "CitationChecker",
                "source_file": "validation.json",
                "llm_involved": False,
                "hallucination_risk": None,
                "consumed_by": ["VerifierAgent.V1"]
            },
            "C5": {
                "name": "metadata_verify_rate",
                "computed_by": "CitationChecker.validate",
                "source_file": "validation.json",
                "llm_involved": False,
                "hallucination_risk": None,
                "consumed_by": ["VerifierAgent.V1"]
            },
            "C6": {
                "name": "citation_sentence_alignment",
                "computed_by": "CitationChecker.analyze_citation_sentence_alignment",
                "source_file": "c6_alignment.json",
                "llm_involved": True,
                "hallucination_risk": "low",
                "consumed_by": ["VerifierAgent.V2"]
            },
            # T Series (Temporal)
            "T1": {
                "name": "year_span",
                "computed_by": "CitationAnalyzer.compute_temporal_metrics",
                "source_file": "analysis.json",
                "llm_involved": False,
                "hallucination_risk": None,
                "consumed_by": ["ReaderAgent.R1"]
            },
            "T2": {
                "name": "foundational_retrieval_gap",
                "computed_by": "CitationAnalyzer + LiteratureSearch",
                "source_file": "analysis.json + trend_baseline.json",
                "llm_involved": True,
                "hallucination_risk": "low",
                "consumed_by": ["ReaderAgent.R1"]
            },
            "T3": {
                "name": "peak_year_ratio",
                "computed_by": "CitationAnalyzer.compute_temporal_metrics",
                "source_file": "analysis.json",
                "llm_involved": False,
                "hallucination_risk": None,
                "consumed_by": ["ReaderAgent.R1"]
            },
            "T4": {
                "name": "temporal_continuity",
                "computed_by": "CitationAnalyzer.compute_temporal_metrics",
                "source_file": "analysis.json",
                "llm_involved": False,
                "hallucination_risk": None,
                "consumed_by": ["ReaderAgent.R1"]
            },
            "T5": {
                "name": "trend_alignment",
                "computed_by": "CitationAnalyzer + LiteratureSearch",
                "source_file": "analysis.json + trend_baseline.json",
                "llm_involved": True,
                "hallucination_risk": "low",
                "consumed_by": ["ReaderAgent.R1"]
            },
            # S Series (Structural)
            "S1": {
                "name": "section_count",
                "computed_by": "CitationAnalyzer.compute_structural_metrics",
                "source_file": "analysis.json",
                "llm_involved": False,
                "hallucination_risk": None,
                "consumed_by": ["ReaderAgent.R3"]
            },
            "S2": {
                "name": "citation_density",
                "computed_by": "CitationAnalyzer.compute_structural_metrics",
                "source_file": "analysis.json",
                "llm_involved": False,
                "hallucination_risk": None,
                "consumed_by": ["ReaderAgent.R2"]
            },
            "S3": {
                "name": "citation_gini",
                "computed_by": "CitationAnalyzer.compute_structural_metrics",
                "source_file": "analysis.json",
                "llm_involved": False,
                "hallucination_risk": None,
                "consumed_by": ["ReaderAgent.R2"]
            },
            "S4": {
                "name": "zero_citation_section_rate",
                "computed_by": "CitationAnalyzer.compute_structural_metrics",
                "source_file": "analysis.json",
                "llm_involved": False,
                "hallucination_risk": None,
                "consumed_by": ["ReaderAgent.R2"]
            },
            "S5": {
                "name": "section_cluster_alignment",
                "computed_by": "CitationGraphAnalyzer.compute_section_cluster_alignment",
                "source_file": "graph_analysis.json",
                "llm_involved": False,
                "hallucination_risk": None,
                "consumed_by": ["ExpertAgent.E2", "ReaderAgent.R2", "ReaderAgent.R3"]
            },
            # G Series (Graph)
            "G1": {
                "name": "graph_density",
                "computed_by": "CitationGraphAnalyzer.analyze",
                "source_file": "graph_analysis.json",
                "llm_involved": False,
                "hallucination_risk": None,
                "consumed_by": ["ExpertAgent.E1"]
            },
            "G2": {
                "name": "connected_component_count",
                "computed_by": "CitationGraphAnalyzer.analyze",
                "source_file": "graph_analysis.json",
                "llm_involved": False,
                "hallucination_risk": None,
                "consumed_by": ["ExpertAgent.E1"]
            },
            "G3": {
                "name": "max_component_ratio",
                "computed_by": "CitationGraphAnalyzer.analyze",
                "source_file": "graph_analysis.json",
                "llm_involved": False,
                "hallucination_risk": None,
                "consumed_by": ["ExpertAgent.E1"]
            },
            "G4": {
                "name": "foundational_coverage_rate",
                "computed_by": "FoundationalCoverageAnalyzer.analyze",
                "source_file": "key_papers.json",
                "llm_involved": True,
                "hallucination_risk": "low",
                "consumed_by": ["ExpertAgent.E1"]
            },
            "G5": {
                "name": "cluster_count",
                "computed_by": "CitationGraphAnalyzer.analyze",
                "source_file": "graph_analysis.json",
                "llm_involved": False,
                "hallucination_risk": None,
                "consumed_by": ["ExpertAgent.E2"]
            },
            "G6": {
                "name": "isolated_node_ratio",
                "computed_by": "CitationGraphAnalyzer.analyze",
                "source_file": "graph_analysis.json",
                "llm_involved": False,
                "hallucination_risk": None,
                "consumed_by": ["ExpertAgent.E1"]
            }
        },
        "agent_dimensions": {
            "VerifierAgent": {
                "input_evidence": ["C3", "C5", "C6"],
                "output_dimensions": ["V1", "V2", "V4"],
                "corrector_targets": ["V4"]
            },
            "ExpertAgent": {
                "input_evidence": ["G1", "G2", "G3", "G4", "G5", "G6", "S5"],
                "output_dimensions": ["E1", "E2", "E3", "E4"],
                "corrector_targets": ["E2", "E3", "E4"]
            },
            "ReaderAgent": {
                "input_evidence": ["T1", "T2", "T3", "T4", "T5", "S1", "S2", "S3", "S4", "S5"],
                "output_dimensions": ["R1", "R2", "R3", "R4"],
                "corrector_targets": ["R2", "R3", "R4"]
            }
        }
    }

    return metrics_index


def _save_workflow_step(
    step_name: str,
    state: SurveyState,
    data: dict,
    input_state: Optional[SurveyState] = None,
    run_params: Optional[dict] = None,
) -> None:
    """Save workflow step data with incremental output (v3 design).

    For v3, step JSON files are saved to papers/{paper_id}/nodes/{step_name}.json
    and only contain incremental output.

    Args:
        step_name: Name of the workflow step
        state: Current workflow state
        data: Output data from the step
        input_state: Input state before the step (optional, not saved in v3)
        run_params: Run parameters used (optional)
    """
    try:
        import json
        from datetime import datetime, timezone

        store = _get_result_store(state.get("source_pdf_path", ""))
        source_path = state.get("source_pdf_path", "")
        if source_path:
            paper_id = store.register_paper(source_path)

            # Build step record (v3: incremental output only)
            step_record = {
                "step": step_name,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source_pdf": source_path,
            }

            # Add output data (v3: no input state saved)
            output_data = _sanitize_output_for_logging(data)

            # v3: Special handling for ref_metadata_cache
            # Reference it instead of including the full data
            if step_name == "02_evidence_collection":
                if "ref_metadata_cache" in output_data:
                    output_data["ref_metadata_cache"] = {
                        "_ref": "see validation.json",
                        "_note": "Full ref_metadata_cache stored in tool artifact"
                    }

            step_record["output"] = output_data

            # Add run parameters
            if run_params:
                step_record["run_params"] = run_params

            # Save to papers/{paper_id}/nodes/{step_name}.json
            store.save_node_step(paper_id, step_name, step_record)
            logger.info(f"Saved {step_name} to nodes/{step_name}.json")
    except Exception as e:
        logger.warning(f"Failed to save workflow step {step_name}: {e}")


def _sanitize_state_for_logging(state: SurveyState) -> dict: #FIXME: why truncate?
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
    # TODO: Consider more lenient truncation for large dict/list values (e.g., tool_evidence ~200KB).
    # Current truncation at 10000 chars can corrupt JSON and break downstream state reads
    # (e.g., tool_evidence becomes truncated JSON string, graph_analysis dict is lost).
    result = {}
    for key, value in data.items():
        if value is None:
            result[key] = None
        elif isinstance(value, str):
            # Truncate long strings
            result[key] = value[:5000] + "..." if len(value) > 5000 else value
        elif isinstance(value, (list, dict)):
            # Convert to JSON-serializable form without truncation
            try:
                import json
                json_str = json.dumps(value, ensure_ascii=False, default=str)
                result[key] = json.loads(json_str)  # Parse back to dict
            except Exception as e:
                logger.warning(f"Failed to serialize state value for key '{key}': {e}")
                result[key] = str(value)[:1000]
        else:
            result[key] = value
    return result


# Wrapper functions for workflow nodes to save intermediate results
async def _wrap_parse_pdf(state: SurveyState) -> dict:
    """Wrapper for parse_pdf node with result saving."""
    import time
    t0 = time.monotonic()
    input_state = dict(state)
    result = await _parse_pdf_node(state)
    _save_workflow_step(
        "01_parse_pdf", state,
        {"parsed_content": result.get("parsed_content", ""), "metadata": result.get("metadata", {})},
        input_state=input_state,
        run_params={"node": "parse_pdf"}
    )
    content = result.get("parsed_content", "")
    chars = len(content) if isinstance(content, str) else 0
    log_pipeline_step("01", 7, "parse_pdf", detail=f"{chars} chars", elapsed=time.monotonic() - t0)
    return result


async def _wrap_evidence_collection(state: SurveyState) -> dict:
    """Wrapper for evidence_collection node with result saving."""
    input_state = dict(state)
    # Get result store for tool artifact persistence (v3)
    store = _get_result_store(state.get("source_pdf_path", ""))
    try: #FIXME: recover when bug is fixed
        result = await run_evidence_collection(state, result_store=store)
    except Exception as e:
        logger.error(f"run_evidence_collection raised: {e}", exc_info=True)
        # Save error info so it persists in the step JSON
        _save_workflow_step(
            "02_evidence_collection", state,
            {
                "tool_evidence": {},
                "ref_metadata_cache": {},
                "topic_keywords": [],
                "field_trend_baseline": {},
                "candidate_key_papers": [],
                "warnings": [{"code": "EVIDENCE_COLLECTION_ERROR", "message": str(e)}],
            },
            input_state=input_state,
            run_params={"node": "evidence_collection", "error": str(e)}
        )
        raise
    _save_workflow_step(
        "02_evidence_collection", state, result,
        input_state=input_state,
        run_params={"node": "evidence_collection"}
    )
    return result


async def _wrap_evidence_dispatch(state: SurveyState) -> dict:
    """Wrapper for evidence_dispatch node with result saving."""
    import time
    t0 = time.monotonic()
    input_state = dict(state)
    result = await run_evidence_dispatch(state)
    _save_workflow_step(
        "03_evidence_dispatch", state, result,
        input_state=input_state,
        run_params={"node": "evidence_dispatch"}
    )
    specs = result.get("dispatch_specs", {})
    n_agents = len(specs)
    log_pipeline_step("03", 7, "evidence_dispatch", detail=f"{n_agents} agents dispatched", elapsed=time.monotonic() - t0)
    return result


async def _wrap_agent(agent_name: str, agent, state: SurveyState, step_prefix: str = "04") -> dict:
    """Wrapper for agent evaluation nodes with result saving."""
    import time
    t0 = time.monotonic()
    input_state = dict(state)
    result = await agent.process(state)
    _save_workflow_step(
        f"{step_prefix}_{agent_name}", state, result,
        input_state=input_state,
        run_params={"node": agent_name, "agent_class": agent.__class__.__name__}
    )
    elapsed = time.monotonic() - t0

    if step_prefix == "04":
        # Verifier / Expert / Reader: show sub-scores
        sub_scores = result.get("agent_outputs", {}).get(agent_name, {}).get("sub_scores", {})
        score_str = " ".join(
            f"{k}={v.get('score', '?')}" for k, v in sub_scores.items()
        ) if sub_scores else "no scores"
        log_pipeline_step("04", 7, agent_name, detail=score_str, elapsed=elapsed)
    elif step_prefix == "05":
        # Corrector
        corr_out = result.get("corrector_output", {})
        n_corrected = len(corr_out.get("corrections", {}))
        total_calls = corr_out.get("total_model_calls", 0)
        failed = corr_out.get("failed_calls", 0)
        log_pipeline_step("05", 7, "corrector", detail=f"{n_corrected} dims corrected, {total_calls} calls ({failed} failed)", elapsed=elapsed)
    elif step_prefix == "07":
        # Reporter
        report_len = len(result.get("final_report_md", ""))
        log_pipeline_step("07", 7, "reporter", detail=f"report {report_len} chars", elapsed=elapsed)

    return result


def _get_pdf_parser() -> PDFParser:
    """Get or create the shared PDF parser instance (MarkerApiParser or PDFParser)."""
    global _pdf_parser
    if _pdf_parser is None:
        try:
            from src.core.config import load_config
            cfg = load_config()
        except Exception:
            cfg = None
        _pdf_parser = create_pdf_parser(cfg)
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
    run_dir: str = "./output/runs",
) -> StateGraph:
    """Create the SurveyMAE evaluation workflow graph.

    According to Plan v3, the workflow structure is:
    1. parse_pdf -> Extract content and citations
    2. evidence_collection -> Execute all tools, build ref_metadata_cache
    3. evidence_dispatch -> Assemble Evidence Report for each agent
    4. Parallel agent evaluation -> verifier, expert, reader evaluate with evidence
    5. corrector -> Multi-model voting + variance computation
    6. aggregator -> Weighted aggregation
    7. reporter -> Generate final report

    Args:
        config:   Optional configuration for customization.
        run_dir:  Base directory for ResultStore (default: ./output/runs).

    Returns:
        Compiled StateGraph ready for execution.
    """
    # Initialize metrics_index and write to run.json
    metrics_index = _init_metrics_index(config)
    store = _get_result_store(run_dir=run_dir)
    if store:
        store._init_run_file(metrics_index=metrics_index)

    # Create the state graph
    workflow = StateGraph(SurveyState)

    # Get agent classes
    agent_classes = _get_agent_classes()

    # Create evaluation agents
    agents = _create_agents(config, agent_classes)

    # Add nodes for each agent (with wrapper for saving results)
    # Step numbers: 04=verifier/expert/reader, 05=corrector, 07=reporter
    STEP_PREFIXES = {
        "verifier": "04",
        "expert": "04",
        "reader": "04",
        "corrector": "05",
        "reporter": "07",
    }
    for agent in agents:
        step_prefix = STEP_PREFIXES.get(agent.name, "04")
        # Create a partial wrapper for this agent
        async def agent_node_wrapper(state: SurveyState, a=agent, sp=step_prefix):
            return await _wrap_agent(a.name, a, state, step_prefix=sp)
        workflow.add_node(agent.name, agent_node_wrapper)

    # Add PDF parsing node
    workflow.add_node("parse_pdf", _wrap_parse_pdf)

    # Add evidence collection node (Phase 2 new)
    workflow.add_node("evidence_collection", _wrap_evidence_collection)

    # Add evidence dispatch node (Phase 2 new)
    workflow.add_node("evidence_dispatch", _wrap_evidence_dispatch)

    # Add debate node
    workflow.add_node("debate", run_debate) #why still debate, already remove from v3?

    # Add a "gather" node to wait for all agents to complete
    workflow.add_node("gather", _gather_evaluations)

    # Add aggregator node (step 06)
    workflow.add_node("aggregator", _run_aggregator)

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

    # 7. gather -> Check if debate needed -> aggregator (or debate then aggregator)
    workflow.add_conditional_edges(
        "gather",
        should_end,
        {
            "END": "aggregator",
            "debate": "debate",
        },
    )

    # 8. Debate -> Continue or Aggregator
    workflow.add_conditional_edges(
        "debate",
        should_continue_debate,
        {
            "continue": "debate",  # Another round
            "reporter": "aggregator",
        },
    )

    # 9. Aggregator -> Reporter
    workflow.add_edge("aggregator", "reporter")

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
    """Parse the input PDF using the configured parser (MarkerApiParser or PDFParser).

    When using MarkerApiParser, also extracts section_headings from JSON structure.

    Args:
        state: The current workflow state.

    Returns:
        Updated state with parsed_content and section_headings.
    """
    source_path = state.get("source_pdf_path", "")

    if not source_path:
        logger.warning("No source PDF path provided")
        return {"parsed_content": "", "section_headings": [], "metadata": {"error": "no_pdf_path"}}

    if not Path(source_path).exists():
        logger.error(f"PDF file not found: {source_path}")
        return {
            "parsed_content": "",
            "section_headings": [],
            "metadata": {"error": "file_not_found", "path": source_path},
        }

    try:
        parser = _get_pdf_parser()
        parser_name = type(parser).__name__

        import asyncio
        from src.tools.marker_api_parser import MarkerApiParser, extract_section_headings_from_json
        from src.tools.pdf_parser import PDFParser
        
        if isinstance(parser, MarkerApiParser):
            logger.info("PDF 解析后端: MarkerAPI(mode=%s)", parser.mode)
            # 在线程池中运行同步解析，避免 DatalabClient 内部的 asyncio.run() 与 langgraph 的 event loop 冲突
            parsed_content, json_structure = await asyncio.to_thread(
                parser.parse_with_structure, source_path
            )
            section_headings = extract_section_headings_from_json(json_structure)
            logger.info("章节标题 %d 个: %s", len(section_headings), section_headings[:5])
        elif isinstance(parser, PDFParser):
            logger.info("PDF 解析后端: PyMuPDF4LLM(layout=%s)", parser.use_layout)
            # 使用 parse_with_structure 获取结构和章节标题
            parsed_content, structure = await asyncio.to_thread(
                parser.parse_with_structure, source_path
            )
            section_headings = structure.get("headings", [])
            logger.info("章节标题 %d 个: %s", len(section_headings), section_headings[:5])
        else:
            logger.info("PDF 解析后端: %s", parser_name)
            parsed_content = parser.parse(source_path)
            section_headings = []

        return {
            "parsed_content": parsed_content,
            "section_headings": section_headings,
            "metadata": {
                "source": source_path,
                "parsed": "true",
                "parser": parser_name,
            },
        }

    except Exception as e:
        logger.error(f"Failed to parse PDF: {e}")
        return {
            "parsed_content": "",
            "section_headings": [],
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


async def _run_aggregator(state: SurveyState) -> dict:
    """Run aggregation and save results to 06_aggregated_scores.json.

    This node performs the weighted aggregation of all agent scores
    and persists the result before reporter generates the final report.

    Args:
        state: The current workflow state.

    Returns:
        Dict containing aggregation_result for reporter to use.
    """
    from src.graph.nodes.aggregator import aggregate_scores

    import time
    t0 = time.monotonic()
    aggregation_result = await aggregate_scores(state)
    _save_workflow_step(
        "06_aggregator", state, aggregation_result,
        input_state=dict(state),
        run_params={"node": "aggregator", "step": "06"}
    )
    overall = aggregation_result.get("overall_score", 0.0)
    grade = aggregation_result.get("grade", "?")
    log_pipeline_step("06", 7, "aggregator", detail=f"overall={overall:.2f}/10 grade={grade}", elapsed=time.monotonic() - t0)
    return {"aggregation_result": aggregation_result}
