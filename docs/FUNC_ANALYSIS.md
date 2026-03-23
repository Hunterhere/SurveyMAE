# SurveyMAE 函数分层分析文档

> 本文档从下至上（Tools → Agents → Graph → Core）分析项目中主要函数的签名、功能和跨层调用关系。目标：检查代码规范性（冗余实现、类型对齐、异常处理）和运行逻辑。

---

## 目录

- [Tools 层（工具层）](#tools-层工具层)
- [Agents 层（智能体层）](#agents-层智能体层)
- [Graph 层（图编排层）](#graph-层图编排层)
- [Core 层（核心层）](#core-层核心层)
- [跨层调用关系总览](#跨层调用关系总览)
- [代码规范性问题汇总](#代码规范性问题汇总)

---

## Tools 层（工具层）

Tools 层是整个系统的数据处理底层，提供 PDF 解析、引用分析、文献检索等核心能力。

### 1. PDF 解析模块 (`src/tools/pdf_parser.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `PDFParser.parse(pdf_path: str) -> str` | 解析 PDF 文件为 Markdown 文本 | PDF 文件路径 | Markdown 字符串 | 内部调用 pymupdf4llm |
| `PDFParser.parse_cached(pdf_path: str) -> str` | 带进程内缓存的解析 | PDF 文件路径 | Markdown 字符串 | 使用 dict 缓存，有 128 上限 |
| `PDFParser.parse_to_file(pdf_path, output_path?, cache_dir?, overwrite?) -> str` | 解析并持久化到磁盘 | PDF 路径及配置 | 输出文件路径 | 自动创建父目录 |

**调用来源**：
- 被 Graph 层的 `_wrap_parse_pdf` 调用
- 被 Agents 层（如需要直接解析 PDF 时）

---

### 2. 引用检查模块 (`src/tools/citation_checker.py`)

这是工具层最复杂的模块，负责从 PDF 中提取引用和参考文献。

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `CitationChecker.extract_citations_with_context_from_pdf_async(pdf_path, verify_references?, sources?, verify_limit?) -> dict` | 异步提取引用、上下文、参考文献（含验证） | PDF 路径及验证参数 | 含 citations/references/validation 的字典 | **核心入口**，返回真实引用边 |
| `CitationChecker.extract_references_from_pdf(pdf_path) -> List[Dict]` | 从 PDF 提取参考文献列表 | PDF 路径 | 参考文献字典列表 | 支持 GROBID/PyMuPDF 后端 |
| `CitationChecker.build_real_citation_edges(references) -> list` | 从验证后的参考文献构建真实引用边 | 参考文献列表 | (source, target) 元组列表 | 仅使用外部 API 验证的引用 |
| `CitationChecker.analyze_citation_sentence_alignment(citations, references, batch_size?, model_name?, max_concurrency?, contradiction_threshold?) -> dict` | C6 引用-句子对齐分析（异步批处理） | citations 列表、references 列表、批处理参数 | 含 contradiction_rate、auto_fail、contradictions 的字典 | **新增**，基于 LLM 三分类 |
| `CitationChecker._build_c6_prompt(pairs) -> str` | 构建 C6 批处理 prompt | sentence-abstract 对列表 | prompt 字符串 | **新增**，辅助方法 |
| `CitationChecker._parse_c6_response(response, pairs) -> list` | 解析 C6 LLM 响应 | LLM 响应字符串、对列表 | 分类结果列表 | **新增**，支持 support/contradict/insufficient |

**数据模型**：
- `CitationSpan`: 文中引用（含位置信息：page, paragraph_index, line_in_paragraph）
- `ReferenceEntry`: 参考文献条目
- `CitationExtractionResult`: 提取结果容器

**调用来源**：
- 被 Graph 层的 `run_evidence_collection` 调用
- 内部调用 `CitationMetadataChecker` 进行引用验证

---

### 3. 引用分析模块 (`src/tools/citation_analysis.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `CitationAnalyzer.analyze_pdf(pdf_path) -> dict` | 分析 PDF 引用统计 | PDF 路径 | 统计摘要 | 内部调用 CitationChecker |
| `CitationAnalyzer.compute_temporal_metrics(references, field_trend_baseline?) -> dict` | 计算时序指标 T1-T5 | 参考文献列表，领域趋势基线（可选） | T1-T5 指标字典 | **核心指标计算**，含 year_distribution |
| `CitationAnalyzer.compute_structural_metrics(section_ref_counts, total_paragraphs) -> dict` | 计算结构指标 S1-S4 | 章节-引用计数，总段落数 | S1-S4 指标字典 | 计算 Gini 系数等 |
| `CitationAnalyzer.bucket_by_year_window(references, window) -> list[YearBucket]` | 按年份窗口分组统计 | 参考文献列表，窗口大小 | 年份桶列表 | 用于时序可视化 |
| `CitationAnalyzer.year_over_year_trend(references) -> dict` | 年同比趋势 | 参考文献列表 | 趋势字典 | 识别增长/下降趋势 |

**调用来源**：
- 被 Graph 层的 `run_evidence_collection` 调用
- 被 MCP Server 暴露为工具

---

### 4. 引用图分析模块 (`src/tools/citation_graph_analysis.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `CitationGraphAnalyzer.analyze(references, edges?, config?) -> dict` | 完整图分析（密度/连通/中心度/聚类/时序） | 参考文献、边列表、配置 | G1-G6 + S5 + 图统计 | **核心图分析**，返回完整分析结果 |
| `CitationGraphAnalyzer.compute_section_cluster_alignment(section_ref_counts, references, cluster_evidence) -> dict` | 计算章节-聚类对齐度 (S5) | 章节引用计数、参考文献、聚类证据 | NMI/ARI 分数 | 用于评估结构清晰度 |
| `_centrality_summary(nodes, edges) -> dict` | 计算中心度指标 | 节点、边 | PageRank/Betweenness | 内部方法 |
| `_cocitation_clustering(references, edges) -> dict` | 共引聚类 | 参考文献、边 | 聚类结果 | 支持多种聚类算法 |
| `_louvain_clustering(adjacency) -> list` | Louvain 社区检测 | 邻接矩阵 | 社区列表 | 可选聚类方法之一 |

**调用来源**：
- 被 Graph 层的 `run_evidence_collection` 调用
- 返回数据供 ExpertAgent 和 ReaderAgent 使用

---

### 5. 文献检索模块 (`src/tools/literature_search.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `LiteratureSearch.search_field_trend(keyword, year_range?) -> dict` | 搜索领域发表趋势 | 关键词、年份范围 | 各年份论文数量 | **T5 指标核心**，用于趋势对齐 |
| `LiteratureSearch.search_top_cited(keyword, top_k?) -> list` | 搜索高被引论文 | 关键词、top 数量 | 论文列表（title, citations, year） | **G4 指标核心**，用于覆盖率计算 |
| `LiteratureSearch.search_literature(query, sources?, limit?) -> list` | 综合文献检索 | 查询词、来源、限制 | 结果列表 | 聚合多个学术 API |

**调用来源**：
- 被 Graph 层的 `run_evidence_collection` 调用（Step 3-4）
- 支持多源聚合（Semantic Scholar, OpenAlex, CrossRef, arXiv, DBLP）

---

### 6. 基础覆盖率分析模块 (`src/tools/foundational_coverage.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `FoundationalCoverageAnalyzer.analyze(topic_keywords, survey_references, ref_metadata_cache) -> CoverageResult` | 计算核心文献覆盖率 G4 | 关键词、综述参考文献、元数据缓存 | 覆盖率 + 缺失论文列表 | **G4 指标核心** |

**调用来源**：
- 被 Graph 层的 `run_evidence_collection` 调用（Step 7）

---

### 7. 结果持久化模块 (`src/tools/result_store.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `ResultStore.register_paper(source_pdf) -> str` | 注册论文，返回 paper_id | PDF 路径 | 论文 ID | 用于批处理 |
| `ResultStore.save_extraction(paper_id, data) -> Path` | 保存提取结果 | 论文 ID、数据 | 文件路径 | 写入 extraction.json |
| `ResultStore.save_validation(paper_id, data) -> Path` | 保存验证结果 | 论文 ID、数据 | 文件路径 | 写入 validation.json |
| `ResultStore.save_c6_alignment(paper_id, data) -> Path` | 保存 C6 对齐结果 | 论文 ID、数据 | 文件路径 | 写入 c6_alignment.json |
| `ResultStore.save_citation_analysis(paper_id, data) -> Path` | 保存引用分析 | 论文 ID、数据 | 文件路径 | 写入 analysis.json |
| `ResultStore.save_graph_analysis(paper_id, data) -> Path` | 保存图分析结果 | 论文 ID、数据 | 文件路径 | 写入 graph_analysis.json |
| `ResultStore.save_trend_baseline(paper_id, data) -> Path` | 保存趋势基线 | 论文 ID、数据 | 文件路径 | 写入 trend_baseline.json |
| `ResultStore.save_key_papers(paper_id, data) -> Path` | 保存关键论文 | 论文 ID、数据 | 文件路径 | 写入 key_papers.json |
| `ResultStore.append_error(paper_id, error) -> None` | 追加错误日志 | 论文 ID、错误字典 | 无 | 写入 errors.jsonl |

**调用来源**：
- 被 Graph 层的 workflow 步骤保存
- 被 Tools 层作为可选依赖

---

### 8. 关键词提取模块 (`src/tools/keyword_extractor.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `KeywordExtractor.extract_keywords(title, abstract, section_headings?) -> KeywordResult` | LLM 辅助提取检索关键词 | 标题、摘要、章节标题 | 关键词列表 | **低幻觉风险**（LLM 仅做 NLU） |

**调用来源**：
- 被 Graph 层的 `run_evidence_collection` 调用

---

## Agents 层（智能体层）

Agents 层基于 Tools 层的工具产出，利用 LLM 进行评估判断。

### 1. BaseAgent 基类 (`src/agents/base.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `BaseAgent.__init__(name, config?, mcp?, multi_model_config?)` | 初始化 Agent | Agent 名称、配置、MCP 管理器、多模型配置 | 无 | 支持 9+ LLM 提供商 |
| `BaseAgent.evaluate(state, section_name?) -> EvaluationRecord` | 执行评估（抽象方法） | 状态、章节名 | 评估记录 | 子类必须实现 |
| `BaseAgent.process(state) -> dict` | LangGraph 节点调用 | 状态字典 | 状态更新 | 调用 evaluate 并格式化输出 |
| `BaseAgent._call_llm(messages, tools?) -> str` | 调用单个 LLM | 消息列表、工具（可选） | LLM 响应文本 | 内部处理 API 调用 |
| `BaseAgent._call_llm_pool(messages, tools?) -> list` | 并行调用多模型 | 消息列表、工具（可选） | 多模型响应列表 | 用于 CorrectorAgent 投票 |
| `BaseAgent._call_mcp_tool(server, tool, args) -> Any` | 调用 MCP 工具 | 服务器名、工具名、参数 | 工具响应 | 代理 MCP 请求 |
| `BaseAgent._load_prompt(prompt_name, **kwargs) -> str` | 加载 Prompt 模板 | 模板名、变量 | 格式化后的 Prompt | 从 YAML 加载 |
| `BaseAgent.extract_json(text) -> dict` | 从 LLM 输出提取 JSON | 文本 | JSON 字典 | 含错误处理和重试 |

**类型定义**：
- `MultiModelConfig`: 多模型投票配置（models, use_parallel）
- `AgentOutput`: Agent 输出结构化数据

**子类实现要求**：
- 必须实现 `evaluate()` 方法
- 返回 `EvaluationRecord` 或 `AgentOutput` 格式

---

### 2. VerifierAgent (`src/agents/verifier.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `VerifierAgent.evaluate(state, section_name?) -> EvaluationRecord` | 评估引用事实性 | 状态（含 tool_evidence） | V1-V4 评分 | 调用 MCP 工具获取引用验证数据 |

**评估维度**（V1-V4）：
- V1: 引用存在性（依赖 C5）
- V2: 引用支持性（抽样判断）
- V3: 引用准确性（检测误读）
- V4: 内部一致性

**输入来源**：
- `tool_evidence.validation`（C3, C5）
- `tool_evidence.extraction.citations`

---

### 3. ExpertAgent (`src/agents/expert.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `ExpertAgent.evaluate(state, section_name?) -> EvaluationRecord` | 评估学术深度 | 状态（含图分析证据） | E1-E4 评分 | 利用引用图指标判断覆盖和分类 |

**评估维度**（E1-E4）：
- E1: 核心文献覆盖（依赖 G4）
- E2: 方法分类合理性（依赖 G5, S5）
- E3: 技术准确性
- E4: 批判性分析深度

**输入来源**：
- `tool_evidence.graph_analysis`（G1-G6, S5, missing_key_papers, suspicious_centrality）

---

### 4. ReaderAgent (`src/agents/reader.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `ReaderAgent.evaluate(state, section_name?) -> EvaluationRecord` | 评估可读性 | 状态（含时序/结构证据） | R1-R4 评分 | 结合领域基线判断时效性 |

**评估维度**（R1-R4）：
- R1: 时效性（依赖 T1-T5, field_trend_baseline）
- R2: 信息分布均衡性（依赖 S2, S3, S5）
- R3: 结构清晰度（依赖 S1, S5）
- R4: 文字质量

**输入来源**：
- `tool_evidence.analysis`（T1-T5, S1-S5）
- `field_trend_baseline`

---

### 5. CorrectorAgent (`src/agents/corrector.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `CorrectorAgent.evaluate(state, section_name?) -> EvaluationRecord` | 返回占位符 | 状态 | 占位符记录 | 兼容性保留 |
| `CorrectorAgent.process(state) -> dict` | 多模型投票校正 | 状态（含 agent_outputs） | corrector_output | **纯校正器**，仅对高风险维度投票 |

**核心功能**：
- 只对 7 个高风险（hallucination_risk=="high"）维度投票（V4, E2, E3, E4, R2, R3, R4）
- 跳过 4 个低风险维度（V1, V2, E1, R1）
- 使用中位数校正，返回 variance 信息

**输入来源**：
- `agent_outputs`（verifier, expert, reader 的输出）

**输出**：
- `corrector_output.corrections`: 各维度校正记录
- `corrector_output.skipped_dimensions`: 跳过的维度

---

### 6. ReporterAgent (`src/agents/reporter.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `ReporterAgent.evaluate(state, section_name?) -> EvaluationRecord` | 生成评估报告 | 状态（含聚合分数） | 最终报告 | 触发雷达图生成 |

**核心功能**：
- 聚合分数格式化
- 雷达图生成（matplotlib）
- Markdown 报告输出

**输入来源**：
- `aggregated_scores`
- `agent_outputs`

---

## Graph 层（图编排层）

Graph 层使用 LangGraph 编排整个评测流程。

### 1. Workflow 构建 (`src/graph/builder.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `create_workflow(config?) -> StateGraph` | 创建工作流图 | 配置（可选） | 编译后的 LangGraph | **主入口**，定义所有节点和边 |
| `compile_workflow() -> CompiledStateGraph` | 编译工作流 | 无 | 可执行的图 | 内部调用 create_workflow |
| `_wrap_parse_pdf(state) -> dict` | PDF 解析节点包装 | 状态 | parsed_content | 调用 PDFParser |
| `_wrap_evidence_collection(state) -> dict` | 证据收集节点包装 | 状态 | tool_evidence 等 | 调用 run_evidence_collection |
| `_wrap_evidence_dispatch(state) -> dict` | 证据分发节点包装 | 状态 | agent_evidence | 调用 run_evidence_dispatch |
| `_wrap_agent(agent_name, agent, state) -> dict` | Agent 节点包装 | Agent 名、实例、状态 | agent_output | 调用 Agent.process() |
| `_create_agents(config, agent_classes) -> list` | 创建 Agent 实例列表 | 配置、Agent 类列表 | Agent 实例列表 | 初始化所有 Agent |

**工作流节点顺序**：
```
01_parse_pdf → 02_evidence_collection → 03_evidence_dispatch →
  04_verifier → 04_expert → 04_reader → 05_corrector →
    06_aggregator → 07_reporter → END
```

**注意**：Plan v3 移除了 debate 节点，简化了工作流。

---

### 2. 条件边路由 (`src/graph/edges.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `should_continue_debate(state) -> Literal["continue", "reporter"]` | 判断是否继续辩论 | 状态 | "continue" 或 "reporter" | 检查辩论轮数和共识 |
| `should_end(state) -> Literal["END", "debate"]` | 判断是否结束工作流 | 状态 | "END" 或 "debate" | 检查是否需要进入辩论 |
| `_check_if_debate_needed(evaluations) -> bool` | 检查是否需要辩论 | 评估列表 | 布尔值 | 阈值由配置控制 |

---

### 3. 证据收集节点 (`src/graph/nodes/evidence_collection.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `run_evidence_collection(state) -> dict` | **统一执行所有工具** | 状态（含 parsed_content） | tool_evidence, ref_metadata_cache, topic_keywords, field_trend_baseline, candidate_key_papers | **核心证据聚合函数**，执行 8 个步骤 |
| `_collect_citation_extraction(source_pdf) -> tuple` | C3, C5 证据收集 | PDF 路径 | (extraction, references, orphan_rate, verify_rate) | **新增**，子函数拆分 |
| `_collect_c6_citation_alignment(extraction, references) -> dict` | C6 引用-对齐分析 | extraction, references | C6 分析结果含 contradiction_rate | **新增**，LLM 批处理 |
| `_collect_temporal_and_structural(...) -> tuple` | T1-T5, S1-S4 证据收集 | references, extraction, content, trend | (temporal_metrics, structural_metrics) | **新增**，子函数拆分 |
| `_collect_citation_graph(...) -> tuple` | G1-G6, S5 证据收集 | references, cache, extraction, section_counts | (graph_result, s5_result) | **新增**，子函数拆分 |
| `_collect_foundational_coverage(...) -> tuple` | G4 证据收集 | keywords, references, cache | (coverage_rate, missing, suspicious) | **新增**，子函数拆分 |
| `_extract_title_abstract(parsed_content) -> tuple` | 提取标题和摘要 | Markdown 内容 | (title, abstract) | 简单的正则解析 |
| `_build_ref_metadata_cache(references) -> dict` | 构建元数据缓存 | 参考文献列表 | ref_id → 元数据字典 | **核心共享数据结构**，避免重复 API 调用 |
| `_build_citation_edges(ref_metadata_cache) -> list` | 构建引用边 | 元数据缓存 | (source, target) 元组列表 | 仅使用外部验证的引用 |
| `_convert_numpy_types(obj) -> Any` | 类型转换 | 含 numpy 的对象 | 纯 Python 类型 | 用于 JSON 序列化 |

**证据收集 8 步骤**：
1. CitationChecker 提取引用和验证（C3, C5）
1.5. **C6 引用-对齐分析**（新增）
2. KeywordExtractor 提取关键词
3. LiteratureSearch 搜索领域趋势
4. LiteratureSearch 搜索候选核心论文
5. CitationAnalyzer 计算时序指标
6. CitationGraphAnalyzer 计算图指标
7. FoundationalCoverageAnalyzer 计算覆盖率

---

### 4. 证据分发节点 (`src/graph/nodes/evidence_dispatch.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `run_evidence_dispatch(state) -> dict` | 组装并分发证据报告 | 状态 | agent_evidence 字典 | 为每个 Agent 定制证据 |
| `assemble_evidence_report(evidence, agent_name) -> str` | 组装证据报告文本 | 证据、Agent 名 | 格式化报告 | 包含指标定义 + 数值 + 异常标记 |
| `build_verifier_evidence(evidence) -> dict` | 构建 Verifier 证据 | 工具证据 | Verifier 专用证据 | 包含 C3, C5 定义 |
| `build_expert_evidence(evidence) -> dict` | 构建 Expert 证据 | 工具证据 | Expert 专用证据 | 包含 G1-G6, S5, missing_papers |
| `build_reader_evidence(evidence) -> dict` | 构建 Reader 证据 | 工具证据 | Reader 专用证据 | 包含 T1-T5, S1-S5, field_trend_baseline |

---

### 5. 辩论节点 (`src/graph/nodes/debate.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `run_debate(state) -> dict` | 执行辩论轮次 | 状态 | 更新后的状态 | 更新 debate_history，递增 current_round |

**辩论流程**：
- 将上一轮评分差异发送给所有 Agent
- Agent 各自重新评估
- 检查是否达成共识（差异 < 阈值）或达到最大轮数

---

### 6. 聚合节点 (`src/graph/nodes/aggregator.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `aggregate_scores(state) -> dict` | 聚合所有 Agent 评分 | 状态 | aggregated_scores | **加权聚合**，读取 corrector_output |
| `generate_report(aggregation_result, state) -> str` | 生成 Markdown 报告 | 聚合结果、状态 | 报告文本 | 包含维度分数和方差 |
| `_aggregate_from_agent_outputs(agent_outputs, corrector_output?) -> dict` | 从 Agent 输出聚合 | Agent 输出、校正输出 | 聚合结果 | 使用 config weights |
| `_aggregate_from_evaluations(evaluations) -> dict` | 从旧格式评估聚合 | 评估列表 | 聚合结果 | 兼容旧代码 |
| `_get_grade(score) -> str` | 计算字母等级 | 分值 (0-10) | A-F | 阈值：8.5/7.5/6.5/5.5 |
| `_generate_recommendations(dimension_scores, overall) -> list` | 生成改进建议 | 维度分数、总分 | 建议列表 | 基于评分阈值 |

---

## Core 层（核心层）

Core 层定义数据类型、配置加载和 MCP 客户端。

### 1. 状态定义 (`src/core/state.py`)

| 类型名 | 字段 | 说明 |
|--------|------|------|
| `SurveyState` | source_pdf_path, parsed_content, tool_evidence, ref_metadata_cache, topic_keywords, field_trend_baseline, candidate_key_papers, agent_outputs, corrector_output, aggregated_scores, current_round, consensus_reached, final_report_md, metadata | **主状态类型**，贯穿整个工作流 |
| `ToolEvidence` | extraction, validation, c6_alignment, analysis, graph_analysis, trend_baseline, key_papers | 工具产出证据 |
| `AgentOutput` | agent_name, dimension, sub_scores, overall_score, confidence, evidence_summary | Agent 结构化输出 |
| `AgentSubScore` | score, llm_involved, hallucination_risk, tool_evidence, llm_reasoning, flagged_items, variance | 单个子维度评分，含 hallucination_risk |
| `VarianceRecord` | models_used, scores, median, std, high_disagreement | 多模型投票方差 |
| `CorrectionRecord` | original_agent, original_score, corrected_score, variance | 校正记录 |
| `CorrectorOutput` | corrections, skipped_dimensions, skip_reason, total_model_calls, failed_calls | 校正器输出 |
| `DimensionScore` | dim_id, final_score, source, agent, hallucination_risk, variance, weight | 聚合后维度分数 |
| `AggregatedScores` | dimension_scores, deterministic_metrics, overall_score, grade, total_weight | 加权聚合分数 |
| `C6AlignmentResult` | total_pairs, support, contradict, insufficient, contradiction_rate, auto_fail, contradictions, missing_abstract_count | C6 对齐结果 |
| `KeyPapersResult` | candidate_count, matched_count, coverage_rate, missing_key_papers, suspicious_centrality | 关键论文分析结果 |

---

### 2. 配置管理 (`src/core/config.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `load_config(config_path?) -> SurveyMAEConfig` | 加载主配置 | 配置文件路径（可选） | 配置对象 | 从 YAML 加载，支持环境变量 |
| `load_model_config(config_path?) -> ModelConfig` | 加载模型配置 | 配置文件路径（可选） | 模型配置对象 | 加载 models.yaml |
| `SurveyMAEConfig.from_yaml(config_path) -> Self` | 从 YAML 构建 | 配置文件路径 | 配置对象 | 解析 LLM/Agent/Debate/Report 配置 |
| `SurveyMAEConfig.from_env() -> Self` | 从环境变量构建 | 无 | 配置对象 | 用于测试 |

---

### 3. MCP 客户端 (`src/core/mcp_client.py`)

| 函数签名 | 功能描述 | 输入 | 输出 | 备注 |
|---------|---------|------|------|------|
| `MCPManager.connect() -> None` | 连接所有 MCP 服务器 | 无 | 无 | 异步连接 |
| `MCPManager.call_tool(server, tool, args) -> Any` | 调用 MCP 工具 | 服务器名、工具名、参数 | 工具响应 | 代理到对应服务器 |
| `MCPManager.get_langchain_tools(server?) -> list` | 获取 LangChain 工具定义 | 服务器名（可选） | 工具列表 | 用于 Agent 工具绑定 |

---

## 跨层调用关系总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Main Entry (main.py)                        │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Graph Layer (builder.py)                        │
│     create_workflow() → compile_workflow()                          │
│         │                              │                            │
│         ▼                              ▼                            │
│  ┌─────────────┐              ┌─────────────────────┐               │
│  │ parse_pdf   │              │ evidence_collection │               │
│  │ (01)        │              │ (02)                │               │
│  └─────────────┘              └─────────────────────┘               │
│                                       │                             │
│                                       ▼                             │
│                        ┌─────────────────────────┐                  │
│                        │ evidence_dispatch       │                  │
│                        │ (03)                    │                  │
│                        └─────────────────────────┘                  │
│                                       │                             │
│          ┌────────────────────────────┼────────────────────────┐    │
│          ▼                            ▼                        ▼    │
│  ┌──────────────┐          ┌──────────────┐         ┌──────────────┐│
│  │ Verifier     │          │ Expert       │         │ Reader       ││
│  │ (04)         │          │ (04)         │         │ (04)         ││
│  └──────────────┘          └──────────────┘         └──────────────┘│
│          │                            │                        │    │
│          └────────────────────────────┼────────────────────────┘    │
│                                       ▼                             │
│                        ┌─────────────────────────┐                  │
│                        │ Corrector               │                  │
│                        │ (05) - voting           │                  │
│                        └─────────────────────────┘                  │
│                                       │                             │
│                                       ▼                             │
│                        ┌─────────────────────────┐                  │
│                        │ aggregator              │                  │
│                        │ (06) - weighted         │                  │
│                        └─────────────────────────┘                  │
│                                       │                             │
│                                       ▼                             │
│                        ┌─────────────────────────┐                  │
│                        │ reporter                │                  │
│                        │ (07) + run_summary      │                  │
│                        └─────────────────────────┘                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 总结

本项目遵循清晰的层次化架构：

1. **Tools 层**：提供确定性计算能力（引用提取、分析、图构建、文献检索），是整个系统的数据基础
2. **Agents 层**：基于工具产出进行 LLM 判断，每个 Agent 职责明确（Verifier/Expert/Reader/Corrector/Reporter）
3. **Graph 层**：使用 LangGraph 编排工作流，实现加权评分聚合
4. **Core 层**：定义状态类型和配置管理，支撑整个系统运行

**主要调用链**：
```
01_parse_pdf → 02_evidence_collection (8步骤) → 03_evidence_dispatch →
  04_verifier → 04_expert → 04_reader → 05_corrector →
    06_aggregator (weighted) → 07_reporter (+ run_summary.json)
```

代码整体质量较高，主要改进点在于：
- 减少工具层的分支逻辑
- 统一异常处理策略
- 进一步拆分过大的函数
