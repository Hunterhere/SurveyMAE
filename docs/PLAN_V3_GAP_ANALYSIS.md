# Plan v3 与实现对比分析

> 本文档对比 Plan v3 设计文档与当前实现，分析未实现或不符合的部分。

---

## 已实现的功能

| 功能 | 状态 | 说明 |
|------|------|------|
| 工具层独立持久化 | ✅ | extraction.json, validation.json, c6_alignment.json, analysis.json, graph_analysis.json, trend_baseline.json, key_papers.json |
| run_summary.json | ✅ | 包含 agent_scores, corrected_scores, overall_score, grade |
| 增量保存 | ✅ | 02_evidence_collection.json 不含完整 ref_metadata_cache |
| C6 批处理 | ✅ | 支持 batch_size, contradiction_threshold |
| C6 auto_fail 短路 | ✅ | contradiction_rate >= threshold 时 V2=1 |
| Corrector 纯校正 | ✅ | 只对高风险维度投票 |
| 加权聚合 | ✅ | 使用 config weights |

---

## 未实现或不符合的功能

### 1. V3 (citation_accuracy) 维度仍存在 ✅ 已修复

**问题**：Plan v3 要求将 V2（引用支持性）和 V3（引用准确性）合并到 C6，但当前 VerifierAgent 仍输出 V1-V4 四个子维度。

**修复内容**（2026-03-25）：
- `config/prompts/verifier.yaml`：移除 V3 from prompt and output format; V2 标注为 auto-computed from C6
- `src/agents/verifier.py`：
  - C6 读取路径修正：`evidence_report.get("C6")` → `tool_evidence.get("c6_alignment")`
  - V2 sub_score 注入：`evaluate()` 在返回前将计算好的 V2（基于 C6 contradiction_rate）注入 reasoning JSON
- `src/graph/nodes/evidence_dispatch.py`：`build_verifier_evidence()` C6 路径 `graph_analysis.C6` → `evidence.c6_alignment`

**修复后输出**：
```json
"V1_citation_existence": 4,   // LLM 评分
"V2_citation_claim_alignment": 3,  // 自动从 C6 contradiction_rate 计算
"V4_internal_consistency": 4  // LLM 评分
```

---

### 2. metric_index.json 未实现

**问题**：Plan v3 §3.4.3 要求生成 metric_index.json，记录指标索引、config 快照、数据流关系。

**Plan v3 要求**：
```json
{
  "run_id": "...",
  "config_snapshot": {...},
  "metrics": {
    "C3": { "computed_by": "...", "source_file": "...", "consumed_by": [...] },
    ...
  },
  "agent_dimensions": {...}
}
```

**当前状态**：未实现。

---

### 3. V2 不在高风险维度列表

**问题**：Plan v3 §2.6.4 要求 Corrector 对 V2（仅当 C6.auto_fail=false 时）和 V4 等 7 个高风险维度投票。

但当前代码中：
```python
HIGH_RISK_DIMENSIONS = [
    "V4", "E2", "E3", "E4", "R2", "R3", "R4"
]
```

缺少 V2。

**修复建议**：根据 C6.auto_fail 状态动态决定是否对 V2 投票。

---

### 4. 确定性指标与 LLM 指标分离未完整实现

**问题**：Plan v3 要求 Aggregator 分别报告 deterministic_metrics 和 llm_score。

**当前实现**：aggregator.py 只返回 dimension_scores，未区分确定性指标（V1, E1, R1 基于阈值）和 LLM 指标。

**修复建议**：在 AggregatedScores 中添加 deterministic_metrics 字段。

---

### 5. evidence_dispatch 未实现 C6.auto_fail 预填 V2=1

**问题**：Plan v3 §2.6.1 要求当 C6.auto_fail=true 时，VerifierAgent 的 V2 维度预填 1 分，不再调用 LLM。

**当前实现**：VerifierAgent 仍会调用 LLM 评估 V2。

**修复建议**：在 evidence_dispatch 或 VerifierAgent 入口检查 C6.auto_fail，若为 true，直接设置 V2=1。

---

### 6. Aggregator 未写入 06_aggregated_scores.json

**问题**：Plan v3 §3.1 要求 Aggregator 步骤输出到 06_aggregated_scores.json。

**当前实现**：AggregatedScores 只存在于 Reporter 的 run_summary 中。

**修复建议**：在 aggregator.py 或 builder.py 中添加持久化调用。

---

## 待确认的实现

| 功能 | 状态 | 说明 |
|------|------|------|
| Hallucination_risk 标记 | ⚠️ | 需要验证 AgentSubScore 是否都有 hallucination_risk 字段 |
| C6 输入 sources_file 映射 | ⚠️ | 需要验证 metric_index 是否记录正确的数据流 |
| corrector_output 独立性 | ⚠️ | 需要验证 corrector_output 是否独立于 agent_outputs |

---

## 修复优先级

| 优先级 | 问题 | 修复工作量 |
|--------|------|-----------|
| 高 | V3 维度仍存在 | 小 |
| 高 | metric_index.json 未实现 | 中 |
| 中 | V2 投票逻辑 | 小 |
| 中 | 确定性/LLM 指标分离 | 小 |
| 低 | Aggregator 持久化 | 小 |
| 低 | C6.auto_fail 预填 | 小 |
