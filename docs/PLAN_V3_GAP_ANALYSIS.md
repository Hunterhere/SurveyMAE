# Plan v3 与实现对比分析

> 本文档对比 Plan v3 设计文档与当前实现，分析未实现或不符合的部分。

---

## 已实现的功能

| 功能 | 状态 | 说明 |
|------|------|------|
| 工具层独立持久化 | ✅ | extraction.json, validation.json, c6_alignment.json, analysis.json, graph_analysis.json, trend_baseline.json, key_papers.json |
| run_summary.json | ✅ | 包含 agent_scores, corrected_scores, overall_score, grade, deterministic_metrics |
| 增量保存 | ✅ | 02_evidence_collection.json 不含完整 ref_metadata_cache |
| C6 批处理 | ✅ | 支持 batch_size, contradiction_threshold |
| C6 auto_fail 短路 | ✅ | contradiction_rate >= threshold 时 V2=1 |
| Corrector 纯校正 | ✅ | 只对高风险维度投票 |
| 加权聚合 | ✅ | 使用 config weights |
| metric_index | ✅ | 集成在 run.json 的 metrics_index 字段中 |
| 文件编号 | ✅ | 04_verifier/expert/reader, 05_corrector, 06_aggregator, 07_reporter |
| Aggregator 持久化 | ✅ | 输出 06_aggregated_scores.json |
| V3 维度删除 | ✅ | verifier.yaml 和 verifier.py 已移除 V3 |

---

## 未实现或不符合的功能

### 1. V2/C6 动态 hallucination_risk 问题 🔴 设计缺陷

**问题描述**

Plan v3 设计中，V2 的 hallucination_risk 需要动态变化：

| 场景 | C6 状态 | V2 来源 | V2 hallucination_risk | 期望 Corrector 行为 |
|------|---------|---------|----------------------|---------------------|
| A | auto_fail=true | 自动计算 (score=1) | `low` | **跳过投票** |
| B | auto_fail=false | VerifierAgent LLM 评判 | `medium` | **需要投票检查** |

**根本原因**

1. **V2 被硬编码在 LOW_RISK_DIMENSIONS**

   [corrector.py:41-46](src/agents/corrector.py#L41-L46):
   ```python
   LOW_RISK_DIMENSIONS = [
       "V1",  # Citation existence (based on C5 threshold)
       "V2",  # Citation-claim alignment (based on C6, hallucination_risk=low)
       "E1",  # Foundational coverage (based on G4 threshold)
       "R1",  # Timeliness (based on T5 threshold)
   ]
   ```
   V2 始终被标记为 low risk，无论 C6.auto_fail 状态如何。

2. **VerifierAgent 注入 V2 时不设置 hallucination_risk**

   [verifier.py:191-200](src/agents/verifier.py#L191-L200):
   ```python
   sub_scores_data["V2_citation_claim_alignment"] = {
       "score": v2_score,
       "llm_involved": False,
       "tool_evidence": {...},
       # 缺少 hallucination_risk 字段！
   }
   ```

3. **Corrector 默认 hallucination_risk 为 "medium"**

   [corrector.py:237](src/agents/corrector.py#L237):
   ```python
   risk = output["sub_scores"][sub_id].get("hallucination_risk", "medium")
   ```

4. **Corrector 投票逻辑基于 HIGH_RISK_DIMENSIONS 白名单**

   [corrector.py:238](src/agents/corrector.py#L238):
   ```python
   if risk in ["medium", "high"] and sub_id in HIGH_RISK_DIMENSIONS:
   ```
   即使 V2 被检测为 medium risk，也因为不在 HIGH_RISK_DIMENSIONS 白名单中而不投票。

**修复难点**

要正确实现此逻辑，需要：

1. **VerifierAgent** 在注入 V2 时，根据 C6.auto_fail 状态设置正确的 hallucination_risk：
   - C6.auto_fail=true → `hallucination_risk: "low"`（确定性计算，无需投票）
   - C6.auto_fail=false → `hallucination_risk: "medium"`（LLM 评判，需要投票）

2. **移除 V2 从 LOW_RISK_DIMENSIONS 硬编码列表**

3. **将 V2 加入 HIGH_RISK_DIMENSIONS**，或在运行时动态判断

当前架构的问题是：V2 的 hallucination_risk 在 VerifierAgent 注入时就已经固定，但 VerifierAgent 本身没有根据 C6 状态做条件判断的逻辑。

**Plan v3 相关设计**

> Plan v3 §2.6.4：Corrector 仅对 hallucination_risk=medium/high 的 7 个子维度投票：V4, E2, E3, E4, R2, R3, R4。

> Plan v3 §2.6.1：V2 虽然有 LLM 参与（VerifierAgent 审查 contradiction 列表），但其 hallucination_risk=low（因为核心判断依据是 C6 的确定性统计），因此 Corrector 不对 V2 做投票。

这里存在矛盾：Plan v3 一说 V2 hallucination_risk=low 不投票，一说当 C6.auto_fail=false 时需要 LLM 评判。实际实现需要区分这两种场景。

---

### 2. 确定性指标与 LLM 指标分离未完整实现

**问题**：Plan v3 要求 Aggregator 返回 deterministic_metrics 字段，但当前实现返回空字典。

**当前实现**

[aggregator.py:189](src/graph/nodes/aggregator.py#L189):
```python
return {
    "dimension_scores": dimension_scores,
    "deterministic_metrics": {},  # First-layer metrics stored separately
    "overall_score": round(overall_score, 2),
    "grade": grade,
    "total_weight": round(total_weight, 2),
}
```

**修复建议**：Reporter 的 `_extract_deterministic_metrics()` 方法已经正确提取了确定性指标并保存在 run_summary 中，但 aggregator.py 层面未完成此工作。

---

## 待确认的实现

| 功能 | 状态 | 说明 |
|------|------|------|
| Hallucination_risk 标记 | ⚠️ | VerifierAgent 注入 V2 时未设置 hallucination_risk |
| C6 输入 sources_file 映射 | ✅ | metrics_index 记录正确的数据流 |
| corrector_output 独立性 | ✅ | corrector_output 独立于 agent_outputs |

---

## 修复优先级

| 优先级 | 问题 | 修复工作量 | 状态 |
|--------|------|-----------|------|
| 高 | V2/C6 动态 hallucination_risk | 大（需架构修改） | 🔴 设计缺陷 |
| 低 | 确定性指标分离 | 小 | ⚠️ 部分实现 |
| - | 其他 | - | ✅ 已完成 |
