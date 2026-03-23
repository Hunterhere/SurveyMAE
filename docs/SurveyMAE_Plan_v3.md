# SurveyMAE 项目完善方案：评测指标形式化与后续任务规划（v3）

## 一、核心创新定位：证据化评测（Evidence-Grounded Evaluation）

### 1.1 设计哲学：后验视角评测（Posterior-Perspective Evaluation）

贯穿本项目全部设计的核心理念是**后验视角**：评测系统相比综述作者（或生成系统），天然拥有一个认知优势——综述已经写完，评测系统可以站在更高的信息位置上审视它。这意味着：

- **评测系统不应只做"内省"。** 仅阅读综述文本并打分（如纯LLM-as-Judge）是放弃了后验优势。系统应该主动通过检索扩展、元数据交叉验证、引用网络分析等手段，获取比综述作者写作时更全面的视野。
- **每个指标设计都应问：评测系统在这个维度上能否比综述作者/生成系统"看得更远"？** 例如，综述作者可能因模型知识截止或检索策略缺陷而遗漏核心文献，但评测系统可以通过学术API检索该领域高被引论文来发现这些遗漏（G4指标）。综述作者可能不知道自己的引用时序分布是否偏离了领域实际趋势，但评测系统可以检索领域发表量数据来对比（T5指标）。
- **如果某个评测维度无法利用后验优势，其可信度就需要额外审慎。** 例如"技术准确性"（E3）和"批判性分析深度"（E4）目前只能依赖LLM的领域理解来判断，后验优势有限，因此这些维度的`hallucination_risk`应标记为较高，并通过多模型采样严格控制波动。

此理念应在指标设计、工具实现、实验设计和论文叙事中保持一致。

### 1.2 与现有工作的差异化

现有综述评测工作可以沿两个轴分类：**指标来源**（客观计算 vs LLM判断）和**证据追溯性**（评分是否可追溯到具体证据）。

| 系统 | 客观指标 | LLM判断 | 证据追溯 | 鲁棒性机制 |
|------|---------|---------|---------|-----------|
| SurGE | 覆盖率/引用准确/结构指标 | 内容质量打分 | 两层分离，未绑定 | 元评测校验 |
| SurveyEval | 无 | 全维度LLM打分+人类参照 | 弱（依赖LLM自述理由） | 无 |
| SurveyBench | 引用/提纲匹配 | 内容质量win-rate | 中等（quiz驱动） | 无 |
| Tang et al. | NLI事实一致性 | 部分维度 | 中等（NLI可追溯） | 无 |
| **SurveyMAE（本项目）** | **工具产出的结构化指标 + 检索增强的后验分析** | **基于证据的Agent判断** | **强：每条评分绑定工具证据 + 指标元数据标记LLM参与度** | **多模型投票校正 + 波动范围报告** |

SurveyMAE的核心差异是：**评测不是LLM凭空打分，也不是客观指标与主观判断简单拼接，而是确定性工具先产出结构化证据，Agent基于证据做有依据的判断，每条评分都可追溯到具体的数据支撑。** 评测系统的认知优势来自**后验视角**——综述已经写好，系统可以通过检索扩展获取比综述本身更丰富的信息来判断其质量。所有涉及LLM参与的指标均标记参与方式，并通过多厂商多采样策略报告波动范围，确保可信度透明。

### 1.3 技术叙事的一句话总结

> SurveyMAE提出"证据化评测"范式：将学术综述的质量评估分解为**可计算证据层**（引用图分析、检索增强的时序/覆盖分析、结构-聚类对齐等确定性工具输出）和**可解释判断层**（多角色Agent基于证据的rubric化评分），每个指标携带LLM参与度标记与波动范围，通过对高幻觉风险维度的多模型投票校正提升评分鲁棒性，并以结构化JSON协议贯穿全流程实现评分可追溯。

---

## 二、评测指标体系的形式化定义

### 2.1 总体架构：三层评测栈

```
┌─────────────────────────────────────────────────────────┐
│  第三层：综合诊断（Aggregator + Reporter）               │
│  输入：校正后的评分 + 确定性指标                         │
│  输出：加权总分 + 诊断报告 + run_summary.json            │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────┐
│  第二层：多角色Agent判断 + 多模型投票校正                │
│  VerifierAgent / ExpertAgent / ReaderAgent               │
│  → Corrector对高幻觉风险子维度做多模型投票（不产新维度） │
│  每个子维度携带 hallucination_risk 标记                   │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────┐
│  第一层：工具证据层（含检索增强+LLM辅助预处理）         │
│  CitationChecker → CitationAnalyzer → CitationGraph      │
│  → LiteratureSearch（后验扩展检索）                      │
│  输出：结构化统计数据（JSON）+ 独立持久化文件             │
└─────────────────────────────────────────────────────────┘
```

### 2.2 预处理数据流与复用规范

evidence_collection阶段的多个步骤共享预处理结果，避免重复计算和API调用。数据复用关系如下：

```
[parse_pdf]
  │
  ├─→ parsed_content (全文文本)     ─→ 所有Agent共用
  ├─→ section_headings (章节标题)   ─→ S系列 + 关键词提取
  └─→ citations + references        ─→ CitationChecker入口
        │
[CitationChecker.validate]
  │  调用Semantic Scholar/OpenAlex验证每篇参考文献
  │
  ├─→ validation_results (C3, C5)
  ├─→ ref_metadata_cache ──────────┐  每篇ref的完整元数据：
  │   (标题/作者/年份/被引次数/     │  标题、DOI、年份、被引次数、
  │    引用列表/venue/abstract等)   │  引用列表、venue、abstract
  │                                │
  │   ┌────────────────────────────┘
  │   │  ★ 以下步骤全部复用ref_metadata_cache，不再重复请求API
  │   │
  │   ├─→ [C6: citation_sentence_alignment] (LLM辅助，low risk，批处理)
  │   │     输入：citations中的sentence + ref_metadata_cache中的abstract
  │   │     批处理：每次prompt构造batch_size个对（默认10），并发调用
  │   │     输出：逐条support/contradict/insufficient + contradiction_rate
  │   │     ★ 若contradiction_rate ≥ threshold(5%)，V2短路为1分
  │   │
  │   ├─→ CitationAnalyzer.temporal  ─→ T1, T3, T4 (直接从cache中year字段计算)
  │   ├─→ CitationGraphAnalysis     ─→ G1-G3, G5, G6 (从cache中引用列表构建边)
  │   └─→ G4.external_citation_count ─→ suspicious_centrality (从cache中被引次数)
  │
[关键词提取] (LLM辅助，llm_involved=true, hallucination_risk=low)
  │  输入：标题 + 摘要 + section_headings + ref_metadata_cache中的高频venue/keyword
  │  输出：topic_keywords (3-5组检索用关键词)
  │  ★ 此步骤只执行一次，结果同时供T2/T5和G4使用
  │
  ├─→ [field_trend_baseline检索] ─→ T2, T5
  │     多组query检索各年份发表量，取均值
  │
  └─→ [candidate_key_papers检索] ─→ G4
        多组query检索高被引论文top-K
        LLM辅助清洗（去除显著无关文献）
        与ref_metadata_cache做匹配计算覆盖率
```

**复用原则：** ref_metadata_cache是整个evidence_collection阶段的核心共享数据结构。CitationChecker在validate阶段获取的元数据应完整缓存（特别是abstract字段，供C6使用），后续所有工具直接读取cache而非重新请求API。关键词提取也只执行一次，结果在field_trend_baseline检索和candidate_key_papers检索之间共享。

### 2.3 第一层LLM辅助使用规范

第一层指标以确定性计算为主，但部分预处理步骤可使用LLM辅助。与第二层Agent的评判性使用不同，第一层LLM仅承担**结构化信息提取和分类**任务，幻觉风险低。具体规范：

| 使用场景 | LLM任务 | hallucination_risk | 说明 |
|---------|---------|:---:|------|
| 关键词提取 | 从标题/摘要/章节标题中提取领域关键词，生成3-5组检索query | low | LLM擅长的NLU任务，给定明确输入和输出格式，几乎不会出错 |
| Query重写 | 将提取的关键词组合重写为适合学术API的检索query | low | 格式转换任务，无需领域判断 |
| 候选列表清洗 | 对G4检索返回的top-K论文，判断是否与综述主题相关 | low | 给定论文标题/摘要和综述主题，做二分类判断，上下文充分，准确率高 |
| 引用-断言对齐判断 (C6) | 对每条citation-sentence对，判断sentence断言与引用abstract的关系 | low | 三分类任务（支持/反对/信息不足），输入为一个sentence和一个abstract，上下文完整且短小。采用批处理（每次prompt构造batch_size个对），使用轻量模型，支持并发 |

这些LLM使用在指标元数据中标记为`llm_involved: true, hallucination_risk: low`，与第二层的`hallucination_risk: medium/high`做明确区分。低风险LLM辅助不强制要求多模型采样（单模型即可），但可选择性地报告波动。

### 2.4 指标元数据规范

每个指标必须携带以下元数据，标明LLM是否参与及波动控制策略：

```json
{
  "metric_id": "V2",
  "metric_name": "citation_supportiveness",
  "llm_involved": true,
  "llm_role": "判断引用-断言对是否语义匹配",
  "hallucination_risk": "medium",
  "variance_strategy": {
    "method": "multi_model_sampling",
    "models_used": ["gpt-4o", "claude-sonnet-4-20250514", "deepseek-chat"],
    "samples_per_model": 1,
    "aggregation": "median"
  },
  "reported_variance": {
    "score_range": [2.5, 3.5],
    "std": 0.4,
    "inter_model_agreement": 0.78
  }
}
```

对于 `llm_involved: false` 的指标，标记 `confidence: 1.0`，不报告波动。
对于 `llm_involved: true` 的指标，必须报告波动范围，且在最终报告中区分展示。

此设计为消融实验提供天然框架：可直接对比"仅确定性指标"vs"确定性+LLM指标"的评测效果，以及"单模型"vs"多模型采样"的稳定性差异。

### 2.5 第一层：工具产出的可计算指标（含LLM辅助预处理）

这些指标由工具计算产出，核心计算逻辑确定性可复现。部分指标引入学术API检索获取外部参照数据，以及LLM辅助的低风险预处理（关键词提取、query重写、候选清洗，见§2.3规范）。所有LLM辅助步骤在指标元数据中标记为`llm_involved: true, hallucination_risk: low`。

#### 2.5.1 引用完整性指标（CitationChecker产出）

| 指标ID | 指标名 | llm_involved | hallucination_risk | 计算方式 | 含义 |
|--------|--------|:---:|:---:|---------|------|
| C3 | orphan_ref_rate | false | — | 未被正文引用的参考文献数 / 总参考文献数 | 是否存在"挂名引用"——列在参考文献中但正文未实际引用 |
| C5 | metadata_verify_rate | false | — | 通过外部学术API验证存在的参考文献比例 | 文献真实存在的可信度，检测虚假/杜撰引用 |
| C6 | citation_sentence_alignment | true | low | 对每条引用-句子对，LLM判断句子断言与引用abstract的关系（支持/反对/信息不足），输出 contradiction_rate | 综述对所引文献的理解是否正确。合并了原V2（引用支持性）和V3（引用准确性），下沉到工具层逐条产出结构化证据 |

**C6实现细节：**

C6利用extraction阶段已定位的citation-sentence对和validation阶段已获取的ref abstract（均来自ref_metadata_cache），仅需额外的LLM分类调用。执行顺序放在引用元数据检索和validation完成之后。

**批处理机制：** 为控制成本和延迟，C6采用批处理方式调用LLM——每次prompt中构造`batch_size`个sentence+abstract对（默认10，可在config中调整），LLM对每对输出`support`/`contradict`/`insufficient`三分类。使用轻量模型（如gpt-4o-mini）即可，支持并发批处理。

**阈值短路机制：** 当`contradiction_rate ≥ contradiction_threshold`（默认5%，可配置）时，该维度直接判定为严重不合格（V2评分=1），不再调用VerifierAgent做进一步分析，以减少不必要的Agent调用。仅当`contradiction_rate < contradiction_threshold`时，才将完整的contradiction列表交由VerifierAgent逐条审查。

**输出结构：**
```json
{
  "metric_id": "C6",
  "llm_involved": true,
  "hallucination_risk": "low",
  "total_pairs": 312,
  "support": 245,
  "contradict": 12,
  "insufficient": 55,
  "contradiction_rate": 0.038,
  "auto_fail": false,
  "contradictions": [
    {
      "citation": "[68]",
      "sentence": "MolReGPT leverages RAG to enhance...",
      "ref_abstract": "...",
      "llm_judgment": "contradict",
      "note": "Abstract describes molecule-caption translation, not RAG enhancement"
    }
  ]
}
```

**内部质量指标（不纳入评测输出，用于系统自检）：**
- C1 (ref_parse_rate)：衡量PDF解析鲁棒性，非综述质量指标
- C2 (citation_ref_match_rate) / C4 (unresolved_citation_rate)：在规范LaTeX编译文献中默认通过，无区分度

#### 2.5.2 时序分布指标（CitationAnalyzer + LiteratureSearch联合产出）

**设计原则：** CS/AI领域综述的特点是文献集中在近3-5年是正常的，且可能存在某年论文数量激增（如2023年RAG方向的爆发）。因此不应简单惩罚时间集中度，而应检测**综述的引用时序分布是否与该领域的实际发表趋势相匹配**，以及**是否回溯到了足够早期的奠基性工作**。

**检索增强机制：** 使用LLM从被评测综述中提取关键词并重写为检索query（见§2.3 LLM辅助规范），通过Semantic Scholar/OpenAlex API分别检索各年份论文数量分布，取多次查询均值以降低单次偏差，作为**领域发表趋势基线（field_trend_baseline）**。关键词提取结果与G4共享（见§2.2 预处理数据流）。

| 指标ID | 指标名 | llm_involved | hallucination_risk | 计算方式 | 含义 |
|--------|--------|:---:|:---:|---------|------|
| T1 | year_span | false | — | max(引用年份) - min(引用年份) | 文献时间跨度，验证是否回溯到足够早期 |
| T2 | foundational_retrieval_gap | true | low | LLM辅助提取关键词→学术API检索该领域最早高被引论文年份→与综述最早引用年份做差 | 是否覆盖了领域起源阶段的奠基性工作。差值越大，说明可能遗漏早期核心文献 |
| T3 | peak_year_ratio | false | — | 近3年引用占比（描述性统计，提供给Agent参考） | 近期文献集中度。在CS/AI中此值高是正常的，需结合T5判断合理性 |
| T4 | temporal_continuity | false | — | 计算引用年份序列中连续无引用的最长年份gap | 是否存在时间断层。在快速迭代领域中，连续多年（如≥3年）无引用是可疑的 |
| T5 | trend_alignment | true | low | LLM辅助提取关键词→学术API检索各年份发表量→计算综述引用分布与field_trend_baseline的皮尔逊相关 | 引用时序分布与领域实际发表趋势的吻合度 |

**工具输出：** 除上述指标数值外，还输出完整的year_distribution（各年份引用数）、field_trend_baseline（各年份领域发表量）、以及两者的对比图数据，供Agent直接参照。

#### 2.5.3 结构分布指标（CitationAnalyzer产出）

| 指标ID | 指标名 | llm_involved | hallucination_risk | 计算方式 | 含义 |
|--------|--------|:---:|:---:|---------|------|
| S1 | section_count | false | — | 章节总数 | 结构复杂度 |
| S2 | citation_density | false | — | 引用总数 / 段落总数 | 平均引用密度 |
| S3 | citation_gini | false | — | 各章节引用数的Gini系数 | 引用分布不均度（描述性统计，Gini高不一定是问题——重点章节引用密集是合理的，交由Agent结合结构语义判断） |
| S4 | zero_citation_section_rate | false | — | 无引用章节数 / 总章节数 | 无证据支撑的章节比例 |
| S5 | section_cluster_alignment | false | — | 引用图聚类（G5产出）与章节划分之间的归一化互信息（NMI）或调整兰德系数（ARI） | 章节组织与文献结构的吻合度。高NMI说明各章节确实在有组织地归类不同子主题的文献（如test_survey2.pdf中Section 2按Retrieval/Generation/Augmentation划分）；低NMI可能说明章节组织与文献内在关联不匹配 |

**S5计算细节：** 对每篇参考文献标记两个标签——(a) 它主要出现在哪个章节（按引用频次归属），(b) 它属于引用图的哪个聚类。然后计算两组标签的NMI。此指标结合G5（聚类数）共同描述R2（信息分布均衡性）和R3（结构清晰度）维度。

#### 2.5.4 引用图结构指标（CitationGraphAnalysis产出）

| 指标ID | 指标名 | llm_involved | hallucination_risk | 计算方式 | 含义 |
|--------|--------|:---:|:---:|---------|------|
| G1 | graph_density | false | — | 实际边数 / 可能最大边数 | 文献间关联紧密度 |
| G2 | connected_component_count | false | — | 连通分量数 | 主题碎片化程度（1=完全连通） |
| G3 | max_component_ratio | false | — | 最大连通分量节点数 / 总节点数 | 主体文献的聚合度 |
| G4 | foundational_coverage_rate | true | low | LLM辅助关键词提取+query重写→学术API检索高被引论文top-K→LLM辅助清洗→匹配计算 | 核心文献覆盖度（后验评测的核心体现） |
| G5 | cluster_count | false | — | 引用图社区/聚类数 | 子主题覆盖的多样性 |
| G6 | isolated_node_ratio | false | — | 孤立节点数 / 总节点数 | 游离文献比例 |

**G4实现细节（检索增强的后验核心文献覆盖分析）：**

G4集中体现"后验视角评测"理念——评测系统利用自身作为后来者的信息优势，通过检索扩展获取比综述本身更丰富的参照来判断覆盖质量。

1. **提取综述主题关键词（LLM辅助，与T2/T5共享）：** 见§2.2预处理数据流，此步骤只执行一次。
2. **检索领域高被引论文：** 用topic_keywords通过Semantic Scholar/OpenAlex API，按被引次数排序，获取top-K（如top-30）高被引论文。多组query取并集+去重。
3. **候选列表清洗（LLM辅助）：** 对检索返回的候选论文，LLM基于标题/摘要判断是否与综述主题相关，去除显著无关结果（如同名但不同领域的论文）。此为低幻觉风险的二分类任务。
4. **匹配计算：** 将清洗后的候选核心文献集与综述参考文献列表做匹配（基于DOI/标题模糊匹配），计算覆盖率。匹配所需的参考文献元数据直接从ref_metadata_cache读取（见§2.2），无需额外API调用。
5. **辅助输出：**
   - `missing_key_papers`：应引但未引的高被引论文列表（供ExpertAgent参考）
   - `suspicious_centrality`：综述引用图中PageRank排名高但外部被引量低的论文（被引量从ref_metadata_cache读取）
   - 每篇候选核心文献的外部被引量、年份、venue信息

### 2.6 第二层：Agent判断维度与Rubric

每个Agent的评估被分解为3-4个子维度，每个子维度有明确的1-5分rubric。Agent必须输出结构化JSON而非自由文本。所有Agent子维度均为 `llm_involved: true`，必须通过多模型采样报告波动范围。

#### 2.6.1 VerifierAgent（事实性验证）

**输入证据：** C3, C5, C6验证结果、missing_key_papers列表

**阈值短路：** 当C6的`contradiction_rate ≥ contradiction_threshold`（默认5%）时，V2直接判定为1分（严重不合格），不调用VerifierAgent做V2维度的进一步分析。VerifierAgent仅在contradiction_rate < threshold时被调用审查V2，始终被调用审查V1和V4。

| 子维度 | llm_involved | 描述 | 依赖的工具证据 | LLM判断职责 |
|--------|:---:|------|---------------|------------|
| V1: 引用存在性 | true | 参考文献是否真实存在 | C5 (metadata_verify_rate) + 未验证文献列表 | 对工具未能验证的文献做最终判定（如workshop论文/预印本可能未被索引） |
| V2: 引用-断言对齐 | true | 综述对所引文献的理解是否正确 | C6 (citation_sentence_alignment) 的contradiction列表 | 审查每条contradiction是否确实是理解错误（排除因abstract信息不足导致的假阳性），给出典型错误示例和改进建议。**当C6.auto_fail=true时跳过此步，直接评1分** |
| V4: 内部一致性 | true | 综述内部是否存在自相矛盾 | 全文parsed_content | 检测前后矛盾的论断 |

**V2 Rubric（引用-断言对齐）：**
- 5分：contradiction_rate < 1%，LLM确认无实质性理解错误
- 4分：contradiction_rate 1%-2%，少量contradiction经审查为假阳性或轻微问题
- 3分：contradiction_rate 2%-3%，存在个别确实的理解错误
- 2分：contradiction_rate 3%-5%，多处理解错误
- 1分：contradiction_rate ≥ 5%（由C6阈值短路自动判定），或经Agent审查确认大量严重错误

#### 2.6.2 ExpertAgent（学术深度）

**输入证据：** G1-G6图指标、G4的missing_key_papers和suspicious_centrality列表、centrality排名

| 子维度 | llm_involved | 描述 | 依赖的工具证据 | LLM判断职责 |
|--------|:---:|------|---------------|------------|
| E1: 核心文献覆盖 | true | 是否包含该领域的奠基性与代表性工作 | G4 (foundational_coverage_rate) + missing_key_papers列表 | 基于工具检索到的缺失文献列表，判断哪些遗漏是严重的（如开创性工作缺失 vs 边缘工作缺失） |
| E2: 方法分类合理性 | true | 对现有方法的分类是否合理、无遗漏 | G5 (cluster_count) + S5 (section_cluster_alignment) | 评估分类逻辑与学术共识的吻合度 |
| E3: 技术准确性 | true | 对各方法的技术描述是否准确 | parsed_content + 参考文献元数据 | 检测技术细节错误 |
| E4: 批判性分析深度 | true | 是否有比较、趋势归纳、局限指出 | parsed_content | 评估"综"与"述"的平衡性 |

**E1 Rubric（核心文献覆盖）：**
- 5分：G4 ≥ 0.8，且LLM确认missing_key_papers中无开创性或里程碑工作
- 4分：G4 ≥ 0.6，缺失的高被引论文主要为次要贡献或近期热门但非核心
- 3分：G4 ≥ 0.4，存在1-2篇公认核心文献缺失
- 2分：G4 ≥ 0.2，缺失多篇核心文献
- 1分：G4 < 0.2，文献选择严重偏离领域主流

**E4 Rubric（批判性分析深度）：**
- 5分：有系统的方法比较（如对比表）、清晰的发展脉络、对各方法局限的具体分析、开放问题讨论
- 4分：有方法比较和趋势归纳，但局限分析不够具体
- 3分：以罗列为主，有少量比较和评论，但缺乏深度分析
- 2分：几乎纯罗列，极少比较或评论
- 1分：完全是论文摘要堆砌，无任何综合分析

#### 2.6.3 ReaderAgent（可读性与信息量）

**输入证据：** T1-T5时序统计（含field_trend_baseline数据）、S1-S5结构统计

| 子维度 | llm_involved | 描述 | 依赖的工具证据 | LLM判断职责 |
|--------|:---:|------|---------------|------------|
| R1: 时效性 | true | 是否兼顾领域起源与前沿发展 | T1, T2, T3, T4, T5 + field_trend_baseline + year_distribution | 结合工具提供的领域趋势基线数据，判断时序分布的合理性。如T5相关性高说明引用节奏与领域同步，T4断层可能指向遗漏了某阶段的重要发展 |
| R2: 信息分布均衡性 | true | 各章节的信息密度是否合理 | S2, S3, S5, G5 | 结合section_cluster_alignment判断：信息分布不均是否反映了合理的重点安排（而非结构缺陷） |
| R3: 结构清晰度 | true | 层级结构是否合理、阅读路径是否清晰 | S1, S5 + 章节标题列表 | 评估结构组织的逻辑性，S5高说明章节划分与文献内在关联一致 |
| R4: 文字质量 | true | 语言流畅性、术语使用一致性 | parsed_content | 评估语言和表达质量 |

**R1 Rubric（时效性）：**
- 5分：T5 ≥ 0.7（与领域趋势高度吻合），T2 ≤ 2年（几乎追溯到领域起源），T4 ≤ 1年（无明显断层）
- 4分：T5 ≥ 0.5，T4 ≤ 2年，LLM确认整体时间覆盖合理
- 3分：T5 ≥ 0.3，存在轻微时间断层或趋势偏移
- 2分：T5 < 0.3，明显偏离领域发展趋势，或T4 ≥ 3年存在显著断层
- 1分：引用几乎集中在1-2年，与领域趋势严重脱节，或完全缺失早期奠基性工作

#### 2.6.4 CorrectorAgent（多模型投票校正）→ 方案A

**v3变更：CorrectorAgent不再产出独立评分维度（删除原C1/C2/C3），回归为纯校正角色。**

**职责：** 对V/E/R三个Agent输出中`hallucination_risk: medium/high`的子维度，使用多厂商模型重新打分，取中位数作为校正分，计算波动范围。低风险维度（如基于确定性指标阈值的V1/E1/R1）不做投票，直接保留原分。

**输入：** V/E/R三个Agent的完整输出JSON + 对应的工具证据（Evidence Report）

**处理流程：**

1. **识别需要投票的子维度：** 筛选`hallucination_risk: medium/high`的子维度。具体为：
   - V2（引用-断言对齐，仅当C6.auto_fail=false时）、V4（内部一致性）
   - E2（方法分类合理性）、E3（技术准确性）、E4（批判性分析深度）
   - R2（信息分布均衡性）、R3（结构清晰度）、R4（文字质量）

2. **多模型重新打分：** 对每个需要投票的子维度，将该维度的rubric + 对应的工具证据 + 原始Agent的reasoning，发送给3个不同厂商模型独立打分。

3. **聚合与异常检测：**
   - 取3个模型分数的中位数作为校正后分数
   - 计算score_range和std，填入指标元数据的reported_variance
   - 若模型间评分差异 > 2分，标记为`high_disagreement`，建议人工审查

4. **直接保留的子维度（不做投票）：**
   - V1（基于C5阈值，hallucination_risk: low）
   - E1（基于G4阈值，hallucination_risk: low）
   - R1（基于T5阈值，hallucination_risk: low）
   - 这些维度的variance标记为`single_model`

**输出：** 不产出新维度，只对已有子维度附加variance信息并可能修正分数。

```json
{
  "agent_name": "corrector",
  "corrections": {
    "V4_internal_consistency": {
      "original_score": 5,
      "corrected_score": 4,
      "variance": {
        "models_used": ["gpt-4o", "claude-sonnet-4-20250514", "deepseek-chat"],
        "scores": [4, 5, 4],
        "median": 4,
        "std": 0.47,
        "high_disagreement": false
      }
    },
    "E3_technical_accuracy": {
      "original_score": 5,
      "corrected_score": 3,
      "variance": {
        "models_used": ["gpt-4o", "claude-sonnet-4-20250514", "deepseek-chat"],
        "scores": [3, 5, 2],
        "median": 3,
        "std": 1.25,
        "high_disagreement": true
      }
    }
  },
  "skipped_dimensions": ["V1", "E1", "R1"],
  "skip_reason": "low hallucination_risk, threshold-based scoring"
}

### 2.7 Agent输出的结构化JSON Schema

以VerifierAgent为例（注意：variance字段由CorrectorAgent在后续步骤中填充，Agent自身不做多模型投票）：

```json
{
  "agent_name": "verifier",
  "dimension": "factuality",
  "sub_scores": {
    "V1_citation_existence": {
      "score": 4,
      "llm_involved": true,
      "hallucination_risk": "low",
      "tool_evidence": {
        "metric": "metadata_verify_rate",
        "value": 0.85,
        "detail": "34/40 references verified via Semantic Scholar"
      },
      "llm_reasoning": "85% of references were externally verified. The 6 unverified entries appear to be workshop papers or preprints not yet indexed.",
      "flagged_items": ["[23] - title not found in any source", "[37] - year mismatch"],
      "variance": null
    },
    "V2_citation_claim_alignment": {
      "score": 4,
      "auto_failed": false,
      "llm_involved": true,
      "hallucination_risk": "low",
      "tool_evidence": {
        "metric": "citation_sentence_alignment",
        "total_pairs": 312,
        "support": 245,
        "contradict": 5,
        "insufficient": 62,
        "contradiction_rate": 0.016
      },
      "llm_reasoning": "C6 reports 1.6% contradiction rate...",
      "flagged_items": [...],
      "variance": null
    },
    "V4_internal_consistency": {
      "score": 5,
      "llm_involved": true,
      "hallucination_risk": "high",
      "tool_evidence": {},
      "llm_reasoning": "No internal contradictions found...",
      "flagged_items": [],
      "variance": null
    }
  },
  "overall_score": 4.3,
  "confidence": 0.85,
  "evidence_summary": "..."
}
```

**注意：** 每个子维度的`variance`字段初始为null，由CorrectorAgent在后续步骤中对`hallucination_risk: medium/high`的子维度执行多模型投票后填充。`hallucination_risk: low`的子维度保持null。
```

### 2.8 工具输出→Agent输入的映射协议（Evidence Report）

**设计原则：** 考虑到当前旗舰模型的上下文窗口（128K+），不过度压缩工具输出。Evidence Report包含三部分：

**(1) 指标定义与计算方法说明（固定模板）**

每个指标附带一段简短的定义文本，让Agent理解数字含义。例如：
> "T5 (trend_alignment) = 综述引用年份分布与该领域实际发表趋势的皮尔逊相关系数。该趋势基线通过对Semantic Scholar/OpenAlex的多组关键词查询取均值获得。T5 ≥ 0.7 表示高度吻合，T5 < 0.3 表示严重偏离。"

**(2) 完整指标数值与关键数据（不压缩）**

包括所有指标的数值、year_distribution完整表、field_trend_baseline完整表、missing_key_papers列表、suspicious_centrality列表、chapter-cluster对应矩阵等。

**(3) 异常标记与重点提示**

工具自动标记需要Agent重点关注的项目，例如：
- "⚠ C5仅0.60，6篇未验证文献需要审查"
- "⚠ T4=4年，2018-2021年间无引用，可能遗漏该阶段发展"
- "⚠ G4=0.45，missing_key_papers中包含3篇被引>1000的论文"

**Agent分发映射：**
```
VerifierAgent  ← C3, C5完整数据 + C6统计结果及contradiction列表 + 指标定义
                ★ 若C6.auto_fail=true，V2维度跳过Agent直接评1分
ExpertAgent    ← G1-G6完整数据 + missing_key_papers + suspicious_centrality + 指标定义
ReaderAgent    ← T1-T5完整数据 + field_trend_baseline + S1-S5完整数据 + 指标定义
CorrectorAgent ← V/E/R三个Agent的输出JSON + 对应的工具证据
                ★ 仅对hallucination_risk: medium/high的子维度做多模型投票
                ★ 不产出新维度，只附加variance并可能修正分数
```

---

## 三、Agent Workflow重构

### 3.1 重构后的Workflow

```
PDF输入
  │
  ▼
[parse_pdf] ─────────── parsed_content, section_headings, citations, references
  │                      💾 → 01_parse_pdf.json
  ▼
[evidence_collection] ── 统一执行所有工具，产出结构化证据
  │  ├─ CitationChecker.validate(result_store=store)
  │  │   ─→ validation (C3,C5) + ref_metadata_cache ★核心共享数据
  │  │   💾 → extraction.json, validation.json (工具层独立持久化)
  │  ├─ [C6: citation_sentence_alignment] (LLM批处理,low risk)
  │  │   输入：citations×sentence + cache×abstract → contradiction_rate
  │  │   ★ 若 ≥ threshold(5%) → C6.auto_fail=true, V2短路为1分
  │  ├─ [关键词提取] (LLM辅助,low risk) ─→ topic_keywords ★与T2/T5/G4共享
  │  ├─ LiteratureSearch(topic_keywords) ─→ field_trend_baseline (T2,T5用)
  │  ├─ LiteratureSearch(topic_keywords) ─→ candidate_key_papers (G4用)
  │  │   └─ [候选清洗] (LLM辅助,low risk) ─→ 清洗后的候选列表
  │  ├─ CitationAnalyzer(ref_metadata_cache) ─→ analysis (T1-T5, S1-S4)
  │  │   💾 → analysis.json (工具层独立持久化)
  │  └─ CitationGraphAnalysis(ref_metadata_cache) ─→ graph (G1-G6, S5)
  │      💾 → graph_analysis.json (工具层独立持久化)
  │
  │  💾 → 02_evidence_collection.json (增量：仅输出，不含完整state)
  ▼
[evidence_dispatch] ──── 组装Evidence Report（完整数据+定义+异常标记）
  │                      ★ 若C6.auto_fail=true，VerifierAgent的V2维度预填1分
  │                      💾 → 03_evidence_dispatch.json
  │
  ├──→ [verifier_eval] ── VerifierAgent(V1+V2条件+V4)
  │    💾 → 04_verifier.json (增量：仅AgentOutput)
  ├──→ [expert_eval] ──── ExpertAgent(E1-E4)
  │    💾 → 04_expert.json
  └──→ [reader_eval] ──── ReaderAgent(R1-R4)
       💾 → 04_reader.json
  │
  ▼
[corrector] ──────────── 多模型投票校正（仅hallucination_risk: medium/high的子维度）
  │                      ★ 不产出新维度，只附加variance并可能修正分数
  │                      💾 → 05_corrector.json
  ▼
[aggregator] ──────────── 加权聚合校正后评分
  │                       💾 → 06_aggregated_scores.json
  ▼
[reporter] ─────────────── 生成Markdown诊断报告
                           💾 → 07_report.md + run_summary.json
```

### 3.2 关键变化（v3 相对 v2）

**变化1（v3新增）：CorrectorAgent回归纯校正角色。** 删除原C1/C2/C3独立评分维度，Corrector仅对`hallucination_risk: medium/high`的子维度做多模型投票校正。不产出新分数，只附加variance并可能修正已有分数。评估维度从15个（V×3 + E×4 + R×4 + C×3 + V4）精简为11个（V×3 + E×4 + R×4）。

**变化2（v3新增）：持久化机制重设计。** 见§3.4。工具层独立持久化修复（传入result_store）；工作流步骤改为增量保存；新增run_summary.json和metric_index.json。

**变化3（v2保留）：evidence_collection以ref_metadata_cache为核心共享数据。**

**变化4（v2保留）：LLM辅助预处理（低幻觉风险）。**

**变化5（v2保留）：evidence_dispatch输出完整Evidence Report。**

### 3.3 State扩展

```python
class SurveyState(TypedDict):
    # 现有字段
    source_pdf_path: str
    parsed_content: str
    evaluations: List[EvaluationRecord]
    current_round: int
    consensus_reached: bool
    final_report_md: str
    metadata: dict

    # 新增字段
    tool_evidence: ToolEvidence
    ref_metadata_cache: Dict[str, dict]   # ★核心共享数据：每篇ref的完整元数据
    topic_keywords: List[str]             # LLM辅助提取，T2/T5/G4共享
    field_trend_baseline: dict            # 学术API检索得到的领域发表趋势
    candidate_key_papers: List[dict]      # 检索得到的候选核心文献（已清洗）
    agent_outputs: Dict[str, AgentOutput] # V/E/R三个Agent的输出
    corrector_output: CorrectorOutput     # v3新增：校正结果（独立于agent_outputs）
    aggregated_scores: AggregatedScores

class CorrectorOutput(TypedDict):
    """v3新增：Corrector不再是Agent，而是校正器"""
    corrections: Dict[str, CorrectionRecord]  # 子维度ID → 校正记录
    skipped_dimensions: List[str]             # 跳过的低风险维度
    skip_reason: str

class CorrectionRecord(TypedDict):
    original_score: float
    corrected_score: float
    variance: dict  # models_used, scores, median, std, high_disagreement
```

### 3.4 持久化机制设计（v3新增）

#### 3.4.1 设计原则

1. **工具层结果必须独立保存**——每个工具的原始输出保存为独立JSON，可脱离工作流单独使用、检查和复用。
2. **工作流步骤增量保存**——每个步骤只保存该步骤的增量输出，不冗余复制ref_metadata_cache等大字段。
3. **运行级元数据完整**——config快照、指标索引、数据流关系在运行开始时记录，确保可复现。

#### 3.4.2 输出目录结构

```
output/runs/{run_id}/
├── run.json                          # 运行元信息 + config快照 + metrics_index（见3.4.3）
├── run_summary.json                  # ★v3新增：运行结果摘要（见3.4.4）
├── papers/{paper_id}/
│   ├── source.json                   # 源文件信息
│   │
│   │  # 工具层独立持久化（修复result_store传递后生成）
│   ├── extraction.json               # CitationChecker: citations + references
│   ├── validation.json               # CitationChecker: 验证结果 + ref_metadata
│   ├── c6_alignment.json             # CitationChecker: C6逐条对齐结果
│   ├── analysis.json                 # CitationAnalyzer: T1-T5, S1-S4
│   ├── graph_analysis.json           # CitationGraphAnalysis: G1-G6, S5
│   ├── trend_baseline.json           # LiteratureSearch: field_trend_baseline
│   ├── key_papers.json               # LiteratureSearch: candidate_key_papers
│   │
│   │  # 工作流步骤增量持久化
│   ├── 01_parse_pdf.json             # 增量：parsed_content + metadata
│   ├── 02_evidence_collection.json   # 增量：tool_evidence指标汇总（不含完整cache）
│   ├── 03_evidence_dispatch.json     # 增量：各Agent的Evidence Report摘要
│   ├── 04_verifier.json              # 增量：仅VerifierAgent的AgentOutput
│   ├── 04_expert.json                # 增量：仅ExpertAgent的AgentOutput
│   ├── 04_reader.json                # 增量：仅ReaderAgent的AgentOutput
│   ├── 05_corrector.json             # 增量：CorrectorOutput（校正记录）
│   ├── 06_aggregated_scores.json     # 增量：聚合结果
│   └── 07_report.md                  # 最终Markdown报告
```

**关键改进：** ref_metadata_cache完整数据仅在`validation.json`中保存一次。步骤JSON通过引用validation.json获取cache数据，不再每个文件都冗余包含。步骤JSON中如需引用cache数据，记录`"ref_metadata_cache": "→ see validation.json"`。

#### 3.4.3 metrics_index（合并到 run.json）

在运行开始时生成，记录所有指标的定义、计算来源、数据流向。对后续可视化和调试至关重要。

**设计变更**：metrics_index 合并到 run.json 中，作为 `metrics_index` 字段，而非独立文件。

```json
{
  "run_id": "20260317T070826Z_53317b7e",
  "created_at": "2026-03-17T07:00:00Z",
  "schema_version": "v3",
  "metrics_index": {
    "config_snapshot": {
      "evidence": { "foundational_top_k": 30, "c6_batch_size": 10, "contradiction_threshold": 0.05, "..." : "..." },
      "models": { "default": "gpt-4o", "c6_model": "gpt-4o-mini", "corrector_models": ["gpt-4o", "claude-sonnet", "deepseek"] }
    },
    "metrics": {
    "C3": {
      "name": "orphan_ref_rate",
      "computed_by": "CitationChecker",
      "source_file": "validation.json",
      "llm_involved": false,
      "consumed_by": ["VerifierAgent.V1"]
    },
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
      "computed_by": "FoundationalCoverageAnalyzer",
      "source_file": "key_papers.json",
      "llm_involved": true,
      "hallucination_risk": "low",
      "consumed_by": ["ExpertAgent.E1"]
    },
    "T5": {
      "name": "trend_alignment",
      "computed_by": "CitationAnalyzer + LiteratureSearch",
      "source_file": "analysis.json + trend_baseline.json",
      "llm_involved": true,
      "hallucination_risk": "low",
      "consumed_by": ["ReaderAgent.R1"]
    }
  },
  "agent_dimensions": {
    "VerifierAgent": {
      "input_evidence": ["C3", "C5", "C6"],
      "output_dimensions": ["V1", "V2", "V4"],
      "corrector_targets": ["V4"]
    },
    "ExpertAgent": {
      "input_evidence": ["G1", "G2", "G3", "G4", "G5", "G6", "S5"],
      "output_dimensions": ["E1", "E2", "E3", "E4"],
      "corrector_targets": ["E2", "E3", "E4"]
    },
    "ReaderAgent": {
      "input_evidence": ["T1", "T2", "T3", "T4", "T5", "S1", "S2", "S3", "S4", "S5"],
      "output_dimensions": ["R1", "R2", "R3", "R4"],
      "corrector_targets": ["R2", "R3", "R4"]
    }
  }
}
```

此文件同时服务于：(1) 运行参数可复现，(2) 调试时追踪某个指标从哪个工具产出、流向哪个Agent，(3) 可视化时展示数据流图。

#### 3.4.4 run_summary.json（运行结果摘要）

运行结束后生成，包含所有指标最终值和评分结果，方便批量实验时快速比较。

**设计变更**：run_summary.json 放在 run.json 同级目录（output/runs/{run_id}/run_summary.json），而非 papers/{paper_id}/ 目录。

```json
{
  "run_id": "20260317T070826Z_53317b7e",
  "source": "test_paper.pdf",
  "timestamp": "2026-03-17T07:13:20Z",
  "deterministic_metrics": {
    "C3": 0.08, "C5": 0.85, "C6_contradiction_rate": 0.016,
    "T1": 34, "T2": 3, "T3": 0.65, "T4": 1, "T5": 0.77,
    "S1": 7, "S2": 0.897, "S3": 0.25, "S4": 0.0, "S5": 0.72,
    "G1": 0.12, "G2": 2, "G3": 0.85, "G4": 0.65, "G5": 3, "G6": 0.12
  },
  "agent_scores": {
    "V1": 4, "V2": 4, "V4": 5,
    "E1": 4, "E2": 4, "E3": 5, "E4": 4,
    "R1": 4, "R2": 3, "R3": 4, "R4": 3
  },
  "corrected_scores": {
    "V4": { "original": 5, "corrected": 4, "std": 0.47 },
    "E3": { "original": 5, "corrected": 3, "std": 1.25 }
  },
  "overall_score": 7.6,
  "grade": "B"
}
```

#### 3.4.5 _save_workflow_step 改进

```python
def _save_workflow_step(step_name, state, data, ...):
    step_record = {
        "step": step_name,
        "timestamp": now_iso(),
        "source_pdf": state.get("source_pdf_path", ""),
        "output": data,  # 仅该步骤的增量输出
        # 不再保存 input（完整state）
        # 如需追溯输入，从前序步骤的output中获取
    }
```

---

## 四、实验设计

### 4.1 测试集构建

选择2-3个CS子领域主题，使用以下策略构建质量梯度：

| 质量级别 | 来源 | 预期特征 |
|---------|------|---------|
| 高（参照物） | 人类撰写的真实综述 | 引用规范、结构完整、有批判性分析 |
| 中高 | AutoSurvey/SurveyX等系统生成 | 结构尚可，引用可能有错误，批判性不足 |
| 中 | 单LLM直接生成（有RAG） | 流畅但引用问题多，结构可能不均衡 |
| 低 | 单LLM直接生成（无RAG） | 可能存在虚假引用、结构混乱 |

每个主题每个级别1篇，共约8-12篇。

### 4.2 人类标注设计

标注者2-3位，使用与系统相同的rubric打1-5分。标注流程含pilot校准+独立标注+一致性计算（Krippendorff's alpha）+共识讨论。最小标注量：10篇 × 11子维度 × 2标注者 = 220个评分点。

### 4.3 Meta-Evaluation协议

| 分析 | 方法 | 目的 |
|------|------|------|
| 维度级相关 | 每个子维度的Spearman相关系数 | 哪些维度系统评得准 |
| 排序一致性 | 总分排序的Kendall tau | 系统能否区分好坏综述 |
| 确定性 vs LLM指标对比 | 仅用llm_involved=false指标的评测效果 vs 全指标 | 量化LLM参与的边际贡献 |
| 波动范围分析 | llm_involved=true指标的std分布 | 哪些维度的LLM判断最不稳定 |
| 模型敏感性 | 更换backbone LLM后评分变化 | 对模型选择的鲁棒性 |

### 4.4 消融实验

| 实验 | 关闭的组件 | 验证的假设 |
|------|-----------|-----------|
| A1: 无工具证据 | 去除evidence_collection，Agent只看原文 | 工具证据对评分质量的贡献 |
| A2: 无检索增强 | 去除field_trend_baseline和candidate_key_papers | 后验检索对评分质量的贡献 |
| A3: 无C6逐条对齐 | 去除C6，V2改回Agent直接判断（抽样） | 工具层逐条对齐 vs Agent抽样判断的质量和成本对比 |
| A4: 无多模型投票 | Corrector用单模型，或完全跳过 | 多模型投票对高风险维度稳定性的贡献 |
| A5: 单Agent | 合并为一个Agent做全维度评估 | 角色分工对评分质量的贡献 |

---

## 五、优先级排序与执行计划

### Phase 1（最高优先级，1-2周）：评测指标形式化 + Agent输出协议

- [ ] 1.1 实现检索增强指标：field_trend_baseline获取逻辑（关键词提取 + 多query学术API检索 + 均值聚合）
- [ ] 1.2 实现G4 foundational_coverage_rate：候选核心文献检索 + 匹配计算 + missing_key_papers/suspicious_centrality输出
- [ ] 1.3 实现S5 section_cluster_alignment：NMI/ARI计算
- [ ] 1.4 实现指标元数据schema（MetricMetadata），所有指标携带llm_involved和hallucination_risk标记
- [ ] 1.5 完善所有子维度的rubric（参照本文档§2.6模板，注意V2/V3已合并，C1/C2/C3已删除）
- [ ] 1.6 设计Agent输出JSON Schema（参照§2.7，variance由Corrector填充）
- [ ] 1.7 实现evidence_dispatch逻辑：组装Evidence Report + C6.auto_fail短路预填V2=1分
- [ ] 1.8 更新各Agent的system prompt模板，嵌入rubric、输出格式要求和指标定义
- [ ] 1.9 更新state.py添加ToolEvidence、CorrectorOutput等字段
- [ ] 1.10 实现C6 citation_sentence_alignment：批处理LLM调用 + contradiction_rate + auto_fail短路

### Phase 2（高优先级，1-2周）：Workflow重构 + 持久化修复

- [ ] 2.1 修复result_store传递：evidence_collection中所有工具实例化时传入result_store
- [ ] 2.2 实现增量持久化：_save_workflow_step改为仅保存增量输出，ref_metadata_cache不冗余
- [ ] 2.3 实现metric_index.json：运行开始时生成指标索引（定义+来源+数据流）+ config快照
- [ ] 2.4 实现run_summary.json：运行结束时生成轻量结果摘要
- [ ] 2.5 重写CorrectorAgent为纯校正角色：删除C1/C2/C3，改为对hallucination_risk:medium/high子维度做多模型投票
- [ ] 2.6 重写Aggregator：使用校正后分数做加权聚合，区分确定性/LLM指标
- [ ] 2.7 拆分Reporter为纯报告生成（后续版本完善报告模板）
- [ ] 2.8 更新builder.py的节点连接和步骤编号（01-07）
- [ ] 2.9 端到端集成测试

### Phase 3（中优先级，1-2周）：实验执行 + Meta-Evaluation

- [ ] 3.1 收集/生成测试综述集
- [ ] 3.2 设计标注表格，做pilot标注和rubric校准
- [ ] 3.3 收集人类标注
- [ ] 3.4 运行系统评测，收集输出（含Corrector的variance数据）
- [ ] 3.5 计算一致性指标，执行消融实验
- [ ] 3.6 分析确定性指标 vs LLM指标的贡献差异

### Phase 4（后续，1-2周）：论文撰写 + 报告完善 + 可视化

- [ ] 4.1 撰写论文
- [ ] 4.2 完善报告模板：Evidence Dashboard + Agent Assessment + Diagnostic Findings三区域
- [ ] 4.3 前端可视化：引用图、评分雷达图、数据流图（基于metric_index.json）、诊断报告
- [ ] 4.4 代码整理、文档完善

---

## 六、风险与注意事项

1. **学术API限流与数据复用。** ref_metadata_cache是降低API调用量的关键——CitationChecker.validate阶段的元数据获取是整个pipeline中最密集的API调用点，后续所有工具应直接读cache。field_trend_baseline和candidate_key_papers的检索额外需要3-5组query×2个API源，总调用量可控。建议设置合理timeout和fallback（如某API不可用时降级为单源），并在实验中报告检索来源和cache命中率。

2. **S5的聚类稳定性。** 引用图聚类算法（如Louvain、谱聚类）对参数敏感，不同运行可能产生不同聚类结果。建议固定随机种子并报告聚类算法与参数选择的影响。

3. **G4中top-K阈值的选择。** K太小可能遗漏重要文献，K太大会引入噪声（边缘论文也被当作"核心"）。建议在实验中测试K=20/30/50的敏感性。

4. **Corrector多模型投票的成本控制。** v3中Corrector仅对7个高风险子维度做投票（V4, E2-E4, R2-R4），每个维度3个模型调用 = 21次LLM调用。成本约为完整评估（3个Agent各1次 = 3次）的7倍。建议在消融实验中验证投票对哪些维度真正有价值，对收益不明显的维度可以降级为单模型。

5. **ref_metadata_cache中abstract字段的可用性。** C6和G4候选清洗都依赖abstract。部分文献（特别是较老的或非顶会的）在学术API中可能没有abstract返回。应在metric_index.json中记录`missing_abstract_ratio`，在报告中标明C6结果的覆盖范围。

6. **持久化迁移兼容性。** v3将步骤编号从04_*改为04-07连续编号，且Corrector输出结构完全改变。旧版运行结果与新版不兼容，需在run.json中标记schema_version以区分。