# SurveyMAE 开发文档

> **文档版本**: v3.1 (2026-04-07)  
> **对应代码版本**: Phase 2 完成 (refactoring + logging + parallel search)  
> **计划参考**: [SurveyMAE_Plan_v3.md](SurveyMAE_Plan_v3.md)

## 目录

| 章节 | 行号范围 | 说明 |
|------|----------|------|
| [项目概述](#项目概述) | L29-L83 | 核心特性、评估维度（V1-V4/E1-E4/R1-R4） |
| [快速开始](#快速开始) | L84-L133 | 安装步骤、CLI 用法、日志控制参数 |
| [项目架构](#项目架构) | L134-L289 | 目录结构、数据流、各层职责 |
| [配置说明](#配置说明) | L290-L509 | main.yaml、search_engines.yaml、models.yaml |
| [扩展指南](#扩展指南) | L510-L637 | 添加子维度、指标、Agent、工具 |
| [工具集成](#工具集成) | L638-L709 | PDF解析、引用检查、图分析、G4分析 |
| [日志系统](#日志系统) | L710-L805 | Rich+logging架构、进度条、RunStats |
| [并行文献检索](#并行文献检索) | L806-L876 | ParallelDispatcher、并发配置、降级策略 |
| [证据分发系统](#证据分发系统) | L877-L994 | METRIC_REGISTRY、AGENT_REGISTRY、dispatch_specs |
| [结果持久化](#结果持久化) | L995-L1323 | ResultStore、JSON输出示例、文件层级 |
| [SurveyState 完整参考](#surveystate-完整参考) | L1324-L1442 | 状态字段分类、类型定义、读写关系 |
| [测试指南](#测试指南) | L1443-L1499 | 测试运行、分类约定、代码检查 |
| [API 参考](#api-参考) | L1500-L1684 | 日志API、ParallelDispatcher、ResultStore |
| [常见问题](#常见问题) | L1685-L1811 | 配置调试、故障排查、开发技巧 |
| [贡献指南](#贡献指南) | L1812-L1832 | 代码规范、提交流程 |
| [文献检索组件复用](#文献检索组件复用bibguard-fetchers) | L1833-L1868 | BibGuard fetchers集成、MCP配置 |
| [Citation Graph Addendum](#citation-graph-addendum-2026-03) | L1869-L1927 | 引用图流程、可视化、集成测试 |

---

## 项目概述

**SurveyMAE** (Survey Multi-Agent Evaluation) 是一个基于 LangGraph 的多智能体动态评测框架，专门用于评估 LLM 生成的学术综述（Survey）质量。

### 核心特性

- **多维度评估**: 4 个专业智能体从不同角度评估综述质量（V/E/R + Corrector 校正）
- **多厂商模型支持**: 支持 9+ LLM 提供商（OpenAI、Anthropic、Kimi、Qwen、ChatGLM、Step、Deepseek、Gemini、Seed）
- **多模型投票校正**: CorrectorAgent 对高幻觉风险子维度执行多模型并行投票，附加方差信息
- **证据化评测**: 工具层产出结构化证据（引用图分析、C6 对齐、检索增强时序/覆盖分析），Agent 基于证据评分
- **单一真相来源**: `evidence_dispatch.py` 中的 METRIC_REGISTRY 和 AGENT_REGISTRY 驱动全链路指标定义
- **并行文献检索**: ParallelDispatcher 支持多源并发检索、单源重试、降级兜底
- **MCP 协议**: 工具可通过 MCP 协议暴露和调用
- **可扩展架构**: 易于添加新的评估维度和智能体
- **配置驱动**: 所有配置外部化，支持 YAML 管理

### 评估维度（v3）

| 智能体 | 子维度 | 描述 | 幻觉风险 | Corrector 投票 |
|--------|--------|------|----------|----------------|
| VerifierAgent | V1: 引用存在性 | C5 阈值驱动 | low | 否 |
| VerifierAgent | V2: 引用-断言对齐 | C6 contradiction_rate（原V2/V3已合并到C6），可短路为 1 | low | 否 |
| VerifierAgent | V4: 内部一致性 | 基于 parsed_content 的 LLM 判断 | high | **是** |
| ExpertAgent | E1: 核心文献覆盖 | G4 阈值驱动 | low | 否 |
| ExpertAgent | E2: 方法分类合理性 | G5+S5 | medium | **是** |
| ExpertAgent | E3: 技术准确性 | 纯 LLM 判断 | high | **是** |
| ExpertAgent | E4: 批判性分析深度 | 纯 LLM 判断 | high | **是** |
| ReaderAgent | R1: 时效性 | T1-T5 阈值驱动 | low | 否 |
| ReaderAgent | R2: 信息分布均衡性 | S2/S3/S5 | medium | **是** |
| ReaderAgent | R3: 结构清晰度 | S1/S5 | medium | **是** |
| ReaderAgent | R4: 文字质量 | 纯 LLM 判断 | high | **是** |
| CorrectorAgent | —（纯校正角色）| 对 V4/E2-E4/R2-R4 多模型投票并附加方差 | — | — |
| ReporterAgent | —（报告生成）| 聚合 + 报告生成 + run_summary.json | — | — |

> **注意**：CorrectorAgent 在 v3 中不再产出独立评分维度（已移除原 C1/C2/C3），仅对高幻觉风险子维度做多模型投票校正，结果写入 `corrector_output`。

#### 评测指标层次

```
第一层（工具证据层）
  C-series: C3 (orphan_ref_rate), C5 (metadata_verify_rate), C6 (citation_sentence_alignment)
  T-series: T1-T5（时序分布 + 趋势对齐）
  S-series: S1-S5（结构分布 + 章节-聚类对齐）
  G-series: G1-G6（引用图结构 + 核心文献覆盖）

第二层（Agent 判断层）
  V1/V2/V4（VerifierAgent）、E1-E4（ExpertAgent）、R1-R4（ReaderAgent）
  每个子维度携带 hallucination_risk 标记，高风险维度由 Corrector 附加方差

第三层（汇总报告层）
  加权聚合（DimensionScore）、run_summary.json、Markdown 诊断报告
```

---

## 快速开始

### 前置要求

- Python 3.12+
- uv 包管理器

### 安装步骤

```bash
# 克隆项目
git clone https://github.com/your-org/SurveyMAE.git
cd SurveyMAE

# 安装依赖
uv sync

# 复制环境变量模板
cp .env.example .env

# 编辑 .env 添加 API Key
# OPENAI_API_KEY=your-key-here
```

### 运行评测

```bash
# 基本用法
uv run python -m src.main path/to/survey.pdf

# 指定输出目录
uv run python -m src.main path/to/survey.pdf -o ./my_output

# 使用自定义配置
uv run python -m src.main path/to/survey.pdf -c config/main.yaml

# 启用详细日志（控制台输出 DEBUG）
uv run python -m src.main path/to/survey.pdf -v

# 静默模式（仅 WARNING/ERROR，抑制进度条）
uv run python -m src.main path/to/survey.pdf -q

# 自定义日志级别（覆盖 -v/-q）
uv run python -m src.main path/to/survey.pdf --log-level DEBUG
```

> `-v` 和 `-q` 互斥。`--log-level` 显式指定时优先级最高。

---

## 项目架构

### 目录结构

```
SurveyMAE/
├── config/                     # 配置文件目录
│   ├── main.yaml              # 主配置（LLM、Agent、MCP服务器等）
│   ├── models.yaml            # 模型配置（多厂商、多模型投票）
│   ├── search_engines.yaml    # 文献检索配置（含并发/降级策略）
│   └── prompts/               # Agent System Prompt 模板
│       ├── verifier.yaml      # 仅角色描述 + 占位符（rubric 已移至 registry）
│       ├── expert.yaml
│       ├── reader.yaml
│       ├── corrector.yaml
│       └── reporter.yaml
├── src/
│   ├── main.py                # CLI 入口点（自动加载 .env）
│   ├── core/                  # 核心框架层
│   │   ├── state.py           # LangGraph 状态定义（TypedDict）
│   │   ├── config.py          # 配置加载与管理
│   │   ├── search_config.py   # 检索引擎配置（v3 新增，含并发配置）
│   │   ├── mcp_client.py      # MCP 客户端封装
│   │   └── log.py             # 日志系统（Rich + FileHandler + RunStats）
│   ├── agents/                # 智能体层
│   │   ├── base.py            # Agent 抽象基类（统一 evaluate 实现）
│   │   ├── verifier.py        # 事实验证智能体（V1/V2/V4）
│   │   ├── expert.py          # 领域专家智能体（E1-E4）
│   │   ├── reader.py          # 读者模拟智能体（R1-R4）
│   │   ├── corrector.py       # 偏差校正智能体（多模型投票，纯校正角色）
│   │   ├── reporter.py        # 报告生成智能体
│   │   └── output_schema.py   # Agent 输出 schema 定义
│   ├── graph/                 # LangGraph 图编排层
│   │   ├── builder.py         # StateGraph 构建与编译（含 ResultStore 初始化）
│   │   ├── edges.py           # 条件边路由逻辑
│   │   └── nodes/             # 节点实现
│   │       ├── evidence_collection.py  # 证据收集节点
│   │       ├── evidence_dispatch.py    # 证据分发节点（METRIC_REGISTRY/AGENT_REGISTRY）
│   │       ├── aggregator.py          # 评分聚合节点
│   │       └── debate.py              # 辩论/共识节点（保留）
│   └── tools/                 # 工具实现
│       ├── pdf_parser.py
│       ├── citation_checker.py
│       ├── citation_metadata.py
│       ├── citation_analysis.py
│       ├── citation_graph_analysis.py
│       ├── literature_search.py       # 内部改用 ParallelDispatcher
│       ├── parallel_dispatcher.py     # v3 新增：并发多源调度器
│       ├── foundational_coverage.py   # G4 核心文献覆盖分析
│       ├── keyword_extractor.py       # 关键词提取（LLM 辅助）
│       ├── result_store.py            # 结果持久化（tools/+nodes/ 分离）
│       └── fetchers/                  # 各学术源适配器（arXiv/CrossRef等）
├── output/
│   └── runs/{run_id}/                 # main.py 生成的外层目录
│       ├── logs/
│       │   ├── run.log                # 完整 DEBUG 日志
│       │   └── summary.log           # 仅 pipeline 步骤摘要
│       ├── reports/
│       │   └── {pdf_name}_{ts}.md    # 最终评测报告
│       └── {store_run_id}/           # ResultStore 生成的内层目录
│           ├── run.json              # config 快照 + metrics_index（schema v3）
│           ├── run_summary.json      # 轻量结果摘要（含 dimension_scores）
│           ├── index.json            # 所有 paper 状态索引
│           └── papers/{paper_id}/
│               ├── source.json       # 源文件信息（路径、SHA256、大小）
│               ├── nodes/            # workflow 步骤增量输出
│               │   ├── 01_parse_pdf.json
│               │   ├── 02_evidence_collection.json
│               │   ├── 03_evidence_dispatch.json
│               │   ├── 04_verifier.json
│               │   ├── 04_expert.json
│               │   ├── 04_reader.json
│               │   ├── 05_corrector.json
│               │   ├── 06_aggregator.json
│               │   └── 07_reporter.json
│               └── tools/            # 工具层原始输出
│                   ├── extraction.json      # 引用提取结果
│                   ├── validation.json      # C3/C5 + ref_metadata_cache
│                   ├── c6_alignment.json    # C6 对齐分析结果
│                   ├── analysis.json        # T1-T5, S1-S4 时序/结构指标
│                   ├── graph_analysis.json  # G1-G6, S5 图分析指标
│                   ├── trend_baseline.json  # 领域趋势基线
│                   └── key_papers.json      # G4 核心文献覆盖
└── tests/
    ├── unit/
    └── integration/
```

> **目录层级说明**：`run_id`（如 `20260406T161703Z_53317b7e`）由 `main.py` 生成，用于日志和报告目录定位。`store_run_id`（如 `20260406T161726Z_run`）由 `ResultStore` 在内部生成，存放 JSON 数据文件。两者均位于 `output/runs/` 下，形成嵌套结构。
>
> **注意**：批量评测模式（多 PDF）目前尚未完全实现，目录结构已预留支持。当前 `main.py` 仅接受单个 PDF 路径。
>
> ```text
> output/runs/{main_run_id}/
> ├── logs/               # 日志文件（main.py 创建）
> ├── reports/            # Markdown 报告（main.py 创建）
> └── {store_run_id}/     # ResultStore 目录
>     ├── run.json        # config 快照 + metrics_index
>     ├── run_summary.json
>     ├── index.json
>     └── papers/{paper_id}/
>         ├── source.json
>         ├── nodes/      # workflow 步骤输出
>         └── tools/      # 工具层输出
> ```
>
> **示例**：`output/runs/20260406T161703Z_53317b7e/20260406T161726Z_run/papers/40b1a0d0d47b/tools/validation.json`

### 数据流

```
PDF 输入
    │
    ▼
[01_parse_pdf] ─── parsed_content, section_headings
    │               💾 nodes/01_parse_pdf.json
    ▼
[02_evidence_collection] ── 统一执行所有工具，产出结构化证据
    │  ├─ CitationChecker.validate → C3, C5, ref_metadata_cache
    │  │   💾 tools/extraction.json, tools/validation.json
    │  ├─ CitationChecker.C6_alignment → contradiction_rate, auto_fail
    │  │   💾 tools/c6_alignment.json
    │  ├─ KeywordExtractor → topic_keywords（共享给 T2/T5/G4）
    │  ├─ LiteratureSearch → field_trend_baseline（T2/T5）
    │  │   💾 tools/trend_baseline.json
    │  ├─ LiteratureSearch → candidate_key_papers（G4）
    │  │   💾 tools/key_papers.json
    │  ├─ CitationAnalyzer → T1-T5, S1-S4
    │  │   💾 tools/analysis.json
    │  └─ CitationGraphAnalysis → G1-G6, S5
    │      💾 tools/graph_analysis.json
    │  💾 nodes/02_evidence_collection.json（增量，ref_metadata_cache 引用 validation.json）
    ▼
[03_evidence_dispatch] ── 从 METRIC_REGISTRY 提取指标值，生成 dispatch_specs
    │  ★ 若 C6.auto_fail=true → V2 预填 1 分，不出现在 dispatch_specs
    │  💾 nodes/03_evidence_dispatch.json
    │
    ├──→ [04_verifier] ── VerifierAgent(V1+V2+V4)
    ├──→ [04_expert]   ── ExpertAgent(E1-E4)
    └──→ [04_reader]   ── ReaderAgent(R1-R4)
    │  各 Agent 从 state["dispatch_specs"][agent_name] 读取精确上下文
    │  💾 nodes/04_{agent}.json
    ▼
[05_corrector] ─── 从 get_corrector_targets() 动态获取投票目标
    │              对 V4/E2-E4/R2-R4 做多模型并行投票，附加 variance
    │  💾 nodes/05_corrector.json
    ▼
[06_aggregator] ── 加权聚合：corrected_score 优先，保留 DimensionScore
    │  💾 nodes/06_aggregator.json
    ▼
[07_reporter] ─── 生成 Markdown 报告 + run_summary.json
    │  💾 nodes/07_reporter.json, run_summary.json, reports/{pdf_name}_{ts}.md
```

---

## 配置说明

### 主配置文件 (config/main.yaml)

```yaml
llm:
  provider: "openai"
  model: "gpt-4o"
  api_key: "${OPENAI_API_KEY}"
  base_url: null
  temperature: 0.0
  max_tokens: 4096

agents:
  - name: "verifier"
    retry_attempts: 3
    timeout: 120
  - name: "expert"
    retry_attempts: 3
    timeout: 120
  - name: "reader"
    retry_attempts: 3
    timeout: 120
  - name: "corrector"
    retry_attempts: 3
    timeout: 120

debate:
  max_rounds: 3
  score_threshold: 2.0
  aggregator: "weighted"
  weights:
    verifier: 1.0
    expert: 1.2
    reader: 1.0
    corrector: 0.8

report:
  output_dir: "./output"
  include_evidence: true
  include_radar: true
  format: "markdown"

evidence:
  foundational_top_k: 30
  foundational_match_threshold: 0.85
  trend_query_count: 5
  trend_year_range: [2015, 2025]
  c6_batch_size: 10
  c6_model: "qwen3.5-flash"
  c6_max_concurrency: 5
  contradiction_threshold: 0.05
  v2_score_5_threshold: 0.01
  v2_score_4_threshold: 0.02
  v2_score_3_threshold: 0.03
  v2_score_2_threshold: 0.05
  citation_sample_size: 15
  api_timeout_seconds: 30
  fallback_order:
    - semantic_scholar
    - openalex
    - crossref
```

### 检索引擎配置 (config/search_engines.yaml)

v3 新增并发/降级配置段。旧版扁平格式仍可兼容（无 `sources:` 时自动回退到内置默认值）。

```yaml
verify_limit: 50
api_timeout_seconds: 15

concurrency:
  max_concurrent_sources: 3
  merge_strategy: weighted_union   # first_wins | union | weighted_union
  per_source_timeout_seconds: 10

degradation:
  fallback_order: [crossref, dblp]
  on_all_failed: empty             # empty | raise

sources:
  semantic_scholar:
    enabled: true
    priority: 1
    concurrent: true               # 参与并发批次
    max_retries: 2
    retry_delay_seconds: 2.0
    retry_backoff: 2.0
    retry_on_status: [429, 500, 502, 503, 504]
    timeout_seconds: 8
    api_key: ${SEMANTIC_SCHOLAR_API_KEY}

  openalex:
    enabled: true
    priority: 2
    concurrent: true
    max_retries: 1
    retry_delay_seconds: 1.0
    retry_backoff: 1.5
    timeout_seconds: 10
    email: ${OPENALEX_EMAIL}

  crossref:
    enabled: true
    priority: 3
    concurrent: false              # 仅作降级 fallback
    max_retries: 2
    retry_delay_seconds: 1.0
    retry_backoff: 2.0
    timeout_seconds: 12
    mailto: surveymae@example.com

  dblp:
    enabled: true
    priority: 5
    concurrent: false
    max_retries: 1
    timeout_seconds: 10

  scholar:
    enabled: false                 # 默认关闭（爬取风险高）
```

**合并策略说明**：

| 策略 | 行为 | 适用场景 |
|------|------|----------|
| `first_wins` | 取最先返回有结果的源 | 延迟敏感 |
| `union` | 全部源结果合并去重 | 最大召回率 |
| `weighted_union` | priority 高的源结果优先，低优先级补充缺失（默认） | 平衡质量与速度 |

### 模型配置文件 (config/models.yaml)

```yaml
default:
  provider: openai
  model: gpt-4o
  temperature: 0.0
  max_tokens: 4096

tools:
  citation_checker:
    provider: qwen
    model: qwen3.5-flash
    temperature: 0.1
    max_tokens: 4096

agents:
  corrector:
    provider: qwen
    model: qwen3.5-flash
    multi_model:
      enabled: true
      models:
        - provider: qwen
          model: qwen3.5-flash
        - provider: deepseek
          model: deepseek-chat
        - provider: qwen
          model: qwen3.5-flash

providers:
  openai:
    base_url: null
    models: [gpt-4o, gpt-4o-mini, gpt-4-turbo]
  qwen:
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    models: [qwen-turbo, qwen-plus, qwen-max]
  deepseek:
    base_url: https://api.deepseek.com/v1
    models: [deepseek-chat, deepseek-coder]
  # ... 其余 provider 同理
```

### Prompt 模板 (config/prompts/)

**v3 重构后**，prompt yaml 只保留角色描述和通用指令框架，rubric 和 output schema 全部从 AGENT_REGISTRY 在运行时注入（见[证据分发系统](#证据分发系统)）。

```yaml
# config/prompts/verifier.yaml（精简后示例）
template: |
  You are VerifierAgent, a factuality specialist reviewing an academic survey.

  Your task is to evaluate the sub-dimension described below based on the provided evidence.
  Output ONLY a valid JSON object matching the schema in the context.

  Sub-Dimension Context:
  {sub_dimension_context}

  Survey Content:
  {parsed_content}
```

模板中不出现任何 `V1`/`V2` 等子维度 ID 或 `T5`/`C6` 等指标 ID，这些全部由 `{sub_dimension_context}` 在运行时注入。

### 环境变量 (.env)

```bash
# LLM 提供商 API Keys
OPENAI_API_KEY=sk-your-key-here
ANTHROPIC_API_KEY=sk-ant-your-key-here
KIMI_API_KEY=your_kimi_key_here
DASHSCOPE_API_KEY=your_qwen_key_here
ZHIPU_API_KEY=your_chatglm_key_here
STEP_API_KEY=your_step_key_here
DEEPSEEK_API_KEY=your_deepseek_key_here
GOOGLE_API_KEY=your_google_key_here
BYTEAPI_KEY=your_byte_key_here

# 文献检索 API Keys
SEMANTIC_SCHOLAR_API_KEY=your_s2_key_here
OPENALEX_EMAIL=your_email@example.com

# 可选：覆盖检索配置路径
SURVEYMAE_SEARCH_CONFIG=config/search_engines.yaml
```

---

## 扩展指南

### 添加新的评估子维度

只需在 `evidence_dispatch.py` 的 `AGENT_REGISTRY` 中添加 `SubDimensionDef`，无需修改 Agent 代码或 prompt 模板：

```python
# src/graph/nodes/evidence_dispatch.py

SubDimensionDef(
    sub_id="R5",
    name="novelty",
    description="Whether the survey identifies research gaps and future directions",
    hallucination_risk="high",
    evidence_metric_ids=["G4", "G5"],  # 只注入这些指标的上下文
    rubric="""
- 5: Clearly identifies 3+ research gaps with specific future directions
- 4: Identifies 2 gaps with partial future work discussion
- 3: Mentions limitations but lacks depth
- 2: Only superficial mentions of limitations
- 1: No future work or research gap discussion
""",
)
```

添加后，对应 Agent 会自动读取并评分，aggregator 会自动包含该维度，无需改动其他代码。

### 添加新的指标（Metric）

如需添加新的第一层指标（如 C7、T6 等），需在 `METRIC_REGISTRY` 中定义：

```python
# src/graph/nodes/evidence_dispatch.py

METRIC_REGISTRY["C7"] = MetricDef(
    metric_id="C7",
    name="citation_format_consistency",
    description="Consistency of citation format throughout the survey",
    source="CitationChecker",
    extract_path="validation.C7_format_consistency",  # 从 tool_evidence 提取的路径
    llm_involved=False,
    hallucination_risk="none",
)
```

然后在 `evidence_collection.py` 中实现该指标的计算，并在对应 Agent 的 `evidence_metric_ids` 中引用。

### 添加新的评估 Agent

1. **创建 Agent 文件** (`src/agents/new_agent.py`):

```python
from src.agents.base import BaseAgent
from src.core.config import AgentConfig

class NewAgent(BaseAgent):
    def __init__(self, config=None, mcp=None):
        super().__init__(name="new_agent", config=config or AgentConfig(name="new_agent"), mcp=mcp)
    # evaluate() 由基类统一实现，不需要 override
```

2. **在 `AGENT_REGISTRY` 中注册** (`src/graph/nodes/evidence_dispatch.py`):

```python
"new_agent": AgentDef(
    agent_name="new_agent",
    dimension="novelty",
    input_metric_ids=["G4", "G5"],
    sub_dimensions=[
        SubDimensionDef(sub_id="N1", name="gap_identification", ...),
    ],
    state_fields=["parsed_content"],
)
```

3. **注册到 Workflow** (`src/graph/builder.py`):

```python
from src.agents.new_agent import NewAgent
# 在 _create_agents() 中添加 NewAgent
```

4. **更新配置** (`config/main.yaml`):

```yaml
agents:
  - name: "new_agent"
    retry_attempts: 3
```

### 自定义工具

#### 方式 1: 集成现有 Python 库

```python
from src.tools.pdf_parser import PDFParser

class MyAgent(BaseAgent):
    def __init__(self, config=None, mcp=None):
        super().__init__(name="my_agent", config=config, mcp=mcp)
        self.pdf_parser = PDFParser()
```

#### 方式 2: 暴露为 MCP Tool

```python
# src/tools/my_tool.py
from mcp.server import Server
from mcp.types import Tool

app = Server("my-tool")

@app.list_tools()
async def list_tools():
    return [Tool(name="my_function", description="...", inputSchema={...})]
```

#### 方式 3: 使用外部 MCP Server

```yaml
# config/main.yaml
mcp_servers:
  - name: "external_search"
    url: "http://localhost:3000/mcp"
```

---

## 工具集成

### PDF 解析工具

```python
from src.tools.pdf_parser import PDFParser

parser = PDFParser()
content = parser.parse("paper.pdf")
```

### 引用检查工具

```python
from src.tools.citation_checker import CitationChecker

checker = CitationChecker()
result = checker.extract_citations_with_context_from_pdf("paper.pdf")
# result["citations"]: 每条引用含 marker/sentence/page/paragraph_index
# result["references"]: 结构化参考文献列表
```

**关键字段说明**：

| 字段 | 说明 |
|------|------|
| `marker` | 单个引用标记，如 `[15]` |
| `marker_raw` | 原始串，如 `[25, 15, 26]` |
| `sentence` | 引用所在完整句子 |
| `page` | 页码（1-based） |
| `paragraph_index` | 段落序号 |
| `line_in_paragraph` | 段落内行号（1-based） |

### 引用图分析工具

```python
from src.tools.citation_graph_analysis import CitationGraphAnalyzer

analyzer = CitationGraphAnalyzer()
result = analyzer.analyze(references=refs, edges=real_citation_edges)
# result["summary"]["density_connectivity"]: G1/G2/G3
# result["summary"]["centrality"]: PageRank 等
# result["summary"]["cocitation_clustering"]: G5 聚类
```

### G4 核心文献覆盖分析

```python
from src.tools.foundational_coverage import FoundationalCoverageAnalyzer

analyzer = FoundationalCoverageAnalyzer()
result = await analyzer.analyze(
    topic_keywords=keywords,
    references=refs,
    ref_metadata_cache=cache,
    top_k=30,
)
# result["coverage_rate"]: G4 覆盖率
# result["missing_key_papers"]: 应引但未引的高被引论文
# result["suspicious_centrality"]: 内部 PageRank 高但外部被引低的论文
```

### GROBID（可选后端）部署

```bash
docker compose -f docker-compose.grobid.yaml up -d
```

GROBID 仅在可用时参与 References 解析，不可用时自动回退到 PyMuPDF。

---

## 日志系统

### 架构概览

SurveyMAE 使用 Python `logging` + `Rich` 库实现**双通道**日志输出：

```
控制台（stderr）                    文件（run.log / summary.log）
├── Console 直接渲染                ├── FileHandler（纯文本，无 ANSI）
│   ├── 进度条（Rich Progress）     ├── run.log: DEBUG+ 全部级别
│   ├── 步骤信息（log_pipeline_step）└── summary.log: 仅 pipeline 步骤
│   └── 汇总统计（log_run_summary）
│
└── RichHandler → logging
    ├── WARNING（黄色）
    └── ERROR（红色 + traceback）
```

`summary.log` 是 v3 新增的轻量摘要文件，只记录 `log_pipeline_step()` 和 `log_substep()` 的输出，方便事后快速浏览一次运行的步骤概要。

### 日志级别

| 级别 | 控制台 | 文件 | 语义 |
|------|--------|------|------|
| `ERROR` | ✓ | ✓ | 流程中断或数据缺失 |
| `WARNING` | ✓ | ✓ | 已降级但用户应知晓（fallback 策略等） |
| `INFO` | ✓ | ✓ | Pipeline 进度里程碑（步骤开始/完成） |
| `DEBUG` | 仅 `-v` | ✓ | 调试细节（网络参数、state 变更等） |

- 第三方库（langchain、langgraph、httpx、openai 等）统一抑制到 `WARNING`
- Logger 命名规范：`surveymae.<module>`，如 `surveymae.graph.nodes.evidence_collection`

### 核心 API

```python
from src.core.log import (
    setup_logging,        # 初始化：Console + FileHandler + RichHandler + RunStats
    get_console,          # 获取全局 Console 实例
    create_progress,      # Rich Progress（transient=False）
    log_pipeline_step,    # [01/07] name │ detail  2.3s
    log_substep,          # ├── name │ detail  2.3s
    log_run_summary,      # 最终统计汇总
    track_step,           # with 上下文计时
    get_run_stats,        # 线程安全计数器
)
```

### `setup_logging()` 签名

```python
def setup_logging(
    run_dir: str | Path | None = None,
    verbose: bool = False,
    log_level: str | None = None,
    quiet: bool = False,
    pdf_path: str | None = None,   # 写入 summary.log 头部
) -> logging.Logger:
    ...
```

日志级别优先级：`--log-level` > `quiet` > `verbose` > 默认（INFO）。

### 进度条

长耗时迭代操作使用 `create_progress()` 包裹：

```python
from src.core.log import create_progress

progress = create_progress()
with progress:
    task = progress.add_task("验证引用", total=len(refs))
    for ref in refs:
        await validate(ref)
        progress.update(task, advance=1)
```

已集成进度条的场景：
- **引用元数据验证**：`citation_checker._verify_references()`
- **Corrector 多模型投票**：`corrector._vote_all_dimensions()`，使用 `asyncio.as_completed` 实时更新

### RunStats 统计

```python
from src.core.log import get_run_stats

stats = get_run_stats()
stats.record_llm(tokens_in=512, tokens_out=256)  # 在 base.py._call_llm() 中调用
stats.record_api()   # 在各 fetcher HTTP 成功响应后调用
# 最终输出：
log_run_summary(stats, total_elapsed)
# 效果：总耗时 51.2s │ LLM 调用 28 次 │ API 调用 94 次
```

---

## 并行文献检索

### 架构

`ParallelDispatcher`（`src/tools/parallel_dispatcher.py`）实现多源并发检索：

```
调用方 (evidence_collection.py)
    │
    ▼
LiteratureSearch.search_xxx(...)         ← 接口签名不变
    │
    ▼
ParallelDispatcher.dispatch_async(sources, build_op)
    │
    ├─── asyncio.gather (concurrent=True 的源)
    │         ├── [semantic_scholar] ── with_retry(n) ── 成功→结果
    │         └── [openalex]         ── with_retry(n) ── 成功→结果
    │
    ▼
结果合并 (merge_strategy: first_wins | union | weighted_union)
    │
    ▼
降级检查: 若结果为空 → 依次尝试 fallback_order（串行兜底）
```

### 使用方式

`LiteratureSearch` 的 public 方法签名不变，并发逻辑完全在内部：

```python
from src.tools.literature_search import LiteratureSearch

lit_search = LiteratureSearch()
results = await lit_search.search_top_cited(keyword, top_k=30)
trend = lit_search.search_field_trend(keyword, year_range=(2015, 2025))
```

### 直接使用 ParallelDispatcher

```python
from src.tools.parallel_dispatcher import ParallelDispatcher
from src.core.search_config import load_search_engine_config

config = load_search_engine_config()
dispatcher = ParallelDispatcher(config)

results = await dispatcher.dispatch_async(
    sources=config.get_concurrent_sources(),
    build_op=lambda src: lambda: fetcher_map[src].search(query),
)
```

### SearchEngineConfig API

```python
from src.core.search_config import load_search_engine_config

cfg = load_search_engine_config("config/search_engines.yaml")

cfg.get_concurrent_sources()   # 参与并发批次的源列表（按 priority 排序）
cfg.get_enabled_sources()      # 所有启用源列表
cfg.concurrency.merge_strategy # "weighted_union"
cfg.degradation.fallback_order # ["crossref", "dblp"]
cfg.sources["semantic_scholar"].max_retries  # 2
```

`load_search_engine_config()` 兼容新旧两种 YAML 格式。若 YAML 无 `sources:` 节，会使用内置默认值（semantic_scholar + openalex 并发，crossref/dblp 作 fallback）。

---

## 证据分发系统

### 概述

`src/graph/nodes/evidence_dispatch.py` 是 v3 重构的核心，它是指标定义、子维度定义、Rubric、映射关系、Corrector 投票目标的**单一真相来源**。

### METRIC_REGISTRY

19 个指标的定义，每个 `MetricDef` 包含：

| 字段 | 说明 |
|------|------|
| `metric_id` | 唯一标识，如 `"C6"` |
| `extract_path` | 从 `tool_evidence` 提取值的嵌套路径 |
| `llm_involved` | 是否涉及 LLM |
| `hallucination_risk` | `"none"/"low"/"medium"/"high"` |
| `extra_fields` | 额外提取字段（如 C6 的 `auto_fail`、`contradictions`） |

```python
from src.graph.nodes.evidence_dispatch import METRIC_REGISTRY

m = METRIC_REGISTRY["C6"]
# m.extract_path == "c6_alignment.contradiction_rate"
# m.extra_fields == ["auto_fail", "contradictions", "support", "contradict", "insufficient"]
```

### AGENT_REGISTRY

每个 `AgentDef` 包含该 Agent 所有子维度的完整定义：

```python
from src.graph.nodes.evidence_dispatch import AGENT_REGISTRY

agent = AGENT_REGISTRY["verifier"]
# agent.sub_dimensions = [SubDimensionDef(sub_id="V1", ...), SubDimensionDef(sub_id="V2", ...), ...]
```

每个 `SubDimensionDef` 包含 `rubric`（直接写入 dispatch_specs）和 `evidence_metric_ids`（精确上下文过滤），确保每次 LLM 调用只注入该子维度依赖的指标。

### dispatch_specs 结构

`run_evidence_dispatch()` 输出 `dispatch_specs` 写入 SurveyState，Agent 从中读取：

```python
dispatch_specs = {
    "verifier": {
        "sub_dimension_contexts": {
            "V1": {
                "sub_id": "V1",
                "name": "citation_existence",
                "rubric": "...",
                "evidence_metrics": {"C5": {"value": 0.64, "definition": "..."}},
                "supplementary_data": {"unverified_references": [...]},
                "output_schema": {...},
            },
            # V2 仅在 C6.auto_fail=False 时出现
        },
        "pre_filled_scores": {
            # 当 C6.auto_fail=True 时：
            # "V2": {"score": 1, "auto_failed": True, "reason": "C6.auto_fail triggered"}
        },
    },
    "expert": {...},
    "reader": {...},
}
```

### C6 短路机制

当 `contradiction_rate >= contradiction_threshold`（默认 5%）时：

- `c6_alignment.auto_fail = True`
- V2 被预填为 1 分，写入 `pre_filled_scores`，**不出现在 `sub_dimension_contexts`**
- VerifierAgent 不会对 V2 调用 LLM

```python
# 查看当前短路状态
auto_fail = tool_evidence.get("c6_alignment", {}).get("auto_fail", False)
```

### get_corrector_targets()

动态返回需要投票的子维度，基于 AGENT_REGISTRY 中的 `hallucination_risk`：

```python
from src.graph.nodes.evidence_dispatch import get_corrector_targets

targets = get_corrector_targets(agent_outputs, tool_evidence)
# 通常返回:
# {"verifier": ["V4"], "expert": ["E2", "E3", "E4"], "reader": ["R2", "R3", "R4"]}
# 当 C6.auto_fail=True 时，V2 的 risk 降为 low，不在投票列表
```

### BaseAgent.evaluate() 统一实现

v3 重构后，ReaderAgent/ExpertAgent/VerifierAgent 均不再 override `evaluate()`，基类统一实现：

```
读取 dispatch_specs[self.name]
  ↓
合并 pre_filled_scores（短路预填结果）
  ↓
遍历 sub_dimension_contexts（仅需 LLM 评分的子维度）
  ↓ 对每个子维度：
    a. 加载 prompt 模板 + 注入 sub_dimension_context + parsed_content
    b. 调用 LLM
    c. _parse_sub_dimension_output() 解析 JSON（带正则 fallback）
    d. [扩展点：未来可插入工具调用]
  ↓
合并 LLM 结果与 pre_filled_scores → AgentOutput
  ↓
返回 {"agent_outputs": {self.name: agent_output}}
```

子类文件（reader.py/expert.py/verifier.py）保留 `__init__` 和类定义（供未来扩展），不包含工具实例化或自定义解析方法。

---

## 结果持久化

### 分层职责

| 文件 | 层级 | 说明 |
|------|------|------|
| `logs/run.log` | run 级 | 完整 DEBUG 日志（main.py 生成的外层目录） |
| `logs/summary.log` | run 级 | 仅 pipeline 步骤摘要（v3 新增） |
| `reports/{pdf}_{ts}.md` | run 级 | 最终 Markdown 报告 |
| `{store_run_id}/run.json` | run 级 | config 快照 + `metrics_index`（schema_version: v3） |
| `{store_run_id}/run_summary.json` | run 级 | 轻量结果摘要（`dimension_scores` + `deterministic_metrics`） |
| `{store_run_id}/index.json` | run 级 | 所有 paper 的 `paper_id → status` 映射 |
| `papers/{id}/source.json` | paper 级 | 源文件信息（路径、SHA256、大小） |
| `papers/{id}/nodes/*.json` | paper 级 | workflow 步骤增量输出 |
| `papers/{id}/tools/*.json` | paper 级 | 工具层原始输出（独立持久化） |

### ResultStore API

```python
from src.tools.result_store import ResultStore

store = ResultStore(
    base_dir="./output/runs/my_run_id",
    run_id="20260406T161726Z_run",
    config_snapshot={"evidence": {...}},
)

paper_id = store.register_paper("paper.pdf")
store.save_extraction(paper_id, extraction_dict)
store.save_validation(paper_id, validation_dict)
store.save_c6_alignment(paper_id, c6_dict)
store.save_citation_analysis(paper_id, analysis_dict)
store.save_graph_analysis(paper_id, graph_dict)
store.save_trend_baseline(paper_id, trend_dict)
store.save_key_papers(paper_id, key_papers_dict)
store.save_node_step(paper_id, "04_verifier", step_record)
store.update_index(paper_id, status="graph_analyzed")
```

### 输出文件示例

#### tools/extraction.json

```json
{
  "citations": [
    {
      "marker": "[15]",
      "marker_raw": "[25, 15, 26]",
      "kind": "numeric",
      "sentence": "This question is important both scientifically...",
      "page": 1,
      "paragraph_index": 8,
      "line_in_paragraph": 2,
      "ref_key": "ref_15",
      "section_title": "1 Introduction"
    }
  ],
  "references": [...]
}
```

#### tools/validation.json

```json
{
  "paper_id": "40b1a0d0d47b",
  "validated_at": "2026-04-06T16:19:13Z",
  "sources": ["crossref", "dblp", "openalex"],
  "verify_limit": 100,
  "reference_validations": [
    {
      "key": "ref_1",
      "is_valid": true,
      "confidence": 1.0,
      "source": "openalex",
      "metadata": {
        "title": "Deep learning: a statistical viewpoint",
        "authors": ["Peter L. Bartlett", "Andrea Montanari", "Alexander Rakhlin"],
        "year": "2021",
        "abstract": "..."
      }
    }
  ],
  "real_citation_edges": [
    {"source": "ref_1", "target": "ref_3"}
  ],
  "real_citation_edge_stats": {"n_edges": 37, "n_sources": 36, "resolved_target_ratio": 0.02}
}
```

#### tools/c6_alignment.json

```json
{
  "metric_id": "C6",
  "llm_involved": true,
  "hallucination_risk": "low",
  "total_pairs": 76,
  "support": 39,
  "contradict": 29,
  "insufficient": 8,
  "contradiction_rate": 0.4265,
  "auto_fail": true,
  "contradictions": [
    {
      "citation": "[15]",
      "sentence": "This question is important both scientifically...",
      "ref_abstract": "Preface General Introduction...",
      "llm_judgment": "contradict",
      "note": "The abstract describes a book on culture, not LLMs"
    }
  ]
}
```

#### tools/analysis.json

```json
{
  "temporal": {
    "T1_year_span": 34,
    "T2_foundational_retrieval_gap": -25,
    "T3_peak_year_ratio": 0.594,
    "T4_temporal_continuity": 28,
    "T5_trend_alignment": 0.956,
    "year_distribution": {"2021": 3, "2022": 2, "2023": 5, "2024": 19},
    "earliest_year": 1990,
    "latest_year": 2024
  },
  "structural": {
    "S1_section_count": 4,
    "S2_citation_density": 0.897,
    "S3_citation_gini": 0.25,
    "S4_zero_citation_section_rate": 0.0,
    "total_citations": 78,
    "total_paragraphs": 87
  }
}
```

#### tools/trend_baseline.json

```json
{
  "yearly_counts": {
    "2015": 1189, "2016": 1342, "2017": 1390,
    "2018": 1601, "2019": 1608, "2020": 1791,
    "2021": 1732, "2022": 1740, "2023": 4298,
    "2024": 7203
  }
}
```

#### tools/key_papers.json

```json
{
  "candidate_papers": [
    {
      "title": "Large language models encode clinical knowledge",
      "authors": ["Karan Singhal", "..."],
      "year": "2023",
      "citation_count": 2818,
      "doi": "10.1038/s41586-023-06291-2"
    }
  ]
}
```

#### nodes/04_verifier.json

```json
{
  "step": "04_verifier",
  "timestamp": "2026-04-06T16:22:08+00:00",
  "source_pdf": "test_paper.pdf",
  "output": {
    "agent_outputs": {
      "verifier": {
        "agent_name": "verifier",
        "dimension": "factuality",
        "sub_scores": {
          "V2": {
            "score": 1,
            "llm_involved": false,
            "hallucination_risk": "low",
            "llm_reasoning": "C6.auto_fail triggered",
            "flagged_items": [],
            "variance": null
          },
          "V1": {
            "score": 3,
            "llm_involved": true,
            "hallucination_risk": "low",
            "tool_evidence": {"C5": 0.6389},
            "llm_reasoning": "metadata_verify_rate is 63.9%...",
            "flagged_items": ["ref_5"],
            "variance": null
          },
          "V4": {
            "score": 3,
            "llm_involved": true,
            "hallucination_risk": "high",
            "tool_evidence": {"c6_contradictions": 5},
            "llm_reasoning": "Some contradictions found...",
            "flagged_items": ["Citation [15] does not support..."],
            "variance": null
          }
        },
        "overall_score": 2.33,
        "confidence": 0.7
      }
    }
  }
}
```

#### nodes/05_corrector.json

```json
{
  "step": "05_corrector",
  "timestamp": "2026-04-06T16:23:23+00:00",
  "source_pdf": "test_paper.pdf",
  "output": {
    "corrector_output": {
      "corrections": {
        "V4": {
          "original_agent": "verifier",
          "original_score": 3,
          "corrected_score": 3.0,
          "variance": {
            "models_used": ["qwen3.5-flash", "deepseek-chat", "qwen3.5-flash"],
            "scores": [3.0, 3.0, 3.0],
            "median": 3.0,
            "std": 0.0,
            "high_disagreement": false
          }
        },
        "E3": {
          "original_agent": "expert",
          "original_score": 4,
          "corrected_score": 4.0,
          "variance": {
            "models_used": ["qwen3.5-flash", "deepseek-chat", "qwen3.5-flash"],
            "scores": [4.0, 4.0, 4.0],
            "median": 4.0,
            "std": 0.0,
            "high_disagreement": false
          }
        }
      },
      "skipped_dimensions": ["V1", "V2", "E1", "R1"],
      "skip_reason": "low hallucination_risk",
      "total_model_calls": 21,
      "failed_calls": 0
    }
  }
}
```

#### run_summary.json

```json
{
  "run_id": "20260406T161726Z_run",
  "source": "test_paper.pdf",
  "timestamp": "2026-04-06T16:23:23+00:00",
  "schema_version": "v3",
  "deterministic_metrics": {
    "C3": 0.028, "C5": 0.639, "C6_contradiction_rate": 0.4265,
    "G1": 0.0, "G2": 33, "G3": 0.03, "G4": 0.035,
    "G5": 0, "G6": 0.917, "S5": 0
  },
  "dimension_scores": {
    "V1": {"dim_id": "V1", "final_score": 3, "source": "original", "agent": "verifier",
           "hallucination_risk": "low", "variance": null, "weight": 1.0},
    "E2": {"dim_id": "E2", "final_score": 3.0, "source": "corrected", "agent": "expert",
           "hallucination_risk": "medium", "variance": {"std": 0.0, "high_disagreement": false}, "weight": 1.0},
    "E4": {"dim_id": "E4", "final_score": 3.0, "source": "corrected", "agent": "expert",
           "hallucination_risk": "high", "variance": {"std": 0.577, "high_disagreement": false}, "weight": 1.0}
  },
  "overall_score": 5.82,
  "grade": "D"
}
```

> `dimension_scores` 中 `source: "corrected"` 表示经 Corrector 投票校正，`source: "original"` 表示直接采用 Agent 原始分数（低风险维度）。

#### run.json（含 metrics_index）

```json
{
  "run_id": "20260406T161726Z_run",
  "created_at": "2026-04-06T16:17:26Z",
  "schema_version": "v3",
  "metrics_index": {
    "metrics": {
      "C6": {
        "name": "citation_sentence_alignment",
        "computed_by": "CitationChecker.analyze_citation_sentence_alignment",
        "source_file": "c6_alignment.json",
        "llm_involved": true,
        "hallucination_risk": "low",
        "consumed_by": ["VerifierAgent.V2"]
      },
      "G4": {
        "name": "foundational_coverage_rate",
        "computed_by": "FoundationalCoverageAnalyzer.analyze",
        "source_file": "key_papers.json",
        "llm_involved": true,
        "hallucination_risk": "low",
        "consumed_by": ["ExpertAgent.E1"]
      }
    },
    "agent_dimensions": {
      "VerifierAgent": {
        "input_evidence": ["C3", "C5", "C6"],
        "output_dimensions": ["V1", "V2", "V4"],
        "corrector_targets": ["V4"]
      }
    }
  }
}
```

---

## SurveyState 完整参考

`SurveyState` 是 LangGraph 工作流的核心状态类型，定义在 `src/core/state.py`。以下是其完整字段说明：

### 核心字段分类

```python
class SurveyState(TypedDict):
    # --- 输入层 ---
    source_pdf_path: str                    # PDF 文件路径
    parsed_content: str                     # PDF 解析后的文本内容
    section_headings: List[str]             # 章节标题列表

    # --- 工具证据层 (Phase 1) ---
    tool_evidence: ToolEvidence             # 所有工具输出汇总
    ref_metadata_cache: Dict[str, dict]     # 引用元数据缓存 (核心共享数据)
    topic_keywords: List[str]               # LLM 提取的主题关键词
    field_trend_baseline: Dict[str, Any]    # 领域趋势基线 (T2/T5)
    candidate_key_papers: List[dict]        # 候选关键论文 (G4)

    # --- Agent 评估层 (Phase 2) ---
    evaluations: List[EvaluationRecord]     # 评估记录列表 (累加器)
    sections: dict[str, SectionResult]      # 章节级评估结果
    agent_outputs: Dict[str, AgentOutput]   # 各 Agent 结构化输出
    corrector_output: Optional[CorrectorOutput]  # Corrector 校正结果
    aggregated_scores: AggregatedScores     # 聚合后的分数

    # --- 证据分发 (Phase 2) ---
    dispatch_specs: Optional[Dict[str, Any]]  # Agent 评估上下文
    metrics_index: Optional[Dict[str, Any]]   # 指标血缘索引

    # --- 控制流 ---
    current_round: int                      # 当前轮次 (从 0 开始)
    consensus_reached: bool                 # 是否达成共识

    # --- 输出层 ---
    final_report_md: str                    # 最终 Markdown 报告

    # --- 元数据 ---
    metadata: dict[str, str]                # 附加元数据
```

### 关键类型详解

#### ToolEvidence

```python
class ToolEvidence(TypedDict):
    extraction: Dict[str, Any]              # 引用提取结果
    validation: Dict[str, Any]              # C3/C5 验证结果
    c6_alignment: Optional[C6AlignmentResult]  # C6 对齐分析
    analysis: Dict[str, Any]                # T1-T5, S1-S4 时序/结构指标
    graph_analysis: Dict[str, Any]          # G1-G6, S5 图分析指标
    trend_baseline: Optional[Dict[str, Any]]  # 领域趋势基线
    key_papers: Optional[KeyPapersResult]   # G4 核心文献覆盖
```

#### AgentOutput

```python
class AgentOutput(TypedDict):
    agent_name: str                         # Agent 名称
    dimension: str                          # 评估维度
    sub_scores: Dict[str, AgentSubScore]   # 子维度评分
    overall_score: float                    # 综合得分
    confidence: float                       # 置信度
    evidence_summary: str                   # 证据摘要
```

#### AgentSubScore

```python
class AgentSubScore(TypedDict):
    score: float                           # 1-5 分
    llm_involved: bool                     # 是否使用 LLM
    hallucination_risk: str                # 幻觉风险等级
    tool_evidence: Dict[str, Any]          # 使用的工具证据
    llm_reasoning: str                     # LLM 推理过程
    flagged_items: Optional[List[Any]]    # 标记项
    variance: Optional[VarianceRecord]    # 多模型投票方差
```

#### CorrectorOutput

```python
class CorrectorOutput(TypedDict):
    corrections: Dict[str, CorrectionRecord]  # 校正记录
    skipped_dimensions: List[str]            # 跳过的低风险维度
    skip_reason: str                         # 跳过原因
    total_model_calls: int                   # 总模型调用次数
    failed_calls: int                        # 失败调用次数
```

#### AggregatedScores

```python
class AggregatedScores(TypedDict):
    dimension_scores: Dict[str, DimensionScore]    # 各维度最终分数
    deterministic_metrics: Dict[str, float]        # 第一层确定性指标
    overall_score: float                           # 总分 (0-10)
    grade: str                                     # 等级 (A/B/C/D/F)
    total_weight: float                            # 总权重
```

### 字段写入/读取关系

| 字段 | 写入节点 | 读取节点 |
|------|---------|---------|
| `tool_evidence` | evidence_collection | evidence_dispatch |
| `ref_metadata_cache` | evidence_collection | evidence_dispatch |
| `topic_keywords` | evidence_collection | evidence_dispatch |
| `dispatch_specs` | evidence_dispatch | V/E/R Agents |
| `metrics_index` | evidence_dispatch | reporter |
| `agent_outputs` | evidence_dispatch (预填) + V/E/R Agents | corrector, aggregator |
| `corrector_output` | corrector | aggregator, reporter |
| `aggregated_scores` | aggregator | reporter |

---

## 测试指南

> **TODO**: 当前测试脚本存在冗余情况，正在清理中。以下文档描述的是目标状态，实际运行可能需要调整。

### 运行测试

```bash
# 运行所有测试
uv run pytest

# 运行特定测试文件
uv run pytest tests/unit/test_config.py

# 运行特定测试
uv run pytest tests/unit/test_evidence_dispatch.py -v

# 带详细输出
uv run pytest -v

# 生成覆盖率报告
uv run pytest --cov=src --cov-report=html
```

### 测试分类约定

- `tests/unit/`: 纯逻辑、无外部依赖、使用 mock 模拟 LLM 调用
- `tests/integration/`: 允许真实 API / 真实 PDF 解析
- 集成测试应在未配置密钥时 `skip`，避免 CI 报错

### 已有关键测试文件

| 文件 | 覆盖范围 |
|------|---------|
| `tests/unit/test_evidence_dispatch.py` | METRIC_REGISTRY 指标提取、dispatch_specs 结构验证 |
| `tests/unit/test_evidence_dispatch_extraction.py` | 19 个指标的 extract_path 校准 |
| `tests/unit/test_corrector.py` | CorrectorAgent 多模型投票逻辑 |
| `tests/integration/test_citation_graph_pipeline.py` | PDF 解析 → 验证 → 图分析 → 可视化完整链路 |

### 环境变量加载

```python
# tests/conftest.py 在 pytest 启动时自动加载 .env
# 无需手动设置，但测试代码中应检查：
if not os.getenv("OPENAI_API_KEY"):
    pytest.skip("No OPENAI_API_KEY available")
```

### 代码质量检查

```bash
uv run ruff format .
uv run ruff check .
uv run mypy src/
```

---

## API 参考

### 日志系统 API

#### setup_logging

```python
def setup_logging(
    run_dir: str | Path | None = None,
    verbose: bool = False,
    log_level: str | None = None,
    quiet: bool = False,
    pdf_path: str | None = None,
) -> logging.Logger:
    """Initialize SurveyMAE logging system.

    Args:
        run_dir: Output directory for logs (creates logs/run.log)
        verbose: Enable DEBUG output on console
        log_level: Explicit level (DEBUG/INFO/WARNING/ERROR)
        quiet: Suppress progress, only WARNING+ on console
        pdf_path: PDF path for summary.log header

    Returns:
        The "surveymae" root logger
    """
```

#### log_pipeline_step

```python
def log_pipeline_step(
    step: str,
    total: int,
    name: str,
    detail: str = "",
    elapsed: float | None = None,
) -> None:
    """Output pipeline step to console and file.

    Example: [01/07] parse_pdf │ 47 refs, 12 sections 2.3s
    """
```

#### create_progress

```python
def create_progress(quiet: bool = False) -> Progress:
    """Create Rich Progress bar for long-running operations.

    Usage:
        with create_progress() as progress:
            task = progress.add_task("Validating", total=47)
            for item in items:
                process(item)
                progress.update(task, advance=1)
    """
```

### ParallelDispatcher

```python
from src.tools.parallel_dispatcher import ParallelDispatcher
from src.core.search_config import load_search_engine_config

config = load_search_engine_config()
dispatcher = ParallelDispatcher(config)

# Async usage (preferred)
results = await dispatcher.dispatch_async(
    sources=["semantic_scholar", "openalex"],
    build_op=lambda source: lambda: fetcher_map[source].search(query),
)

# Sync usage
results = dispatcher.dispatch(sources, build_op)
```

### ResultStore

```python
from src.tools.result_store import ResultStore

store = ResultStore(
    base_dir="./output/runs",
    run_id="20260406T161726Z_run",
    config_snapshot={"evidence": {...}},
)

# Register a paper
paper_id = store.register_paper("paper.pdf")

# Save tool outputs
store.save_extraction(paper_id, extraction_dict)
store.save_validation(paper_id, validation_dict)
store.save_c6_alignment(paper_id, c6_dict)
store.save_citation_analysis(paper_id, analysis_dict)
store.save_graph_analysis(paper_id, graph_dict)
store.save_trend_baseline(paper_id, trend_dict)
store.save_key_papers(paper_id, key_papers_dict)

# Save workflow node outputs
store.save_node_step(paper_id, "04_verifier", step_record)

# Update index
store.update_index(paper_id, status="completed")
```

### AgentOutput

```python
class AgentOutput(TypedDict):
    agent_name: str
    dimension: str
    sub_scores: Dict[str, AgentSubScore]  # 每个子维度的评分
    overall_score: float
    confidence: float
    evidence_summary: str
```

### AgentSubScore

```python
class AgentSubScore(TypedDict):
    score: float                       # 1-5 整数（或 1.0 预填值）
    llm_involved: bool
    hallucination_risk: str            # "none"/"low"/"medium"/"high"
    tool_evidence: Dict[str, Any]      # 参考的指标值
    llm_reasoning: str
    flagged_items: Optional[List[Any]]
    variance: Optional[VarianceRecord] # 由 Corrector 填充，低风险维度为 null
```

### CorrectorOutput

```python
class CorrectorOutput(TypedDict):
    corrections: Dict[str, CorrectionRecord]  # sub_id → 校正记录
    skipped_dimensions: List[str]             # 低风险维度
    skip_reason: str
    total_model_calls: int
    failed_calls: int
```

### DimensionScore（在 run_summary.json 中）

```python
class DimensionScore(TypedDict):
    dim_id: str
    final_score: float
    source: Literal["original", "corrected"]
    agent: str
    hallucination_risk: str
    variance: Optional[VarianceRecord]
    weight: float
```

### BaseAgent

```python
class BaseAgent(ABC):
    name: str
    config: AgentConfig
    mcp: Optional[MCPManager]
    llm: Runnable
    multi_model_config: Optional[MultiModelConfig]

    async def evaluate(self, state: SurveyState, section_name: str = None) -> dict:
        """读取 dispatch_specs，逐子维度调用 LLM，合并 pre_filled_scores，返回 agent_outputs"""

    async def process(self, state: SurveyState) -> dict:
        """LangGraph 节点入口，调用 evaluate() 并返回状态更新"""
```

### MCPManager

```python
class MCPManager:
    async def connect(self) -> None: ...
    async def call_tool(self, server: str, tool: str, args: dict) -> Any: ...
    def get_langchain_tools(self, server: str = None) -> List[Dict]: ...
```

---

## 常见问题

### Q: 如何添加新的评估子维度？

只需在 `evidence_dispatch.py` 的 `AGENT_REGISTRY` 中对应 `AgentDef` 的 `sub_dimensions` 列表添加 `SubDimensionDef`，定义 `rubric`、`evidence_metric_ids` 和 `hallucination_risk`。dispatch 节点会自动生成上下文，Agent 会自动评分，Corrector 会自动判断是否需要投票。

### Q: 如何添加自定义的 LLM 提供商？

在 `src/agents/base.py` 的 `_init_llm()` 中，`provider_urls` 字典新增映射：

```python
"new_provider": ("https://api.newprovider.com/v1", "NEWPROVIDER_API_KEY"),
```

并在 `config/models.yaml` 的 `providers` 部分添加配置，在 `.env` 中添加对应 API Key。

### Q: C6 短路触发了（auto_fail=True），能手动关闭吗？

修改 `config/main.yaml` 中的 `contradiction_threshold`，设为一个更大的值（如 1.0）即可禁用短路：

```yaml
evidence:
  contradiction_threshold: 1.0
```

### Q: Corrector 投票结果方差很大，如何处理？

`high_disagreement: true` 表示 3 个模型评分差异 > 2 分，报告中会自动标注。可以：
1. 人工审查该维度
2. 在 `config/models.yaml` 中调整 `multi_model.models` 使用更一致的模型组合
3. 修改 `corrector.py` 中高不一致的判断阈值

### Q: 如何调试单个 Agent？

```python
from src.agents.verifier import VerifierAgent
from src.core.state import SurveyState

agent = VerifierAgent()

# 构造包含 dispatch_specs 的 mock state
state = {
    "parsed_content": "...",
    "source_pdf_path": "test.pdf",
    "dispatch_specs": {
        "verifier": {
            "sub_dimension_contexts": {
                "V1": {"sub_id": "V1", "name": "citation_existence", "rubric": "...",
                       "evidence_metrics": {"C5": {"value": 0.85, "definition": "..."}},
                       "output_schema": {...}},
            },
            "pre_filled_scores": {},
        }
    },
}

result = await agent.evaluate(state)
```

### Q: 如何配置多模型投票？

在 `config/models.yaml` 中为 `corrector` 配置 `multi_model`：

```yaml
agents:
  corrector:
    provider: qwen
    model: qwen3.5-flash
    multi_model:
      enabled: true
      models:
        - provider: qwen
          model: qwen3.5-flash
        - provider: deepseek
          model: deepseek-chat
        - provider: openai
          model: gpt-4o-mini
```

### Q: 并发检索时某个源频繁超时怎么办？

调整 `config/search_engines.yaml` 中该源的 `timeout_seconds`，或将其 `concurrent` 改为 `false` 使其仅作 fallback：

```yaml
sources:
  semantic_scholar:
    concurrent: false    # 改为不参与并发批次
    max_retries: 3
    timeout_seconds: 15
```

### Q: 如何查看完整的调试日志？

所有 DEBUG+ 级别日志写入 `output/runs/{run_id}/logs/run.log`。运行时可用 `-v` 参数让控制台也显示 DEBUG：

```bash
uv run python -m src.main survey.pdf -v
```

### Q: 日志目录在哪里？

日志文件位于 `output/runs/{run_id}/logs/` 目录下：

- `run.log` - 完整 DEBUG 日志（包含所有详细信息）
- `summary.log` - 仅 pipeline 步骤摘要（轻量级，便于快速浏览）

### Q: 如何理解输出目录的嵌套结构？

SurveyMAE 使用双层目录结构：

- **外层目录** (`{run_id}/`)：由 `main.py` 生成，包含日志和报告
- **内层目录** (`{store_run_id}/`)：由 `ResultStore` 生成，包含 JSON 数据文件

这种设计支持批量评测场景，多个 PDF 可以共享同一个外层运行目录。

### Q: 为什么 V2 分数有时自动为 1 分？

当 C6 分析的 `contradiction_rate` 超过 `contradiction_threshold`（默认 5%）时，V2 会被自动预填为 1 分（auto_fail）。这是基于工具证据的短路机制，无需 LLM 判断。

### Q: 如何添加新的文献检索源？

1. 在 `src/tools/fetchers/` 创建新的 fetcher 类
2. 在 `search_engines.yaml` 的 `sources` 部分添加配置
3. 在 `SearchEngineConfig` 中添加默认配置（如果需要）

---

## 贡献指南

贡献步骤：

1. Fork 项目
2. 创建功能分支 (`git checkout -b feature/my-feature`)
3. 提交更改 (`git commit -am 'Add new feature'`)
4. 推送到分支 (`git push origin feature/my-feature`)
5. 创建 Pull Request

### 代码规范

- 遵循 PEP 8
- 使用类型注解
- Logger 命名必须以 `surveymae.` 前缀开头（禁止 `logging.getLogger(__name__)`）
- 新工具的 LLM 配置通过 `ModelConfig.get_tool_config()` 获取，禁止硬编码 provider→URL 映射
- 编写测试用例（unit 测试不依赖外部 API）
- 运行代码检查 (`uv run ruff check`)

---

## 文献检索组件复用（BibGuard Fetchers）

本项目已复用 BibGuard 的检索组件（Fetcher 6 种）并封装为统一文献检索工具：

- 代码位置：`src/tools/fetchers/`（arXiv / CrossRef / Semantic Scholar / OpenAlex / DBLP / Scholar）
- 聚合接口：`src/tools/literature_search.py`（内部使用 `ParallelDispatcher`）
- MCP Server：`src/tools/literature_search_server.py`

### 配置与密钥管理

```yaml
# config/search_engines.yaml（新格式）
sources:
  semantic_scholar:
    api_key: ${SEMANTIC_SCHOLAR_API_KEY}
  openalex:
    email: ${OPENALEX_EMAIL}
  crossref:
    mailto: surveymae@example.com
```

可用环境变量：`SEMANTIC_SCHOLAR_API_KEY`、`OPENALEX_EMAIL`、`SURVEYMAE_SEARCH_CONFIG`（覆盖配置文件路径）。

### MCP 集成示例

```yaml
mcp_servers:
  - name: literature_search
    command: uv
    args: [run, python, -m, src.tools.literature_search_server]
    env:
      PYTHONPATH: .
```

---

## Citation Graph Addendum (2026-03)

This section summarizes the citation-graph pipeline, including graph construction, analysis, visualization, and integration testing.

### Scope

- Real citation edge construction in `src/tools/citation_checker.py`
- Metadata enrichment (OpenAlex + Semantic Scholar references) in `src/tools/citation_metadata.py`
- Graph analytics in `src/tools/citation_graph_analysis.py`
- Visualization in `scripts/render_citation_graph_pyvis.py` and integration test export helpers
- End-to-end integration test in `tests/integration/test_citation_graph_pipeline.py`

### 1) Real Edge Construction

- Entry point: `CitationChecker.build_real_citation_edges(...)`
- Only builds in-set **real citation edges** from verified metadata reference lists
- No fallback to sentence co-occurrence edges when real edges are missing
- Persisted fields: `real_citation_edges`, `real_citation_edge_stats`
- Failure semantics: `status=failed`, `failure_reason=NO_REAL_EDGES`

### 2) Citation Graph Analysis Output

`src/tools/citation_graph_analysis.py` outputs four metric groups:

- `density_connectivity` → G1 (density), G2 (components), G3 (lcc_frac)
- `centrality` → PageRank / in-degree distributions
- `cocitation_clustering` → G5 (cluster_count)
- `temporal` → year-based analysis

### 3) Integration Test Pipeline

Primary test: `tests/integration/test_citation_graph_pipeline.py`

Chain: PDF citation parsing → reference metadata verification → real edge construction → citation graph analysis → visualization export (`.mmd`, `.dot`, `.html`)

### 4) Visualization

#### Standalone renderer

```bash
uv run python scripts/render_citation_graph_pyvis.py \
  --validation output/.../tools/validation.json \
  --extraction output/.../tools/extraction.json \
  --output output/test_artifacts/citation_graph/preview.html
```

Center selection strategy: `authority_center + elbow`（自动选择聚类中心数，非固定 top-k）

#### Environment Variables

- `GROBID_URL` (default `http://localhost:8070`)
- `CITATION_VERIFY_SOURCES` (default `semantic_scholar,openalex`)
- `CITATION_GRAPH_EXPORT_DIR` (default `output/test_artifacts/citation_graph`)

### 5) Maintenance Notes

- Keep `scripts/render_citation_graph_pyvis.py` and integration-test visualization logic aligned
- Keep "real-edge-first" semantics unchanged unless requirement explicitly changes
- Reference image: `docs/test_survey2_citation_graph.png`
