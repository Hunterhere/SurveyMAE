# SurveyMAE 实现补充说明 v3（供 Claude Code 参照）

本文档是 SurveyMAE_Plan_v3.md 的实现层补充。Plan v3 是设计规范（what & why），本文档是实现指南（how & where）。冲突时以 Plan v3 为准。

**适用范围：** Phase 2 及后续工作。Phase 1 已基本实现。

---

## 1. ResultStore 持久化文件与工具方法映射

### 1.1 完整映射表

| Plan v3 文件名 | 内容 | 产出工具类 | 产出方法 | 现有 ResultStore 方法 | 状态 | 操作 |
|---|---|---|---|---|---|---|
| `extraction.json` | citations + references 原始提取 | CitationChecker | `extract_citations_with_context_from_pdf()` | `save_extraction()` (citation_checker.py:647) | ✅ 已定义 | 修复 result_store 传递即可 |
| `validation.json` | 验证结果 + ref_metadata_cache 完整数据（含 abstract、citation_count） | CitationChecker | validate 流程 | `save_validation()` (citation_checker.py:678) | ⚠️ 已定义但需确认内容 | 修复传递 + 确认保存内容包含完整 metadata |
| `c6_alignment.json` | C6 逐条对齐结果（support/contradict/insufficient + contradiction_rate） | CitationChecker | `analyze_citation_sentence_alignment()` | ❌ 无 | **需新增** | 新增 `save_c6_alignment(paper_id, data)` |
| `analysis.json` | CitationAnalyzer 的 T1-T5, S1-S4 指标 | CitationAnalyzer | `analyze_from_validation()` 或现有 temporal/structural 方法 | ❌ 无（现有 `save_analysis()` 被图分析占用） | **需新增** | 新增 `save_citation_analysis(paper_id, data)` |
| `graph_analysis.json` | CitationGraphAnalysis 的 G1-G6, S5 指标 | CitationGraphAnalysis | `analyze()` | `save_analysis()` (citation_graph_analysis.py:1203) | ⚠️ 名称不匹配 | **重命名**为 `save_graph_analysis(paper_id, data)` |
| `trend_baseline.json` | field_trend_baseline（各年份领域发表量） | LiteratureSearch | `search_field_trend()` | ❌ 无 | **需新增** | 新增 `save_trend_baseline(paper_id, data)` |
| `key_papers.json` | candidate_key_papers（清洗后的高被引论文列表 + G4 覆盖率 + missing/suspicious） | LiteratureSearch + FoundationalCoverageAnalyzer | `search_top_cited()` + 匹配计算 | ❌ 无 | **需新增** | 新增 `save_key_papers(paper_id, data)` |

**汇总：** 7 个文件中 2 个可直接复用现有方法（修复 result_store 传递即可），1 个需重命名，4 个需新增 ResultStore 方法。

### 1.2 ResultStore 需要新增的方法

```python
# src/tools/result_store.py 新增方法

def save_c6_alignment(self, paper_id: str, data: dict) -> Path:
    """保存 C6 citation-sentence alignment 结果"""
    return self._save_json(paper_id, "c6_alignment.json", data)

def save_citation_analysis(self, paper_id: str, data: dict) -> Path:
    """保存 CitationAnalyzer 的 T/S 系列指标"""
    return self._save_json(paper_id, "analysis.json", data)

def save_graph_analysis(self, paper_id: str, data: dict) -> Path:
    """保存 CitationGraphAnalysis 的 G 系列指标 + S5
    注意：替代原 save_analysis()，原方法名有歧义"""
    return self._save_json(paper_id, "graph_analysis.json", data)

def save_trend_baseline(self, paper_id: str, data: dict) -> Path:
    """保存 field_trend_baseline（领域年份发表量趋势）"""
    return self._save_json(paper_id, "trend_baseline.json", data)

def save_key_papers(self, paper_id: str, data: dict) -> Path:
    """保存 candidate_key_papers + G4 覆盖率 + missing/suspicious 列表"""
    return self._save_json(paper_id, "key_papers.json", data)

def _save_json(self, paper_id: str, filename: str, data: dict) -> Path:
    """通用 JSON 保存方法"""
    paper_dir = self.papers_dir / paper_id
    paper_dir.mkdir(parents=True, exist_ok=True)
    path = paper_dir / filename
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return path
```

### 1.3 evidence_collection 中传入 result_store 的修改点

```python
# src/graph/nodes/evidence_collection.py 修改

async def run_evidence_collection(state: SurveyState, result_store: ResultStore = None) -> dict:
    # ...
    checker = CitationChecker(result_store=result_store)  # ← 修复：传入 result_store
    # ...
    # C6 结果保存
    if result_store and paper_id:
        result_store.save_c6_alignment(paper_id, c6_result)

    # CitationAnalyzer 结果保存
    if result_store and paper_id:
        result_store.save_citation_analysis(paper_id, analysis_result)

    # graph_analysis 结果保存（使用重命名后的方法）
    graph_analyzer = CitationGraphAnalysis(result_store=result_store)
    # ...内部调用 result_store.save_graph_analysis()

    # trend/key_papers 结果保存
    if result_store and paper_id:
        result_store.save_trend_baseline(paper_id, field_trend_baseline)
        result_store.save_key_papers(paper_id, key_papers_data)
```

### 1.4 builder.py wrapper 修改

```python
# src/graph/builder.py

async def _wrap_evidence_collection(state: SurveyState) -> dict:
    store = _get_result_store(state.get("source_pdf_path", ""))
    result = await run_evidence_collection(state, result_store=store)  # ← 传入 store
    _save_workflow_step("02_evidence_collection", state, result, ...)
    return result
```

### 1.5 原有 save_analysis() 的迁移

`citation_graph_analysis.py` 中所有 `self.result_store.save_analysis(...)` 调用需改为 `self.result_store.save_graph_analysis(...)`。同时需确保 CitationGraphAnalysis 初始化时接收 result_store 参数。

---

## 2. Corrector 多模型投票实现细节

### 2.1 使用哪 3 个模型？

**从配置读取。** 在 `config/models.yaml` 的 `corrector` 段配置：

```yaml
# config/models.yaml
agents:
  corrector:
    multi_model:
      enabled: true
      models:
        - provider: openai
          model: gpt-4o
        - provider: anthropic
          model: claude-sonnet-4-20250514
        - provider: deepseek
          model: deepseek-chat
```

代码中从配置加载，不硬编码模型名。fallback 策略：若某模型调用失败，用剩余模型的结果计算（至少需要 2 个模型成功）。

### 2.2 投票是逐维度还是批量？

**逐维度调用，但可并发。** 每个子维度需要独立的 prompt（包含该维度的 rubric + 工具证据 + 原始 Agent reasoning），不同维度的 prompt 不同，无法合并为一个 batch。但 7 个维度 × 3 个模型 = 21 次调用可以用 `asyncio.gather` 并发执行。

```python
async def run_correction(agent_outputs, evidence_reports, config):
    tasks = []
    for dim_id in HIGH_RISK_DIMENSIONS:
        for model_config in config.corrector_models:
            tasks.append(score_dimension(dim_id, agent_outputs, evidence_reports, model_config))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # 按维度分组，取中位数
```

### 2.3 校正分数是否更新原始 agent_outputs？

**不更新。** 原始 agent_outputs 保持不变（保留原始评分用于 meta-evaluation 对比）。校正结果存储在独立的 `corrector_output: CorrectorOutput` 中。Aggregator 使用 corrector_output 中的 `corrected_score`（如果有）或 agent_outputs 中的 `original_score`（如果该维度未被校正）。

```python
# aggregator 逻辑
def get_final_score(dim_id, agent_outputs, corrector_output):
    if dim_id in corrector_output["corrections"]:
        return corrector_output["corrections"][dim_id]["corrected_score"]
    else:
        return agent_outputs[agent_name]["sub_scores"][dim_id]["score"]
```

### 2.4 需要投票的子维度清单

| 子维度 | hallucination_risk | 投票？ | 说明 |
|--------|:---:|:---:|------|
| V1 (引用存在性) | low | ❌ | 基于 C5 阈值 |
| V2 (引用-断言对齐) | low | ❌ | hallucination_risk=low（核心依据是 C6 确定性统计）。C6.auto_fail=true 时由 evidence_dispatch 预填 1 分；auto_fail=false 时由 VerifierAgent 基于 C6 数据判断。两种情况均不投票 |
| V4 (内部一致性) | high | ✅ | 纯 LLM 判断，无工具证据支持 |
| E1 (核心文献覆盖) | low | ❌ | 基于 G4 阈值 |
| E2 (方法分类合理性) | medium | ✅ | LLM 结合 S5/G5 判断 |
| E3 (技术准确性) | high | ✅ | 纯 LLM 判断 |
| E4 (批判性分析深度) | high | ✅ | 纯 LLM 判断 |
| R1 (时效性) | low | ❌ | 基于 T5 阈值 |
| R2 (信息分布均衡性) | medium | ✅ | LLM 结合 S3/S5 判断 |
| R3 (结构清晰度) | medium | ✅ | LLM 结合 S1/S5 判断 |
| R4 (文字质量) | high | ✅ | 纯 LLM 判断 |

**共 7 个子维度需要投票**（V4, E2, E3, E4, R2, R3, R4），× 3 个模型 = 21 次 LLM 调用。

### 2.5 Corrector 的投票 prompt 模板

```yaml
# config/prompts/corrector_vote.yaml
template: |
  You are re-scoring a survey evaluation dimension as part of a multi-model voting process.

  ## Dimension: {dimension_id} - {dimension_name}

  ## Rubric:
  {rubric_text}

  ## Tool Evidence:
  {tool_evidence_summary}

  ## Original Agent Assessment:
  Agent: {original_agent_name}
  Score: {original_score}/5
  Reasoning: {original_reasoning}

  Based on the rubric, tool evidence, and your own judgment, provide your score (1-5).
  Output ONLY a JSON object: {"score": <int>, "brief_reason": "<one sentence>"}
```

---

## 3. State 类型定义详细规范

### 3.1 ToolEvidence

ToolEvidence 是当前 `tool_evidence` 的**结构化版本**，字段不变但增加类型约束：

```python
class ToolEvidence(TypedDict):
    extraction: ExtractionResult       # citations + references 原始提取
    validation: ValidationResult       # 验证结果，包含 ref_metadata_cache 的数据源
    c6_alignment: C6AlignmentResult    # v3 新增：C6 逐条对齐结果
    analysis: CitationAnalysisResult   # T1-T5, S1-S4
    graph_analysis: GraphAnalysisResult # G1-G6, S5
    trend_baseline: TrendBaselineResult # field_trend_baseline
    key_papers: KeyPapersResult         # candidate_key_papers + G4

class C6AlignmentResult(TypedDict):
    total_pairs: int
    support: int
    contradict: int
    insufficient: int
    contradiction_rate: float
    auto_fail: bool
    contradictions: List[dict]         # 每条 contradict 的详细信息
    missing_abstract_count: int        # abstract 缺失数

class KeyPapersResult(TypedDict):
    candidate_count: int
    matched_count: int
    coverage_rate: float               # G4 值
    missing_key_papers: List[dict]     # 应引未引
    suspicious_centrality: List[dict]  # 内部高中心性但外部低被引
```

### 3.2 CorrectorOutput

```python
class CorrectorOutput(TypedDict):
    corrections: Dict[str, CorrectionRecord]  # dim_id → 校正记录
    skipped_dimensions: List[str]             # 跳过的低风险维度 ID
    skip_reason: str                          # 如 "low hallucination_risk, threshold-based"
    total_model_calls: int                    # 本次校正的总 LLM 调用次数
    failed_calls: int                         # 失败的调用次数

class CorrectionRecord(TypedDict):
    original_agent: str                       # 原始打分的 Agent 名
    original_score: float
    corrected_score: float                    # 中位数
    variance: VarianceRecord

class VarianceRecord(TypedDict):
    models_used: List[str]                    # 实际使用的模型名
    scores: List[float]                       # 各模型分数
    median: float
    std: float
    high_disagreement: bool                   # std > 1.0 或 max-min > 2
```

### 3.3 AggregatedScores

```python
class AggregatedScores(TypedDict):
    # 按维度的最终分数（使用校正后分数）
    dimension_scores: Dict[str, DimensionScore]

    # 汇总
    deterministic_metrics: Dict[str, float]   # C3, C5, C6_rate, T1-T5, S1-S5, G1-G6 的数值
    overall_score: float                      # 加权总分（0-10 scale）
    grade: str                                # A/B/C/D/F

class DimensionScore(TypedDict):
    dim_id: str                               # V1, E2, R4, ...
    final_score: float                        # 校正后（若有）或原始分
    source: str                               # "original" | "corrected"
    agent: str                                # 产出该分数的 Agent
    hallucination_risk: str
    variance: Optional[VarianceRecord]        # 校正时产出（若有）
    weight: float                             # 聚合权重
```

---

## 4. 评分聚合公式

### 4.1 总体思路

最终得分 = 11 个子维度分数的**加权平均**，每个子维度使用校正后分数（若有）或原始分数。分数从 1-5 scale 线性映射到 0-10 scale。

```
overall_score = Σ(weight_i × final_score_i) / Σ(weight_i) × 2
```

（乘以 2 是因为子维度 1-5 分，总分 0-10 分）

### 4.2 权重配置

在 `config/main.yaml` 中配置，默认值如下：

```yaml
aggregation:
  weights:
    # VerifierAgent 维度（事实性，权重最高）
    V1_citation_existence: 1.2
    V2_citation_claim_alignment: 1.5    # 引用准确性是综述核心质量
    V4_internal_consistency: 1.0

    # ExpertAgent 维度（学术深度）
    E1_foundational_coverage: 1.3
    E2_classification_reasonableness: 1.0
    E3_technical_accuracy: 1.2
    E4_critical_analysis_depth: 1.3     # 批判性分析是区分好坏综述的关键

    # ReaderAgent 维度（可读性）
    R1_timeliness: 1.0
    R2_information_balance: 0.8
    R3_structural_clarity: 0.8
    R4_writing_quality: 0.7             # 文字质量权重最低（与内容质量相比）
```

**权重设计原则：** 引用准确性（V2）和批判性分析深度（E4）权重最高，因为这是区分高质量综述与低质量综述的核心维度。文字质量（R4）权重最低，因为LLM生成的文字通常流畅度不差，该维度区分度有限。

### 4.3 确定性指标 vs LLM 指标的处理

**不分别计算后合并。** 11 个子维度使用统一的加权平均。但在报告和 run_summary.json 中，单独列出：

- `deterministic_metrics`：所有第一层指标的原始数值（C3, C5, C6_rate, T1-T5, S1-S5, G1-G6），不参与加权平均，仅作为参考展示。
- `dimension_scores`：11 个子维度的最终评分，这些是参与加权平均的。

**理由：** 第一层确定性指标已经被编码进了 Agent 的 rubric 中（如 "V1 rubric: C5≥0.95→5分"），所以它们通过 Agent 评分间接参与了总分计算。再单独加权一次会导致双重计算。

### 4.4 Aggregator 实现伪代码

```python
def aggregate(agent_outputs, corrector_output, weights_config):
    dimension_scores = {}

    for agent_name, output in agent_outputs.items():
        for dim_id, sub_score in output["sub_scores"].items():
            # 使用校正后分数（若有）
            if dim_id in corrector_output.get("corrections", {}):
                final = corrector_output["corrections"][dim_id]["corrected_score"]
                source = "corrected"
                variance = corrector_output["corrections"][dim_id]["variance"]
            else:
                final = sub_score["score"]
                source = "original"
                variance = None

            dimension_scores[dim_id] = {
                "dim_id": dim_id,
                "final_score": final,
                "source": source,
                "agent": agent_name,
                "hallucination_risk": sub_score.get("hallucination_risk", "medium"),
                "variance": variance,
                "weight": weights_config.get(dim_id, 1.0),
            }

    # 加权平均 → 0-10 scale
    weighted_sum = sum(d["final_score"] * d["weight"] for d in dimension_scores.values())
    total_weight = sum(d["weight"] for d in dimension_scores.values())
    overall_score = (weighted_sum / total_weight) * 2  # 1-5 → 0-10

    return {
        "dimension_scores": dimension_scores,
        "overall_score": round(overall_score, 2),
        "grade": _get_grade(overall_score),
    }
```

---

## 5. 持久化文件命名与代码位置映射

### 5.1 工具层独立持久化（由工具类内部调用 result_store）

| 文件 | 调用位置 | 触发时机 |
|------|---------|---------|
| `extraction.json` | `citation_checker.py` 内 `save_extraction()` | `extract_citations_with_context_from_pdf()` 完成后 |
| `validation.json` | `citation_checker.py` 内 `save_validation()` | validate 流程完成后 |
| `c6_alignment.json` | `citation_checker.py` 内 `save_c6_alignment()` **新增** | `analyze_citation_sentence_alignment()` 完成后 |
| `analysis.json` | `evidence_collection.py` 中手动调用 `result_store.save_citation_analysis()` **新增** | CitationAnalyzer 计算完成后 |
| `graph_analysis.json` | `citation_graph_analysis.py` 内 `save_graph_analysis()` **重命名** | `analyze()` 完成后 |
| `trend_baseline.json` | `evidence_collection.py` 中手动调用 `result_store.save_trend_baseline()` **新增** | field_trend_baseline 检索完成后 |
| `key_papers.json` | `evidence_collection.py` 中手动调用 `result_store.save_key_papers()` **新增** | G4 计算完成后 |

### 5.2 工作流步骤增量持久化（由 builder.py wrapper 调用）

| 文件 | 内容（仅增量） | 不包含 |
|------|---------------|--------|
| `01_parse_pdf.json` | parsed_content + metadata | — |
| `02_evidence_collection.json` | tool_evidence 指标汇总 + topic_keywords | ref_metadata_cache（→ see validation.json） |
| `03_evidence_dispatch.json` | 各 Agent 的 Evidence Report 摘要 + 异常标记 | 完整证据数据（→ see 工具层文件） |
| `04_verifier.json` | VerifierAgent 的 AgentOutput | evidence_reports（→ see 03） |
| `04_expert.json` | ExpertAgent 的 AgentOutput | 同上 |
| `04_reader.json` | ReaderAgent 的 AgentOutput | 同上 |
| `05_corrector.json` | CorrectorOutput（校正记录） | Agent 原始输出（→ see 04_*） |
| `06_aggregated_scores.json` | AggregatedScores | — |
| `07_report.md` | 最终 Markdown 报告 | — |

### 5.3 运行级文件

| 文件 | 生成时机 | 内容 |
|------|---------|------|
| `run.json` | 运行开始 | run_id + created_at + **schema_version** + config 参数 |
| `metric_index.json` | 运行开始 | 指标定义 + 来源 + 数据流 + config 快照（见 Plan v3 §3.4.3） |
| `run_summary.json` | 运行结束 | 所有指标最终值 + 评分 + 总分（见 Plan v3 §3.4.4） |

---

## 6. 需要修改和新建的文件清单（Phase 2）

### 6.1 实现顺序

按以下顺序执行，每步依赖前序步骤完成：

```
Step 1: State 类型定义
        → src/core/state.py 新增 CorrectorOutput, CorrectionRecord,
          VarianceRecord, AggregatedScores, DimensionScore 等 TypedDict
        → 移除 debate_history

Step 2: ResultStore 方法
        → src/tools/result_store.py 新增 5 个 save_* 方法 + 重命名 1 个
        → 见 §1.2

Step 3: 配置文件更新
        → config/main.yaml 新增 aggregation.weights 配置段
        → config/models.yaml 确认 corrector.multi_model 配置段
        → 见 §9

Step 4: 证据收集节点修复
        → src/graph/nodes/evidence_collection.py 接收 result_store 参数
        → src/graph/builder.py wrapper 传入 result_store
        → 见 §1.3, §1.4

Step 5: 工具层独立持久化
        → citation_checker.py: save_c6_alignment() 调用
        → citation_graph_analysis.py: save_analysis → save_graph_analysis 重命名
        → evidence_collection.py: 手动调用 save_citation_analysis/trend/key_papers
        → 见 §5.1

Step 6: 工作流步骤增量保存
        → builder.py: _save_workflow_step 改为增量（不含 ref_metadata_cache）
        → builder.py: _init_run_file 保存 config 快照 + schema_version
        → 见 §5.2, §5.3

Step 7: Corrector 重写
        → src/agents/corrector.py: 删除 C1/C2/C3，改为多模型投票校正
        → config/prompts/corrector_vote.yaml: 投票 prompt 模板
        → 见 §2

Step 8: Aggregator 重写
        → src/graph/nodes/aggregator.py: 读取 corrector_output + 加权聚合
        → 见 §4

Step 9: Reporter 扩展
        → src/agents/reporter.py: 生成 run_summary.json + metric_index.json
        → 报告模板后续版本完善（Phase 4）
```

### 6.2 需要修改的文件

| 文件 | 修改内容 |
|------|---------|
| `src/tools/result_store.py` | 新增 5 个方法（§1.2）；重命名 save_analysis → save_graph_analysis |
| `src/tools/citation_checker.py` | C6 方法末尾添加 `result_store.save_c6_alignment()` 调用 |
| `src/tools/citation_graph_analysis.py` | 内部 `save_analysis()` 调用改为 `save_graph_analysis()` |
| `src/graph/nodes/evidence_collection.py` | (1) 接收 result_store 参数；(2) 传入所有工具实例；(3) 手动调用 save_citation_analysis/save_trend_baseline/save_key_papers |
| `src/graph/builder.py` | (1) wrapper 传入 result_store；(2) `_save_workflow_step` 改为增量保存；(3) `_init_run_file` 保存 config 快照 + schema_version |
| `src/agents/corrector.py` | **重写**：删除 C1/C2/C3 独立评分，改为多模型投票校正（§2） |
| `src/graph/nodes/aggregator.py` | **重写**：使用校正后分数 + 加权聚合（§4） |
| `src/agents/reporter.py` | 新增 run_summary.json 生成；报告模板后续版本完善 |
| `src/core/state.py` | 新增 CorrectorOutput, CorrectionRecord, VarianceRecord, AggregatedScores, DimensionScore 类型；移除 debate_history |
| `config/main.yaml` | 新增 aggregation.weights 配置段 |
| `config/models.yaml` | 确认 corrector.multi_model 配置段已包含 3 个模型 |

### 6.3 需要新建的文件

| 文件 | 职责 |
|------|------|
| `config/prompts/corrector_vote.yaml` | Corrector 投票 prompt 模板（§2.5） |
| `tests/unit/test_corrector_voting.py` | Corrector 投票逻辑单元测试 |
| `tests/unit/test_aggregator_weighted.py` | 加权聚合单元测试 |
| `tests/unit/test_result_store_new_methods.py` | 新增 ResultStore 方法测试 |

---

## 7. Rubric 完整性补充

Plan v3 中已给出 V2, E1, E4, R1 的完整 rubric。以下子维度需要补写：

| 子维度 | rubric 设计要点 |
|--------|---------------|
| V1 (引用存在性) | 基于 C5：5分→≥0.95, 4分→≥0.85, 3分→≥0.70, 2分→≥0.50, 1分→<0.50。LLM 判断未验证文献是 workshop/preprint 还是真不存在 |
| V4 (内部一致性) | 纯 LLM 判断，hallucination_risk=high。按矛盾数量和严重程度分级：5分→无矛盾, 4分→1处轻微, 3分→2-3处或1处严重, 2分→多处, 1分→系统性矛盾 |
| E2 (方法分类合理性) | 结合 G5+S5：S5(NMI)≥0.7 + LLM 确认分类合理→5分。hallucination_risk=medium |
| E3 (技术准确性) | 纯 LLM 判断，hallucination_risk=high。按错误数量和严重程度分级 |
| R2 (信息分布均衡性) | 结合 S2/S3/S5/G5。注意 S3(Gini) 高不一定扣分 |
| R3 (结构清晰度) | 结合 S1/S5。S5≥0.7 + 标题层次清晰→高分 |
| R4 (文字质量) | 纯 LLM 判断，hallucination_risk=high。按语法、术语一致性、可读性分级 |

---

## 8. 优雅降级策略

| 场景 | 降级策略 | 影响 |
|------|---------|------|
| Semantic Scholar 不可用 | fallback 到 OpenAlex（或反之） | C5, C6(abstract 缺失增加), G4, T2, T5 数据质量下降 |
| 所有学术 API 不可用 | C5="unavailable"; T2/T5/G4="degraded" | 检索增强指标不可用，报告中标记 |
| LLM API 不可用 | 关键词提取 fallback 到 TF-IDF/RAKE；C6 标记 "unavailable" | C6 不可用时 V2 标记 "unable to evaluate" |
| Corrector 某个模型失败 | 用剩余模型（至少 2 个）计算中位数 | variance 精度下降，在 CorrectorOutput 中记录 failed_calls |
| Corrector 所有模型失败 | 跳过校正，使用原始 Agent 分数 | 所有维度的 source="original"，variance=null |

---

## 9. 配置外部化

```yaml
# config/main.yaml 新增/修改配置段

evidence:
  # C6 相关
  c6_batch_size: 10
  c6_model: "gpt-4o-mini"
  c6_max_concurrency: 5
  contradiction_threshold: 0.05

  # G4 相关
  foundational_top_k: 30
  foundational_match_threshold: 0.85

  # T 系列相关
  trend_query_count: 5
  trend_year_range: [2000, 2025]

  # S5 相关
  clustering_algorithm: "louvain"
  clustering_seed: 42

  # 降级配置
  api_timeout_seconds: 30
  fallback_order: ["semantic_scholar", "openalex", "crossref"]

aggregation:
  weights:
    V1_citation_existence: 1.2
    V2_citation_claim_alignment: 1.5
    V4_internal_consistency: 1.0
    E1_foundational_coverage: 1.3
    E2_classification_reasonableness: 1.0
    E3_technical_accuracy: 1.2
    E4_critical_analysis_depth: 1.3
    R1_timeliness: 1.0
    R2_information_balance: 0.8
    R3_structural_clarity: 0.8
    R4_writing_quality: 0.7

persistence:
  schema_version: "v3"
  incremental_save: true                # 步骤 JSON 仅保存增量
  save_tool_artifacts: true             # 工具层独立持久化
```

---

## 10. 注意事项（容易犯的错误）

1. **Corrector 不更新 agent_outputs。** 校正结果存在独立的 `corrector_output` 中，原始 Agent 输出保持不变。Aggregator 需要同时读取两者。

2. **save_analysis() 重命名后的向后兼容。** 旧版运行结果中 `save_analysis()` 保存的是图分析数据。如果需要读取旧数据，需要处理文件名差异。建议在 run.json 中标记 `schema_version: "v3"` 以区分。

3. **C6 的 abstract 缺失处理。** ref_metadata_cache 中部分 ref 可能没有 abstract。这些对应的 citation-sentence 对自动标记为 `insufficient`，在 C6 输出中报告 `missing_abstract_count`。

4. **Corrector 投票的 prompt 必须包含 rubric。** 不同维度的 rubric 不同，不能用同一个 prompt。corrector_vote.yaml 中的 `{rubric_text}` 占位符在运行时替换为对应维度的 rubric。

5. **加权聚合的 scale 转换。** 子维度是 1-5 分，总分是 0-10 分。乘以 2 转换。不要在子维度层面做 0-10 映射。

6. **C6 阈值短路与 VerifierAgent 的关系。** 当 C6.auto_fail=true（contradiction_rate ≥ 5%）时，V2 直接评 1 分，**跳过 VerifierAgent 对 V2 维度的判断**。当 C6.auto_fail=false 时，V2 交由 VerifierAgent 基于 C6 的 contradiction 列表做判断。这是 evidence_dispatch 层面的短路逻辑，与 Corrector 无关。

7. **第一层 LLM 辅助指标不做 Corrector 投票。** V2 虽然有 LLM 参与（VerifierAgent 审查 contradiction 列表），但其 `hallucination_risk=low`（因为核心判断依据是 C6 的确定性统计），因此 Corrector 不对 V2 做投票。同理，V1（基于 C5 阈值）、E1（基于 G4 阈值）、R1（基于 T5 阈值）也不投票。**Corrector 仅对 hallucination_risk=medium/high 的 7 个子维度投票：V4, E2, E3, E4, R2, R3, R4。**

7. **metric_index.json 在运行开始时生成。** 不要等到运行结束才写。这样即使运行中途失败，也能从 metric_index.json 了解运行的配置和预期数据流。