# SurveyMAE Developer Guide

> **Document version**: v4.0 (2026-04-27)
> **Checked against**: `src/`, `config/`, `tests/`, `scripts/`, and the latest run directory `output/runs/20260423T153603Z_dab99f59`
> **Purpose**: This guide is for developers and AI maintainers who need to understand the project structure, find important interfaces quickly, and inspect configuration fields and output artifacts. The README is only the entry point; this document is the detailed development reference.

## Table of Contents

| Section | Purpose |
|---------|---------|
| [1. Project Overview](#1-project-overview) | Understand SurveyMAE's goal, evaluation layers, and current implementation boundaries |
| [2. Quick Run](#2-quick-run) | Install, configure, run the CLI, start GROBID, and run common tests |
| [3. Code Structure Quick Reference](#3-code-structure-quick-reference) | Locate entry points, state, graph nodes, agents, tools, and tests |
| [4. Workflow and Data Flow](#4-workflow-and-data-flow) | LangGraph nodes, runtime state, evidence artifacts, and report generation |
| [5. Configuration System](#5-configuration-system) | `main.yaml`, `models.yaml`, `search_engines.yaml`, and `.env` fields |
| [6. Metrics and Agent Mapping](#6-metrics-and-agent-mapping) | 19 tool metrics, 11 agent sub-dimensions, and Corrector voting targets |
| [7. Key Interface Reference](#7-key-interface-reference) | Common classes, functions, input/output fields, and extension points |
| [8. Output Directories and Run Artifacts](#8-output-directories-and-run-artifacts) | Real `output/runs/...` file layout and JSON fields |
| [9. Secondary Development Guide](#9-secondary-development-guide) | Add metrics, sub-dimensions, agents, tools, search sources, and report fields |
| [10. Testing and Quality Checks](#10-testing-and-quality-checks) | Unit tests, integration tests, external dependencies, and code quality commands |
| [11. FAQ](#11-faq) | Debug configuration, GROBID, output directories, scoring, and search fallback |

---

## 1. Project Overview

SurveyMAE is a LangGraph-based multi-agent evaluation framework for assessing the quality of LLM-generated academic surveys. The current implementation follows this main path: collect tool evidence first, let agents score from that evidence, let Corrector re-check high-risk dimensions, and let Reporter generate the final report.

### 1.1 Three-Layer Evaluation Structure

| Layer | Output | Main files |
|-------|--------|------------|
| Tool evidence layer | C/T/S/G metrics, citation extraction, validation, citation graph, foundational coverage | `src/graph/nodes/evidence_collection.py`, `src/tools/*` |
| Agent judgment layer | 11 sub-dimension scores from Verifier / Expert / Reader | `src/agents/base.py`, `src/graph/nodes/evidence_dispatch.py` |
| Aggregation and reporting layer | Corrector corrections, weighted total score, Markdown report, `run_summary.json` | `src/agents/corrector.py`, `src/graph/nodes/aggregator.py`, `src/agents/reporter.py` |

### 1.2 Current Agents and Responsibilities

| Agent | Dimension | Sub-dimensions | Responsibility |
|-------|-----------|----------------|----------------|
| VerifierAgent | factuality | V1, V2, V4 | Citation existence, citation-claim alignment, internal consistency |
| ExpertAgent | academic_depth | E1-E4 | Core literature coverage, classification quality, technical accuracy, critical depth |
| ReaderAgent | readability | R1-R4 | Timeliness, information distribution, structural clarity, writing quality |
| CorrectorAgent | correction | No independent scoring dimension | Multi-model voting for medium/high hallucination-risk dimensions; writes `corrector_output` |
| ReportAgent | report_generation | No scoring dimension | Calls aggregation logic, generates Markdown and `run_summary.json` |

### 1.3 Scoring Semantics

The current score contract uses **0-5 / 1-5 semantics**:

- Agent sub-dimension outputs are `1-5`.
- `EvaluationRecordModel.score` validates `[0.0, 5.0]`.
- The aggregated total remains on `0-5`; it is no longer converted to `0-10`.
- Grade thresholds are defined in `src/graph/nodes/aggregator.py::_get_grade()`: `A >= 4.25`, `B >= 3.75`, `C >= 3.25`, `D >= 2.75`, otherwise `F`.

---

## 2. Quick Run

### 2.1 Requirements

- Python 3.12+
- `uv`
- Optional: Docker, for running GROBID
- Optional: Datalab Marker API key, for the `marker_api` PDF parsing backend

### 2.2 Install and Local Environment

```bash
uv sync
cp .env.example .env
```

Fill in your own API keys in the local `.env` file. Do not commit `.env`; `.env.example` should only contain field names.

Common environment variables:

```bash
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
KIMI_API_KEY=
DASHSCOPE_API_KEY=
ZHIPU_API_KEY=
STEP_API_KEY=
DEEPSEEK_API_KEY=
GOOGLE_API_KEY=
BYTEAPI_KEY=
SEMANTIC_SCHOLAR_API_KEY=
OPENALEX_EMAIL=
DATALAB_API_KEY=
GROBID_URL=
SURVEYMAE_OUTPUT_DIR=
```

### 2.3 CLI Usage

The entry point is `src/main.py`. The CLI currently supports `.pdf` and `.md` inputs:

```bash
uv run python -m src.main path/to/survey.pdf
uv run python -m src.main path/to/survey.md
uv run python -m src.main path/to/survey.pdf -c config/main.yaml
uv run python -m src.main path/to/survey.pdf -o ./output
uv run python -m src.main path/to/survey.pdf -v
uv run python -m src.main path/to/survey.pdf -q
uv run python -m src.main path/to/survey.pdf --log-level DEBUG
```

`-v` and `-q` are mutually exclusive. An explicit `--log-level` has the highest priority.

### 2.4 Optional GROBID Backend

GROBID improves reference extraction and CrossRef DOI completion. In the current `config/main.yaml`, `citation.backend` defaults to `grobid`.

```bash
docker pull grobid/grobid:0.9.0-crf
```

Windows PowerShell:

```powershell
.\scripts\grobid.ps1 -Action start
.\scripts\grobid.ps1 -Action status
.\scripts\grobid.ps1 -Action stop
```

Linux/macOS shell:

```bash
scripts/grobid.sh start
scripts/grobid.sh status
scripts/grobid.sh stop
```

The default service URL is `http://localhost:8070`. Related fields in `config/main.yaml`:

```yaml
citation:
  backend: grobid          # grobid | auto | mupdf
  grobid_url: http://localhost:8070
  grobid_timeout_s: 60
  grobid_consolidate: true
```

### 2.5 Common Test Commands

```bash
uv run pytest tests/unit
uv run pytest tests/unit/test_evidence_dispatch.py
uv run pytest tests/integration/test_citation_graph_pipeline.py
uv run ruff format .
uv run ruff check .
uv run mypy src/
```

---

## 3. Code Structure Quick Reference

```text
SurveyMAE/
├── config/
│   ├── main.yaml                 # Main workflow, PDF, citation, evidence, agent, MCP, aggregation, and report config
│   ├── models.yaml               # Provider, agent, tool, and multi-model voting config
│   ├── search_engines.yaml       # Literature search sources, concurrency, retry, and fallback strategy
│   └── prompts/                  # verifier/expert/reader/corrector/reporter/citation_alignment prompts
├── docs/
│   ├── DEVELOPER_GUIDE.md        # English developer guide
│   ├── DEVELOPER_GUIDE.zh-CN.md  # Chinese developer guide
│   └── README.zh-CN.md           # Chinese README
├── scripts/
│   ├── grobid.ps1                # Windows GROBID container helper
│   ├── grobid.sh                 # Linux/macOS GROBID container helper
│   ├── run_evaluation.ps1/.sh    # Evaluation helper scripts
│   └── render_citation_graph_pyvis.py
├── src/
│   ├── main.py                   # CLI and run_evaluation()
│   ├── core/                     # Config, state, logging, MCP client, search config
│   ├── agents/                   # BaseAgent, Verifier, Expert, Reader, Corrector, Reporter
│   ├── graph/                    # LangGraph builder, edges, nodes
│   ├── tools/                    # PDF, citation, search, graph analysis, result store
│   └── web/                      # Local web viewer
├── tests/
│   ├── unit/
│   └── integration/
└── output/runs/                  # Run artifacts
```

### 3.1 Core File Responsibilities

| File | Responsibility |
|------|----------------|
| `src/main.py` | Loads `.env`, parses CLI args, initializes logging, creates the workflow, saves the final report |
| `src/core/config.py` | Pydantic config models and `load_config()` / `load_model_config()` |
| `src/core/search_config.py` | Parses concurrency search config from `config/search_engines.yaml` |
| `src/core/state.py` | `SurveyState`, `ToolEvidence`, `AgentOutput`, `AggregatedScores`, and related state types |
| `src/core/log.py` | Rich console, file logging, `summary.log`, `RunStats` |
| `src/graph/builder.py` | LangGraph nodes and edges, ResultStore initialization, node output persistence |
| `src/graph/nodes/evidence_collection.py` | Unified tool-evidence collection |
| `src/graph/nodes/evidence_dispatch.py` | `METRIC_REGISTRY`, `AGENT_REGISTRY`, `dispatch_specs` |
| `src/graph/nodes/aggregator.py` | Weighted aggregation and Markdown report rendering functions |
| `src/agents/base.py` | Shared LLM calls, prompt loading, dispatch_specs-driven sub-dimension scoring |
| `src/agents/corrector.py` | Multi-model voting correction; outputs `corrector_output` |
| `src/agents/reporter.py` | Calls aggregation, generates the final report, writes `run_summary.json` |
| `src/tools/result_store.py` | File-based persistence under `output/runs` |

---

## 4. Workflow and Data Flow

### 4.1 LangGraph Node Order

`src/graph/builder.py::create_workflow()` defines the current graph:

```text
START
  -> parse_pdf
  -> evidence_collection
  -> evidence_dispatch
  -> verifier / expert / reader
  -> corrector
  -> gather
  -> aggregator
  -> reporter
  -> END
```

The code still keeps a `debate` node and conditional edges, but the current main path is Corrector + Aggregator.

### 4.2 Node Responsibilities and Outputs

| Step | Node/function | State fields written | Artifacts |
|------|---------------|----------------------|-----------|
| 01 | `_parse_pdf_node()` | `parsed_content`, `section_headings`, `metadata` | `nodes/01_parse_pdf.json` |
| 02 | `run_evidence_collection()` | `tool_evidence`, `ref_metadata_cache`, `topic_keywords`, `field_trend_baseline`, `candidate_key_papers` | `tools/*.json`, `nodes/02_evidence_collection.json` |
| 03 | `run_evidence_dispatch()` | `dispatch_specs`, `metrics_index` | `nodes/03_evidence_dispatch.json` |
| 04 | `BaseAgent.process()` | `evaluations`, `agent_outputs` | `nodes/04_verifier.json`, etc. |
| 05 | `CorrectorAgent.process()` | `corrector_output` | `nodes/05_corrector.json` |
| 06 | `_run_aggregator()` / `aggregate_scores()` | `aggregated_scores` | `nodes/06_aggregator.json` |
| 07 | `ReportAgent.process()` | `final_report_md`, `overall_score`, `grade`, `run_summary` | `nodes/07_reporter.json`, `run_summary.json`, `reports/*.md` |

### 4.3 `SurveyState` Field Groups

`src/core/state.py::SurveyState` is the LangGraph state contract:

| Field | Type/meaning | Main writer |
|-------|--------------|-------------|
| `source_pdf_path` | Input source path; currently supports `.pdf` / `.md` | `main.py` |
| `parsed_content` | Markdown/text body | `main.py`, `parse_pdf` |
| `section_headings` | Section heading list | `parse_pdf` |
| `tool_evidence` | Aggregated tool evidence | `evidence_collection` |
| `ref_metadata_cache` | Reference metadata cache | `evidence_collection` |
| `topic_keywords` | LLM or fallback topic keywords | `evidence_collection` |
| `field_trend_baseline` | Field-level yearly trend | `evidence_collection` |
| `candidate_key_papers` | G4 candidate key papers | `evidence_collection` |
| `evaluations` | Legacy-compatible agent evaluation records; accumulated with `operator.add` | Agent nodes |
| `agent_outputs` | New structured agent outputs; merged with `dict_merge` | Agent nodes |
| `corrector_output` | Multi-model correction output | Corrector |
| `aggregated_scores` | Aggregated dimension scores | Aggregator/Reporter |
| `dispatch_specs` | Exact per-agent contexts | Evidence Dispatch |
| `metrics_index` | Metric lineage index | Builder/Evidence Dispatch |
| `final_report_md` | Final Markdown report | Reporter |

### 4.4 `tool_evidence` Structure

`ToolEvidence` is a flattened in-memory aggregate view:

```python
tool_evidence = {
    "extraction": {...},
    "validation": {...},
    "c6_alignment": {...},
    "analysis": {
        "T1_year_span": ...,
        "T2_foundational_retrieval_gap": ...,
        "T3_peak_year_ratio": ...,
        "T4_temporal_continuity": ...,
        "T5_trend_alignment": ...,
        "year_distribution": {...},
        "S1_section_count": ...,
        "S2_citation_density": ...,
        "S3_citation_gini": ...,
        "S4_zero_citation_section_rate": ...,
    },
    "graph_analysis": {
        "G1_density": ...,
        "G2_components": ...,
        "G3_lcc_frac": ...,
        "G4_coverage_rate": ...,
        "G5_clusters": ...,
        "G6_isolates": ...,
        "S5_nmi": ...,
        "S5_ari": ...,
        "missing_key_papers": [...],
        "suspicious_centrality": [...],
    },
}
```

Note: raw `tools/graph_analysis.json` has `citation_graph_analysis` as its outer object. `tool_evidence.graph_analysis` is the flattened metric view extracted by Evidence Collection for Evidence Dispatch.

---

## 5. Configuration System

### 5.1 `config/main.yaml`

Parsed by `src/core/config.py::SurveyMAEConfig`. Key sections:

| Section | Model | Description |
|---------|-------|-------------|
| `general` | `dict` | Debug and default log level |
| `llm` | `LLMConfig` | Default LLM config; used as the base config when creating agents |
| `pdf_parser` | `PdfParserConfig` | PDF backend: `marker_api`, `pymupdf4llm`, `auto` |
| `citation` | `CitationConfig` | Citation backend: `grobid`, `auto`, `mupdf` |
| `evidence` | `EvidenceConfig` | G4, T-series, S5, C6, and sampling parameters |
| `agents` | `list[AgentConfig]` | Prompt path, tools, retries, timeout |
| `mcp_servers` | `list[MCPServerConfig]` | Local or remote MCP server definitions |
| `aggregation` | `AggregationConfig` | Weights for the 11 sub-dimensions |
| `persistence` | Stored in YAML | Schema and tool artifact persistence intent |
| `report` | `ReportConfig` | Report output directory and format |

Current default PDF parsing config:

```yaml
pdf_parser:
  backend: "marker_api"
  marker_api:
    base_url: "https://www.datalab.to"
    mode: "balanced"
    include_markdown_in_chunks: true
    additional_config:
      keep_pageheader_in_output: false
      keep_pagefooter_in_output: false
  pymupdf4llm:
    use_layout: true
    show_header: false
    show_footer: false
  cache_dir: "./output/pdf_cache"
```

### 5.2 `config/models.yaml`

Parsed by `load_model_config()`. Core fields:

| Field | Description |
|-------|-------------|
| `default` | Default provider/model/temperature/max_tokens |
| `tools.citation_checker` | Model for C6 citation-sentence alignment |
| `tools.keyword_extractor` | Model for topic keyword extraction |
| `agents.verifier/expert/reader` | Models for the three scoring agents |
| `agents.corrector.multi_model` | Corrector multi-model voting list |
| `agents.reporter` | Reporter agent config |
| `providers.*.base_url` | OpenAI-compatible endpoint |
| `providers.*.env_key` | Environment variable name for the API key |

`ModelConfig.get_agent_config(agent_name)` and `get_tool_config(tool_name)` fill in `base_url` and `api_key`.

### 5.3 `config/search_engines.yaml`

Parsed by `src/core/search_config.py::load_search_engine_config()`, then used by `ParallelDispatcher` and `LiteratureSearch`.

```yaml
verify_limit: 100
api_timeout_seconds: 15

concurrency:
  max_concurrent_sources: 3
  merge_strategy: weighted_union
  per_source_timeout_seconds: 10

degradation:
  fallback_order: [crossref, dblp, openalex]
  on_all_failed: empty

sources:
  semantic_scholar:
    enabled: true
    priority: 1
    concurrent: true
    api_key: ${SEMANTIC_SCHOLAR_API_KEY}
```

Merge strategies:

| Strategy | Behavior |
|----------|----------|
| `first_wins` | Use the first non-empty result; favors latency |
| `union` | Merge all source results and deduplicate |
| `weighted_union` | Prefer high-priority sources and use lower-priority sources to fill gaps |

### 5.4 Prompt Templates

Prompt files live in `config/prompts/`. `BaseAgent._load_prompt(prompt_name, **kwargs)` reads the YAML `template` or `prompt` field.

Detailed rubrics for the three scoring agents are not hard-coded in the prompt YAML files. They are injected into `dispatch_specs` from `evidence_dispatch.py::AGENT_REGISTRY`.

---

## 6. Metrics and Agent Mapping

### 6.1 Tool Metric Registry

`src/graph/nodes/evidence_dispatch.py::METRIC_REGISTRY` is the runtime source of truth for the 19 first-layer metrics.

| Metric | Name | Source | Extract path | Consumer |
|--------|------|--------|--------------|----------|
| C3 | orphan_ref_rate | CitationChecker | `validation.C3_orphan_ref_rate` | V1 |
| C5 | metadata_verify_rate | CitationChecker | `validation.C5_metadata_verify_rate` | V1 |
| C6 | citation_sentence_alignment | CitationChecker C6 | `c6_alignment.contradiction_rate` | V2 |
| T1 | year_span | CitationAnalyzer | `analysis.T1_year_span` | R1 |
| T2 | foundational_retrieval_gap | CitationAnalyzer + LiteratureSearch | `analysis.T2_foundational_retrieval_gap` | R1 |
| T3 | peak_year_ratio | CitationAnalyzer | `analysis.T3_peak_year_ratio` | R1 |
| T4 | temporal_continuity | CitationAnalyzer | `analysis.T4_temporal_continuity` | R1 |
| T5 | trend_alignment | CitationAnalyzer + LiteratureSearch | `analysis.T5_trend_alignment` | R1 |
| S1 | section_count | CitationAnalyzer | `analysis.S1_section_count` | R3 |
| S2 | citation_density | CitationAnalyzer | `analysis.S2_citation_density` | R2 |
| S3 | citation_gini | CitationAnalyzer | `analysis.S3_citation_gini` | R2 |
| S4 | zero_citation_section_rate | CitationAnalyzer | `analysis.S4_zero_citation_section_rate` | R2 |
| S5 | section_cluster_alignment | CitationGraphAnalyzer | `graph_analysis.S5_nmi` | E2, R2, R3 |
| G1 | graph_density | CitationGraphAnalyzer | `graph_analysis.G1_density` | E1 |
| G2 | connected_component_count | CitationGraphAnalyzer | `graph_analysis.G2_components` | E1 |
| G3 | max_component_ratio | CitationGraphAnalyzer | `graph_analysis.G3_lcc_frac` | E1 |
| G4 | foundational_coverage_rate | FoundationalCoverageAnalyzer | `graph_analysis.G4_coverage_rate` | E1 |
| G5 | cluster_count | CitationGraphAnalyzer | `graph_analysis.G5_clusters` | E2 |
| G6 | isolated_node_ratio | CitationGraphAnalyzer | `graph_analysis.G6_isolates` | E1 |

### 6.2 Agent Sub-Dimension Registry

`src/graph/nodes/evidence_dispatch.py::AGENT_REGISTRY` defines each agent's input metrics, output sub-dimensions, rubrics, supplementary data, and short-circuit rules.

| Agent | Input metrics | Output dimensions | Default Corrector targets |
|-------|---------------|-------------------|---------------------------|
| VerifierAgent | C3, C5, C6 | V1, V2, V4 | V4; V2 may become a candidate when it does not auto-fail and is treated as medium risk |
| ExpertAgent | G1-G6, S5 | E1-E4 | E2, E3, E4 |
| ReaderAgent | T1-T5, S1-S5 | R1-R4 | R2, R3, R4 |

### 6.3 C6 Short-Circuit Rule

V2's short-circuit rule is in `SubDimensionDef.short_circuit`:

```python
short_circuit={
    "condition": "C6.auto_fail == True",
    "action": "pre_fill_score",
    "result": 1,
}
```

When `c6_alignment.auto_fail` is `true`, `dispatch_specs.verifier.pre_filled_scores.V2` is written with `score=1`, and Verifier no longer calls the LLM for V2.

### 6.4 Corrector Voting Targets

`get_corrector_targets(agent_outputs, tool_evidence)` computes targets from hallucination risk:

- Skip low-risk or deterministic dimensions: V1, E1, R1, and V2 after auto-fail.
- Vote on medium/high-risk dimensions: usually V4, E2, E3, E4, R2, R3, R4.
- If V2 does not auto-fail, its risk is treated as medium and it may enter the voting targets.

---

## 7. Key Interface Reference

### 7.1 CLI and Workflow

| Interface | File | Usage |
|-----------|------|-------|
| `main()` | `src/main.py` | CLI parsing, file existence checks, extension checks |
| `run_evaluation(pdf_path, config=None, output_dir=None)` | `src/main.py` | Runs the full evaluation and returns `(report, run_dir)` |
| `create_workflow(config=None, run_dir="./output/runs")` | `src/graph/builder.py` | Builds the LangGraph |
| `compile_workflow(workflow=None, config=None, checkpointer=None)` | `src/graph/builder.py` | Compiles the graph; defaults to `MemorySaver` |
| `_save_workflow_step(step_name, state, data, ...)` | `src/graph/builder.py` | Saves `nodes/{step}.json` |

### 7.2 Configuration Interfaces

| Interface | Returns | Notes |
|-----------|---------|-------|
| `load_config(config_path=None)` | `SurveyMAEConfig` | Defaults to `config/main.yaml` |
| `load_model_config(config_path=None)` | `ModelConfig` | Defaults to `config/models.yaml` |
| `ModelConfig.get_agent_config(agent_name)` | `LLMConfig` | Resolves agent model, provider base_url, and env key |
| `ModelConfig.get_tool_config(tool_name)` | `LLMConfig` | Resolves tool model |
| `load_search_engine_config(config_path=None)` | `SearchEngineConfig` | Parses search sources and resolves `${ENV}` values |

### 7.3 Agent Output Interface

`src/core/state.py::AgentOutput`:

```python
{
    "agent_name": str,
    "dimension": str,
    "sub_scores": {
        "V1": {
            "score": float,
            "llm_involved": bool,
            "hallucination_risk": str,
            "tool_evidence": dict,
            "llm_reasoning": str,
            "flagged_items": list | None,
            "variance": dict | None,
        }
    },
    "overall_score": float,
    "confidence": float,
    "evidence_summary": str,
}
```

Key behavior of `BaseAgent.evaluate()`:

1. Reads `state["dispatch_specs"][self.name]`.
2. Merges `pre_filled_scores` first.
3. Calls the LLM for every sub-dimension in `sub_dimension_contexts`.
4. Parses JSON fields: `sub_id`, `score`, `llm_reasoning`, `flagged_items`, `tool_evidence_used`.
5. Stores results in `self._sub_scores`; `process()` wraps them as `agent_outputs`.

### 7.4 Corrector Output Interface

`src/core/state.py::CorrectorOutput`:

```python
{
    "corrections": {
        "E3": {
            "original_agent": "expert",
            "original_score": 4,
            "corrected_score": 2,
            "variance": {
                "models_used": ["qwen3.5-flash", "glm-5"],
                "scores": [2.0, 2.0],
                "median": 2.0,
                "std": 0.0,
                "high_disagreement": false,
            },
        }
    },
    "skipped_dimensions": ["V1", "E1", "R1", ...],
    "skip_reason": "low hallucination_risk, threshold-based scoring",
    "total_model_calls": int,
    "failed_calls": int,
}
```

### 7.5 Aggregation Output Interface

`aggregate_scores(state)` returns:

```python
{
    "dimension_scores": {
        "E3": {
            "dim_id": "E3",
            "final_score": 2.0,
            "source": "corrected",
            "agent": "expert",
            "hallucination_risk": "high",
            "variance": {...},
            "weight": 1.0,
        }
    },
    "deterministic_metrics": {},
    "overall_score": 2.91,
    "grade": "D",
    "total_weight": 11.0,
}
```

Weights come from `config/main.yaml::aggregation.weights`; the fallback lives in `aggregator.py::_aggregate_from_agent_outputs()`.

### 7.6 PDF Parsing Interfaces

| Class/function | File | Notes |
|----------------|------|-------|
| `create_pdf_parser(config=None)` | `src/tools/pdf_parser.py` | Returns `MarkerApiParser` or `PDFParser` based on `pdf_parser.backend` and `DATALAB_API_KEY` |
| `PDFParser.parse(pdf_path)` | `src/tools/pdf_parser.py` | Converts PDF to Markdown via PyMuPDF4LLM |
| `PDFParser.parse_with_structure(pdf_path)` | `src/tools/pdf_parser.py` | Returns `(markdown, json_structure)` |
| `MarkerApiParser.parse_with_structure(pdf_path)` | `src/tools/marker_api_parser.py` | Datalab Marker API, JSON + Markdown, with disk cache |
| `extract_section_headings_from_json(json_structure)` | `src/tools/marker_api_parser.py` | Extracts section headings from Marker blocks |

### 7.7 Citation and Evidence Tool Interfaces

| Tool | Key interfaces | Artifacts |
|------|----------------|-----------|
| `CitationChecker` | `extract_citations_with_context_from_pdf()`, `extract_references_from_pdf()`, `build_real_citation_edges()`, `analyze_citation_sentence_alignment()` | `extraction.json`, `validation.json`, `c6_alignment.json` |
| `CitationAnalyzer` | `compute_temporal_metrics()`, `compute_structural_metrics()`, `analyze_paragraph_distribution()` | `analysis.json` |
| `CitationGraphAnalyzer` | `analyze()`, `compute_section_cluster_alignment()` | `graph_analysis.json` and flattened G/S metrics |
| `KeywordExtractor` | `extract_keywords(title, abstract)` | `topic_keywords` |
| `LiteratureSearch` | `search_field_trend()`, `search_top_cited()`, `search_literature()` | `trend_baseline.json`, candidate key papers |
| `FoundationalCoverageAnalyzer` | `analyze(candidate_papers, references, graph_analysis)` | `key_papers.json`, G4 coverage |
| `ParallelDispatcher` | `dispatch_async()`, `dispatch()` | Merged multi-source search results |

### 7.8 ResultStore Interface

`src/tools/result_store.py::ResultStore` is the central file persistence layer:

| Method | Write path |
|--------|------------|
| `register_paper(source_path)` | `papers/{paper_id}/source.json` |
| `save_extraction()` | `papers/{paper_id}/tools/extraction.json` |
| `save_validation()` | `papers/{paper_id}/tools/validation.json` |
| `save_c6_alignment()` | `papers/{paper_id}/tools/c6_alignment.json` |
| `save_citation_analysis()` | `papers/{paper_id}/tools/analysis.json` |
| `save_graph_analysis()` | `papers/{paper_id}/tools/graph_analysis.json` |
| `save_trend_baseline()` | `papers/{paper_id}/tools/trend_baseline.json` |
| `save_key_papers()` | `papers/{paper_id}/tools/key_papers.json` |
| `save_node_step()` | `papers/{paper_id}/nodes/{step}.json` |
| `update_index()` | `{store_run_id}/index.json` |

`paper_id` is the first 12 characters of the source file SHA256.

---

## 8. Output Directories and Run Artifacts

### 8.1 Directory Layout

Latest run directory:

```text
output/runs/20260423T153603Z_dab99f59/
├── logs/
│   ├── run.log
│   └── summary.log
├── reports/
│   └── test_survey2_20260423T155627Z.md
└── 20260423T153607Z_run/
    ├── run.json
    ├── index.json
    └── papers/
        └── 615cbba96913/
            ├── source.json
            ├── run_summary.json
            ├── nodes/
            │   ├── 01_parse_pdf.json
            │   ├── 02_evidence_collection.json
            │   ├── 03_evidence_dispatch.json
            │   ├── 04_verifier.json
            │   ├── 04_expert.json
            │   ├── 04_reader.json
            │   ├── 05_corrector.json
            │   ├── 06_aggregator.json
            │   └── 07_reporter.json
            └── tools/
                ├── extraction.json
                ├── validation.json
                ├── c6_alignment.json
                ├── analysis.json
                ├── graph_analysis.json
                ├── key_papers.json
                └── trend_baseline.json
```

The outer run id is generated by `src/main.py::_generate_run_id()` as `{UTC time}_{first 8 chars of md5(path)}`. The inner ResultStore run id defaults to `{UTC time}_run`.

### 8.2 `run.json`

Located at `{store_run_id}/run.json`, it records:

- `run_id`
- `created_at`
- `schema_version`
- `metrics_index.metrics`
- `metrics_index.agent_dimensions`

`metrics_index` is the metric lineage index. Each metric contains `name`, `computed_by`, `source_file`, `llm_involved`, `hallucination_risk`, and `consumed_by`.

### 8.3 `index.json`

Records paper status under the current store run:

```json
{
  "papers": {
    "615cbba96913": {
      "paper_id": "615cbba96913",
      "status": "graph_analyzed",
      "updated_at": "2026-04-23T15:54:35Z",
      "source_path": "..."
    }
  }
}
```

### 8.4 `run_summary.json`

Generated by `ReportAgent._generate_run_summary()` for batch experiment comparison:

```json
{
  "run_id": "20260423T153607Z_run",
  "source": ".\\test_survey2.pdf",
  "timestamp": "2026-04-23T15:56:27+00:00",
  "schema_version": "v3",
  "llm_calls": 0,
  "api_calls": 0,
  "deterministic_metrics": {
    "C3": 0.0061,
    "C5": 0.5185,
    "C6_contradiction_rate": 0.6011,
    "G1": 0.0057,
    "G4": 0.1127,
    "S5": 1.0
  },
  "dimension_scores": {...},
  "agent_scores": {...},
  "corrected_scores": {...},
  "overall_score": 2.91,
  "grade": "D"
}
```

### 8.5 `summary.log`

`summary.log` is the fastest run-diagnosis entry point. The latest sample shows:

```text
[01/07] parse_pdf | 85620 chars
[02/07] evidence_collection | 162 refs, 5 keywords
[03/07] evidence_dispatch | 3 agents dispatched
[04/07] verifier | V2=1 V1=2 V4=3
[04/07] reader | R1=3 R2=4 R3=5 R4=4
[04/07] expert | E1=1 E2=4 E3=4 E4=3
[05/07] corrector | 7 dims corrected, 17 calls (4 failed)
[06/07] aggregator | overall=2.91/5 grade=D
[07/07] reporter | report 10558 chars
```

---

## 9. Secondary Development Guide

### 9.1 Add a New Tool Metric

Change points:

1. Compute the metric in a tool or in `evidence_collection.py`, then put it into `tool_evidence`.
2. Add a `MetricDef` in `evidence_dispatch.py::METRIC_REGISTRY`.
3. Reference that metric in the relevant `SubDimensionDef.evidence_metric_ids`.
4. If the raw artifact needs persistence, add a `save_*()` method in `ResultStore` or reuse an existing tools file.
5. Add unit tests. Prioritize `extract_metric_value()`, `build_sub_dimension_context()`, and the related tool functions.

Example:

```python
"X1": MetricDef(
    metric_id="X1",
    name="new_metric",
    description="...",
    source="MyTool",
    extract_path="my_tool.X1_new_metric",
    llm_involved=False,
    hallucination_risk="none",
)
```

### 9.2 Add or Modify an Agent Sub-Dimension

Modify `src/graph/nodes/evidence_dispatch.py::AGENT_REGISTRY`:

- Add a `SubDimensionDef`.
- Define `sub_id`, `name`, `description`, `hallucination_risk`, `evidence_metric_ids`, and `rubric`.
- Add `short_circuit` if deterministic pre-fill is needed.
- If extra context is needed, add data extraction logic in `supplementary_data` and `build_sub_dimension_context()`.
- Update `config/main.yaml::aggregation.weights`.
- Update related tests and the metric mapping table in this document.

### 9.3 Add a New Agent

All current agents inherit from `BaseAgent`. Minimum changes:

1. Create `src/agents/my_agent.py`, inheriting from `BaseAgent`.
2. Export it from `src/agents/__init__.py`.
3. Register it in `builder.py::_get_agent_classes()`.
4. Add nodes and edges in `builder.py::create_workflow()`.
5. Add an `AgentDef` in `evidence_dispatch.py::AGENT_REGISTRY`.
6. Add config in `config/main.yaml::agents` and `config/models.yaml::agents`.
7. Update `SurveyState` or aggregation logic if the agent introduces new state fields or scoring dimensions.

### 9.4 Add a Literature Search Source

1. Add a fetcher under `src/tools/fetchers/`.
2. Wire it into initialization and `_resolve_sources()` logic in `src/tools/literature_search.py`.
3. Add source config under `config/search_engines.yaml::sources`.
4. If it should participate in concurrent dispatch, provide complete `enabled`, `priority`, `concurrent`, `timeout_seconds`, and `max_retries` fields.
5. Add `tests/unit/test_literature_fetchers.py` coverage or an integration test.

### 9.5 Customize the PDF Parsing Backend

`create_pdf_parser(config)` is the unified entry point. To add a backend:

1. Create a class compatible with `PDFParser`, at minimum providing `parse()`. If structure should be preserved, also provide `parse_with_structure()`.
2. Extend `PdfParserConfig`.
3. Add a backend branch in `create_pdf_parser()`.
4. Update `builder._parse_pdf_node()` so section headings can be extracted.
5. Add unit or integration tests.

### 9.6 Modify Report Output

Reports are split into two layers:

- `aggregate_scores()` performs only mathematical aggregation.
- `generate_report()` renders Markdown.
- `ReportAgent._generate_run_summary()` writes experiment-summary JSON.

When adding report fields, update:

1. `generate_report()` or its `_render_*()` helpers.
2. `ReportAgent._generate_run_summary()`.
3. The `run_summary.json` documentation.
4. Tests or sample-output checks.

### 9.7 Modify the Scoring Scale

The scoring scale crosses several boundaries. Do not only edit display text:

- `src/graph/nodes/aggregator.py`
- `src/core/state.py::EvaluationRecordModel`
- Score parsing and fallback logic in `src/agents/base.py`
- `config/main.yaml::aggregation.weights`
- Report text and README/developer-guide documentation
- `tests/unit/test_aggregator.py`, `tests/unit/test_state.py`

---

## 10. Testing and Quality Checks

### 10.1 Unit Tests

Unit tests live under `tests/unit/` and should generally not depend on real external APIs.

```bash
uv run pytest tests/unit
uv run pytest tests/unit/test_config.py
uv run pytest tests/unit/test_evidence_dispatch.py
uv run pytest tests/unit/test_evidence_dispatch_extraction.py
uv run pytest tests/unit/test_aggregator.py tests/unit/test_state.py
```

Key coverage:

| File | Coverage |
|------|----------|
| `test_config.py` | Main config and model config loading |
| `test_evidence_dispatch.py` | `METRIC_REGISTRY`, `AGENT_REGISTRY`, `dispatch_specs` |
| `test_evidence_dispatch_extraction.py` | Metric extract_path calibration |
| `test_aggregator.py` | 0-5 aggregation, Corrector priority, grade |
| `test_state.py` | Pydantic score bounds |
| `test_citation_graph_analysis.py` | Graph metrics and clustering logic |
| `test_pdf_parser.py` | PDF parser interface and fallback |

### 10.2 Integration Tests

Integration tests live under `tests/integration/` and may require Docker, API keys, real PDFs, or network access.

```bash
uv run pytest tests/integration/test_citation_graph_pipeline.py
uv run pytest tests/integration/test_citation_grobid.py
uv run pytest tests/integration/test_marker_api_parser.py
uv run pytest tests/integration/test_parallel_literature_search.py
uv run pytest tests/integration/test_semantic_scholar_fetcher.py
```

Conventions:

- Missing external API keys should cause skips, not failures.
- GROBID tests require local `http://localhost:8070`.
- Marker API tests require `DATALAB_API_KEY`.
- Network retrieval tests require relevant API keys or accessible public endpoints.

### 10.3 Code Quality

```bash
uv run ruff format .
uv run ruff check .
uv run mypy src/
```

### 10.4 Documentation Update Self-Check

When updating this document, check at least:

```powershell
Select-String -Path docs\DEVELOPER_GUIDE.md -Pattern 'Addendum'
git diff --check
```

---

## 11. FAQ

### Q: Why are there two run-id levels in the output directory?

The outer directory is created by `main.py` for logs and the final report:

```text
output/runs/{outer_run_id}/logs
output/runs/{outer_run_id}/reports
```

The inner directory is created by `ResultStore` for structured JSON:

```text
output/runs/{outer_run_id}/{store_run_id}/run.json
output/runs/{outer_run_id}/{store_run_id}/papers/{paper_id}/...
```

### Q: How do I check whether GROBID is available?

```bash
curl http://localhost:8070/api/isalive
```

Or use the scripts:

```powershell
.\scripts\grobid.ps1 -Action status
```

```bash
scripts/grobid.sh status
```

### Q: Why is V2 sometimes directly scored as 1?

When C6 `contradiction_rate` exceeds `config/main.yaml::evidence.contradiction_threshold`, `c6_alignment.auto_fail=true`. Evidence Dispatch then writes V2 into `pre_filled_scores` with score 1.

### Q: Why does Corrector not have an independent score?

Corrector is currently a pure correction role. It no longer outputs independent C1/C2/C3-style dimensions. It only writes `corrector_output.corrections`; Aggregator prefers `corrected_score` when computing `dimension_scores`.

### Q: How do I quickly locate a run failure?

Recommended order:

1. `output/runs/{outer}/logs/summary.log`
2. `output/runs/{outer}/logs/run.log`
3. `output/runs/{outer}/{store}/papers/{paper_id}/nodes/{step}.json`
4. The relevant raw tool output under `tools/*.json`

### Q: Why are `tools/graph_analysis.json` and `tool_evidence.graph_analysis` different?

`tools/graph_analysis.json` is the raw structure returned by `CitationGraphAnalyzer.analyze()`, with `citation_graph_analysis` as the outer object. Evidence Collection extracts G1-G6, S5, and missing/suspicious lists from that structure and stores them as flattened keys in `tool_evidence.graph_analysis` for Evidence Dispatch.

### Q: How do I change the multi-model voting models?

Edit `config/models.yaml::agents.corrector.multi_model.models`. Each model needs provider, model, and temperature. Provider `base_url` and `env_key` are defined in the `providers` section.

### Q: How do I disable a search source?

Edit `config/search_engines.yaml`:

```yaml
sources:
  semantic_scholar:
    enabled: false
```

If a source is unstable but should remain available as a fallback, set:

```yaml
concurrent: false
```

and include it in `degradation.fallback_order`.

### Q: What is the difference between `.md` and `.pdf` input?

`src/main.py` supports `.md` and reads it directly as text. `builder._parse_pdf_node()` also extracts headings from `.md`. A `.pdf` input goes through the configured PDF parser and may create Marker/PyMuPDF cache artifacts.
