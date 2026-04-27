# SurveyMAE 开发文档

> **文档版本**: v4.0 (2026-04-27)
> **核对范围**: `src/`、`config/`、`tests/`、`scripts/` 以及最新运行目录 `output/runs/20260423T153603Z_dab99f59`
> **文档定位**: 面向开发者和 AI 维护者，用于快速理解项目结构、查找关键接口、确认配置字段和输出产物结构。README 只保留项目入口信息，本文档是深入开发参考。

## 目录

| 章节 | 用途 |
|------|------|
| [1. 项目概览](#1-项目概览) | 理解 SurveyMAE 的目标、评估层次和当前实现边界 |
| [2. 快速运行](#2-快速运行) | 安装、配置、CLI、GROBID 和常用测试命令 |
| [3. 代码结构速查](#3-代码结构速查) | 按目录定位入口、状态、图节点、Agent、工具和测试 |
| [4. 主流程与数据流](#4-主流程与数据流) | LangGraph 节点、运行时状态、证据产物和报告生成路径 |
| [5. 配置系统](#5-配置系统) | `main.yaml`、`models.yaml`、`search_engines.yaml` 和 `.env` 字段 |
| [6. 评估指标与 Agent 映射](#6-评估指标与-agent-映射) | 19 个工具指标、11 个 Agent 子维度和 Corrector 投票目标 |
| [7. 关键接口速查](#7-关键接口速查) | 常用类、函数、输入输出字段和扩展点 |
| [8. 输出目录与运行产物](#8-输出目录与运行产物) | `output/runs/...` 的真实文件层级和 JSON 字段 |
| [9. 二次开发指南](#9-二次开发指南) | 添加指标、子维度、Agent、工具、检索源和报告字段 |
| [10. 测试与质量检查](#10-测试与质量检查) | 单元测试、集成测试、外部依赖和代码质量命令 |
| [11. 常见问题](#11-常见问题) | 调试配置、GROBID、输出目录、评分和检索降级 |

---

## 1. 项目概览

SurveyMAE 是一个基于 LangGraph 的多智能体评测框架，用于评估 LLM 生成的学术综述质量。当前实现以“工具证据先行、Agent 基于证据评分、Corrector 对高风险维度复核、Reporter 输出报告”为主线。

### 1.1 三层评估结构

| 层级 | 产出 | 主要文件 |
|------|------|----------|
| 工具证据层 | C/T/S/G 系列指标、引用抽取、验证、引用图、核心文献覆盖 | `src/graph/nodes/evidence_collection.py`、`src/tools/*` |
| Agent 判断层 | Verifier / Expert / Reader 的 11 个子维度评分 | `src/agents/base.py`、`src/graph/nodes/evidence_dispatch.py` |
| 汇总报告层 | Corrector 校正、加权总分、Markdown 报告、`run_summary.json` | `src/agents/corrector.py`、`src/graph/nodes/aggregator.py`、`src/agents/reporter.py` |

### 1.2 当前 Agent 与职责

| Agent | 维度 | 子维度 | 说明 |
|-------|------|--------|------|
| VerifierAgent | factuality | V1, V2, V4 | 引用存在性、引用-断言对齐、内部一致性 |
| ExpertAgent | academic_depth | E1-E4 | 核心文献覆盖、分类合理性、技术准确性、批判性分析深度 |
| ReaderAgent | readability | R1-R4 | 时效性、信息分布、结构清晰度、文字质量 |
| CorrectorAgent | correction | 无独立评分维度 | 对中/高幻觉风险子维度进行多模型投票，写入 `corrector_output` |
| ReportAgent | report_generation | 无评分维度 | 调用聚合逻辑，生成 Markdown 和 `run_summary.json` |

### 1.3 评分语义

当前总分和子维度分数均使用 **0-5 / 1-5 语义**：

- Agent 子维度输出为 `1-5`。
- `EvaluationRecordModel.score` 校验范围为 `[0.0, 5.0]`。
- 聚合总分保持在 `0-5`，不再转换到 `0-10`。
- 等级阈值在 `src/graph/nodes/aggregator.py::_get_grade()`：`A >= 4.25`、`B >= 3.75`、`C >= 3.25`、`D >= 2.75`，否则 `F`。

---

## 2. 快速运行

### 2.1 前置要求

- Python 3.12+
- `uv`
- 可选：Docker，用于运行 GROBID
- 可选：Datalab Marker API Key，用于 `marker_api` PDF 解析后端

### 2.2 安装和本地环境变量

```bash
uv sync
cp .env.example .env
```

在本地 `.env` 文件中填写你自己的 API Key。`.env` 不应提交；`.env.example` 只保留字段名。

常用环境变量：

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

### 2.3 CLI 用法

入口是 `src/main.py`。当前 CLI 支持 `.pdf` 和 `.md`：

```bash
uv run python -m src.main path/to/survey.pdf
uv run python -m src.main path/to/survey.md
uv run python -m src.main path/to/survey.pdf -c config/main.yaml
uv run python -m src.main path/to/survey.pdf -o ./output
uv run python -m src.main path/to/survey.pdf -v
uv run python -m src.main path/to/survey.pdf -q
uv run python -m src.main path/to/survey.pdf --log-level DEBUG
```

`-v` 和 `-q` 互斥；`--log-level` 显式指定时优先级最高。

### 2.4 GROBID 可选后端

GROBID 用于增强参考文献抽取和 CrossRef DOI 补全。当前 `config/main.yaml` 中 `citation.backend` 默认设为 `grobid`。

```bash
docker pull grobid/grobid:0.9.0-crf
```

Windows PowerShell：

```powershell
.\scripts\grobid.ps1 -Action start
.\scripts\grobid.ps1 -Action status
.\scripts\grobid.ps1 -Action stop
```

Linux/macOS shell：

```bash
scripts/grobid.sh start
scripts/grobid.sh status
scripts/grobid.sh stop
```

默认服务地址为 `http://localhost:8070`。相关配置字段在 `config/main.yaml`：

```yaml
citation:
  backend: grobid          # grobid | auto | mupdf
  grobid_url: http://localhost:8070
  grobid_timeout_s: 60
  grobid_consolidate: true
```

### 2.5 常用测试命令

```bash
uv run pytest tests/unit
uv run pytest tests/unit/test_evidence_dispatch.py
uv run pytest tests/integration/test_citation_graph_pipeline.py
uv run ruff format .
uv run ruff check .
uv run mypy src/
```

---

## 3. 代码结构速查

```text
SurveyMAE/
├── config/
│   ├── main.yaml                 # 主流程、PDF、引用、证据、Agent、MCP、聚合和报告配置
│   ├── models.yaml               # provider、agent、tool、多模型投票配置
│   ├── search_engines.yaml       # 文献检索源、并发、重试和降级策略
│   └── prompts/                  # verifier/expert/reader/corrector/reporter/citation_alignment prompt
├── docs/
│   ├── DEVELOPER_GUIDE.md        # 英文开发文档
│   ├── DEVELOPER_GUIDE.zh-CN.md  # 本文档
│   └── README.zh-CN.md           # 中文 README
├── scripts/
│   ├── grobid.ps1                # Windows GROBID 容器管理
│   ├── grobid.sh                 # Linux/macOS GROBID 容器管理
│   ├── run_evaluation.ps1/.sh    # 运行辅助脚本
│   └── render_citation_graph_pyvis.py
├── src/
│   ├── main.py                   # CLI 和 run_evaluation()
│   ├── core/                     # 配置、状态、日志、MCP 客户端、检索配置
│   ├── agents/                   # BaseAgent、Verifier、Expert、Reader、Corrector、Reporter
│   ├── graph/                    # LangGraph builder、edges、nodes
│   ├── tools/                    # PDF、引用、检索、图分析、结果存储等工具
│   └── web/                      # 本地 Web 查看界面
├── tests/
│   ├── unit/
│   └── integration/
└── output/runs/                  # 运行产物
```

### 3.1 核心文件职责

| 文件 | 职责 |
|------|------|
| `src/main.py` | 加载 `.env`、解析 CLI、初始化日志、创建 workflow、保存最终报告 |
| `src/core/config.py` | Pydantic 配置模型与 `load_config()` / `load_model_config()` |
| `src/core/search_config.py` | `config/search_engines.yaml` 的并发检索配置解析 |
| `src/core/state.py` | `SurveyState`、`ToolEvidence`、`AgentOutput`、`AggregatedScores` 等状态类型 |
| `src/core/log.py` | Rich 控制台、文件日志、`summary.log`、`RunStats` |
| `src/graph/builder.py` | LangGraph 节点和边、ResultStore 初始化、节点输出持久化 |
| `src/graph/nodes/evidence_collection.py` | 统一执行工具层证据收集 |
| `src/graph/nodes/evidence_dispatch.py` | `METRIC_REGISTRY`、`AGENT_REGISTRY`、`dispatch_specs` |
| `src/graph/nodes/aggregator.py` | 加权聚合和 Markdown 报告渲染函数 |
| `src/agents/base.py` | 通用 LLM 调用、prompt 加载、dispatch_specs 驱动的子维度评分 |
| `src/agents/corrector.py` | 多模型投票校正，输出 `corrector_output` |
| `src/agents/reporter.py` | 调用聚合、生成最终报告、写入 `run_summary.json` |
| `src/tools/result_store.py` | `output/runs` 文件化持久化 |

---

## 4. 主流程与数据流

### 4.1 LangGraph 节点顺序

`src/graph/builder.py::create_workflow()` 定义当前工作流：

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

代码中仍保留 `debate` 节点和条件边，但当前主路径以 Corrector + Aggregator 为核心。

### 4.2 节点职责和输出

| 步骤 | 节点/函数 | 写入状态字段 | 产物 |
|------|-----------|--------------|------|
| 01 | `_parse_pdf_node()` | `parsed_content`, `section_headings`, `metadata` | `nodes/01_parse_pdf.json` |
| 02 | `run_evidence_collection()` | `tool_evidence`, `ref_metadata_cache`, `topic_keywords`, `field_trend_baseline`, `candidate_key_papers` | `tools/*.json`, `nodes/02_evidence_collection.json` |
| 03 | `run_evidence_dispatch()` | `dispatch_specs`, `metrics_index` | `nodes/03_evidence_dispatch.json` |
| 04 | `BaseAgent.process()` | `evaluations`, `agent_outputs` | `nodes/04_verifier.json` 等 |
| 05 | `CorrectorAgent.process()` | `corrector_output` | `nodes/05_corrector.json` |
| 06 | `_run_aggregator()` / `aggregate_scores()` | `aggregated_scores` | `nodes/06_aggregator.json` |
| 07 | `ReportAgent.process()` | `final_report_md`, `overall_score`, `grade`, `run_summary` | `nodes/07_reporter.json`, `run_summary.json`, `reports/*.md` |

### 4.3 `SurveyState` 字段分组

`src/core/state.py::SurveyState` 是 LangGraph 状态契约：

| 字段 | 类型/含义 | 主要写入者 |
|------|-----------|------------|
| `source_pdf_path` | 输入源路径，当前支持 `.pdf` / `.md` | `main.py` |
| `parsed_content` | Markdown/text 正文 | `main.py`, `parse_pdf` |
| `section_headings` | 章节标题列表 | `parse_pdf` |
| `tool_evidence` | 工具层证据聚合 | `evidence_collection` |
| `ref_metadata_cache` | 参考文献元数据缓存 | `evidence_collection` |
| `topic_keywords` | LLM 或 fallback 抽取的主题关键词 | `evidence_collection` |
| `field_trend_baseline` | 领域年度趋势 | `evidence_collection` |
| `candidate_key_papers` | G4 候选核心论文 | `evidence_collection` |
| `evaluations` | 兼容旧格式的 Agent 评估记录，使用 `operator.add` 累加 | Agent 节点 |
| `agent_outputs` | 新格式结构化 Agent 输出，使用 `dict_merge` 合并 | Agent 节点 |
| `corrector_output` | 多模型校正结果 | Corrector |
| `aggregated_scores` | 聚合后各维度分数 | Aggregator/Reporter |
| `dispatch_specs` | 分发给各 Agent 的精确上下文 | Evidence Dispatch |
| `metrics_index` | 指标血缘索引 | Builder/Evidence Dispatch |
| `final_report_md` | 最终 Markdown 报告 | Reporter |

### 4.4 `tool_evidence` 结构

`ToolEvidence` 在内存中是扁平聚合视图：

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

注意：原始 `tools/graph_analysis.json` 外层是 `citation_graph_analysis`，而 `tool_evidence.graph_analysis` 是 Evidence Collection 提取后的扁平指标视图。

---

## 5. 配置系统

### 5.1 `config/main.yaml`

由 `src/core/config.py::SurveyMAEConfig` 解析。关键段：

| 段 | 对应模型 | 说明 |
|----|----------|------|
| `general` | `dict` | 调试和默认日志级别 |
| `llm` | `LLMConfig` | 默认 LLM 配置；Agent 创建时作为基础配置 |
| `pdf_parser` | `PdfParserConfig` | PDF 解析后端：`marker_api`、`pymupdf4llm`、`auto` |
| `citation` | `CitationConfig` | 引用抽取后端：`grobid`、`auto`、`mupdf` |
| `evidence` | `EvidenceConfig` | G4、T 系列、S5、C6 和采样参数 |
| `agents` | `list[AgentConfig]` | prompt 路径、工具列表、重试、超时 |
| `mcp_servers` | `list[MCPServerConfig]` | 本地或远程 MCP 服务定义 |
| `aggregation` | `AggregationConfig` | 11 个子维度权重 |
| `persistence` | 当前由 YAML 保存 | schema 和工具产物保存意图 |
| `report` | `ReportConfig` | 报告输出目录和格式 |

当前 PDF 解析默认配置：

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

由 `load_model_config()` 解析。核心字段：

| 字段 | 说明 |
|------|------|
| `default` | 默认 provider/model/temperature/max_tokens |
| `tools.citation_checker` | C6 引用-句子对齐使用的模型 |
| `tools.keyword_extractor` | 主题关键词抽取使用的模型 |
| `agents.verifier/expert/reader` | 三个评分 Agent 的模型 |
| `agents.corrector.multi_model` | Corrector 多模型投票列表 |
| `agents.reporter` | 报告 Agent 配置 |
| `providers.*.base_url` | OpenAI-compatible endpoint |
| `providers.*.env_key` | API Key 环境变量名 |

`ModelConfig.get_agent_config(agent_name)` 和 `get_tool_config(tool_name)` 会补齐 `base_url` 和 `api_key`。

### 5.3 `config/search_engines.yaml`

由 `src/core/search_config.py::load_search_engine_config()` 解析，供 `ParallelDispatcher` 和 `LiteratureSearch` 使用。

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

合并策略：

| 策略 | 行为 |
|------|------|
| `first_wins` | 使用第一个非空结果，优先低延迟 |
| `union` | 合并所有源并去重 |
| `weighted_union` | 高优先级源优先，低优先级补齐缺失项 |

### 5.4 Prompt 模板

Prompt 文件位于 `config/prompts/`。`BaseAgent._load_prompt(prompt_name, **kwargs)` 读取 YAML 中的 `template` 或 `prompt` 字段。

当前三类评分 Agent 的细粒度 rubric 不写死在 prompt YAML 中，而由 `evidence_dispatch.py::AGENT_REGISTRY` 注入到 `dispatch_specs`。

---

## 6. 评估指标与 Agent 映射

### 6.1 工具指标注册表

`src/graph/nodes/evidence_dispatch.py::METRIC_REGISTRY` 是 19 个一层指标的运行时真相来源。

| 指标 | 名称 | 来源 | 提取路径 | 消费者 |
|------|------|------|----------|--------|
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

### 6.2 Agent 子维度注册表

`src/graph/nodes/evidence_dispatch.py::AGENT_REGISTRY` 定义 Agent 输入指标、输出子维度、rubric、补充数据和短路规则。

| Agent | 输入指标 | 输出维度 | Corrector 默认目标 |
|-------|----------|----------|--------------------|
| VerifierAgent | C3, C5, C6 | V1, V2, V4 | V4；V2 在非 auto-fail 时按 medium risk 可进入候选 |
| ExpertAgent | G1-G6, S5 | E1-E4 | E2, E3, E4 |
| ReaderAgent | T1-T5, S1-S5 | R1-R4 | R2, R3, R4 |

### 6.3 C6 短路规则

V2 的短路规则在 `SubDimensionDef.short_circuit`：

```python
short_circuit={
    "condition": "C6.auto_fail == True",
    "action": "pre_fill_score",
    "result": 1,
}
```

当 `c6_alignment.auto_fail` 为 `true` 时，`dispatch_specs.verifier.pre_filled_scores.V2` 会写入 `score=1`，Verifier 不再对 V2 调 LLM。

### 6.4 Corrector 投票目标

`get_corrector_targets(agent_outputs, tool_evidence)` 根据 hallucination risk 计算目标：

- 跳过低风险或确定性维度：V1、E1、R1，以及 auto-fail 后的 V2。
- 投票中/高风险维度：通常包括 V4、E2、E3、E4、R2、R3、R4。
- 如果 V2 未触发 auto-fail，V2 的风险视为 medium，可进入投票目标。

---

## 7. 关键接口速查

### 7.1 CLI 和工作流

| 接口 | 文件 | 用法 |
|------|------|------|
| `main()` | `src/main.py` | CLI 参数解析、文件存在性和后缀检查 |
| `run_evaluation(pdf_path, config=None, output_dir=None)` | `src/main.py` | 执行完整评测，返回 `(report, run_dir)` |
| `create_workflow(config=None, run_dir="./output/runs")` | `src/graph/builder.py` | 构建 LangGraph |
| `compile_workflow(workflow=None, config=None, checkpointer=None)` | `src/graph/builder.py` | 编译图，默认 `MemorySaver` |
| `_save_workflow_step(step_name, state, data, ...)` | `src/graph/builder.py` | 保存 `nodes/{step}.json` |

### 7.2 配置接口

| 接口 | 返回 | 说明 |
|------|------|------|
| `load_config(config_path=None)` | `SurveyMAEConfig` | 默认查找 `config/main.yaml` |
| `load_model_config(config_path=None)` | `ModelConfig` | 默认查找 `config/models.yaml` |
| `ModelConfig.get_agent_config(agent_name)` | `LLMConfig` | 解析 agent 模型、provider base_url 和 env key |
| `ModelConfig.get_tool_config(tool_name)` | `LLMConfig` | 解析工具模型 |
| `load_search_engine_config(config_path=None)` | `SearchEngineConfig` | 解析检索源并替换 `${ENV}` |

### 7.3 Agent 输出接口

`src/core/state.py::AgentOutput`：

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

`BaseAgent.evaluate()` 的关键行为：

1. 读取 `state["dispatch_specs"][self.name]`。
2. 先合并 `pre_filled_scores`。
3. 对 `sub_dimension_contexts` 中每个子维度调用 LLM。
4. 解析 JSON 输出字段 `sub_id`、`score`、`llm_reasoning`、`flagged_items`、`tool_evidence_used`。
5. 将结果保存到 `self._sub_scores`，再由 `process()` 包装为 `agent_outputs`。

### 7.4 Corrector 输出接口

`src/core/state.py::CorrectorOutput`：

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

### 7.5 聚合输出接口

`aggregate_scores(state)` 返回：

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

权重来自 `config/main.yaml::aggregation.weights`，fallback 在 `aggregator.py::_aggregate_from_agent_outputs()`。

### 7.6 PDF 解析接口

| 类/函数 | 文件 | 说明 |
|---------|------|------|
| `create_pdf_parser(config=None)` | `src/tools/pdf_parser.py` | 根据 `pdf_parser.backend` 和 `DATALAB_API_KEY` 返回 `MarkerApiParser` 或 `PDFParser` |
| `PDFParser.parse(pdf_path)` | `src/tools/pdf_parser.py` | PyMuPDF4LLM 转 Markdown |
| `PDFParser.parse_with_structure(pdf_path)` | `src/tools/pdf_parser.py` | 返回 `(markdown, json_structure)` |
| `MarkerApiParser.parse_with_structure(pdf_path)` | `src/tools/marker_api_parser.py` | Datalab Marker API，JSON + Markdown，带磁盘缓存 |
| `extract_section_headings_from_json(json_structure)` | `src/tools/marker_api_parser.py` | 从 Marker block 中提取章节标题 |

### 7.7 引用与证据工具接口

| 工具 | 关键接口 | 产物 |
|------|----------|------|
| `CitationChecker` | `extract_citations_with_context_from_pdf()`、`extract_references_from_pdf()`、`build_real_citation_edges()`、`analyze_citation_sentence_alignment()` | `extraction.json`、`validation.json`、`c6_alignment.json` |
| `CitationAnalyzer` | `compute_temporal_metrics()`、`compute_structural_metrics()`、`analyze_paragraph_distribution()` | `analysis.json` |
| `CitationGraphAnalyzer` | `analyze()`、`compute_section_cluster_alignment()` | `graph_analysis.json` 和扁平 G/S 指标 |
| `KeywordExtractor` | `extract_keywords(title, abstract)` | `topic_keywords` |
| `LiteratureSearch` | `search_field_trend()`、`search_top_cited()`、`search_literature()` | `trend_baseline.json`、候选核心论文 |
| `FoundationalCoverageAnalyzer` | `analyze(candidate_papers, references, graph_analysis)` | `key_papers.json`、G4 覆盖率 |
| `ParallelDispatcher` | `dispatch_async()`、`dispatch()` | 多源检索合并结果 |

### 7.8 ResultStore 接口

`src/tools/result_store.py::ResultStore` 是文件持久化中心：

| 方法 | 写入位置 |
|------|----------|
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

`paper_id` 是源文件 SHA256 的前 12 位。

---

## 8. 输出目录与运行产物

### 8.1 目录层级

最新一次运行目录：

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

外层 run id 由 `src/main.py::_generate_run_id()` 生成，格式为 `{UTC时间}_{md5(path)前8位}`。内层 ResultStore run id 默认为 `{UTC时间}_run`。

### 8.2 `run.json`

位于 `{store_run_id}/run.json`，记录：

- `run_id`
- `created_at`
- `schema_version`
- `metrics_index.metrics`
- `metrics_index.agent_dimensions`

`metrics_index` 是指标血缘索引，包含每个指标的 `name`、`computed_by`、`source_file`、`llm_involved`、`hallucination_risk`、`consumed_by`。

### 8.3 `index.json`

记录当前 store run 下的 paper 状态：

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

由 `ReportAgent._generate_run_summary()` 生成，供批量实验比较：

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

`summary.log` 是最快速的运行诊断入口。最新样例显示：

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

## 9. 二次开发指南

### 9.1 添加新工具指标

修改位置：

1. 在工具或 `evidence_collection.py` 中计算指标，并放入 `tool_evidence`。
2. 在 `evidence_dispatch.py::METRIC_REGISTRY` 添加 `MetricDef`。
3. 在对应 `SubDimensionDef.evidence_metric_ids` 中引用该指标。
4. 如需保存原始产物，在 `ResultStore` 中新增 `save_*()` 或复用现有 tools 文件。
5. 添加单元测试：优先覆盖 `extract_metric_value()`、`build_sub_dimension_context()` 和相关工具函数。

示例形态：

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

### 9.2 添加或修改 Agent 子维度

修改 `src/graph/nodes/evidence_dispatch.py::AGENT_REGISTRY`：

- 新增 `SubDimensionDef`。
- 写清 `sub_id`、`name`、`description`、`hallucination_risk`、`evidence_metric_ids`、`rubric`。
- 如需自动打分，增加 `short_circuit`。
- 如需额外上下文，在 `supplementary_data` 和 `build_sub_dimension_context()` 中添加数据提取逻辑。
- 更新 `config/main.yaml::aggregation.weights`。
- 更新相关测试和本文档的指标映射表。

### 9.3 添加新 Agent

当前 Agent 类都继承 `BaseAgent`。新增 Agent 的最小改动：

1. 新建 `src/agents/my_agent.py`，继承 `BaseAgent`。
2. 在 `src/agents/__init__.py` 导出。
3. 在 `builder.py::_get_agent_classes()` 注册类。
4. 在 `builder.py::create_workflow()` 增加节点和边。
5. 在 `evidence_dispatch.py::AGENT_REGISTRY` 添加 AgentDef。
6. 在 `config/main.yaml::agents` 和 `config/models.yaml::agents` 添加配置。
7. 更新 `SurveyState` 或输出聚合逻辑，如果新增状态字段或评分维度。

### 9.4 添加文献检索源

1. 在 `src/tools/fetchers/` 新增 fetcher。
2. 在 `src/tools/literature_search.py` 初始化和 `_resolve_sources()` 相关逻辑中接入。
3. 在 `config/search_engines.yaml::sources` 添加配置。
4. 如果需要并发调度，确保 source 配置中 `enabled`、`priority`、`concurrent`、`timeout_seconds`、`max_retries` 完整。
5. 添加 `tests/unit/test_literature_fetchers.py` 或集成测试。

### 9.5 自定义 PDF 解析后端

`create_pdf_parser(config)` 是统一入口。要添加新后端：

1. 新建与 `PDFParser` 兼容的类，至少提供 `parse()`；如果要保留章节结构，提供 `parse_with_structure()`。
2. 扩展 `PdfParserConfig`。
3. 修改 `create_pdf_parser()` 的 backend 分支。
4. 修改 `builder._parse_pdf_node()`，确保能读取章节标题。
5. 添加单元或集成测试。

### 9.6 修改报告输出

报告由两层组成：

- `aggregate_scores()` 只负责数学聚合。
- `generate_report()` 负责 Markdown 渲染。
- `ReportAgent._generate_run_summary()` 负责实验摘要 JSON。

如果新增报告字段，需要同步：

1. `generate_report()` 或其 `_render_*()` 函数。
2. `ReportAgent._generate_run_summary()`。
3. `run_summary.json` 文档说明。
4. 对应测试或样例输出检查。

### 9.7 修改评分尺度

评分尺度牵涉多个边界，不要只改显示文案：

- `src/graph/nodes/aggregator.py`
- `src/core/state.py::EvaluationRecordModel`
- `src/agents/base.py` 的分数解析和 fallback
- `config/main.yaml::aggregation.weights`
- 报告文案和 README/开发文档
- `tests/unit/test_aggregator.py`、`tests/unit/test_state.py`

---

## 10. 测试与质量检查

### 10.1 单元测试

单元测试位于 `tests/unit/`，原则上不依赖真实外部 API。

```bash
uv run pytest tests/unit
uv run pytest tests/unit/test_config.py
uv run pytest tests/unit/test_evidence_dispatch.py
uv run pytest tests/unit/test_evidence_dispatch_extraction.py
uv run pytest tests/unit/test_aggregator.py tests/unit/test_state.py
```

关键覆盖：

| 文件 | 覆盖范围 |
|------|----------|
| `test_config.py` | 主配置和模型配置加载 |
| `test_evidence_dispatch.py` | `METRIC_REGISTRY`、`AGENT_REGISTRY`、`dispatch_specs` |
| `test_evidence_dispatch_extraction.py` | 指标 extract_path 校准 |
| `test_aggregator.py` | 0-5 聚合、Corrector 优先级、grade |
| `test_state.py` | Pydantic 分数边界 |
| `test_citation_graph_analysis.py` | 图指标和聚类逻辑 |
| `test_pdf_parser.py` | PDF parser 接口和 fallback |

### 10.2 集成测试

集成测试位于 `tests/integration/`，可能需要 Docker、API Key、真实 PDF 或网络。

```bash
uv run pytest tests/integration/test_citation_graph_pipeline.py
uv run pytest tests/integration/test_citation_grobid.py
uv run pytest tests/integration/test_marker_api_parser.py
uv run pytest tests/integration/test_parallel_literature_search.py
uv run pytest tests/integration/test_semantic_scholar_fetcher.py
```

约定：

- 未配置外部 API Key 时应 skip，而不是失败。
- GROBID 测试需要本地 `http://localhost:8070` 可用。
- Marker API 测试需要 `DATALAB_API_KEY`。
- 网络检索测试需要相应 API Key 或可访问的公开端点。

### 10.3 代码质量

```bash
uv run ruff format .
uv run ruff check .
uv run mypy src/
```

### 10.4 文档更新自检

更新本文档时至少检查：

```powershell
Select-String -Path docs\DEVELOPER_GUIDE.zh-CN.md -Pattern 'Addendum'
git diff --check
```

---

## 11. 常见问题

### Q: 为什么输出目录有两层 run id？

外层目录由 `main.py` 创建，用于日志和最终报告：

```text
output/runs/{outer_run_id}/logs
output/runs/{outer_run_id}/reports
```

内层目录由 `ResultStore` 创建，用于结构化 JSON：

```text
output/runs/{outer_run_id}/{store_run_id}/run.json
output/runs/{outer_run_id}/{store_run_id}/papers/{paper_id}/...
```

### Q: 如何判断 GROBID 是否可用？

```bash
curl http://localhost:8070/api/isalive
```

或使用脚本：

```powershell
.\scripts\grobid.ps1 -Action status
```

```bash
scripts/grobid.sh status
```

### Q: V2 为什么有时直接是 1 分？

当 C6 的 `contradiction_rate` 超过 `config/main.yaml::evidence.contradiction_threshold` 时，`c6_alignment.auto_fail=true`，Evidence Dispatch 会把 V2 写入 `pre_filled_scores`，分数为 1。

### Q: Corrector 为什么没有独立分数？

当前 Corrector 是纯校正角色，不再输出 C1/C2/C3 之类独立维度。它只写入 `corrector_output.corrections`，Aggregator 在计算 `dimension_scores` 时优先使用 `corrected_score`。

### Q: 如何快速定位一次运行失败？

优先顺序：

1. `output/runs/{outer}/logs/summary.log`
2. `output/runs/{outer}/logs/run.log`
3. `output/runs/{outer}/{store}/papers/{paper_id}/nodes/{step}.json`
4. `tools/*.json` 中对应工具的原始输出

### Q: 为什么 `tools/graph_analysis.json` 和 `tool_evidence.graph_analysis` 不一样？

`tools/graph_analysis.json` 是 `CitationGraphAnalyzer.analyze()` 的原始结构，外层为 `citation_graph_analysis`。Evidence Collection 会从该结构中抽取 G1-G6、S5、missing/suspicious 列表，放到 `tool_evidence.graph_analysis` 的扁平键中，供 Evidence Dispatch 读取。

### Q: 如何修改多模型投票模型？

修改 `config/models.yaml::agents.corrector.multi_model.models`。每个模型需要 provider、model、temperature。provider 的 `base_url` 和 `env_key` 在 `providers` 段定义。

### Q: 如何关闭某个检索源？

修改 `config/search_engines.yaml`：

```yaml
sources:
  semantic_scholar:
    enabled: false
```

若某源不稳定但仍想作为兜底，可设置：

```yaml
concurrent: false
```

并把它放入 `degradation.fallback_order`。

### Q: `.md` 输入和 `.pdf` 输入有什么区别？

`src/main.py` 支持 `.md`，会直接读取文本。`builder._parse_pdf_node()` 也对 `.md` 做标题抽取。`.pdf` 会走配置的 PDF parser，并可能产生 Marker/PyMuPDF 缓存。
