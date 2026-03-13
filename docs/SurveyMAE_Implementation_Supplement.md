# SurveyMAE 实现补充说明（供 Claude Code 参照）

本文档是 SurveyMAE_Plan_v2.md 的实现层补充，解决设计文档中未覆盖的工程细节。Claude Code 应同时参照两份文档。

---

## 1. 现有代码 → 任务映射

### 1.1 需要修改的现有文件

| 文件 | 修改内容 |
|------|---------|
| `src/core/state.py` | 添加 ToolEvidence, MetricMetadata, AgentOutput 等 TypedDict；扩展 SurveyState 字段 |
| `src/core/config.py` | 添加 evidence_collection 相关配置项（G4 的 top_k、聚类算法选择等） |
| `src/tools/citation_checker.py` | validate 流程中将获取的完整元数据写入 ref_metadata_cache（当前只保存验证状态，需扩展保存被引次数、引用列表、venue等完整字段） |
| `src/tools/citation_analysis.py` | 新增 T2/T4/T5 指标计算方法；现有 temporal 分析方法可复用为 T1/T3 |
| `src/tools/citation_graph_analysis.py` | 新增 G4 计算（依赖外部检索结果输入）；新增 S5 计算 |
| `src/tools/literature_search.py` | 新增 `search_field_trend(keywords, year_range)` 和 `search_top_cited(keywords, top_k)` 方法 |
| `src/agents/verifier.py` | 重写 evaluate() 以接收 Evidence Report 并输出结构化 JSON |
| `src/agents/expert.py` | 同上 |
| `src/agents/reader.py` | 同上 |
| `src/agents/corrector.py` | 新增波动范围计算逻辑 |
| `src/agents/reporter.py` | 拆分为纯报告生成（不再做数据收集） |
| `src/graph/builder.py` | 重构节点拓扑：parse_pdf → evidence_collection → evidence_dispatch → 并行agents → corrector → debate? → aggregator → reporter |
| `src/graph/nodes/aggregator.py` | 重写为纯数学聚合（加权平均），不涉及LLM |
| `config/prompts/*.yaml` | 所有Agent的prompt模板需要重写 |

### 1.2 需要新建的文件

| 文件 | 职责 |
|------|------|
| `src/graph/nodes/evidence_collection.py` | 统一工具执行节点：顺序调用 CitationChecker → 关键词提取(LLM) → LiteratureSearch → CitationAnalyzer → CitationGraphAnalysis |
| `src/graph/nodes/evidence_dispatch.py` | 证据分发节点：为每个Agent组装Evidence Report |
| `src/tools/keyword_extractor.py` | LLM辅助关键词提取（从标题/摘要/章节标题中提取topic_keywords） |
| `src/tools/trend_analyzer.py` | field_trend_baseline 计算（调用 literature_search + 年份聚合 + 相关系数计算）。也可直接在 citation_analysis.py 中新增方法，取决于代码组织偏好 |
| `src/core/metric_metadata.py` | MetricMetadata 定义与辅助函数（创建、校验、序列化） |
| `tests/unit/test_s5_alignment.py` | S5 (NMI/ARI) 单元测试 |
| `tests/unit/test_trend_alignment.py` | T5 (trend_alignment) 单元测试 |
| `tests/unit/test_foundational_coverage.py` | G4 单元测试 |
| `tests/integration/test_evidence_collection.py` | evidence_collection 全链路集成测试 |

---

## 2. 依赖库选择

以下库应已在项目依赖中或可通过 `uv add` 安装：

| 用途 | 推荐库 | 备注 |
|------|--------|------|
| 图分析（G1-G6） | `networkx` | 项目已使用（citation_graph_analysis.py） |
| NMI/ARI（S5） | `sklearn.metrics.normalized_mutual_info_score`, `adjusted_rand_score` | sklearn 应已在依赖中 |
| 皮尔逊相关（T5） | `scipy.stats.pearsonr` | scipy 应已在依赖中 |
| Gini系数（S3） | 手写（约5行）或 `numpy` | 无需额外依赖 |
| 标题模糊匹配（G4） | `rapidfuzz.fuzz.token_sort_ratio` | 比 difflib 快且准确，用于DOI缺失时的标题匹配 |

---

## 3. ref_metadata_cache 与现有数据结构的对接

### 3.1 当前 CitationChecker 的输出结构

当前 `validation.json` 每条 reference 大约保存：
```json
{
  "ref_id": "[12]",
  "title": "...",
  "year": "2023",
  "status": "verified",  // verified | unverified | mismatch
  "source": "semantic_scholar",
  "matched_metadata": { ... }  // 外部API返回的匹配结果
}
```

### 3.2 需要扩展的字段

`matched_metadata` 中需要确保包含（如果API返回了的话）：
```json
{
  "doi": "10.xxx",
  "title": "...",
  "year": 2023,
  "citation_count": 1542,       // ★ G4 suspicious_centrality 需要
  "reference_count": 45,
  "references": ["paperId1", "paperId2", ...],  // ★ 引用图边构建需要
  "venue": "NeurIPS",           // ★ 关键词提取的参考
  "fields_of_study": ["Computer Science"],
  "authors": [{"name": "...", "authorId": "..."}],
  "abstract": "..."            // ★ G4候选清洗时LLM判断相关性需要
}
```

### 3.3 缓存实现建议

ref_metadata_cache 可以直接复用现有的 `ResultStore` 机制（保存到 `papers/<paper_id>/validation.json`），只需扩展保存的字段。关键是：后续工具（CitationAnalyzer、CitationGraphAnalysis）应从 ResultStore 读取已保存的 validation 数据，而非重新调用 API。

具体来说，在 `evidence_collection` 节点中：
```python
# 伪代码
checker = CitationChecker(result_store=store)
extraction = checker.extract_citations_with_context_from_pdf(pdf_path)
validation = checker.validate_references(extraction, verify_sources=["semantic_scholar", "openalex"])
# validation 现在包含扩展的 matched_metadata

# 后续工具直接接收 validation 数据，不再调用 API
analyzer = CitationAnalyzer()
analysis = analyzer.analyze_from_validation(validation)  # 从 validation 的 year 字段计算 T1-T5

graph = CitationGraphAnalysis()
graph_result = graph.analyze_from_validation(validation)  # 从 references 字段构建边
```

---

## 4. 执行顺序与依赖关系

Phase 1 内部有隐含依赖，推荐按以下顺序执行：

```
1.9 state.py 扩展 ──────────────────────────────┐
1.4 MetricMetadata schema ──────────────────────┤  基础设施
                                                 │  （先做这些）
1.3 S5 NMI/ARI 计算 ───────────────────────────┤
                                                 │
1.1 field_trend_baseline ──┐                    │
1.2 G4 coverage_rate ──────┤  检索增强指标       │
     (两者共享关键词提取)   │  （需要1.4的schema）│
                            │                    │
1.5 完善所有rubric ─────────┤                    │
1.6 Agent输出JSON Schema ──┤  Agent协议         │
                            │  （需要1.4的schema）│
1.7 evidence_dispatch ──────┤                    │
1.8 prompt模板更新 ─────────┘  （需要1.5/1.6/1.7）│
```

Phase 2 的 2.1 (evidence_collection) 依赖 Phase 1 的所有工具实现完成。

---

## 5. Rubric 完整性补充

Plan v2 中只给出了 V2, E1, E4, R1 四个子维度的完整 rubric 示例。以下子维度需要在实现时补写 rubric：

| 子维度 | rubric设计要点 |
|--------|---------------|
| V1 (引用存在性) | 主要依赖 C5 数值，rubric 阈值可参考：5分→C5≥0.95, 4分→≥0.85, 3分→≥0.70, 2分→≥0.50, 1分→<0.50。LLM负责对未验证文献做"是workshop/preprint还是真的不存在"的判断 |
| V3 (引用准确性) | 与V2类似的抽样判断，但关注点不同：V2看"是否支持"，V3看"是否正确理解"。典型错误类型：误读（misinterpretation）、过度概括（overgeneralization）、错误归因（misattribution） |
| V4 (内部一致性) | 无工具证据直接支持，纯LLM判断。rubric 按矛盾数量和严重程度分级 |
| E2 (方法分类合理性) | 结合 G5+S5：如果 S5(NMI)高说明章节与聚类吻合，分类可能合理。LLM评估分类是否与学术共识一致 |
| E3 (技术准确性) | 纯LLM判断，hallucination_risk 高。rubric 按技术错误数量和严重程度分级 |
| R2 (信息分布均衡性) | 结合 S2/S3/S5/G5。S3(Gini)高不一定扣分，需LLM判断是否合理的重点安排 |
| R3 (结构清晰度) | 结合 S1/S5。S5高 + 章节标题层次清晰 → 高分 |
| R4 (文字质量) | 纯LLM判断，无工具证据。rubric 按语法错误、术语一致性、可读性分级 |

**建议：** rubric 初版可以参照上述要点快速起草，在 Phase 3 的 pilot 标注阶段根据实际标注反馈调整。不必追求一次完美。

---

## 6. 第一层 LLM 辅助的具体 Prompt 指导

### 6.1 关键词提取 prompt 模板

```yaml
# config/prompts/keyword_extractor.yaml
template: |
  You are a keyword extraction assistant for academic survey evaluation.

  Given the following survey metadata, extract 3-5 keyword groups for searching
  academic databases. Each group should be a short query (2-5 words) targeting
  the core topic and sub-topics of this survey.

  Survey Title: {title}
  Abstract: {abstract}
  Section Headings: {section_headings}
  Top Venues in References: {top_venues}
  Top Keywords in References: {top_keywords}

  Output as JSON array of strings. Only output the JSON, no explanation.
  Example: ["retrieval augmented generation", "RAG LLM", "dense passage retrieval", "knowledge grounded generation"]
```

### 6.2 G4 候选清洗 prompt 模板

```yaml
# config/prompts/candidate_filter.yaml
template: |
  You are evaluating whether a candidate paper is relevant to a survey's topic.

  Survey Topic Keywords: {topic_keywords}
  Survey Title: {survey_title}

  Candidate Paper:
  - Title: {candidate_title}
  - Abstract: {candidate_abstract}
  - Venue: {candidate_venue}

  Is this paper relevant to the survey's topic? Answer only "yes" or "no".
```

---

## 7. 优雅降级策略

当外部 API 不可用时（网络故障、rate limit、API key 缺失），系统应降级而非崩溃：

| 场景 | 降级策略 | 影响的指标 |
|------|---------|-----------|
| Semantic Scholar 不可用 | fallback 到 OpenAlex（或反之） | C5, G4, T2, T5 的数据质量下降但仍可计算 |
| 所有学术 API 不可用 | C5 标记为 "unavailable"；T2/T5/G4 标记为 "degraded"，使用 ref_metadata_cache 中已有数据做尽力计算 | 检索增强指标不可用，在报告中标记 |
| LLM API 不可用 | 关键词提取 fallback 到 TF-IDF/RAKE 等无监督方法；候选清洗跳过（接受更多噪声） | hallucination_risk 实际降为 none，但检索精度下降 |

每个指标的输出中应包含 `data_source` 字段标明实际使用了哪些数据源，以便实验中报告。

---

## 8. 配置外部化

以下参数应在 `config/main.yaml` 中可配置，而非硬编码：

```yaml
# config/main.yaml 新增配置段
evidence:
  # G4 相关
  foundational_top_k: 30            # 候选核心文献检索数量
  foundational_match_threshold: 0.85 # 标题模糊匹配阈值 (rapidfuzz score)
  
  # T 系列相关
  trend_query_count: 5              # field_trend_baseline 检索的query组数
  trend_year_range: [2000, 2025]    # 趋势检索的年份范围
  
  # S5 相关
  clustering_algorithm: "louvain"   # louvain | spectral | leiden
  clustering_seed: 42               # 固定随机种子
  
  # 抽样相关
  citation_sample_size: 15          # V2/V3 引用-断言抽样对数量
  
  # 降级配置
  api_timeout_seconds: 30
  fallback_order: ["semantic_scholar", "openalex", "crossref"]
```

---

## 9. 测试策略

### 9.1 单元测试（不依赖网络/LLM）

所有新增的计算逻辑必须有单元测试，使用 mock 数据：

- **S5 测试：** 构造已知聚类和章节归属的 mock 数据，验证 NMI/ARI 计算正确性
- **T5 测试：** 构造两个已知分布，验证 pearsonr 计算
- **G4 测试：** 构造 candidate_list 和 ref_list，验证匹配率计算和 missing_key_papers 输出
- **Gini系数测试：** 已知分布验证
- **evidence_dispatch 测试：** 验证 Evidence Report 的组装格式完整性

### 9.2 集成测试

使用项目中已有的 `test_survey2.pdf` 作为测试输入，验证 evidence_collection 全链路。该 PDF 是 KDD '24 发表的 RAG 综述，引用规范、结构完整，适合作为"中高质量"测试样本。

---

## 10. 注意事项（容易犯的错误）

1. **不要在 CitationAnalyzer 中重新调用 API。** 所有年份、被引次数等数据必须从 ref_metadata_cache 读取。如果 cache 中某条 ref 的 year 缺失，标记为 unknown 并在指标输出中报告 `missing_year_ratio`。

2. **S5 的"章节归属"需要处理多章节引用的情况。** 同一篇参考文献可能在多个章节被引用。建议按引用频次归属到主章节（引用次数最多的章节），或以最早出现的章节为主。需在文档中明确选择并测试两种策略的差异。

3. **G4 的标题匹配要处理各种格式差异。** 学术论文标题在不同来源中可能有大小写、标点、LaTeX 符号等差异。建议先 normalize（lowercase、去除标点和 LaTeX 命令）再做模糊匹配。DOI 匹配优先于标题匹配。

4. **field_trend_baseline 的年份范围要合理。** 不要从1900年开始检索，应该从该领域合理的起始年份开始（可以用综述中最早引用年份 - 5年 作为下界）。

5. **evidence_collection 节点的错误处理。** 如果某个工具执行失败（如图分析因无边而失败），不应阻断整个pipeline。应将该工具的输出标记为 `status: "failed"` 并继续执行后续步骤。Agent 在收到 failed 证据时应在评分中标注"因工具异常无法评估此维度"。

6. **prompt 模板中的 rubric 要与 Plan v2 中定义的完全一致。** 不要让 Claude Code 自行发挥 rubric 内容。所有 rubric 应从 Plan v2 中直接复制到 prompt yaml 中。

7. **多模型投票的实现。** CorrectorAgent 的多模型投票不是"让3个模型分别运行完整的Agent评估"，而是"对已有Agent输出的每个子维度分数，用3个模型分别重新打分"。这样可以大幅降低成本（只需要3次打分调用，而非3次完整评估）。
