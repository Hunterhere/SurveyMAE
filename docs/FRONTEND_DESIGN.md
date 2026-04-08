# SurveyMAE 前端设计方案

> 基于: SurveyMAE_Plan_v3.md, CACHE_PERSISTENCE_DESIGN.md, LOGGING_DESIGN.md
> 创建时间: 2026/04/05
> 目的: 需求分析与信息架构设计（不涉及技术栈选择）

---

## 一、设计定位

### 1.1 用户与场景

**目标用户：** 领域研究者——关注自动生成综述质量评测的学者，希望理解系统如何工作、评分依据是什么。

**核心场景：** 用户上传一篇 PDF 综述 → 等待系统评测（1-10 分钟）→ 查看诊断报告 → 追溯任意评分的完整证据链。

**不需要支持：** 批量对比视图、用户账户系统、历史记录管理。

### 1.2 核心设计目标

1. **证据可追溯** — 这是系统的核心创新。用户看到任何一个分数，都应能在 1-2 次点击内追溯到产出它的工具证据和 Agent 推理。整个前端的信息架构围绕"分数 → 证据 → 原始数据"这条链路展开。

2. **区分确定性与 LLM 判断** — 视觉上区分 `llm_involved=false` 的客观计算指标与 `llm_involved=true` 的 Agent 判断，让用户理解"哪些是硬数据，哪些有主观成分"。

3. **处理过程透明** — 评测运行期间不是空白等待，而是逐步展示已完成步骤的中间结果。

4. **渐进式展开** — 表面简洁，深层丰富。默认展示结论和关键数字，折叠区域包含完整证据、原始数据和工具分析详情。

---

## 二、页面结构

整个前端由两个页面状态组成（不是两个独立页面，而是同一页面的两个阶段）：

```
[上传阶段] → [处理阶段（渐进展示）] → [结果阶段（完整报告）]
```

### 2.1 上传阶段

极简界面：一个 PDF 上传区域 + 一个"开始评测"按钮。

上传区域下方展示**历史评测结果列表**（数据来自 `GET /api/runs`）。每条显示 PDF 文件名、总分、等级。点击某条历史结果，直接跳到结果渲染阶段，跳过上传和处理等待。

```
┌──────────────────────────────────────┐
│  上传 PDF 开始评测                    │
│  [拖拽上传区域]                       │
│                                       │
│  ── 或查看历史结果 ──                 │
│  ┌──────────────────────────────┐    │
│  │ test_survey2.pdf    7.3  C   │    │
│  │ another_survey.pdf  8.1  B   │    │
│  └──────────────────────────────┘    │
└──────────────────────────────────────┘
```

此设计同时服务于两个场景：前端开发调试时直接加载已有结果，以及用户查看过去的评测记录。

### 2.2 处理阶段

用户上传 PDF 后，页面过渡到处理阶段。这个阶段的核心是**渐进式结果交付**——已完成的步骤立即展示中间结果，而不是等到全部完成。

#### 处理进度面板

页面顶部（或侧边）显示 pipeline 步骤列表，每个步骤三种状态：

| 状态 | 视觉 | 说明 |
|------|------|------|
| 待执行 | 灰色 | 尚未开始 |
| 执行中 | 蓝色 + 动画 | 当前步骤，显示子步骤进度 |
| 已完成 | 绿色 + 勾 | 显示关键结果数字 + 耗时 |
| 失败 | 红色 + 叉 | 显示错误信息 |

步骤列表：

```
✅ [01] PDF 解析           │ 47 refs, 12 sections              2.3s
🔄 [02] 证据收集           │ 验证引用 42/47...                  
⬜ [03] 证据分发
⬜ [04] Agent 评估
⬜ [05] 校正投票
⬜ [06] 评分聚合
⬜ [07] 报告生成
```

#### 渐进式结果交付

**关键交互：已完成的步骤可以立即点击展开查看中间结果。** 例如：

- PDF 解析完成后 → 用户可以查看提取出的章节结构和引用列表
- 证据收集完成后 → 用户可以查看所有确定性指标（C3/C5/T1-T5/S1-S5/G1-G6）和工具分析可视化
- Agent 评估完成后 → 用户可以查看各 Agent 的评分和推理

这使得等待时间变得有意义——用户在等后续步骤的同时，已经在探索前序步骤的结果。

#### 数据来源

前端轮询（或 WebSocket 推送）后端的文件生成状态：

| 文件生成 | 对应步骤完成 | 前端可展示的内容 |
|---------|------------|----------------|
| `tools/extraction.json` | 01 PDF 解析 | 引用列表、章节结构 |
| `tools/validation.json` | 02 证据收集（部分） | C3/C5 指标、引用验证详情 |
| `tools/c6_alignment.json` | 02 证据收集（部分） | C6 矛盾率、矛盾案例 |
| `tools/analysis.json` | 02 证据收集（部分） | T/S 系列指标、时序图、结构图 |
| `tools/graph_analysis.json` | 02 证据收集（部分） | G 系列指标、引用图 |
| `tools/key_papers.json` | 02 证据收集（部分） | G4 覆盖率、缺失论文列表 |
| `nodes/04_verifier.json` | 04 Agent 评估 | V 系列评分 + 推理 |
| `nodes/04_expert.json` | 04 Agent 评估 | E 系列评分 + 推理 |
| `nodes/04_reader.json` | 04 Agent 评估 | R 系列评分 + 推理 |
| `nodes/05_corrector.json` | 05 校正投票 | 校正记录 |
| `run_summary.json` | 07 全部完成 | 最终评分和等级 |

### 2.3 结果阶段

全部步骤完成后，进度面板收起（或缩小到顶部），主体区域展示完整的诊断报告。这是用户停留时间最长的页面状态，也是信息密度最高的区域。

---

## 三、结果页面的信息架构

结果页面从上到下分为四个区域，对应系统的三层评测栈 + 工具分析详情：

```
┌─────────────────────────────────────────────────┐
│  区域 A: 诊断概览                                │  ← 一屏之内
│  总分 + 等级 + 雷达图 + 摘要                      │
└─────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────┐
│  区域 B: 维度评分卡片（证据链核心）               │  ← 主体内容
│  11 个子维度，按语义分组                          │
│  每个维度: 分数 → 工具证据 → Agent 推理           │
└─────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────┐
│  区域 C: 工具分析详情                             │  ← 可折叠展开
│  PDF 解析 / 引用验证 / 时序分析 / 结构分析 / 图分析 │
└─────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────┐
│  区域 D: 系统信息                                │  ← 折叠
│  运行配置 / 模型信息 / 指标定义 / 原始 JSON       │
└─────────────────────────────────────────────────┘
```

---

### 区域 A：诊断概览

**设计原则：一屏之内展示全貌。**

#### A1. 总分与等级

- 大号数字展示总分（如 `7.6 / 10`）和等级（如 `B`）
- 等级用颜色编码：A 绿色、B 蓝色、C 黄色、D 橙色、F 红色

#### A2. 雷达图

- 11 个子维度（V1/V2/V4, E1-E4, R1-R4）的 1-5 分雷达图
- 维度标签使用**语义名称**而非代号：不是 "V1"，而是 "引用存在性"
- 雷达图上区分两种标记：
  - **实心点**：`hallucination_risk: low` 或 `null`（确定性指标驱动，可信度高）
  - **空心点/虚线**：`hallucination_risk: medium/high`（LLM 判断，有波动）
- 如果某维度被 Corrector 校正，在雷达图上用双点标记（原始分 + 校正分）

数据来源：`run_summary.json` → `dimension_scores`

#### A3. 摘要

2-3 句话的核心结论。来源：`nodes/07_report.md` 或由前端从 `run_summary.json` 的分数分布自动生成（标记低分维度和高分维度）。

#### A4. 关键警告

如果存在以下情况，在概览区域用醒目标记提示：
- C6 `auto_fail=true`（严重引用矛盾，V2 被短路为 1 分）
- 任何维度的 Corrector 校正幅度 ≥ 2 分
- 任何维度的 `high_disagreement=true`（模型间严重分歧）
- C5 验证率极低（如 < 30%）

---

### 区域 B：维度评分卡片

**设计原则：每条评分都可在 1-2 次点击内追溯到完整证据链。**

#### B1. 分组方式

按用户可理解的语义维度分三组，而非按 Agent 内部名称：

| 组名 | 包含维度 | 对应 Agent |
|------|---------|-----------|
| 事实性验证 | V1 引用存在性、V2 引用-断言对齐、V4 内部一致性 | VerifierAgent |
| 学术深度 | E1 核心文献覆盖、E2 方法分类、E3 技术准确性、E4 批判性分析 | ExpertAgent |
| 可读性与信息量 | R1 时效性、R2 信息分布、R3 结构清晰度、R4 文字质量 | ReaderAgent |

#### B2. 单个维度卡片的信息层级

每个维度卡片采用三层渐进展开：

**第一层（默认展示 — 卡片头部）：**

```
┌──────────────────────────────────────────────────┐
│  V1 引用存在性                    4 / 5  ██████░░ │
│  ○ hallucination_risk: low                        │
│  工具证据: C5=89.4% (42/47 refs 通过验证)          │
│                                    [展开详情 ▼]   │
└──────────────────────────────────────────────────┘
```

包含：维度名、分数（含进度条）、hallucination_risk 标记、支撑该分数的关键工具指标数值。

**关键设计：** 卡片头部直接显示最关键的工具证据数字（如 C5=89.4%），让用户不需要展开就能看到"这个分数是基于什么数据的"。这是证据链的第一环。

**第二层（点击展开 — Agent 推理 + 证据详情）：**

```
┌──────────────────────────────────────────────────────┐
│  Rubric 等级说明                                      │
│  "4分: C5 ≥ 0.6，缺失的引用主要为 workshop 论文      │
│   或预印本，非核心遗漏"                               │
│                                                       │
│  Agent 推理                                           │
│  "85% of references were externally verified.         │
│   The 6 unverified entries appear to be workshop      │
│   papers or preprints not yet indexed..."             │
│                                                       │
│  标记项目                                             │
│  ⚠ [23] - title not found in any source              │
│  ⚠ [37] - year mismatch (2023 vs 2024)               │
│                                                       │
│  校正信息（如有）                                     │
│  原始分: 5 → 校正分: 4 (std=0.47)                     │
│  模型: gpt-4o=4, claude-sonnet=5, deepseek=4          │
│                                                       │
│                                    [查看原始数据 ▼]   │
└──────────────────────────────────────────────────────┘
```

包含：该分数对应的 rubric 等级描述、Agent 的完整 reasoning 文本、Agent 标记的具体问题项（flagged_items）、Corrector 校正记录（如有）。

数据来源：`nodes/04_verifier.json`（或 04_expert / 04_reader）→ `sub_scores.{dim_id}`

**第三层（再展开 — 原始工具数据）：**

直接展示该维度依赖的工具 JSON 原始数据。例如 V1 维度展开后显示 `validation.json` 中的 `reference_validations` 列表，包含每条引用的验证状态、来源、元数据。

这一层面向需要深入调试的用户，信息密度高，使用等宽字体或 JSON 树形展示。

#### B3. 特殊维度的展示

部分维度有特殊的可视化需求：

| 维度 | 特殊展示 |
|------|---------|
| V2 引用-断言对齐 | contradiction 列表：每条显示 citation marker + 原文句子 + ref abstract + 判定理由。如果 `auto_fail=true`，整个卡片用红色边框标记 |
| E1 核心文献覆盖 | `missing_key_papers` 列表：每篇显示标题、被引次数、年份、venue。这是用户最可操作的信息——"你缺了这些论文" |
| E1 核心文献覆盖 | `suspicious_centrality` 列表：图中重要但外部被引低的论文 |
| R1 时效性 | 内嵌时序分布图（见区域 C 详述，此处嵌入缩略版） |

---

### 区域 C：工具分析详情

**设计原则：展示系统的"后验分析能力"，每个工具的完整分析结果都可独立查看。**

区域 C 是可折叠的工具分析面板集合。每个面板对应一个工具的完整输出，默认折叠，点击标题展开。

#### C1. PDF 解析（extraction.json）

| 展示内容 | 数据来源 |
|---------|---------|
| 章节结构树：层级标题列表 | `extraction.json` → citations 中提取的 section_title 去重 |
| 引用列表表格：marker / sentence / page / section | `extraction.json` → `citations` |
| 参考文献列表：编号 / 标题 / 作者 / 年份 | `extraction.json` → `references` |
| 基础统计：总引用数、总参考文献数、章节数 | 计算得出 |

#### C2. 引用验证（validation.json）

| 展示内容 | 数据来源 |
|---------|---------|
| 验证汇总：通过/失败/跳过 数量 + 饼图 | `validation.json` → `reference_validations` 聚合 |
| 验证详情表格：每条 ref 的验证状态、来源、confidence、元数据 | `validation.json` → `reference_validations` |
| C3 (orphan_ref_rate) 和 C5 (metadata_verify_rate) 数值 | 计算或从 `run_summary.json` |
| 未通过验证的引用列表（高亮） | 筛选 `is_valid=false` |

#### C3. 引用-断言对齐分析（c6_alignment.json）

| 展示内容 | 数据来源 |
|---------|---------|
| C6 汇总：total_pairs / support / contradict / insufficient / contradiction_rate | `c6_alignment.json` |
| 矛盾案例列表：citation marker + sentence + ref_abstract + llm_judgment + note | `c6_alignment.json` → `contradictions` |
| auto_fail 状态标记 | `c6_alignment.json` → `auto_fail` |

#### C4. 时序分析（analysis.json + trend_baseline.json）

| 展示内容 | 数据来源 |
|---------|---------|
| **时序分布图**（核心可视化）：X 轴=年份，双线叠加 — 综述引用年份分布 vs 领域趋势基线 | `analysis.json` → `year_distribution` + `trend_baseline.json` |
| T1-T5 指标数值表 | `analysis.json` → temporal 部分 |
| T5 相关系数的解读说明 | 固定文案 + T5 值 |

**时序分布图设计要点：**
- 综述引用分布用柱状图（实心）
- 领域趋势基线用折线图（叠加）
- 如果存在 T4 标记的断层年份，用垂直虚线标记
- 如果 T5 < 0.3（严重偏离趋势），图表标题附带警告

#### C5. 章节结构分析（analysis.json）

| 展示内容 | 数据来源 |
|---------|---------|
| **章节引用密度图**：横向条形图，每个章节一条，长度=该章节引用数 | `analysis.json` → structural 部分 |
| S1-S4 指标数值表 | `analysis.json` → structural 部分 |
| S3 (Gini 系数) 的含义说明 | 固定文案 |
| S4 标记的零引用章节（高亮） | 筛选 |

#### C6. 引用图分析（graph_analysis.json + validation.json）

| 展示内容 | 数据来源 |
|---------|---------|
| **引用网络图**（核心可视化，vis.js 前端渲染）：交互式节点-边图 | `validation.json` → `real_citation_edges` + `reference_validations`；`graph_analysis.json` → `cocitation_clustering.clusters` |
| G1-G6 指标数值表 | `graph_analysis.json` |
| S5 章节-聚类对齐度 | `graph_analysis.json` |
| 聚类着色：节点按社区/聚类着色 | `graph_analysis.json` → `cocitation_clustering.clusters` |
| 节点大小：按 in-degree/out-degree 对数缩放 | 从 `real_citation_edges` 计算 |

**引用网络图设计要点：**
- 前端使用 vis.js 直接从 JSON 数据渲染（不嵌入后端生成的 pyvis HTML）
- 渲染逻辑参考 `scripts/render_citation_graph_pyvis.py`，详见 §九 引用网络图渲染方案
- 节点 = 参考文献，hover 显示标题/作者/年份/被引次数（来自 `reference_validations[].metadata`）
- 边 = 真实引用关系（来自 `real_citation_edges`）
- 节点按聚类着色（来自 `cocitation_clustering.clusters`）
- `missing_key_papers`（来自 `key_papers.json`）用虚线框/特殊颜色标记
- 孤立节点保留展示，视觉上弱化（灰色）
- **交互能力：** 节点点击可跳转到引用验证详情（区域 C2），与 E1 维度卡片的 missing_key_papers 列表联动高亮

#### C7. 核心文献覆盖分析（key_papers.json）

| 展示内容 | 数据来源 |
|---------|---------|
| G4 覆盖率 | `key_papers.json` |
| 匹配的核心文献列表 | `key_papers.json` → matched |
| **缺失的核心文献列表**（可操作建议）：标题 / 被引次数 / 年份 / venue | `key_papers.json` → missing |
| 检索用的关键词 | `key_papers.json` → keywords_used |

---

### 区域 D：系统信息

完全折叠，面向需要了解系统配置的用户。

| 展示内容 | 数据来源 |
|---------|---------|
| 运行 ID、时间戳 | `run.json` |
| 使用的模型配置 | `run.json` → config_snapshot |
| 指标定义表：每个指标的 ID、名称、计算方式、llm_involved、consumed_by | `run.json` → `metrics_index` |
| 数据流图：指标从哪个工具产出、流向哪个 Agent | `run.json` → `metrics_index` → `agent_dimensions`  |
| 原始 JSON 文件下载链接 | 所有 tools/ 和 nodes/ 文件 |

---

## 四、证据链交互设计

这是前端的核心创新体现。设计一条从"总分 → 维度分 → 工具证据 → 原始数据"的连贯追溯路径。

### 4.1 追溯路径示例

以 E1 (核心文献覆盖) 为例：

```
[雷达图上 E1=4 的点]
  ↓ 点击
[区域 B: E1 卡片展开]
  显示: G4=66%, 评分 rubric, Agent reasoning
  显示: missing_key_papers 列表 (3 篇核心论文缺失)
  ↓ 点击 "查看完整分析"
[区域 C6: 引用图分析面板 展开/滚动到]
  显示: 引用网络图，缺失论文用虚线框标记
[区域 C7: 核心文献覆盖面板 展开/滚动到]
  显示: 完整的匹配/缺失列表 + 检索关键词
```

### 4.2 交互方式

- **雷达图点击 → 跳转到对应维度卡片**（平滑滚动到区域 B 中的对应卡片并展开）
- **维度卡片中的指标数字 → 链接到区域 C 的工具面板**（如 "C5=89.4%" 可点击，跳转到引用验证面板）
- **工具面板中的条目 → 展开查看原始 JSON**

### 4.3 视觉区分：确定性 vs LLM 判断

整个结果页面中，对两类信息使用一致的视觉区分：

| 类型 | 视觉标记 | 适用位置 |
|------|---------|---------|
| 确定性指标 (`llm_involved=false`) | 实心圆点 / 实线边框 / 无特殊标记 | 雷达图、维度卡片、指标表 |
| LLM 辅助指标 (`llm_involved=true, risk=low`) | 半实心标记 + "LLM 辅助" 小标签 | C6、G4、T2、T5 |
| LLM 判断 (`hallucination_risk=medium/high`) | 空心圆点 / 虚线边框 + 波动范围显示 | Agent 维度评分 |
| Corrector 校正过 | 双色标记（原始色 + 校正色）| 被校正的维度 |

---

## 五、关键可视化组件清单

| 组件 | 位置 | 数据来源 | 优先级 |
|------|------|---------|--------|
| 雷达图（11 维度） | 区域 A | `run_summary.json` | P0 |
| 维度评分卡片（11 个） | 区域 B | `nodes/04_*.json` + `nodes/05_corrector.json` | P0 |
| 时序分布双线图 | 区域 C4 / R1 卡片内嵌 | `analysis.json` + `trend_baseline.json` | P0 |
| 章节引用密度条形图 | 区域 C5 | `analysis.json` | P1 |
| 引用网络图（交互式） | 区域 C6 | `validation.json` + `graph_analysis.json` | P1 |
| 引用验证状态饼图 | 区域 C2 | `validation.json` | P1 |
| 缺失论文列表 | E1 卡片 / 区域 C7 | `key_papers.json` | P0 |
| 矛盾案例列表 | V2 卡片 / 区域 C3 | `c6_alignment.json` | P0 |
| 处理进度步骤条 | 处理阶段 | 文件存在性轮询 | P0 |
| 数据流图（指标→Agent 映射） | 区域 D | `run.json` → `metrics_index` | P2 |

---

## 六、信息密度控制

### 6.1 默认展示层（面向场景 A：快速了解质量）

用户不做任何交互就能看到的信息：

- 总分 + 等级 + 雷达图
- 11 个维度卡片的折叠态（分数 + 一行工具证据摘要）
- 关键警告标记

**信息量控制：约一到两屏。**

### 6.2 一次展开层（面向场景 A 深入：理解每个维度）

用户点击单个维度卡片展开后看到的信息：

- Rubric 等级描述
- Agent 推理全文
- 标记项目列表
- 校正信息

**信息量控制：每个卡片展开后 100-300 词。**

### 6.3 工具详情层（面向场景 C：追溯原始数据）

用户展开区域 C 的工具面板后看到的信息：

- 完整的引用列表、验证详情表格、图分析指标、时序分布原始数据
- 交互式引用网络图

**信息量控制：按工具分面板折叠，每个面板展开后 300-1000 词 + 图表。**

### 6.4 原始数据层（面向开发者）

- 区域 D 的配置信息和指标定义
- 各 JSON 文件的下载链接

---

## 七、数据流设计

### 7.1 前端需要读取的 JSON 文件

按优先级排列：

| 优先级 | 文件 | 用途 |
|--------|------|------|
| P0 | `run_summary.json` | 区域 A：总分、等级、所有维度分数 |
| P0 | `run.json` | metrics_index（指标定义、数据流映射） |
| P0 | `nodes/04_verifier.json` | V 系列维度的 Agent 推理和证据 |
| P0 | `nodes/04_expert.json` | E 系列维度的 Agent 推理和证据 |
| P0 | `nodes/04_reader.json` | R 系列维度的 Agent 推理和证据 |
| P0 | `nodes/05_corrector.json` | 校正记录 |
| P1 | `tools/c6_alignment.json` | 矛盾案例详情 |
| P1 | `tools/key_papers.json` | 缺失论文列表 |
| P1 | `tools/analysis.json` | 时序/结构指标 + 分布数据 |
| P1 | `tools/trend_baseline.json` | 领域趋势基线（时序图叠加线） |
| P1 | `tools/validation.json` | 引用验证详情 + 真实引用边 |
| P1 | `tools/graph_analysis.json` | 图分析指标 + 聚类数据 |
| P2 | `tools/extraction.json` | PDF 解析结果（引用列表、章节结构） |

### 7.2 处理阶段的轮询策略

前端通过轮询文件存在性判断步骤完成状态：

```
每 2 秒检查一次:
  tools/extraction.json 存在? → 步骤 01 完成
  tools/validation.json 存在? → 步骤 02 部分完成
  tools/analysis.json 存在?   → 步骤 02 更多完成
  ...
  run_summary.json 存在?      → 全部完成，切换到结果阶段
```

或者后端提供一个轻量 API：`GET /api/run/{run_id}/status` 返回当前步骤编号和已生成的文件列表。

---

## 八、技术栈

### 8.1 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  浏览器                                                      │
│  src/web/static/                                             │
│    index.html + app.js + style.css                           │
│    ECharts (CDN) — 雷达图、时序图、条形图                      │
│    vis.js (CDN)  — 引用网络图                                 │
└──────────────────────┬──────────────────────────────────────┘
                       │ fetch()
┌──────────────────────┴──────────────────────────────────────┐
│  FastAPI 薄层                                                │
│  src/web/app.py (~150 行)                                    │
│    POST /api/upload        → 保存 PDF, 后台启动评测           │
│    GET  /api/run/{id}/status → 返回步骤完成状态               │
│    GET  /api/run/{id}/files/{path} → 返回 JSON 文件内容      │
│    GET  /static/*          → 静态文件服务                     │
└──────────────────────┬──────────────────────────────────────┘
                       │ import & await
┌──────────────────────┴──────────────────────────────────────┐
│  现有 Python 后端（零修改）                                   │
│    run_evaluation()  →  JSON 文件写入磁盘                     │
│    output/runs/{run_id}/papers/{paper_id}/tools/*.json        │
│    output/runs/{run_id}/papers/{paper_id}/nodes/*.json        │
└─────────────────────────────────────────────────────────────┘
```

### 8.2 技术选择与理由

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 后端 API | FastAPI | 原生 async 支持，`BackgroundTasks` 可直接调度 `run_evaluation()`，无需任务队列 |
| 前端框架 | 无框架，纯 HTML + JS | demo 定位，无构建步骤，项目保持纯 Python |
| 图表库 | ECharts (CDN) | 雷达图、折线图、柱状图功能完整，一个库覆盖所有需求 |
| 引用网络图 | vis.js (CDN) | pyvis 的底层库，前端直接读取 JSON 数据渲染，可实现节点交互 |
| 静态资源加载 | CDN | 不需要在项目中打包 JS 库，离线部署时改为本地路径即可 |

### 8.3 文件结构

```
src/web/
├── __init__.py
├── app.py                    # FastAPI 应用
└── static/
    ├── index.html            # 页面结构
    ├── app.js                # 交互逻辑 + 数据加载 + 图表渲染
    └── style.css             # 样式
```

### 8.4 FastAPI 端点设计

```python
# src/web/app.py

from fastapi import FastAPI, BackgroundTasks, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

app = FastAPI()
app.mount("/static", StaticFiles(directory="src/web/static"), name="static")

@app.get("/")
async def index():
    """返回主页面。"""
    return FileResponse("src/web/static/index.html")

@app.get("/api/runs")
async def list_runs():
    """
    列出所有已完成的历史 run。
    扫描 output/runs/ 目录，读取每个 run 的 run_summary.json 摘要信息。
    用于开发调试时跳过评测直接渲染结果，也用于上传页面展示历史记录。

    返回示例:
    [
      {
        "run_id": "20260403T111515Z_run",
        "paper_id": "615cbba96913",
        "source": "test_survey2.pdf",
        "overall_score": 7.27,
        "grade": "C",
        "timestamp": "2026-04-03T11:22:26+00:00",
        "finished": true
      }
    ]
    """
    ...

@app.post("/api/upload")
async def upload_pdf(file: UploadFile, background_tasks: BackgroundTasks):
    """
    接收 PDF 文件，后台启动评测。
    立即返回 run_id，前端轮询进度。
    """
    # 1. 保存 PDF 到临时位置
    # 2. 生成 run_id 和 paper_id
    # 3. 后台调度 run_evaluation()
    background_tasks.add_task(run_evaluation_wrapper, pdf_path, run_id)
    return {"run_id": run_id, "paper_id": paper_id}

@app.get("/api/run/{run_id}/status")
async def get_status(run_id: str):
    """
    检查哪些 JSON 文件已生成，返回步骤完成状态。
    前端每 2 秒轮询此端点。

    返回示例:
    {
      "run_id": "20260405T...",
      "paper_id": "615cbba96913",
      "completed_files": ["extraction.json", "validation.json"],
      "current_step": 2,
      "total_steps": 7,
      "finished": false
    }
    """
    ...

@app.get("/api/run/{run_id}/files/{path:path}")
async def get_file(run_id: str, path: str):
    """
    直接返回 JSON 文件内容。
    path 示例: "papers/615cbba/tools/validation.json"
    """
    ...
```

### 8.5 启动方式

```bash
# 启动 Web 服务（与 CLI 模式并行，不冲突）
uv run python -m src.web.app
# → http://localhost:8000

# 原有 CLI 模式不受影响
uv run python -m src.main survey.pdf
```

---

## 九、引用网络图：前端渲染方案

### 9.1 方案说明

引用网络图由前端使用 vis.js 直接从 JSON 数据渲染，不嵌入后端生成的 pyvis HTML。这样引用图成为前端页面的原生组件，可以实现：

- 节点点击 → 跳转到引用验证详情（区域 C2）
- hover 显示完整元数据（标题、作者、年份、被引次数）
- 与维度卡片联动高亮 missing_key_papers
- 与 E1 卡片联动高亮 suspicious_centrality 节点

渲染逻辑参考现有 `scripts/render_citation_graph_pyvis.py` 的实现。

### 9.2 数据来源与字段映射

前端需要从以下 JSON 文件读取数据来渲染引用网络图：

#### 节点数据

**主要来源：`tools/validation.json` → `reference_validations`**

每条 reference validation 提供一个节点：

```json
{
  "key": "ref_1",           // → 节点 ID
  "is_valid": true,         // → 节点验证状态标记
  "confidence": 1.0,
  "source": "semantic_scholar",
  "metadata": {
    "title": "Deep learning: a statistical viewpoint",  // → hover 显示
    "authors": ["P. Bartlett", ...],                    // → hover 显示
    "year": "2021",                                     // → hover 显示
    "citation_count": 321                               // → hover 显示
  }
}
```

**补充来源：`tools/extraction.json` → `references`**

⚠️ **Claude Code 注意：** `extraction.json` 的 references 结构可能与 validation.json 不同，需要查看实际文件确认字段名。用途是补全 validation 中未覆盖的节点（确保所有 reference 都出现在图中）。

#### 边数据

**来源：`tools/validation.json` → `real_citation_edges`**

```json
[
  {"source": "ref_1", "target": "ref_3"},
  {"source": "ref_10", "target": "ref_16"}
]
```

#### 聚类数据

**来源：`tools/graph_analysis.json` → `cocitation_clustering.clusters`**

```json
{
  "cocitation_clustering": {
    "clusters": [
      {
        "cluster_id": 0,
        "size": 1,
        "top_papers": [
          {"paper_id": "ref_1", "score": 0.03}
        ]
      },
      {
        "cluster_id": 1,
        "size": 1,
        "top_papers": [
          {"paper_id": "ref_10", "score": 0.03}
        ]
      }
    ]
  }
}
```

⚠️ **Claude Code 注意：** 需要从 `clusters` 数组构建 `paper_id → cluster_id` 的映射。每个 cluster 的 `top_papers` 中列出了属于该 cluster 的论文。需要确认：是否所有属于该 cluster 的论文都在 `top_papers` 中，还是只有得分最高的若干篇？如果是后者，需要查找 `graph_analysis.json` 中是否有单独的完整 `node → cluster_id` 映射字段。

#### 缺失论文标记

**来源：`tools/key_papers.json`**

⚠️ **Claude Code 注意：** 需要查看 `key_papers.json` 的实际结构，确认 missing key papers 列表的字段名和格式。这些论文需要在引用图中以特殊样式标记（如虚线边框或特殊颜色），表示"应在图中但不在"。

### 9.3 渲染参数（来自 pyvis 脚本）

以下参数从 `scripts/render_citation_graph_pyvis.py` 提取，前端应参考实现：

**节点颜色：**
```javascript
const CLUSTER_PALETTE = [
  "#60a5fa", "#f59e0b", "#34d399", "#f472b6", "#a78bfa",
  "#22d3ee", "#fb7185", "#facc15", "#2dd4bf", "#c084fc"
];
// 孤立节点（in_deg=0 且 out_deg=0）: "#9ca3af"
// 有聚类的节点: CLUSTER_PALETTE[cluster_id % 10]
// 有边但无聚类: "#60a5fa"
```

**节点大小：**
```javascript
function nodeSize(inDeg, outDeg) {
  const score = 2.2 * inDeg + 1.0 * outDeg;
  const size = 10.0 + 5.2 * Math.log1p(score);
  return Math.max(8, Math.min(40, size));
}
```

**vis.js 物理引擎配置：**
```javascript
const options = {
  physics: {
    solver: "barnesHut",
    barnesHut: {
      gravitationalConstant: -52000,
      centralGravity: 0.02,
      springLength: 320,
      springConstant: 0.0035,
      damping: 0.95,
      avoidOverlap: 1.0
    },
    stabilization: { enabled: true, iterations: 2200, fit: true },
    minVelocity: 0.15
  },
  interaction: {
    hover: true,
    multiselect: true,
    navigationButtons: true,
    hideEdgesOnDrag: true
  },
  edges: { smooth: false }
};
```

**边样式：**
```javascript
// 同聚类内: 聚类颜色 + 66 透明度, width=1.15
// 跨聚类: "#94a3b844", width=0.6
```

**初始布局：** 参考 pyvis 脚本中的 `_node_xy()` 函数实现极坐标布局——按聚类分组，每个聚类占一个扇区，成员在扇区内散布。孤立节点放在外围。vis.js 的物理引擎会在初始位置基础上进一步优化布局。

---

## 十、JSON 字段映射参考

### 10.1 已确认的字段映射

以下字段映射已从实际 JSON 文件和代码中确认：

| 前端用途 | JSON 文件 | 字段路径 | 示例值 |
|---------|---------|---------|--------|
| 总分 | `run_summary.json` | `overall_score` | `7.27` |
| 等级 | `run_summary.json` | `grade` | `"C"` |
| 各维度最终分 | `run_summary.json` | `dimension_scores.{dim_id}.final_score` | `4` |
| 校正来源 | `run_summary.json` | `dimension_scores.{dim_id}.source` | `"original"` 或 `"corrected"` |
| 幻觉风险 | `run_summary.json` | `dimension_scores.{dim_id}.hallucination_risk` | `"low"` / `"medium"` / `"high"` |
| 校正方差 | `run_summary.json` | `dimension_scores.{dim_id}.variance` | `VarianceRecord` 或 `null` |
| 确定性指标值 | `run_summary.json` | `deterministic_metrics.{metric_id}` | `{"C3": 0.169, "C5": 0.189, ...}` |
| 指标定义 | `run.json` | `metrics_index.metrics.{id}` | 含 name, computed_by, consumed_by |
| 指标→Agent 映射 | `run.json` | `metrics_index.agent_dimensions` | 含 input_evidence, output_dimensions |
| C6 矛盾率 | `tools/c6_alignment.json` | `contradiction_rate` | `0.0` |
| C6 矛盾列表 | `tools/c6_alignment.json` | `contradictions` | `[{citation, sentence, ...}]` |
| C6 auto_fail | `tools/c6_alignment.json` | `auto_fail` | `false` |
| 引用边 | `tools/validation.json` | `real_citation_edges` | `[{source, target}]` |
| 引用验证 | `tools/validation.json` | `reference_validations` | `[{key, is_valid, metadata}]` |
| 聚类 | `tools/graph_analysis.json` | `cocitation_clustering.clusters` | `[{cluster_id, top_papers}]` |

### 10.2 需要 Claude Code 查看实际文件确认的字段

以下字段在设计文档中引用，但具体结构未完全确认。Claude Code 实现时需到对应源文件中查找确切字段名和格式：

| 前端用途 | 预期所在文件 | 需要确认的内容 |
|---------|------------|--------------|
| Agent 推理文本 | `nodes/04_verifier.json` 等 | Agent 输出的 JSON 结构中，`sub_scores.{dim_id}` 下的 `llm_reasoning`、`flagged_items`、`tool_evidence` 等字段的确切名称和格式。参考 `SurveyMAE_Plan_v3.md` §2.7 的 schema 设计 |
| Corrector 校正记录 | `nodes/05_corrector.json` | `corrections.{dim_id}` 下的 `original_score`、`corrected_score`、`variance.scores`、`variance.models_used` 等字段。参考 `SurveyMAE_Plan_v3.md` §2.6.4 |
| 时序分布数据 | `tools/analysis.json` | `year_distribution`（年份→引用数映射）的确切字段名和格式，以及 T1-T5 各指标值的存放位置 |
| 领域趋势基线 | `tools/trend_baseline.json` | 年份→发表量 的映射格式，用于时序图叠加线 |
| 结构分析数据 | `tools/analysis.json` | 章节级引用分布数据（每章节引用数），S1-S4 指标值的字段名 |
| 引用列表 | `tools/extraction.json` | `references` 数组中每条 ref 的字段结构（key / title / authors / year），以及 `citations` 数组的结构 |
| 缺失核心论文 | `tools/key_papers.json` | missing key papers 列表的字段名（可能是 `missing` / `missing_key_papers` / 其他），每条含标题/被引次数/年份/venue 的字段名 |
| G4 覆盖率 | `tools/key_papers.json` | `foundational_coverage_rate` 或类似字段名 |
| 聚类完整映射 | `tools/graph_analysis.json` | `cocitation_clustering.clusters[].top_papers` 是否包含该 cluster 的**全部**论文，还是只有 top-N。如果不完整，是否有单独的 `node_to_cluster` 映射字段 |
| 图分析指标 | `tools/graph_analysis.json` | G1-G6 各指标（graph_density, connected_component_count 等）在 JSON 中的确切路径 |

---

## 十二、实现记录（Phase 3 初版，2026-04-07）

> 本章记录第一轮前端实现的完成情况，供代码审查和后续迭代使用。

### 12.1 已确认的字段映射（实现阶段补充）

实现阶段通过阅读实际 JSON 文件，解决了 §10.2 中列出的所有待确认字段：

| 问题 | 实际结构 |
|------|---------|
| Agent `sub_scores` key 格式 | **缩写形式**（`V1`、`E1`、`R1` 等），非全称 |
| Agent 输出路径 | `output.agent_outputs.{verifier\|expert\|reader}.sub_scores.{dim_id}.{score, llm_reasoning, tool_evidence, flagged_items, variance, hallucination_risk}` |
| Corrector 校正路径 | `output.corrector_output.corrections.{dim_id}.{original_score, corrected_score, variance.{models_used, scores, median, std, high_disagreement}}` |
| 时序数据 | `analysis.json` → `temporal.{T1_year_span, T2_foundational_retrieval_gap, T3_peak_year_ratio, T4_temporal_continuity, T5_trend_alignment, year_distribution}` |
| 结构数据 | `analysis.json` → `structural.{S1_section_count, S2_citation_density, S3_citation_gini, S4_zero_citation_section_rate}` ；**无章节级分布数据**（S5 来自 graph_analysis） |
| 趋势基线 | `trend_baseline.json` → `yearly_counts.{年份: 发表量}` |
| 缺失核心论文 | `key_papers.json` → `missing_key_papers[].{title, year, citation_count, venue, doi, authors}`；覆盖率 → `coverage_rate` |
| G1-G6 原始路径 | 深层嵌套：`citation_graph_analysis.summary.density_connectivity.{density_global→G1, n_weak_components→G2, lcc_frac→G3, n_isolates→G6}`；`cocitation_clustering.n_clusters→G5`；G4 来自 `key_papers.json` |
| G1-G6 扁平化 | `run_summary.json` → `deterministic_metrics.{G1..G6, S5}` 已由 reporter 计算好，前端优先使用此处 |
| 聚类映射完整性 | `top_papers` 包含该 cluster **全部**论文（本次测试数据 n_edges=0，每个 cluster size=1）；有边时需实际验证 |

### 12.2 新增/修改的文件

#### 后端修改

| 文件 | 类型 | 变更说明 |
|------|------|---------|
| `src/agents/reporter.py` | 修改 | `process()` 中将 `run_summary.json` 改为保存至 `papers/{paper_id}/run_summary.json`；通过 `store._paper_cache` 获取 paper_id，失败时回退到 run 根目录 |
| `pyproject.toml` | 修改 | 新增依赖：`fastapi[standard]>=0.111.0`（含 uvicorn、python-multipart） |

#### 新增文件

| 文件 | 说明 |
|------|------|
| `src/web/__init__.py` | 空文件，使 `src.web` 成为 Python 包 |
| `src/web/app.py` | FastAPI 应用主体，见 §12.3 |
| `src/web/static/index.html` | 单页面 HTML，三阶段结构（上传/处理/结果） |
| `src/web/static/style.css` | 完整 CSS 样式，Design tokens + 各组件样式 |
| `src/web/static/app.js` | 完整前端逻辑，见 §12.4 |

### 12.3 `src/web/app.py` 函数说明

```
FastAPI 应用，提供薄层 API 服务。
项目根路径自动探测：兼容主仓库（src/web/）和 git worktree（worktrees/frontend/src/web/）两种布局。
```

**路径常量：**

- `_PROJECT_ROOT` — 自动探测的项目根目录（通过 `_detect_project_root()` 计算）
- `_RUNS_DIR` = `_PROJECT_ROOT / "output" / "runs"`
- `_UPLOADS_DIR` = `_PROJECT_ROOT / "uploads"`

**步骤信号文件（`_STEP_FILES`）：**

每个 `(step_number, relative_path)` 元组，`relative_path` 相对于 `paper_dir`。status 端点通过文件存在性推断当前步骤。

**内部函数：**

| 函数 | 签名 | 说明 |
|------|------|------|
| `_detect_project_root()` | `() → Path` | 探测项目根：若路径含 `worktrees`，截取其父路径；否则取 `_HERE.parent.parent` |
| `_find_inner_run_dir(outer_dir)` | `(Path) → Optional[Path]` | 在 bundle 目录下找内层 run 目录（排除 `logs/`、`reports/`） |
| `_get_paper_id(inner_dir)` | `(Path) → Optional[str]` | 读取 `index.json`，返回第一个 paper_id |
| `_check_completed(paper_dir, inner_dir)` | `(Path, Optional[Path]) → list[str]` | 返回已存在的输出文件相对路径列表；`run_summary.json` 兼容 paper_dir 和 inner_dir（旧版） |
| `_infer_step(completed)` | `(list[str]) → int` | 从已完成文件列表推断当前 pipeline 步骤号（1-7） |
| `_run_eval(eval_id, pdf_path)` | `async (str, str) → None` | 后台任务：重置全局 `_result_store`，调用 `run_evaluation()`，更新 `_evals` 状态字典 |

**API 端点：**

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 返回 `index.html` |
| `/run/{eval_id:path}` | GET | 返回 `index.html`（SPA 历史 run 入口） |
| `/api/upload` | POST | 接收 PDF，保存到 `uploads/`，计算 `eval_id`（同 `main.py` 的 `_generate_run_id` 公式），启动后台任务，返回 `{eval_id, filename}` |
| `/api/run/{eval_id}/status` | GET | 返回 `{eval_id, inner_run_id, paper_id, completed_files, current_step, total_steps, finished, status, error, step_labels}` |
| `/api/run/{eval_id}/files/{path:path}` | GET | 服务 `inner_run_dir/{path}` 的 JSON 文件；`run_summary.json` 兼容两个位置 |
| `/api/runs` | GET | 列出所有历史 run，返回 `{runs: [{eval_id, inner_run_id, paper_id, overall_score, grade, timestamp, source, finished}]}` |

### 12.4 `src/web/static/app.js` 函数说明

单文件 vanilla JS，约 650 行，无构建步骤。

**常量：**

| 常量 | 说明 |
|------|------|
| `DIMENSIONS` | 11 个维度的元数据：`label`（中文名）、`group`（factual/depth/readability）、`agent`、`evidenceKey`（关键工具指标）、`special`（特殊渲染标记） |
| `RUBRICS` | 各维度 1-5 分对应的 rubric 文本（从 `src/agents/output_schema.py` 翻译） |
| `DIM_ORDER` | 维度排列顺序：`['V1','V2','V4','E1','E2','E3','E4','R1','R2','R3','R4']` |
| `STEP_SIGNALS` | 步骤信号文件列表，与后端 `_STEP_FILES` 对应 |

**状态对象 `S`：**

单例全局状态，包含当前阶段、eval_id、paper_id、已加载数据（summary/verifier/expert/reader/corrector/analysis 等）、图表实例（radarChart/temporalChart/citationNetwork）。

**API 函数：**

| 函数 | 签名 | 说明 |
|------|------|------|
| `apiUpload(file)` | `(File) → Promise<{eval_id}>` | POST /api/upload |
| `apiStatus(evalId)` | `(str) → Promise<StatusObj>` | GET /api/run/{id}/status |
| `apiFile(evalId, paperId, path)` | `(str, str, str) → Promise<any>` | GET /api/run/{id}/files/papers/{pid}/{path} |
| `apiRunJson(evalId)` | `(str) → Promise<any>` | GET /api/run/{id}/files/run.json |
| `apiRuns()` | `() → Promise<{runs}>` | GET /api/runs |

**阶段管理：**

| 函数 | 说明 |
|------|------|
| `setPhase(phase)` | 切换 `phase-upload` / `phase-processing` / `phase-results` 的显示 |
| `initUpload()` | 初始化上传区（拖拽、文件选择、按钮），调用 `loadHistory()` |
| `loadHistory()` | 从 `/api/runs` 加载历史记录，渲染到上传页底部 |
| `startEval(evalId, skipProcessing?)` | 开始跟踪一次评测：更新 URL、切换到处理阶段、启动轮询 |
| `startPolling(evalId)` | 每 2 秒调用 `poll()`，直到 finished=true 或 error |
| `poll(evalId)` | 调用 status API，更新步骤显示，触发渐进数据加载 |
| `switchToResults()` | 并行加载所有 JSON 数据，切换到结果阶段并调用 `renderResults()` |
| `newEval()` | 重置全局状态，返回上传页面 |

**渲染函数：**

| 函数 | 说明 |
|------|------|
| `renderSteps(currentStep, completed)` | 渲染进度步骤列表（done/active/pending 三态） |
| `renderResults()` | 总入口：依次调用 A/B/C/D 四个区域的渲染函数 |
| `renderOverview()` | 渲染区域 A：总分、等级（带颜色）、雷达图、摘要、关键警告 |
| `renderRadar(sum)` | 使用 ECharts 渲染 11 维度雷达图；节点颜色按 `hallucination_risk` 着色 |
| `renderDimensionCards()` | 渲染区域 B：按 group 将 11 个维度卡片填入三个分组容器 |
| `buildDimCard(dimId, meta, dimScore, subScore, corrections)` | 构建单个维度卡片 DOM（三层：头部/推理/原始数据） |
| `evidenceSummaryHtml(dimId, subScore, dimScore)` | 返回卡片头部的工具证据摘要 HTML（按维度特殊格式化） |
| `toggleCard(dimId)` | 切换维度卡片第二层（推理详情）的展开/折叠 |
| `toggleRaw(dimId)` | 切换维度卡片第三层（原始 JSON）的展开/折叠 |
| `renderToolPanels()` | 渲染区域 C 所有工具面板（调用以下 6 个函数） |
| `renderExtractionPanel()` | C1：章节列表、参考文献表（前 20 条） |
| `renderValidationPanel()` | C2：验证汇总统计、引用验证表（前 30 条） |
| `renderC6Panel()` | C3：C6 矛盾统计、矛盾案例列表 |
| `renderTemporalPanel()` | C4：T/S 系列指标表 + 时序双线图 |
| `renderTemporalChart(temporal, trendBaseline)` | ECharts 柱状图（综述引用）+ 折线图（领域趋势，归一化） |
| `renderGraphPanel()` | C6：G 系列指标表，触发引用网络图渲染 |
| `renderCitationGraph()` | vis.js 引用网络图：节点着色（按聚类/孤立/未知）、节点大小（log 度数） |
| `renderKeyPapersPanel()` | C7：G4 覆盖率统计、缺失核心文献列表 |
| `renderSysInfo()` | 区域 D：run 元信息、metrics_index 原始 JSON、run_summary 原始 JSON |

**工具函数：**

| 函数 | 说明 |
|------|------|
| `gradeColor(g)` | 等级 → 颜色（A绿/B蓝/C黄/D橙/F红） |
| `scoreColor(s)` | 1-5 分值 → 颜色 |
| `pct(v)` | 小数 → 百分比字符串 |
| `escHtml(s)` | HTML 转义 |
| `jumpTo(id)` | 平滑滚动到区域，更新导航栏激活状态 |
| `openPanel(panelId)` | 打开指定工具面板并滚动到 |
| `showPartialValidation()` / `showPartialTemporal()` | 处理阶段的渐进提示文本 |

### 12.5 启动方式

```bash
# 安装依赖（如尚未执行）
cd worktrees/frontend
uv sync

# 启动 Web 服务
uv run uvicorn src.web.app:app --host 0.0.0.0 --port 8000

# 访问页面
# 上传新 PDF：http://localhost:8000/
# 查看历史 run：http://localhost:8000/run/{eval_id}
# 示例（已有测试数据）：http://localhost:8000/run/20260406T161703Z_53317b7e

# 原 CLI 模式不受影响
uv run python -m src.main path/to/survey.pdf
```

**注意：** 服务必须从 `worktrees/frontend/` 目录启动（`_detect_project_root()` 依赖路径中含 `worktrees` 来定位主项目根）。`output/` 目录不被 git 追踪，评测结果存放在主项目目录 `output/runs/` 下。

### 12.6 已实现功能（P0）

| 功能 | 状态 |
|------|------|
| PDF 上传 + 后台启动评测 | ✅ |
| 2 秒轮询进度，步骤列表 done/active/pending 三态 | ✅ |
| 渐进式中间结果提示（处理阶段） | ✅ 基础版（文字提示验证率/时序结果） |
| 区域 A：总分 + 等级 + 雷达图（11 维度，hallucination_risk 着色） | ✅ |
| 区域 A：关键警告（C6 auto_fail、C5 低、Corrector 大幅校正、high_disagreement） | ✅ |
| 区域 B：11 个维度卡片（三层展开：头部/推理/原始） | ✅ |
| 区域 B：卡片头部工具证据摘要 | ✅ |
| 区域 B：Rubric 等级描述 | ✅ |
| 区域 B：Corrector 校正信息展示 | ✅ |
| 区域 B：V2 矛盾率 inline 预览 + 跳转链接 | ✅ |
| 区域 B：E1 缺失论文 inline 预览 + 跳转链接 | ✅ |
| 区域 C1：PDF 解析（章节列表、参考文献表） | ✅ |
| 区域 C2：引用验证汇总 + 详情表 | ✅ |
| 区域 C3：C6 矛盾分析 + 矛盾案例列表 | ✅ |
| 区域 C4：时序分布双线图（ECharts）+ T/S 指标表 | ✅ |
| 区域 C6：引用网络图（vis.js，聚类着色，度数缩放） | ✅ |
| 区域 C7：核心文献覆盖，缺失论文列表 | ✅ |
| 区域 D：run 元信息 + metrics_index + 原始 JSON | ✅ |
| 历史 run 列表（上传页）+ URL 直达 `/run/{eval_id}` | ✅ |

### 12.7 未实现功能（P1/P2）

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 章节引用密度条形图（区域 C5） | P1 | `analysis.json` 目前只有聚合 S1-S4，无章节级分布。需后端在 `CitationAnalyzer` 中输出 `section_citation_counts` 字段 |
| 引用验证状态饼图（区域 C2） | P1 | 当前只有数字，ECharts 饼图未实现 |
| 雷达图节点点击 → 跳转维度卡片 | P1 | ECharts radar 的 click 事件映射到维度卡片滚动，框架已预留但未接线 |
| 引用网络图与维度卡片联动高亮（missing_key_papers） | P1 | vis.js 已渲染，但点击节点跳转验证详情的交互未实现 |
| 处理阶段渐进式结果（已完成步骤可展开查看中间结果） | P1 | 当前只有文字提示，缺 inline 结果展示卡片 |
| 数据流图（指标→Agent 映射可视化） | P2 | 区域 D 显示原始 JSON，可视化图未实现 |

### 12.8 已知 Bug / 待修复问题

| 问题 | 严重程度 | 说明 |
|------|---------|------|
| 全局 `_result_store` 并发冲突 | 中 | `src/graph/builder.py` 使用全局单例，并发上传两个 PDF 会冲突。当前设计为单用户 demo，暂不处理 |
| `analysis.json` 无章节级数据，S4/S5 显示不完整 | 低 | S4（零引用章节率）有值但无法展示具体是哪些章节；S5 显示为 0（来自图分析） |
| 时序图归一化：领域趋势基线全为 0 时曲线消失 | 低 | `trend_baseline.json` 在 API 调用失败时返回全 0，趋势线不渲染（但不崩溃） |
| `cocitation_clustering.top_papers` 完整性 | 低 | 本次测试数据 n_edges=0，每 cluster size=1，`top_papers` 恰好完整。有实际引用边时需验证所有节点是否均被覆盖 |
| vis.js CDN 依赖 | 低 | 离线环境无法渲染引用网络图，需改为本地资源 |
| `eval_id` 预计算与实际 run_id 的时间戳偏差 | 低 | 上传端点计算 `eval_id` 后启动后台任务，`main.py` 内重新计算 run_id，若跨秒边界则目录名可能不一致（概率极低） |
