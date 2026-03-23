# SurveyMAE 中间缓存与结果持久化设计分析

> 本文档记录了 SurveyMAE 项目的中间缓存和结果持久化设计。

## 1. 设计架构概览

项目采用**分层缓存设计**，从内存到文件系统形成多级持久化体系：

```
┌─────────────────────────────────────────────────────────────┐
│                     Core Layer (内存)                        │
│  SurveyState (TypedDict) + ref_metadata_cache + tool_evidence │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    Graph Layer (内存+磁盘)                   │
│  ResultStore (全局单例) + _save_workflow_step() + MemorySaver │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                   Tools Layer (文件系统)                    │
│  ResultStore 文件系统持久化 + JSON/JSONL 格式             │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    Agent Layer (无持久化)                    │
│  返回状态更新，由 Graph 层包装持久化                         │
└─────────────────────────────────────────────────────────────┘
```

1. **工具层独立持久化**：extraction.json, validation.json, c6_alignment.json, analysis.json, graph_analysis.json, trend_baseline.json, key_papers.json
2. **步骤增量保存**：02_evidence_collection.json 不再包含完整 ref_metadata_cache
3. **run_summary.json**：轻量结果摘要，用于批量实验对比
4. **加权聚合**：根据 config/main.yaml 中的 weights 配置进行加权评分

---

## 2. 各层详细设计

### 2.1 Core Layer - 内存状态缓存

**核心文件**: `src/core/state.py`

#### SurveyState - 工作流主状态

```python
class SurveyState(TypedDict):
    # --- 核心缓存字段 ---
    ref_metadata_cache: Dict[str, dict]      # 引用元数据缓存
    tool_evidence: ToolEvidence              # 工具证据
    topic_keywords: List[str]                 # 主题关键词
    field_trend_baseline: Dict[str, Any]     # 领域趋势基线
    candidate_key_papers: List[dict]        # 候选关键论文

    # --- 评估数据 ---
    agent_outputs: Annotated[Dict[str, AgentOutput], dict_merge]
    corrector_output: Optional[CorrectorOutput]  # 校正输出

    # --- 控制流 ---
    current_round: int
    consensus_reached: bool
```

#### 新增类型

```python
class VarianceRecord(TypedDict):
    """多模型投票的方差信息"""
    models_used: List[str]
    scores: List[float]
    median: float
    std: float
    high_disagreement: bool

class CorrectorOutput(TypedDict):
    """校正器输出"""
    corrections: Dict[str, CorrectionRecord]
    skipped_dimensions: List[str]
    skip_reason: str
    total_model_calls: int
    failed_calls: int

class DimensionScore(TypedDict):
    """聚合后的维度分数"""
    dim_id: str
    final_score: float
    source: Literal["original", "corrected"]
    agent: str
    hallucination_risk: str
    variance: Optional[VarianceRecord]
    weight: float
```

---

### 2.2 Graph Layer - 工作流级缓存与持久化

**核心文件**: `src/graph/builder.py`

#### ResultStore 全局单例

```python
_result_store: Optional[ResultStore] = None

def _get_result_store(source_pdf_path: str = "") -> ResultStore:
    global _result_store
    if _result_store is None:
        pdf_hash = hashlib.md5(source_pdf_path.encode()).hexdigest()[:8]
        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{pdf_hash}"
        _result_store = ResultStore(base_dir="./output/runs", run_id=run_id)
    return _result_store
```

#### 步骤级自动持久化 - Wrapper 模式

```python
async def _wrap_evidence_collection(state: SurveyState) -> dict:
    input_state = dict(state)
    store = _get_result_store(state.get("source_pdf_path", ""))
    result = await run_evidence_collection(state, result_store=store)
    _save_workflow_step("02_evidence_collection", state, result, ...)
    return result
```

#### 增量保存

`_save_workflow_step` 函数对 02_evidence_collection 步骤做了特殊处理：

```python
# 引用 ref_metadata_cache 而不是包含完整数据
if step_name == "02_evidence_collection":
    if "ref_metadata_cache" in output_data:
        output_data["ref_metadata_cache"] = {
            "_ref": "see validation.json",
            "_note": "Full ref_metadata_cache stored in tool artifact"
        }
```

---

### 2.3 Tools Layer - 文件系统持久化

**核心文件**: `src/tools/result_store.py`

#### 持久化方法

| 方法 | 用途 | 状态 |
|------|------|------|
| `save_extraction()` | 保存引用提取结果 | ✅ |
| `save_validation()` | 保存验证结果 + ref_metadata_cache | ✅ |
| `save_c6_alignment()` | 保存 C6 对齐结果 | ✅ |
| `save_citation_analysis()` | 保存 T/S 系列指标 | ✅ |
| `save_graph_analysis()` | 保存 G 系列指标 | ✅ |
| `save_trend_baseline()` | 保存领域趋势基线 | ✅ |
| `save_key_papers()` | 保存候选关键论文 | ✅ |

---

### 2.4 Agent Layer - 无直接持久化

**核心文件**: `src/agents/base.py`

Agent 层通过返回状态更新，由 Graph 层 Wrapper 捕获并持久化。

```python
async def process(self, state: SurveyState) -> Dict[str, Any]:
    record = await self.evaluate(state)
    return {
        "evaluations": [record],
        "agent_outputs": {self.name: agent_output},
    }
```

---

## 3. 实际运行结果数据示例

### 3.1 目录结构

```
output/runs/{run_id}/papers/{paper_id}/
├── source.json                    # ResultStore.register_paper()
├── extraction.json              # CitationChecker
├── validation.json              # CitationChecker
├── c6_alignment.json           # CitationChecker.analyze_citation_sentence_alignment()
├── analysis.json                # CitationAnalyzer
├── graph_analysis.json          # CitationGraphAnalyzer
├── trend_baseline.json         # LiteratureSearch
├── key_papers.json             # FoundationalCoverageAnalyzer
├── run_summary.json            # ReportAgent
├── 01_parse_pdf.json          # workflow step
├── 02_evidence_collection.json # workflow step
├── 03_evidence_dispatch.json  # workflow step
├── 04_verifier.json           # workflow step
├── 04_expert.json             # workflow step
├── 04_reader.json             # workflow step
├── 04_corrector.json          # workflow step
└── 04_reporter.json           # workflow step
```

| 文件 | 来源 |
|------|------|
| extraction.json | CitationChecker - 引用和参考文献提取 |
| validation.json | CitationChecker - 引用验证和元数据获取 |
| c6_alignment.json | CitationChecker - C6 引用-句子对齐分析 |
| analysis.json | CitationAnalyzer - T/S 系列指标计算 |
| graph_analysis.json | CitationGraphAnalyzer - G 系列指标计算 |
| trend_baseline.json | LiteratureSearch - 领域趋势基线 |
| key_papers.json | FoundationalCoverageAnalyzer - 候选关键论文分析 |
| run_summary.json | ReportAgent - 轻量结果摘要 |

### 3.2 extraction.json

引用提取结果：

```json
{
  "citations": [
    {
      "marker": "[15]",
      "marker_raw": "[25, 15, 26]",
      "kind": "numeric",
      "sentence": "This question is important both scientifically and practically...",
      "page": 1,
      "ref_key": "ref_15",
      "section_title": "1 Introduction"
    }
  ],
  "references": [...]
}
```

### 3.3 validation.json

引用验证结果（包含 real_citation_edges）：

```json
{
  "paper_id": "40b1a0d0d47b",
  "validated_at": "2026-03-19T04:04:56Z",
  "sources": ["semantic_scholar"],
  "verify_limit": 50,
  "reference_validations": [
    {
      "key": "ref_1",
      "is_valid": true,
      "confidence": 1.0,
      "source": "semantic_scholar",
      "metadata": {
        "title": "Deep learning: a statistical viewpoint",
        "authors": ["P. Bartlett", "A. Montanari", "A. Rakhlin"],
        "year": "2021",
        "citation_count": 321,
        "reference_targets": [...]
      }
    }
  ],
  "real_citation_edges": [
    {"source": "ref_1", "target": "ref_3"},
    {"source": "ref_10", "target": "ref_16"}
  ],
  "real_citation_edge_stats": {
    "n_edges": 37,
    "n_sources": 36,
    "resolved_target_ratio": 0.02
  }
}
```

### 3.4 c6_alignment.json

C6 引用-句子对齐结果：

```json
{
  "metric_id": "C6",
  "llm_involved": true,
  "hallucination_risk": "low",
  "total_pairs": 76,
  "support": 0,
  "contradict": 0,
  "insufficient": 76,
  "contradiction_rate": 0.0,
  "auto_fail": false,
  "contradictions": [],
  "missing_abstract_count": 5,
  "status": "ok"
}
```

### 3.5 run_summary.json

轻量结果摘要：

```json
{
  "run_id": "20260319T065912Z_53317b7e",
  "source": "test_paper.pdf",
  "timestamp": "2026-03-19T07:20:36+00:00",
  "agent_scores": {
    "E1_foundational_coverage": 3,
    "E2_classification_reasonableness": 4,
    "E3_technical_accuracy": 4,
    "E4_critical_analysis_depth": 3,
    "R1_timeliness": 4,
    "R2_information_balance": 4,
    "R3_structural_clarity": 4,
    "R4_writing_quality": 4,
    "V1_citation_existence": 4,
    "V2_citation_supportiveness": 3,
    "V3_citation_accuracy": 4,
    "V4_internal_consistency": 4
  },
  "corrected_scores": {},
  "overall_score": 7.41,
  "grade": "C"
}
```

### 3.6 生成的评估报告

```
# SurveyMAE Evaluation Report

**Generated**: 2026-03-19 15:20:36

**Source**: test_paper.pdf

## Overall Score: 7.41/10

**Grade**: C

## Score Summary

| Dimension | Score | Source | Agent |
|-----------|-------|--------|-------|
| E1_foundational_coverage | 3.0/5 | original | expert |
| E2_classification_reasonableness | 4.0/5 | original | expert |
| ... |
| V1_citation_existence | 4.0/5 | original | verifier |
| V2_citation_supportiveness | 3.0/5 | original | verifier |

## Recommendations

**Areas Requiring Attention:**
- **E1_foundational_coverage** (Score: 3.0/5)
- **E4_critical_analysis_depth** (Score: 3.0/5)
- **V2_citation_supportiveness** (Score: 3.0/5)
```

---

## 4. 数据流与指标计算

### 4.1 C5 (metadata_verify_rate) 计算路径

**正确路径**：

1. `CitationChecker.extract_citations_with_context_from_pdf_async()` 执行验证
2. 验证结果保存在 `validation.json` 的 `reference_validations` 字段
3. `evidence_collection.py` 遍历 references，计算 verified 数量
4. 计算公式：`verified_count / total_refs`

```python
# evidence_collection.py
verified_count = 0
for r in references:
    validation = r.get("validation")
    if validation and validation.get("verified", False):
        verified_count += 1
metadata_verify_rate = verified_count / total_refs if total_refs > 0 else 0.0
```

### 4.2 V1 (citation_existence) 计算路径

V1 基于 C5 (metadata_verify_rate)：

- C5 >= 0.8 → V1 = 5
- C5 >= 0.6 → V1 = 4
- C5 >= 0.4 → V1 = 3
- C5 >= 0.2 → V1 = 2
- C5 < 0.2 → V1 = 1

### 4.3 C6 (citation_sentence_alignment) 计算路径

1. `CitationChecker.analyze_citation_sentence_alignment()` 使用 LLM 分析
2. 需要 citations (含 sentence) + references (含 abstract)
3. 结果保存在 `c6_alignment.json`

---

## 5. 总结

| 层次 | 缓存类型 | 介质 | 作用 | 状态 |
|------|----------|------|------|------|
| Core | SurveyState + TypedDict | 内存 | 工作流状态传递 | ✅ |
| Graph | ResultStore 单例 | 内存+磁盘 | 步骤自动持久化 | ✅ |
| Tools | ResultStore | 文件系统 | 工具结果独立持久化 | ✅ |
| Agent | 无 | - | 返回状态更新 | ✅ |

已实现完整的工具层独立持久化，包括：

- extraction.json
- validation.json
- c6_alignment.json
- analysis.json
- graph_analysis.json
- trend_baseline.json
- key_papers.json
- run_summary.json

---

## 6. 相关文件索引

| 文件 | 描述 |
|------|------|
| `src/core/state.py` | SurveyState 定义 |
| `src/graph/builder.py` | 工作流构建与 ResultStore 单例 |
| `src/graph/nodes/evidence_collection.py` | 证据收集节点 |
| `src/graph/nodes/aggregator.py` | 评分聚合逻辑 |
| `src/tools/result_store.py` | ResultStore 实现 |
| `src/tools/citation_checker.py` | 引用检查工具 |
| `src/tools/citation_graph_analysis.py` | 引用图分析工具 |
| `src/agents/base.py` | Agent 基类 |
| `src/agents/verifier.py` | VerifierAgent 实现 |
| `src/agents/corrector.py` | CorrectorAgent 实现 |
| `src/agents/reporter.py` | ReporterAgent 实现 |
| `config/main.yaml` | weights 配置 |
