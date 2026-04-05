# SurveyMAE 日志系统分析

> 分析时间: 2026/04/05
> 对应项目文档: DEVELOPER_GUIDE.md, SurveyMAE_Plan_v3.md, FUNC_ANALYSIS.md, CACHE_PERSISTENCE_DESIGN.md

---

## 1. 日志层级

项目使用 Python 标准 `logging` 模块，全局配置在 `src/main.py:28-31`：

```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(Name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
```

### 1.1 日志级别定义

| 级别 | 使用场景 |
|------|----------|
| `INFO` | 主要工作流节点（评估开始/结束、PDF解析、报告保存） |
| `WARNING` | 非致命错误（API重试失败、工具调用跳过、可选功能缺失） |
| `ERROR` | 致命错误（Agent评估失败、PDF解析失败、MCP连接失败） |
| `DEBUG` | 详细输出（仅 `-v` 参数启用 `logging.getLogger("src").setLevel(logging.DEBUG)`） |

### 1.2 Verbose 模式

```python
# src/main.py:149-150
if args.verbose:
    logging.getLogger("src").setLevel(logging.DEBUG)
```

通过 CLI `-v` 参数可开启 DEBUG 级别日志。

---

## 2. 关键节点日志覆盖

### 2.1 工作流入口

| 位置 | 日志 | 级别 |
|------|------|------|
| `main.py:50` | `Starting evaluation of: {pdf_path}` | INFO |
| `main.py:93` | `Running evaluation workflow...` | INFO |
| `main.py:109` | `Report saved to: {output_path}` | INFO |
| `main.py:154` | `PDF file not found: {path}` | ERROR |
| `main.py:161` | `Loaded configuration from: {path}` | INFO |
| `main.py:185` | `Evaluation failed: {e}` (with traceback) | ERROR |

### 2.2 PDF 解析节点

| 位置 | 日志 | 级别 |
|------|------|------|
| `builder.py:656` | `No source PDF path provided` | WARNING |
| `builder.py:660` | `PDF file not found: {path}` | ERROR |
| `builder.py:664` | `Parsing PDF: {path}` | INFO |
| `builder.py:679` | `Failed to parse PDF: {e}` | ERROR |
| `pdf_parser.py:67` | `Successfully parsed PDF: {path} ({len} chars)` | INFO |
| `pdf_parser.py:71` | `pymupdf4llm not available, using fallback parser` | WARNING |
| `pdf_parser.py:75` | `Failed to parse PDF: {e}` | ERROR |

### 2.3 证据收集节点 (`evidence_collection.py`)

该节点有最详细的分步骤日志：

| 位置 | 日志 | 级别 |
|------|------|------|
| `:241` | `Step 1: Extracting and validating citations...` | INFO |
| `:274` | `C3 (orphan_ref_rate): {rate:.2%}` | INFO |
| `:275` | `C5 (metadata_verify_rate): {rate:.2%}` | INFO |
| `:299` | `Step 1.5: Analyzing citation-sentence alignment (C6)...` | INFO |
| `:315` | `No references available for C6 analysis` | WARNING |
| `:335-341` | C6 进度和结果统计 | INFO |
| `:373` | `Step 5: Computing temporal metrics...` | INFO |
| `:402-403` | `T1 (year_span)`, `T5 (trend_alignment)` | INFO |
| `:429` | `Step 6: Computing citation graph metrics...` | INFO |
| `:436` | `Using {n} real citation edges from verification` | INFO |
| `:440` | `No citation edges found, graph metrics may be limited` | WARNING |
| `:461` | `Graph analysis failed: {e}` | WARNING |
| `:476` | `S5 computation failed: {e}` | WARNING |
| `:502` | `Step 7: Computing foundational coverage...` | INFO |
| `:520` | `G4 analysis failed: {e}` | WARNING |
| `:525` | `G4 (foundational_coverage_rate): {rate}` | INFO |
| `:564` | `Failed to register paper: {e}` | WARNING |
| `:567` | `No parsed content available` | WARNING |
| `:913` | `Evidence collection complete: {n} references, {k} keywords` | INFO |
| `:928` | `Evidence collection failed: {e}` (with traceback) | ERROR |

### 2.4 证据分发节点

| 位置 | 日志 | 级别 |
|------|------|------|
| `evidence_dispatch.py:418` | `Running evidence dispatch node...` | INFO |

### 2.5 Agent 评估节点

| Agent | 位置 | 日志 | 级别 |
|-------|------|------|------|
| Verifier | `verifier.py:231` | `Citation analysis failed: {e}` | WARNING |
| Expert | `expert.py:183` | `Citation graph analysis failed: {e}` | WARNING |
| Reader | `reader.py:175` | `Citation analysis failed: {e}` | WARNING |
| Corrector | `corrector.py:138` | `No agent_outputs found in state` | WARNING |
| Corrector | `corrector.py:153` | `Corrector voting on {n} dimensions: {dims}` | INFO |
| Corrector | `corrector.py:154` | `Skipping {n} low-risk dimensions: {dims}` | INFO |
| Corrector | `corrector.py:184` | `Model {model} failed for {dim}: {result}` | WARNING |
| Corrector | `corrector.py:218` | `{dim}: {old} -> {new} (std={std:.2f})` | INFO |
| Corrector | `corrector.py:220` | `{dim}: insufficient model results, skipping` | WARNING |
| Corrector | `corrector.py:303` | `Failed to vote on {dim} with model {model}: {e}` | WARNING |
| Corrector | `corrector.py:338` | `Model {model} failed: {error}` | WARNING |
| Corrector | `corrector.py:558` | `No LLM pool configured, skipping variance computation` | WARNING |
| Corrector | `corrector.py:575` | `No LLM-involved sub-scores to compute variance for` | INFO |
| Corrector | `corrector.py:578` | `Computing variance for {n} sub-scores` | INFO |
| Corrector | `corrector.py:613` | `Failed to parse model response: {e}` | WARNING |

### 2.6 辩论节点

| 位置 | 日志 | 级别 |
|------|------|------|
| `debate.py:30` | `Running debate round {n}` | INFO |

### 2.7 聚合节点

| 位置 | 日志 | 级别 |
|------|------|------|
| `aggregator.py:51` | `No evaluations to aggregate` | WARNING |

### 2.8 报告生成节点

| 位置 | 日志 | 级别 |
|------|------|------|
| `reporter.py:94` | `Saved run_summary.json to run directory` | INFO |
| `reporter.py:96` | `Failed to save run_summary.json: {e}` | WARNING |

### 2.9 MCP 客户端

| 位置 | 日志 | 级别 |
|------|------|------|
| `mcp_client.py:106` | `Connected to HTTP MCP server: {name}` | INFO |
| `mcp_client.py:121` | `Connected to stdio MCP server: {name}` | INFO |
| `mcp_client.py:124` | `Server {name}: no valid connection config provided` | WARNING |
| `mcp_client.py:127` | `Failed to connect to MCP server {name}: {e}` | ERROR |
| `mcp_client.py:146` | `Server {name} has {n} tools` | DEBUG |
| `mcp_client.py:148` | `Failed to list tools from {name}: {e}` | ERROR |
| `mcp_client.py:197` | `Tool call failed: {server}.{tool}: {e}` | ERROR |
| `mcp_client.py:230` | `Disconnected from MCP server: {name}` | INFO |
| `mcp_client.py:232` | `Error disconnecting from {name}: {e}` | ERROR |

### 2.10 Agent 基类

| 位置 | 日志 | 级别 |
|------|------|------|
| `base.py:260` | `LLM call attempt {n}/{max} failed: {e}` | WARNING |
| `base.py:262` | `All {max} attempts failed` | ERROR |
| `base.py:298` | `Model {key} failed: {resp}` | ERROR |
| `base.py:321` | `MCP not configured, skipping tool call: {tool}` | WARNING |
| `base.py:333` | `MCP tool call failed: {tool}, error: {e}` | ERROR |
| `base.py:363` | `Prompt template not found: {name}` | WARNING |
| `base.py:530` | `Agent {name} evaluation failed: {e}` | ERROR |
| `base.py:531` | `Traceback: {traceback}` | ERROR |

### 2.11 工具层

| 工具 | 位置 | 日志 | 级别 |
|------|------|------|------|
| CitationChecker | `citation_checker.py:589` | 警告消息 | WARNING |
| CitationChecker | `citation_checker.py:655` | `Failed to persist extraction result` | WARNING |
| CitationChecker | `citation_checker.py:686` | `Failed to persist validation result` | WARNING |
| CitationChecker | `citation_checker.py:775` | `Starting C6 citation-sentence alignment analysis...` | INFO |
| CitationChecker | `citation_checker.py:808` | `Built {n} citation-sentence pairs` | INFO |
| CitationChecker | `citation_checker.py:829` | `Pairs with abstract: {n}, without: {m}` | INFO |
| CitationChecker | `citation_checker.py:841` | `Failed to initialize LLM: {e}` | ERROR |
| CitationChecker | `citation_checker.py:863` | `Processing {n} batches with max concurrency {c}` | INFO |
| CitationChecker | `citation_checker.py:873` | `Batch processing failed: {e}` | WARNING |
| CitationAnalysis | `citation_analysis.py:70` | `Failed to persist analysis result` | WARNING |
| CitationAnalysis | `citation_analysis.py:630` | `Failed to persist paragraph analysis` | WARNING |
| CitationGraphAnalysis | `citation_graph_analysis.py:639` | `networkx or python-louvain not available, falling back to cocitation` | WARNING |
| CitationGraphAnalysis | `citation_graph_analysis.py:734` | `sklearn not available, falling back to cocitation` | WARNING |
| CitationGraphAnalysis | `citation_graph_analysis.py:788` | `Spectral clustering failed: {e}, falling back to cocitation` | WARNING |
| CitationGraphAnalysis | `citation_graph_analysis.py:890` | `sklearn not available, S5 alignment will be skipped` | WARNING |
| CitationGraphAnalysis | `citation_graph_analysis.py:950` | `Failed to compute NMI/ARI: {e}` | WARNING |
| CitationGraphAnalysis | `citation_graph_analysis.py:1199` | `ResultStore persistence skipped: missing source path` | WARNING |
| CitationGraphAnalysis | `citation_graph_analysis.py:1208` | `Failed to persist citation graph analysis` | WARNING |
| LiteratureSearch | `literature_search.py:66-440` | 各类搜索失败 WARNING/ERROR | WARNING/ERROR |
| KeywordExtractor | `keyword_extractor.py:226` | `Keyword extraction failed: {e}` | WARNING |
| FoundationalCoverage | `foundational_coverage.py:115` | `Failed to search for keyword '{kw}': {e}` | WARNING |
| FoundationalCoverage | `foundational_coverage.py:184` | `LLM filter failed for '{title}': {e}` | WARNING |
| DBLPFetcher | `dblp_fetcher.py:54` | `DBLP rate limit exceeded. Waiting longer...` | WARNING |
| DBLPFetcher | `dblp_fetcher.py:59` | `DBLP API error: {code}` | WARNING |
| DBLPFetcher | `dblp_fetcher.py:65` | `Error fetching from DBLP: {exc}` | ERROR |
| DBLPFetcher | `dblp_fetcher.py:103` | `Error parsing DBLP response: {exc}` | ERROR |

---

## 3. 日志持久化机制

### 3.1 ResultStore 持久化（结构化数据）

`src/tools/result_store.py` 提供基于文件的持久化，目录结构：

```
output/runs/{run_id}/
├── run.json                    # 运次元数据、配置快照、schema_version
├── index.json                  # 论文状态索引
└── papers/{paper_id}/
    ├── source.json              # 源文件信息（SHA256、mtime、size）
    ├── extraction.json          # 引用抽取结果（citations + references）
    ├── validation.json          # C3/C5 验证结果 + ref_metadata_cache
    ├── c6_alignment.json         # C6 引用-句子对齐分析
    ├── analysis.json            # T/S 系列指标（T1-T5, S1-S4）
    ├── graph_analysis.json       # G 系列 + S5 指标
    ├── trend_baseline.json       # 领域趋势基线（年度发表量）
    ├── key_papers.json          # 关键候选论文 + G4 覆盖率
    ├── errors.jsonl             # 错误日志（追加写入）
    └── agent_logs.jsonl         # Agent 运行时日志（追加写入）
```

**关键方法：**

| 方法 | 用途 |
|------|------|
| `register_paper(source_path)` | 注册论文，返回 paper_id |
| `save_extraction(paper_id, data)` | 保存引用抽取结果 |
| `save_validation(paper_id, data)` | 保存 C3/C5 验证结果 |
| `save_c6_alignment(paper_id, data)` | 保存 C6 对齐分析 |
| `save_citation_analysis(paper_id, data)` | 保存 T/S 指标 |
| `save_graph_analysis(paper_id, data)` | 保存图分析指标 |
| `save_trend_baseline(paper_id, data)` | 保存趋势基线 |
| `save_key_papers(paper_id, data)` | 保存关键论文 |
| `save_node_step(paper_id, step_name, data)` | 保存 workflow 节点步骤（nodes/ 目录） |
| `append_error(paper_id, record)` | 追加错误记录到 errors.jsonl |
| `append_agent_log(paper_id, record)` | 追加 Agent 日志到 agent_logs.jsonl |
| `update_index(paper_id, status)` | 更新论文状态 |

**注意**：`errors.jsonl` 和 `agent_logs.jsonl` 的 `append_*` 方法存在，但在代码中**几乎未被调用**（仅在文档示例中出现）。

### 3.2 Workflow 步骤持久化

`src/graph/builder.py` 的 `_save_workflow_step()` 函数在每个节点执行后将输入/输出保存为 JSON：

```
output/runs/{run_id}/papers/{paper_hash}/
├── nodes/                        # workflow 步骤（v3 重构后）
│   ├── 01_parse_pdf.json
│   ├── 02_evidence_collection.json
│   ├── 03_evidence_dispatch.json
│   ├── 04_verifier.json
│   ├── 04_expert.json
│   ├── 04_reader.json
│   ├── 05_corrector.json
│   └── 06_aggregator.json
└── tools/                        # 工具层独立输出
    ├── extraction.json
    ├── validation.json
    ├── c6_alignment.json
    ├── analysis.json
    ├── graph_analysis.json
    ├── trend_baseline.json
    └── key_papers.json
```

每个节点 JSON 文件结构：

```json
{
  "step": "04_verifier",
  "timestamp": "2026-03-12T10:21:41+00:00",
  "source_pdf": "test_survey2.pdf",
  "output": { ... },
  "run_params": {
    "node": "verifier",
    "agent_class": "VerifierAgent"
  }
}
```

### 3.3 最终报告持久化

报告保存到 `run_dir/reports/{pdf_name}_{timestamp}.md`。

---

## 4. LangGraph Checkpoint

`src/graph/builder.py:584` 使用内存 checkpoint：

```python
checkpointer = checkpointer or MemorySaver()
```

目前**无持久化 checkpoint**，所有状态仅存储在内存中。

---

## 5. 缺失与不足

| 问题 | 严重程度 | 说明 |
|------|----------|------|
| **Python logging 不落盘** | 高 | `basicConfig()` 仅输出到控制台，无 `FileHandler`，日志不持久化 |
| **无独立日志文件** | 高 | 没有 `app.log` / `evaluation.log` 之类的日志文件 |
| **errors.jsonl 使用率极低** | 中 | `append_error()` 方法存在但几乎未被调用，错误信息通过 Python logging 输出 |
| **agent_logs.jsonl 使用率极低** | 中 | `append_agent_log()` 方法存在但几乎未被调用 |
| **工作流节点入口缺少细粒度日志** | 中 | `run_evaluation()` 缺少各阶段开始/完成的细粒度日志 |
| **无日志轮转** | 中 | 无 `RotatingFileHandler` 或 `TimedRotatingFileHandler` |
| **无结构化日志格式** | 中 | 日志格式为普通文本，机器解析不友好 |
| **无日志分级配置** | 中 | 无法通过配置文件控制各模块日志级别 |
| **LangGraph checkpoint 不持久化** | 中 | 仅 `MemorySaver`，无磁盘持久化 |
| **Verbose 模式仅针对 "src" logger** | 低 | `logging.getLogger("src").setLevel(logging.DEBUG)` 可能漏掉第三方库日志 |

---

## 6. 重构建议

基于以上分析，日志系统重构可考虑：

1. **增加 FileHandler**：将 Python logging 同时输出到文件（如 `output/logs/surveymae_{date}.log`）
2. **结构化日志格式**：采用 JSON 格式日志，便于日志聚合和分析
3. **日志轮转**：使用 `RotatingFileHandler` 或 `TimedRotatingFileHandler`
4. **增加 errors.jsonl / agent_logs.jsonl 的调用点**：在 Agent 评估、工具调用等处主动追加结构化日志
5. **统一日志配置**：在 `config/logging.yaml` 中集中配置各模块日志级别
6. **持久化 Checkpoint**：考虑使用 `SqliteSaver` 或 `PostgresSaver` 替代 `MemorySaver`
