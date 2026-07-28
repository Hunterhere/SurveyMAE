'use strict';
/* ═══════════════════════════════════════════════════════════════════
   SurveyMAE Frontend – app.js
   Single-file vanilla JS application (no build step)
   ═══════════════════════════════════════════════════════════════════ */

// ── Constants ────────────────────────────────────────────────────────────────

const DIMENSIONS = {
  V1: { label: '引用存在性',    group: 'factual',      agent: 'verifier', evidenceKey: 'C5' },
  V2: { label: '引用-断言对齐', group: 'factual',      agent: 'verifier', evidenceKey: 'C6', special: 'c6' },
  V4: { label: '内部一致性',    group: 'factual',      agent: 'verifier' },
  E1: { label: '核心文献覆盖',  group: 'depth',        agent: 'expert',   evidenceKey: 'G4', special: 'keypapers' },
  E2: { label: '方法分类',      group: 'depth',        agent: 'expert',   evidenceKey: 'S5' },
  E3: { label: '技术准确性',    group: 'depth',        agent: 'expert' },
  E4: { label: '批判性分析',    group: 'depth',        agent: 'expert' },
  R1: { label: '时效性',        group: 'readability',  agent: 'reader',   evidenceKey: 'T5', special: 'temporal' },
  R2: { label: '信息分布',      group: 'readability',  agent: 'reader',   evidenceKey: 'S3' },
  R3: { label: '结构清晰度',    group: 'readability',  agent: 'reader',   evidenceKey: 'S5' },
  R4: { label: '文字质量',      group: 'readability',  agent: 'reader' },
};

const DIM_ORDER = ['V1', 'V2', 'V4', 'E1', 'E2', 'E3', 'E4', 'R1', 'R2', 'R3', 'R4'];

const GROUP_CONTAINERS = {
  factual:      'cards-factual',
  depth:        'cards-depth',
  readability:  'cards-readability',
};

const RUBRICS = {
  V1: { 5:'C5 ≥ 0.95', 4:'C5 ≥ 0.85', 3:'C5 ≥ 0.70', 2:'C5 ≥ 0.50', 1:'C5 < 0.50' },
  V2: { 5:'≥90% 引用-断言对支持', 4:'70–89% 支持，少量局部支持', 3:'50–69% 支持',
        2:'30–49% 支持，大量不匹配', 1:'<30% 支持或存在严重误引' },
  V4: { 5:'无矛盾检出', 4:'轻微不一致，容易解释', 3:'部分矛盾需澄清',
        2:'多处矛盾影响可信度', 1:'严重矛盾使综述失去可靠性' },
  E1: { 5:'各子领域聚类均有高被引中心文献，主题高度相关',
        4:'≥80% 聚类有中心文献，核心领域覆盖良好',
        3:'≥60% 聚类有中心文献，部分子领域可能缺失',
        2:'<60% 聚类有中心文献，核心领域缺乏基础文献',
        1:'多数聚类缺乏中心，或引文图过于稀疏无法形成有效子领域' },
  E2: { 5:'S5 (NMI) 高，分类与引用聚类高度吻合', 4:'良好对齐，少许偏差',
        3:'部分不对齐但尚可接受', 2:'显著不对齐', 1:'分类与引用结构相悖' },
  E3: { 5:'无技术错误', 4:'轻微技术不准确', 3:'部分错误但不影响理解',
        2:'频繁技术错误', 1:'严重技术误解' },
  E4: { 5:'系统性比较，趋势清晰，详细分析局限', 4:'良好比较，有一定分析',
        3:'有比较但主要是罗列', 2:'几乎只有罗列，分析极少', 1:'纯摘要，没有分析' },
  R1: { 5:'T5 ≥ 0.7，T2 ≤ 2年，T4 ≤ 1年', 4:'T5 ≥ 0.5，T4 ≤ 2年，覆盖合理',
        3:'T5 ≥ 0.3，有小的缺口', 2:'T5 < 0.3 或 T4 ≥ 3年', 1:'引用集中在 1-2 年或缺少基础工作' },
  R2: { 5:'均衡分布，重点章节聚焦合理', 4:'基本均衡，轻微不均',
        3:'有不均衡但有理由', 2:'显著不均衡', 1:'严重不均衡影响完整性' },
  R3: { 5:'层次清晰，S5 (NMI) 高', 4:'结构良好，轻微问题',
        3:'结构尚可', 2:'结构不清晰', 1:'结构混乱，难以跟读' },
  R4: { 5:'语言流畅，术语一致', 4:'语言良好，轻微问题',
        3:'尚可，有些不一致', 2:'频繁语言问题', 1:'语言质量差，难以理解' },
};

const STEP_ICONS = { done: '✓', active: '', pending: '○', error: '✗' };
const STEP_LABELS = {
  1: 'PDF 解析', 2: '证据收集', 3: '证据分发',
  4: 'Agent 评估', 5: '校正投票', 6: '评分聚合', 7: '报告生成',
};
// Which files signal a step complete (step, relative path from paper_dir)
const STEP_SIGNALS = [
  [1, 'tools/extraction.json'],
  [2, 'tools/validation.json'],
  [2, 'tools/analysis.json'],
  [2, 'tools/graph_analysis.json'],
  [3, 'nodes/03_evidence_dispatch.json'],
  [4, 'nodes/04_verifier.json'],
  [4, 'nodes/04_expert.json'],
  [4, 'nodes/04_reader.json'],
  [5, 'nodes/05_corrector.json'],
  [6, 'nodes/06_aggregator.json'],
  [7, 'run_summary.json'],
];

// ── i18n ──────────────────────────────────────────────────────────────────────

let LANG = localStorage.getItem('surveymae-lang') || 'zh';

const I18N = {
  zh: {
    // Page
    page: { title:'SurveyMAE — 学术综述质量评测' },
    // Dimension labels
    dim: { V1:'引用存在性', V2:'引用-断言对齐', V4:'内部一致性', E1:'核心文献覆盖', E2:'方法分类', E3:'技术准确性', E4:'批判性分析', R1:'时效性', R2:'信息分布', R3:'结构清晰度', R4:'文字质量' },
    // Rubrics
    rubric: {
      V1: { 5:'C5 ≥ 0.95', 4:'C5 ≥ 0.85', 3:'C5 ≥ 0.70', 2:'C5 ≥ 0.50', 1:'C5 < 0.50' },
      V2: { 5:'≥90% 引用-断言对支持', 4:'70–89% 支持，少量局部支持', 3:'50–69% 支持', 2:'30–49% 支持，大量不匹配', 1:'<30% 支持或存在严重误引' },
      V4: { 5:'无矛盾检出', 4:'轻微不一致，容易解释', 3:'部分矛盾需澄清', 2:'多处矛盾影响可信度', 1:'严重矛盾使综述失去可靠性' },
      E1: { 5:'各子领域聚类均有高被引中心文献，主题高度相关', 4:'≥80% 聚类有中心文献，核心领域覆盖良好', 3:'≥60% 聚类有中心文献，部分子领域可能缺失', 2:'<60% 聚类有中心文献，核心领域缺乏基础文献', 1:'多数聚类缺乏中心，或引文图过于稀疏无法形成有效子领域' },
      E2: { 5:'S5 (NMI) 高，分类与引用聚类高度吻合', 4:'良好对齐，少许偏差', 3:'部分不对齐但尚可接受', 2:'显著不对齐', 1:'分类与引用结构相悖' },
      E3: { 5:'无技术错误', 4:'轻微技术不准确', 3:'部分错误但不影响理解', 2:'频繁技术错误', 1:'严重技术误解' },
      E4: { 5:'系统性比较，趋势清晰，详细分析局限', 4:'良好比较，有一定分析', 3:'有比较但主要是罗列', 2:'几乎只有罗列，分析极少', 1:'纯摘要，没有分析' },
      R1: { 5:'T5 ≥ 0.7，T2 ≤ 2年，T4 ≤ 1年', 4:'T5 ≥ 0.5，T4 ≤ 2年，覆盖合理', 3:'T5 ≥ 0.3，有小的缺口', 2:'T5 < 0.3 或 T4 ≥ 3年', 1:'引用集中在 1-2 年或缺少基础工作' },
      R2: { 5:'均衡分布，重点章节聚焦合理', 4:'基本均衡，轻微不均', 3:'有不均衡但有理由', 2:'显著不均衡', 1:'严重不均衡影响完整性' },
      R3: { 5:'层次清晰，S5 (NMI) 高', 4:'结构良好，轻微问题', 3:'结构尚可', 2:'结构不清晰', 1:'结构混乱，难以跟读' },
      R4: { 5:'语言流畅，术语一致', 4:'语言良好，轻微问题', 3:'尚可，有些不一致', 2:'频繁语言问题', 1:'语言质量差，难以理解' },
    },
    // Steps
    step: { 1:'PDF 解析', 2:'证据收集', 3:'证据分发', 4:'Agent 评估', 5:'校正投票', 6:'评分聚合', 7:'报告生成' },
    // Upload
    upload: { subtitle:'多智能体学术综述质量评测系统', title:'上传文献', drag:'拖放 PDF 文件到此处', sub:'或者选择本地文件', select:'选择文件', start:'开始评测', uploading:'上传中…', failPrefix:'上传失败：' },
    // History
    history: { title:'历史评测记录', empty:'暂无评测记录', loadError:'加载历史记录失败' },
    // Processing
    processing: { title:'评测进行中', waiting:'等待 PDF 解析完成…', errorPrefix:'评测过程出错', failPrefix:'✗ 评测失败：' },
    // Navigation
    nav: { overview:'概览', dimensions:'维度评分', tools:'工具详情', sysinfo:'系统信息', back:'← 返回' },
    // Overview
    overview: { title:'诊断概览', summaryTitle:'评测摘要', totalScore:'TOTAL SCORE / 5.0', strengths:'Strengths', limitations:'Limitations', complete:'评测完成，见维度详情。' },
    // Dimension cards
    dims: {
      factual:'事实性验证', depth:'学术深度', readability:'可读性与信息量',
      dimensionsTitle:'维度评分详情',
      corrected:'已校正',
      agentReasoning:'Agent 推理', evidenceSummary:'证据摘要', flaggedItems:'标记项目',
      correctorAdj:'Corrector 校正', model:'模型', subScores:'各分',
      c6Title:'C6 引用-断言对齐', contradictionRate:'矛盾率', pairs:'对', viewContradictions:'查看完整矛盾列表 →',
      clusterAnchor:'聚类中心分析', clustersWithAnchor:'{0}/{1} 聚类有中心', moreClusters:'… 还有 {0} 个聚类', viewCluster:'查看完整聚类分析 →',
      missingOld:'缺失核心文献（旧版数据，前{0}篇）', viewList:'查看完整列表 →',
      noClusterTitle:'聚类中心分析', noClusterMsg:'(!)引文图无有效聚类结构，G4 指标不可用，评分基于定性评估。', viewDetails:'查看详情 →',
      viewRaw:'查看原始数据 ▾',
    },
    // Tool panels
    panel: {
      extraction:'C1 · PDF 解析结果', validation:'C2 · 引用验证', c6:'C3 · 引用-断言对齐（C6）',
      temporal:'C4 · 时序分布分析', graph:'C6 · 引用网络图', keypapers:'G4 · 聚类中心文献分析',
      sysinfo:'系统信息与原始数据',
    },
    // Tool evidence
    evidence: {
      C5:'C5 验证率', C6_rate:'C6 矛盾率', C6_samples:'C6 矛盾样本', items:'条', example:'示例',
      G4:'G4 聚类中心覆盖率', anchorClusters:'中心聚类 / 总聚类', missingOld:'缺失文献（旧格式）', papers:'篇',
      fallbackItem:'项', fallbackObj:'对象',
    },
    // Extraction panel
    extraction: { refs:'参考文献', citations:'引用实例', sections:'章节', sectionList:'章节列表', refList:'参考文献（前20）', colNum:'编号', colTitle:'标题', colAuthor:'作者', colYear:'年份' },
    // Validation panel
    validation: { passed:'通过验证', failed:'未通过', total:'总计', C5:'C5 验证率', C3:'C3 孤立引用率', colKey:'引用键', colTitle:'标题', colYear:'年份', colStatus:'状态', colConf:'置信度', pass:'通过', fail:'失败' },
    // C6 panel
    c6: { totalPairs:'总对数', support:'支持', contradict:'矛盾', insufficient:'信息不足', rate:'矛盾率', insufficientNote:'{0} 对因缺少摘要而标记为 insufficient', noContradictions:'无矛盾案例。', listTitle:'矛盾案例列表' },
    // Temporal panel
    temporal: {
      T1:'T1 时间跨度（年）', T2:'T2 基础文献缺口', T3:'T3 近年引用比', T4:'T4 最大连续空白', T5:'T5 趋势对齐（r）',
      S1:'S1 章节数', S2:'S2 引用密度', S3:'S3 Gini 系数', S4:'S4 零引用章节率',
      barName:'综述引用分布', lineName:'领域发表趋势', y1:'引用数', y2:'归一化趋势',
    },
    // Graph panel
    graph: {
      nodes:'节点数', edges:'边数', G1:'G1 密度', G2:'G2 连通分量', G3:'G3 最大分量比', G4:'G4 聚类中心覆盖率', G6:'G6 孤立节点率',
      tooltipYear:'年份', tooltipValid:'验证', visFail:'vis.js 库加载失败，请检查网络连接。', nodeEdge:'{0} 节点 · {1} 边',
    },
    // Key papers panel
    keypapers: {
      G4:'G4 覆盖率', G4Coverage:'G4 聚类中心覆盖率', anchorClusters:'有中心聚类', noAnchorClusters:'无中心聚类', threshold:'引用量阈值',
      noClusterMsg:'引文图无有效共被引聚类结构，G4 指标不可用。<br>ExpertAgent 已基于定性评估对 E1 进行评分。',
      anchorDef:'中心定义：聚类中心文献（最高 PageRank）引用量 ≥ {0}，表示该子领域有一篇公认的高影响力论文。相关性由 ExpertAgent 综合判断。',
      missingTitle:'(!)缺少中心的聚类（{0} 个）', cited:'被引', times:'次', years:'年', clusterSize:'聚类规模', papersUnit:'篇',
      allAnchored:'所有聚类均有基础中心文献。',
      allCenters:'所有聚类中心文献（{0} 个，按引用量降序）', anchor:'[Center]', noAnchor:'[No center]',
    },
    // Sysinfo
    sysinfo: { field:'字段', value:'值', timestamp:'时间戳', pdfSource:'PDF 来源', schemaVer:'Schema 版本', metricsIndex:'指标定义（metrics_index）', rawSummary:'run_summary.json 原始数据' },
    // Risk
    risk: { deterministic:'确定性', llm:'LLM判断', llmHigh:'LLM判断(高风险)' },
    // PDF viewer
    pdf: { loadFail:'无法加载 PDF 预览', notFound:'未找到 PDF 文件路径', cannotDisplay:'无法直接显示 PDF', downloadHint:'浏览器不支持 PDF 预览，请<a href="{0}">点击下载</a>', loading:'PDF 预览加载中…', hint:'如果无法显示，请检查文件路径' },
    // Lang
    lang: { label:'EN' },
    // Common
    common: { cited:'被引' },
    // C6 alerts
    alert: {
      autoFail:'C6 自动失败：引用矛盾率过高，V2 被强制评为 1 分',
      lowVerification:'引用验证率极低 (C5 = {0})，可能存在大量虚构引用',
      correctorAdjust:'{0} 被 Corrector 校正幅度 ≥ 2 分',
      highDisagreement:'部分维度模型间存在较大分歧（high_disagreement=true）',
    },
  },
  en: {
    page: { title:'SurveyMAE — Academic Survey Quality Evaluation' },
    dim: { V1:'Citation Existence', V2:'Citation-Claim Alignment', V4:'Internal Consistency', E1:'Core Literature Coverage', E2:'Method Taxonomy', E3:'Technical Accuracy', E4:'Critical Analysis', R1:'Timeliness', R2:'Information Distribution', R3:'Structural Clarity', R4:'Language Quality' },
    rubric: {
      V1: { 5:'C5 ≥ 0.95', 4:'C5 ≥ 0.85', 3:'C5 ≥ 0.70', 2:'C5 ≥ 0.50', 1:'C5 < 0.50' },
      V2: { 5:'≥90% citation-claim pairs supported', 4:'70–89% supported, minor gaps', 3:'50–69% supported', 2:'30–49% supported, many mismatches', 1:'<30% supported or severe misrepresentation' },
      V4: { 5:'No contradictions detected', 4:'Minor inconsistencies, easily explained', 3:'Some contradictions need clarification', 2:'Multiple contradictions affect credibility', 1:'Severe contradictions undermine reliability' },
      E1: { 5:'All subfield clusters have high-citation center papers, topics highly relevant', 4:'≥80% clusters have centers, core areas well covered', 3:'≥60% clusters have centers, some subfields may be missing', 2:'<60% clusters have centers, core areas lack foundational papers', 1:'Most clusters lack centers, or citation graph too sparse to form subfields' },
      E2: { 5:'S5 (NMI) high, taxonomy aligns strongly with citation clusters', 4:'Good alignment, minor deviations', 3:'Partial misalignment but acceptable', 2:'Significant misalignment', 1:'Taxonomy contradicts citation structure' },
      E3: { 5:'No technical errors', 4:'Minor technical inaccuracies', 3:'Some errors but not misleading', 2:'Frequent technical errors', 1:'Severe technical misunderstandings' },
      E4: { 5:'Systematic comparison, clear trends, detailed limitation analysis', 4:'Good comparison with some analysis', 3:'Some comparison but mostly listing', 2:'Mostly listing, minimal analysis', 1:'Pure summary, no analysis' },
      R1: { 5:'T5 ≥ 0.7, T2 ≤ 2yr, T4 ≤ 1yr', 4:'T5 ≥ 0.5, T4 ≤ 2yr, reasonable coverage', 3:'T5 ≥ 0.3, minor gaps', 2:'T5 < 0.3 or T4 ≥ 3yr', 1:'Citations concentrated in 1–2 years or missing foundational work' },
      R2: { 5:'Balanced distribution, key sections well focused', 4:'Mostly balanced, minor unevenness', 3:'Uneven but justifiable', 2:'Significantly uneven', 1:'Severe imbalance affecting completeness' },
      R3: { 5:'Clear hierarchy, S5 (NMI) high', 4:'Good structure, minor issues', 3:'Acceptable structure', 2:'Unclear structure', 1:'Chaotic structure, hard to follow' },
      R4: { 5:'Fluent language, consistent terminology', 4:'Good language, minor issues', 3:'Adequate, some inconsistencies', 2:'Frequent language problems', 1:'Poor language quality, hard to understand' },
    },
    step: { 1:'PDF Parsing', 2:'Evidence Collection', 3:'Evidence Dispatch', 4:'Agent Evaluation', 5:'Correction Voting', 6:'Score Aggregation', 7:'Report Generation' },
    upload: { subtitle:'Multi-Agent Academic Survey Quality Evaluation System', title:'Upload Paper', drag:'Drop PDF file here', sub:'or browse from local disk', select:'Choose File', start:'Start Evaluation', uploading:'Uploading…', failPrefix:'Upload failed: ' },
    history: { title:'Evaluation History', empty:'No evaluation records', loadError:'Failed to load history' },
    processing: { title:'Evaluation in Progress', waiting:'Waiting for PDF parsing…', errorPrefix:'Evaluation error', failPrefix:'✗ Evaluation failed: ' },
    nav: { overview:'Overview', dimensions:'Dimensions', tools:'Tool Details', sysinfo:'System Info', back:'← Back' },
    overview: { title:'Diagnostic Overview', summaryTitle:'Evaluation Summary', totalScore:'TOTAL SCORE / 5.0', strengths:'Strengths', limitations:'Limitations', complete:'Evaluation complete. See dimension details below.' },
    dims: {
      factual:'Factual Verification', depth:'Academic Depth', readability:'Readability & Information',
      dimensionsTitle:'Dimension Scores',
      corrected:'Corrected',
      agentReasoning:'Agent Reasoning', evidenceSummary:'Evidence Summary', flaggedItems:'Flagged Items',
      correctorAdj:'Corrector Adjustment', model:'Models', subScores:'Sub-scores',
      c6Title:'C6 Citation-Claim Alignment', contradictionRate:'Contradiction Rate', pairs:'pairs', viewContradictions:'View Full Contradiction List →',
      clusterAnchor:'Cluster Center Analysis', clustersWithAnchor:'{0}/{1} clusters have centers', moreClusters:'… {0} more clusters', viewCluster:'View Full Cluster Analysis →',
      missingOld:'Missing Core Papers (legacy data, top {0})', viewList:'View Full List →',
      noClusterTitle:'Cluster Center Analysis', noClusterMsg:'(!)No valid co-citation cluster structure found. G4 metric unavailable; E1 scored by qualitative assessment.', viewDetails:'View Details →',
      viewRaw:'View Raw Data ▾',
    },
    panel: {
      extraction:'C1 · PDF Extraction Results', validation:'C2 · Citation Validation', c6:'C3 · Citation-Claim Alignment (C6)',
      temporal:'C4 · Temporal Distribution Analysis', graph:'C6 · Citation Network Graph', keypapers:'G4 · Cluster-Center Literature Analysis',
      sysinfo:'System Information & Raw Data',
    },
    evidence: {
      C5:'C5 Verification Rate', C6_rate:'C6 Contradiction Rate', C6_samples:'C6 Contradiction Samples', items:'items', example:'Example',
      G4:'G4 Cluster-Center Coverage', anchorClusters:'Center Clusters / Total', missingOld:'Missing Papers (legacy)', papers:'papers',
      fallbackItem:'items', fallbackObj:'object',
    },
    extraction: { refs:'References', citations:'Citation Instances', sections:'Sections', sectionList:'Section List', refList:'References (Top 20)', colNum:'#', colTitle:'Title', colAuthor:'Author', colYear:'Year' },
    validation: { passed:'Passed', failed:'Failed', total:'Total', C5:'C5 Verification Rate', C3:'C3 Orphan Citation Rate', colKey:'Ref Key', colTitle:'Title', colYear:'Year', colStatus:'Status', colConf:'Confidence', pass:'Pass', fail:'Fail' },
    c6: { totalPairs:'Total Pairs', support:'Support', contradict:'Contradict', insufficient:'Insufficient', rate:'Contradiction Rate', insufficientNote:'{0} pairs marked insufficient due to missing abstracts', noContradictions:'No contradictions found.', listTitle:'Contradiction List' },
    temporal: {
      T1:'T1 Time Span (years)', T2:'T2 Foundational Gap', T3:'T3 Recent Citation Ratio', T4:'T4 Maximum Consecutive Gap', T5:'T5 Trend Alignment (r)',
      S1:'S1 Section Count', S2:'S2 Citation Density', S3:'S3 Gini Coefficient', S4:'S4 Zero-Citation Section Rate',
      barName:'Survey Citation Distribution', lineName:'Field Publication Trend', y1:'Citation Count', y2:'Normalized Trend',
    },
    graph: {
      nodes:'Nodes', edges:'Edges', G1:'G1 Density', G2:'G2 Components', G3:'G3 LCC Fraction', G4:'G4 Cluster-Center Coverage', G6:'G6 Isolate Rate',
      tooltipYear:'Year', tooltipValid:'Valid', visFail:'vis.js library failed to load. Please check your network connection.', nodeEdge:'{0} nodes · {1} edges',
    },
    keypapers: {
      G4:'G4 Coverage', G4Coverage:'G4 Cluster-Center Coverage', anchorClusters:'Centered Clusters', noAnchorClusters:'Uncentered Clusters', threshold:'Citation Threshold',
      noClusterMsg:'No valid co-citation cluster structure found. G4 metric unavailable.<br>ExpertAgent scored E1 based on qualitative assessment.',
      anchorDef:'Center definition: the highest-PageRank center paper in a cluster with ≥ {0} citations, indicating a recognized high-impact paper in that subfield. Relevance judged by ExpertAgent.',
      missingTitle:'(!)Clusters Without Centers ({0})', cited:'cited', times:'times', years:'years', clusterSize:'cluster size', papersUnit:'papers',
      allAnchored:'All clusters have foundational center papers.',
      allCenters:'All Cluster Center Papers ({0}, sorted by citation count)', anchor:'[Center]', noAnchor:'[No center]',
    },
    sysinfo: { field:'Field', value:'Value', timestamp:'Timestamp', pdfSource:'PDF Source', schemaVer:'Schema Version', metricsIndex:'Metrics Index', rawSummary:'run_summary.json Raw Data' },
    risk: { deterministic:'Deterministic', llm:'LLM Judgment', llmHigh:'LLM Judgment (High Risk)' },
    pdf: { loadFail:'Failed to load PDF preview', notFound:'PDF file path not found', cannotDisplay:'Cannot display PDF directly', downloadHint:'Browser does not support PDF preview. <a href="{0}">Click to download</a>', loading:'Loading PDF preview…', hint:'If the PDF cannot be displayed, please check the file path' },
    lang: { label:'中文' },
    common: { cited:'cited' },
    alert: {
      autoFail:'C6 Auto-Fail: contradiction rate too high; V2 forced to score 1',
      lowVerification:'Very low citation verification rate (C5 = {0}); possible fabricated citations',
      correctorAdjust:'{0} adjusted by Corrector ≥ 2 points',
      highDisagreement:'High disagreement between models on some dimensions (high_disagreement=true)',
    },
  }
};

function t(key, ...args) {
  const keys = key.split('.');
  let val = I18N[LANG];
  for (const k of keys) {
    if (val == null) return key;
    val = val[k];
  }
  if (typeof val !== 'string') return key;
  return val.replace(/\{(\d+)\}/g, (_, i) => args[i] != null ? args[i] : '');
}

function updateDomI18n() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.getAttribute('data-i18n'));
  });
  document.querySelectorAll('[data-i18n-html]').forEach(el => {
    el.innerHTML = t(el.getAttribute('data-i18n-html'));
  });
  document.documentElement.lang = LANG === 'en' ? 'en' : 'zh-CN';
}

function switchLang(lang) {
  localStorage.setItem('surveymae-lang', lang);
  location.reload();
}

// ── Application state ────────────────────────────────────────────────────────

const S = {
  phase: 'upload',
  evalId: null,
  paperId: null,
  innerRunId: null,
  pollTimer: null,
  completedFiles: [],
  // loaded data
  summary: null,
  verifier: null,
  expert: null,
  reader: null,
  corrector: null,
  analysis: null,
  trendBaseline: null,
  validation: null,
  c6: null,
  keyPapers: null,
  graphAnalysis: null,
  extraction: null,
  runJson: null,
  // chart instances
  radarChart: null,
  temporalChart: null,
  citationNetwork: null,
  // which panels have been rendered
  rendered: new Set(),
};

// ── Utilities ────────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html !== undefined) e.innerHTML = html; return e; };
const pct = v => v == null ? 'N/A' : `${(v * 100).toFixed(1)}%`;
const fmt1 = v => v == null ? 'N/A' : v.toFixed(1);
const fmt3 = v => v == null ? 'N/A' : v.toFixed(3);

function gradeColor(g) {
  return { A:'#4A7C59', B:'#2C3E50', C:'#B07D3A', D:'#8B3A3A', F:'#8B3A3A' }[g] || '#999999';
}

function scoreColor(s) {
  if (s >= 4.5) return '#4A7C59';
  if (s >= 3.5) return '#2C3E50';
  if (s >= 2.5) return '#B07D3A';
  return '#8B3A3A';
}

// ── API helpers ──────────────────────────────────────────────────────────────

async function apiUpload(file) {
  const fd = new FormData();
  fd.append('file', file);
  const r = await fetch('/api/upload', { method: 'POST', body: fd });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function apiStatus(evalId) {
  const r = await fetch(`/api/run/${evalId}/status`);
  return r.json();
}

async function apiFile(evalId, paperId, path) {
  const url = `/api/run/${evalId}/files/papers/${paperId}/${path}`;
  const r = await fetch(url);
  if (!r.ok) return null;
  return r.json();
}

async function apiRunJson(evalId) {
  const r = await fetch(`/api/run/${evalId}/files/run.json`);
  if (!r.ok) return null;
  return r.json();
}

async function apiRuns() {
  const r = await fetch('/api/runs');
  return r.json();
}

// ── Phase management ─────────────────────────────────────────────────────────

function setPhase(phase) {
  document.querySelectorAll('.phase').forEach(el => el.classList.remove('active'));
  $(`phase-${phase}`)?.classList.add('active');
  S.phase = phase;
}

// ── Upload phase ─────────────────────────────────────────────────────────────

function initUpload() {
  const zone = $('upload-zone');
  const input = $('pdf-input');
  const btn = $('start-btn');
  let selectedFile = null;

  function selectFile(f) {
    if (!f || !f.name.toLowerCase().endsWith('.pdf')) return;
    selectedFile = f;
    $('upload-filename').textContent = f.name;
    btn.disabled = false;
  }

  // Don't trigger file input if clicking on the button itself
  zone.addEventListener('click', (e) => {
    if (e.target !== input && !e.target.closest('label')) {
      input.click();
    }
  });
  input.addEventListener('change', () => selectFile(input.files[0]));
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', e => {
    e.preventDefault(); zone.classList.remove('drag-over');
    selectFile(e.dataTransfer.files[0]);
  });

  btn.addEventListener('click', async () => {
    if (!selectedFile) return;
    btn.disabled = true;
    btn.textContent = t('upload.uploading');
    try {
      const { eval_id } = await apiUpload(selectedFile);
      $('progress-filename').textContent = selectedFile.name;
      startEval(eval_id);
    } catch (e) {
      alert(t('upload.failPrefix') + e.message);
      btn.disabled = false;
      btn.textContent = t('upload.start');
    }
  });

  loadHistory();
}

async function loadHistory() {
  try {
    const { runs } = await apiRuns();
    const list = $('history-list');
    list.innerHTML = '';

    if (!runs.length) {
      list.innerHTML = '<div class="history-empty">' + t('history.empty') + '</div>';
      return;
    }

    runs.slice(0, 10).forEach(run => {
      const item = el('div', 'history-item');
      const grade = run.grade || '?';
      const gradeClass = grade === 'A' ? 'pill-green' : grade === 'B' ? 'pill-blue' : grade === 'C' ? 'pill-orange' : 'pill-red';
      item.innerHTML = `
        <div class="history-grade" style="color:${gradeColor(grade)};background:${gradeColor(grade)}1a">${grade}</div>
        <div class="history-info">
          <div class="history-source">${run.source || run.eval_id}</div>
          <div class="history-meta">${formatDate(run.timestamp)}</div>
        </div>
        <div class="history-score">${run.overall_score != null ? run.overall_score.toFixed(1) : '—'}</div>
      `;
      item.addEventListener('click', () => startEval(run.eval_id, true));
      list.appendChild(item);
    });
  } catch (_) {
    const list = $('history-list');
    if (list) list.innerHTML = '<div class="history-empty">' + t('history.loadError') + '</div>';
  }
}

// ── Evaluation start & polling ────────────────────────────────────────────────

function startEval(evalId, skipProcessing = false) {
  S.evalId = evalId;
  window.history.pushState({}, '', `/run/${evalId}`);
  setPhase('processing');
  renderSteps(0, []);
  startPolling(evalId, skipProcessing);
}

function startPolling(evalId, tryDirectResult = false) {
  if (S.pollTimer) clearInterval(S.pollTimer);
  poll(evalId, tryDirectResult);
  S.pollTimer = setInterval(() => poll(evalId, false), 2000);
}

async function poll(evalId, tryDirect) {
  try {
    const status = await apiStatus(evalId);
    S.paperId = status.paper_id;
    S.innerRunId = status.inner_run_id;
    S.completedFiles = status.completed_files || [];

    renderSteps(status.current_step, S.completedFiles);
    loadAvailableData();

    if (status.finished) {
      clearInterval(S.pollTimer);
      S.pollTimer = null;
      // Give a short delay for the last file to be fully written
      setTimeout(() => switchToResults(), 400);
    } else if (status.status === 'error') {
      clearInterval(S.pollTimer);
      showError(status.error || t('processing.errorPrefix'));
    }
  } catch (_) {}
}

function showError(msg) {
  setPhase('processing');
  const hint = $('waiting-hint');
  hint.style.display = 'block';
  hint.innerHTML = `<span style="color:var(--danger)">${t('processing.failPrefix')}${msg}</span>`;
}

// ── Steps rendering ───────────────────────────────────────────────────────────

function renderSteps(currentStep, completed) {
  const list = $('steps-list');
  list.innerHTML = '';

  // Derive set of completed steps
  const doneSteps = new Set();
  STEP_SIGNALS.forEach(([step, rel]) => { if (completed.includes(rel)) doneSteps.add(step); });

  for (let s = 1; s <= 7; s++) {
    const isDone = doneSteps.has(s);
    const isActive = !isDone && s === currentStep + 1;
    const cls = isDone ? 'done' : isActive ? 'active' : 'error' === 'error' ? 'error' : 'pending';
    const icon = isDone ? STEP_ICONS.done : isActive ? '<span class="spinner"></span>' : STEP_ICONS.pending;

    const li = el('li', `step-item ${isDone ? 'done' : isActive ? 'active' : 'pending'}`);
    li.innerHTML = `<span class="step-icon">${icon}</span>
      <div class="step-body">
        <div class="step-label">【${String(s).padStart(2,'0')}】${t('step.' + s)}</div>
      </div>`;
    list.appendChild(li);
  }
}

// ── Incremental data loading during processing ────────────────────────────────

function loadAvailableData() {
  const cf = S.completedFiles;
  const id = S.evalId, pid = S.paperId;
  if (!pid) return;

  if (cf.includes('tools/extraction.json') && !S.extraction)
    apiFile(id, pid, 'tools/extraction.json').then(d => { S.extraction = d; });

  if (cf.includes('tools/validation.json') && !S.validation)
    apiFile(id, pid, 'tools/validation.json').then(d => {
      S.validation = d;
      showPartialValidation();
      if (document.getElementById('panel-graph')?.open && S.graphAnalysis) renderGraphPanel();
    });

  if (cf.includes('tools/c6_alignment.json') && !S.c6)
    apiFile(id, pid, 'tools/c6_alignment.json').then(d => { S.c6 = d; });

  if (cf.includes('tools/analysis.json') && !S.analysis)
    apiFile(id, pid, 'tools/analysis.json').then(d => { S.analysis = d; showPartialTemporal(); });

  if (cf.includes('tools/trend_baseline.json') && !S.trendBaseline)
    apiFile(id, pid, 'tools/trend_baseline.json').then(d => { S.trendBaseline = d; showPartialTemporal(); });

  if (cf.includes('tools/graph_analysis.json') && !S.graphAnalysis)
    apiFile(id, pid, 'tools/graph_analysis.json').then(d => {
      S.graphAnalysis = d;
      if (document.getElementById('panel-graph')?.open && S.validation) renderGraphPanel();
    });

  if (cf.includes('tools/key_papers.json') && !S.keyPapers)
    apiFile(id, pid, 'tools/key_papers.json').then(d => { S.keyPapers = d; });

  if (cf.includes('nodes/04_verifier.json') && !S.verifier)
    apiFile(id, pid, 'nodes/04_verifier.json').then(d => { S.verifier = d; });
  if (cf.includes('nodes/04_expert.json') && !S.expert)
    apiFile(id, pid, 'nodes/04_expert.json').then(d => { S.expert = d; });
  if (cf.includes('nodes/04_reader.json') && !S.reader)
    apiFile(id, pid, 'nodes/04_reader.json').then(d => { S.reader = d; });
  if (cf.includes('nodes/05_corrector.json') && !S.corrector)
    apiFile(id, pid, 'nodes/05_corrector.json').then(d => { S.corrector = d; });
  if (cf.includes('run_summary.json') && !S.summary)
    apiFile(id, pid, 'run_summary.json').then(d => { S.summary = d; });
}

function showPartialValidation() {
  const hint = $('waiting-hint');
  if (!S.validation) return;
  const vr = S.validation.reference_validations || [];
  const c5 = vr.length ? (vr.filter(r => r.is_valid).length / vr.length) : 0;
  hint.style.display = 'block';
  hint.innerHTML = `${t('dims.evidenceSummary')}：<strong>${vr.length}</strong> ${t('evidence.items')}，${t('evidence.C5')} <strong>${pct(c5)}</strong>`;
}

function showPartialTemporal() {
  if (!S.analysis) return;
  const td = S.analysis.temporal || {};
  const hint = $('waiting-hint');
  hint.innerHTML += `<br>${t('temporal.T1')}=${td.T1_year_span ?? '?'} ${t('keypapers.times')}，${t('temporal.T5')}=${td.T5_trend_alignment != null ? fmt3(td.T5_trend_alignment) : 'computing…'}`;
}

// ── Switch to results ─────────────────────────────────────────────────────────

async function switchToResults() {
  // Load anything not yet loaded
  const id = S.evalId, pid = S.paperId;
  const loads = [];
  if (!S.summary)      loads.push(apiFile(id, pid, 'run_summary.json').then(d => S.summary = d));
  if (!S.verifier)     loads.push(apiFile(id, pid, 'nodes/04_verifier.json').then(d => S.verifier = d));
  if (!S.expert)       loads.push(apiFile(id, pid, 'nodes/04_expert.json').then(d => S.expert = d));
  if (!S.reader)       loads.push(apiFile(id, pid, 'nodes/04_reader.json').then(d => S.reader = d));
  if (!S.corrector)    loads.push(apiFile(id, pid, 'nodes/05_corrector.json').then(d => S.corrector = d));
  if (!S.analysis)     loads.push(apiFile(id, pid, 'tools/analysis.json').then(d => S.analysis = d));
  if (!S.trendBaseline)loads.push(apiFile(id, pid, 'tools/trend_baseline.json').then(d => S.trendBaseline = d));
  if (!S.validation)   loads.push(apiFile(id, pid, 'tools/validation.json').then(d => S.validation = d));
  if (!S.c6)           loads.push(apiFile(id, pid, 'tools/c6_alignment.json').then(d => S.c6 = d));
  if (!S.keyPapers)    loads.push(apiFile(id, pid, 'tools/key_papers.json').then(d => S.keyPapers = d));
  if (!S.graphAnalysis)loads.push(apiFile(id, pid, 'tools/graph_analysis.json').then(d => S.graphAnalysis = d));
  if (!S.extraction)   loads.push(apiFile(id, pid, 'tools/extraction.json').then(d => S.extraction = d));
  if (!S.runJson)      loads.push(apiRunJson(id).then(d => S.runJson = d));
  await Promise.all(loads);

  setPhase('results');
  renderPdfViewer();
  renderResults();
}

// ── Results rendering ─────────────────────────────────────────────────────────

function renderResults() {
  [renderOverview, renderDimensionCards, renderToolPanels, renderSysInfo].forEach(fn => {
    try {
      fn();
    } catch (e) {
      console.error('[renderResults] render failed', {
        fn: fn?.name || 'unknown',
        evalId: S.evalId,
        paperId: S.paperId,
        message: e?.message,
        stack: e?.stack,
      });
    }
  });
}

// ── Area A: Overview ──────────────────────────────────────────────────────────

function renderOverview() {
  const sum = S.summary;
  if (!sum) return;

  const score = sum.overall_score ?? 0;
  const grade = sum.grade ?? 'F';
  $('score-big').textContent = score.toFixed(2);
  const gb = $('grade-badge');
  gb.textContent = grade;
  gb.className = `grade-badge ${grade}`;

  // Radar
  renderRadar(sum);

  // Summary text (auto-generated from scores)
  const dims = sum.dimension_scores || {};
  const low  = Object.entries(dims).filter(([,d]) => d.final_score < 3).map(([k]) => t('dim.' + k));
  const high = Object.entries(dims).filter(([,d]) => d.final_score >= 4).map(([k]) => t('dim.' + k));
  const parts = [];
  if (high.length) parts.push(`<strong>${t('overview.strengths')}：</strong>${high.join(', ')}`);
  if (low.length)  parts.push(`<strong>${t('overview.limitations')}：</strong>${low.join(', ')}`);
  $('summary-text').innerHTML = parts.join('<br>') || t('overview.complete');

  // Key alerts
  const alerts = $('key-alerts');
  alerts.innerHTML = '';
  const addAlert = (cls, msg) => {
    const d = el('div', `alert-item ${cls}`);
    d.textContent = msg;
    alerts.appendChild(d);
  };

  const c6 = S.c6;
  if (c6?.auto_fail) addAlert('danger', t('alert.autoFail'));

  const metrics = sum.deterministic_metrics || {};
  if (metrics.C5 != null && metrics.C5 < 0.3)
    addAlert('warn', t('alert.lowVerification', pct(metrics.C5)));

  const correctedDims = Object.entries(sum.corrected_scores || {}).filter(([,v]) => Math.abs((v.corrected||0) - (v.original||0)) >= 2);
  if (correctedDims.length) addAlert('warn', t('alert.correctorAdjust', correctedDims.map(([k])=>k).join(', ')));

  const highDisagree = Object.values(sum.dimension_scores || {}).some(d => d.variance?.high_disagreement);
  if (highDisagree) addAlert('info', t('alert.highDisagreement'));
}

function renderRadar(sum) {
  const dims = sum.dimension_scores || {};
  const indicators = DIM_ORDER.map(d => ({ name: t('dim.' + d), max: 5 }));
  const values = DIM_ORDER.map(d => dims[d]?.final_score ?? 0);
  const container = $('radar-chart');
  if (!S.radarChart) S.radarChart = echarts.init(container);
  S.radarChart.setOption({
    tooltip: {
      trigger: 'item',
      backgroundColor: '#FFFFFF',
      borderColor: '#E5E5E5',
      borderWidth: 1,
      textStyle: { color: '#333333', fontSize: 12 },
    },
    radar: {
      indicator: indicators,
      radius: '65%',
      splitNumber: 5,
      axisName: { fontSize: 11, color: '#666666', formatter: v => v },
      splitLine: { lineStyle: { color: '#E5E5E5' } },
      splitArea: { show: false },
      axisLine: { lineStyle: { color: '#E5E5E5' } },
    },
    series: [{
      type: 'radar',
      data: [{
        value: values,
        name: 'Score',
        symbol: 'circle',
        symbolSize: 4,
        lineStyle: { color: '#2C3E50', width: 1.5 },
        areaStyle: { color: 'rgba(44, 62, 80, 0.06)' },
        itemStyle: { color: '#2C3E50' },
      }],
    }],
  }, { notMerge: true });
  container.onclick = e => {
    // ECharts radar click → jump to card
    const idx = S.radarChart.convertFromPixel({ seriesIndex: 0 }, [e.offsetX, e.offsetY]);
  };
}

// ── Area B: Dimension cards ───────────────────────────────────────────────────

function renderDimensionCards() {
  const sum     = S.summary;
  const corrections = S.corrector?.output?.corrector_output?.corrections || {};
  const agentMap = {
    verifier: S.verifier?.output?.agent_outputs?.verifier,
    expert:   S.expert?.output?.agent_outputs?.expert,
    reader:   S.reader?.output?.agent_outputs?.reader,
  };

  // Clear containers before re-rendering
  Object.values(GROUP_CONTAINERS).forEach(id => {
    const el = $(id);
    if (el) el.innerHTML = '';
  });

  DIM_ORDER.forEach(dimId => {
    const meta     = DIMENSIONS[dimId];
    const dimScore = sum?.dimension_scores?.[dimId];
    const agentOut = agentMap[meta.agent];
    const subScore = agentOut?.sub_scores?.[dimId];
    const container = $(GROUP_CONTAINERS[meta.group]);
    if (container) container.appendChild(buildDimCard(dimId, meta, dimScore, subScore, corrections));
  });
}

function buildDimCard(dimId, meta, dimScore, subScore, corrections) {
  const score    = dimScore?.final_score ?? subScore?.score ?? 0;
  const risk     = dimScore?.hallucination_risk ?? subScore?.hallucination_risk ?? 'medium';
  const corrData = corrections[dimId];
  const isAutoFail = dimId === 'V2' && S.c6?.auto_fail;

  const card = el('div', `dim-card${isAutoFail ? ' auto-fail' : ''}`);
  card.id = `card-${dimId}`;

  // ── Header ──────────────────────────────────────────
  const header = el('div', 'dim-header');
  header.onclick = () => toggleCard(dimId);

  const titleDiv = el('div', 'dim-title');
  titleDiv.innerHTML = `
    <span class="dim-id">${dimId}</span>
    <span class="dim-name">${t('dim.' + dimId)}</span>
    ${corrData ? `<span class="risk-badge corrected">${t('dims.corrected')}</span>` : `<span class="risk-badge ${risk}">${riskLabel(risk)}</span>`}
  `;

  const scoreDiv = el('div', 'dim-score-block');
  const pct5 = (score / 5) * 100;
  scoreDiv.innerHTML = `
    <span class="score-num" style="color:${scoreColor(score)}">${Number.isInteger(score) ? score : score.toFixed(1)}</span>
    <span class="score-denom">/5</span>
    <div class="score-bar"><div class="score-fill" style="width:${pct5}%"></div></div>
  `;

  const expandBtn = el('button', 'expand-btn');
  expandBtn.textContent = '▾';
  expandBtn.type = 'button';

  header.appendChild(titleDiv);
  header.appendChild(scoreDiv);
  header.appendChild(expandBtn);

  // ── Detail (level 2) ─────────────────────────────────
  const detail = el('div', 'dim-detail');
  detail.id = `detail-${dimId}`;

  // Agent reasoning
  const reasoning = subScore?.llm_reasoning;
  if (reasoning) {
    const rs = el('div', 'detail-section');
    rs.innerHTML = `<h4>${t('dims.agentReasoning')}</h4><p>${escHtml(reasoning)}</p>`;
    detail.appendChild(rs);
  }

  // Tool evidence used by this dimension
  const te = subScore?.tool_evidence;
  if (te && typeof te === 'object' && Object.keys(te).length) {
    const evidenceLines = buildToolEvidenceLines(dimId, te);
    if (evidenceLines.length) {
    const ts = el('div', 'detail-section');
    const lines = evidenceLines.map(item => `
      <div class="tool-evidence-line">
        <span class="tool-evidence-key">${escHtml(item.label)}</span>
        <span class="tool-evidence-value">${escHtml(item.value)}</span>
      </div>
    `).join('');
    ts.innerHTML = `
      <h4>${t('dims.evidenceSummary')}</h4>
      <div class="tool-evidence-lines">${lines}</div>
    `;
    detail.appendChild(ts);
    }
  }

  // Flagged items
  const flagged = subScore?.flagged_items || [];
  if (flagged.length) {
    const fs = el('div', 'detail-section');
    fs.innerHTML = `<h4>${t('dims.flaggedItems')}</h4><ul class="flagged-list">${flagged.map(f => `<li>${escHtml(String(f))}</li>`).join('')}</ul>`;
    detail.appendChild(fs);
  }

  // Corrector info
  if (corrData) {
    const cs = el('div', 'detail-section');
    const v = corrData.variance || {};
    const models = (v.models_used || []).join(', ');
    const scores = (v.scores || []).join(' / ');
    cs.innerHTML = `<div class="corrector-box">
      <strong>${t('dims.correctorAdj')}</strong>：${corrData.original_score} → ${corrData.corrected_score}（std=${(v.std||0).toFixed(3)}）
      <div class="model-scores">${t('dims.model')}：${models}<br>${t('dims.subScores')}：${scores}</div>
    </div>`;
    detail.appendChild(cs);
  }

  // Special: V2 contradictions inline preview
  if (dimId === 'V2' && S.c6) {
    const cs = el('div', 'detail-section');
    const rate = S.c6.contradiction_rate;
    const fail = S.c6.auto_fail;
    cs.innerHTML = `<h4>${t('dims.c6Title')}</h4>
      <p>${t('dims.contradictionRate')} <strong>${pct(rate)}</strong>（${S.c6.contradict}/${S.c6.total_pairs} ${t('dims.pairs')}）
      ${fail ? ' <span style="color:var(--danger);font-weight:700">AUTO-FAIL</span>' : ''}</p>
      <a class="btn-outline" style="font-size:.78rem;padding:4px 10px;display:inline-block;margin-top:6px" onclick="event.stopPropagation();openPanel('panel-c6')">${t('dims.viewContradictions')}</a>`;
    detail.appendChild(cs);
  }

  // Special: E1 cluster centers overview (new format) or missing papers (old format)
  if (dimId === 'E1' && S.keyPapers) {
    const centers = S.keyPapers.cluster_centers || [];
    const oldMissing = S.keyPapers.missing_key_papers || [];
    const ms = el('div', 'detail-section');

    if (centers.length > 0) {
      // New cluster-centric format
      const top3 = centers.slice(0, 3);
      const anchorCount = centers.filter(c => c.is_foundational_anchor).length;
      ms.innerHTML = `<h4>${t('dims.clusterAnchor')}（${t('dims.clustersWithAnchor', anchorCount, centers.length)}）</h4>` +
        top3.map(c => {
          const label = c.is_foundational_anchor ? t('keypapers.anchor') : t('keypapers.noAnchor');
          const norm = c.citation_norm != null ? `| norm: ${c.citation_norm.toFixed(1)}` : '';
          return `<div style="font-size:.82rem;padding:3px 0"><span class="pill" style="font-size:.7rem;margin-right:4px">${label}</span><strong>${escHtml(c.center_title||'(empty)')}</strong> (${c.center_year||'?'}, ${t('common.cited')} ${c.citation_count||0}${norm})</div>`;
        }).join('') +
        (centers.length > 3 ? `<div style="font-size:.78rem;padding:3px 0;color:var(--text-muted)">${t('dims.moreClusters', centers.length - 3)}</div>` : '') +
        `<a class="btn-outline" style="font-size:.78rem;padding:4px 10px;display:inline-block;margin-top:6px" onclick="event.stopPropagation();openPanel('panel-keypapers')">${t('dims.viewCluster')}</a>`;
    } else if (oldMissing.length > 0) {
      // Old-format fallback: missing papers from external search
      const top3 = oldMissing.slice(0, 3);
      ms.innerHTML = `<h4>${t('dims.missingOld', top3.length)}</h4>` +
        top3.map(p => `<div style="font-size:.82rem;padding:3px 0"><strong>${escHtml(p.title||'')}</strong> (${p.year||'?'}, ${t('common.cited')} ${p.citation_count||'?'})</div>`).join('') +
        `<a class="btn-outline" style="font-size:.78rem;padding:4px 10px;display:inline-block;margin-top:6px" onclick="event.stopPropagation();openPanel('panel-keypapers')">${t('dims.viewList')}</a>`;
    } else {
      ms.innerHTML = `<h4>${t('dims.noClusterTitle')}</h4>
        <div style="font-size:.82rem;padding:6px 0;color:var(--text-muted)">${t('dims.noClusterMsg')}</div>
        <a class="btn-outline" style="font-size:.78rem;padding:4px 10px;display:inline-block;margin-top:6px" onclick="event.stopPropagation();openPanel('panel-keypapers')">${t('dims.viewDetails')}</a>`;
    }
    detail.appendChild(ms);
  }

  // Raw toggle
  const rawBtn = el('button', 'raw-toggle-btn');
  rawBtn.textContent = t('dims.viewRaw');
  rawBtn.type = 'button';
  rawBtn.onclick = e => { e.stopPropagation(); toggleRaw(dimId); };
  detail.appendChild(rawBtn);

  // ── Raw (level 3) ────────────────────────────────────
  const raw = el('div', 'dim-raw');
  raw.id = `raw-${dimId}`;
  raw.textContent = JSON.stringify({ dimScore, subScore }, null, 2);

  card.appendChild(header);
  card.appendChild(detail);
  card.appendChild(raw);
  return card;
}

function riskLabel(r) {
  return { low: t('risk.deterministic'), medium: t('risk.llm'), high: t('risk.llmHigh'), null: '—' }[r] || r || '—';
}

function buildToolEvidenceLines(dimId, te) {
  const numFmt = (v) => (typeof v === 'number' && Number.isFinite(v) ? (Number.isInteger(v) ? `${v}` : v.toFixed(3)) : String(v));
  const trunc = (v, n = 140) => {
    const s = String(v);
    return s.length > n ? `${s.slice(0, n)}...` : s;
  };
  const lines = [];

  const pushIf = (label, value) => {
    if (value == null || value === '') return;
    lines.push({ label, value: trunc(value) });
  };

  switch (dimId) {
    case 'V1':
      pushIf(t('evidence.C5'), te.C5 != null ? pct(te.C5) : null);
      break;
    case 'V2':
      pushIf(t('evidence.C6_rate'), te.C6_contradiction_rate != null ? pct(te.C6_contradiction_rate) : null);
      break;
    case 'V4': {
      const cons = Array.isArray(te.c6_contradictions) ? te.c6_contradictions : [];
      pushIf(t('evidence.C6_samples'), `${cons.length} ${t('evidence.items')}`);
      if (cons.length) {
        const sample = cons[0];
        const preview = sample?.sentence || sample?.note || JSON.stringify(sample);
        pushIf(t('evidence.example'), preview);
      }
      break;
    }
    case 'E1': {
      pushIf(t('evidence.G4'), te.G4 != null ? pct(te.G4) : null);
      // Show center cluster summary from keyPapers if available
      const kp = S.keyPapers;
      const centers = kp?.cluster_centers || [];
      if (centers.length > 0) {
        const anchorCount = centers.filter(c => c.is_foundational_anchor).length;
        pushIf(t('evidence.anchorClusters'), `${anchorCount} / ${centers.length}`);
      } else if (kp?.missing_key_papers?.length > 0) {
        // Old-format fallback
        pushIf(t('evidence.missingOld'), `${kp.missing_key_papers.length} ${t('evidence.papers')}`);
      }
      break;
    }
    case 'E2':
    case 'R3':
      pushIf('S5 (NMI)', te.S5 != null ? numFmt(te.S5) : null);
      break;
    case 'R1':
      pushIf('T5', te.T5 != null ? numFmt(te.T5) : null);
      break;
    case 'R2':
      pushIf('S3 (Gini)', te.S3 != null ? numFmt(te.S3) : null);
      break;
    default:
      break;
  }

  // Fallback for dimensions with sparse/unknown schema: show compact scalar fields.
  if (!lines.length) {
    Object.entries(te).forEach(([k, v]) => {
      if (v == null) return;
      if (typeof v === 'number' || typeof v === 'boolean' || typeof v === 'string') {
        lines.push({ label: k, value: typeof v === 'number' ? numFmt(v) : String(v) });
      } else if (Array.isArray(v)) {
        lines.push({ label: k, value: `${v.length} ${t('evidence.fallbackItem')}` });
      } else if (typeof v === 'object') {
        lines.push({ label: k, value: t('evidence.fallbackObj') });
      }
    });
  }

  return lines.slice(0, 6);
}

function toggleCard(dimId) {
  const card = $(`card-${dimId}`);
  if (!card) return;
  card.classList.toggle('open');
}

function toggleRaw(dimId) {
  const card = $(`card-${dimId}`);
  if (!card) return;
  card.classList.toggle('raw-open');
}

// ── Area C: Tool panels ───────────────────────────────────────────────────────

function renderToolPanels() {
  const fns = [renderExtractionPanel, renderValidationPanel, renderC6Panel,
               renderTemporalPanel, renderGraphPanel, renderKeyPapersPanel];
  fns.forEach(fn => {
    try {
      fn();
    } catch (e) {
      const vr = S.validation?.reference_validations || [];
      const edges = S.validation?.real_citation_edges || [];
      const uniqueKeys = new Set(vr.map(r => r?.key).filter(Boolean)).size;
      console.error('[renderToolPanels] panel render failed', {
        fn: fn?.name || 'unknown',
        evalId: S.evalId,
        paperId: S.paperId,
        validationCount: vr.length,
        validationUniqueKeys: uniqueKeys,
        validationDuplicateKeys: Math.max(0, vr.length - uniqueKeys),
        realEdgeCount: edges.length,
        graphNodes: S.graphAnalysis?.citation_graph_analysis?.meta?.n_nodes,
        graphEdges: S.graphAnalysis?.citation_graph_analysis?.meta?.n_edges,
        message: e?.message,
        stack: e?.stack,
      });
    }
  });
}

function renderExtractionPanel() {
  if (!S.extraction) return;
  const body = $('body-extraction');
  const refs = S.extraction.references || [];
  const cits = S.extraction.citations || [];
  const sections = [...new Set(cits.map(c => c.section_title).filter(Boolean))];

  body.innerHTML = `
    <div class="stat-row">
      <div class="stat-box"><div class="stat-val">${refs.length}</div><div class="stat-key">${t('extraction.refs')}</div></div>
      <div class="stat-box"><div class="stat-val">${cits.length}</div><div class="stat-key">${t('extraction.citations')}</div></div>
      <div class="stat-box"><div class="stat-val">${sections.length}</div><div class="stat-key">${t('extraction.sections')}</div></div>
    </div>
    <h4 style="margin-top:16px;margin-bottom:6px;font-size:.82rem;color:var(--text-muted);text-transform:uppercase">${t('extraction.sectionList')}</h4>
    <div>${sections.map(s => `<span class="tag" style="margin:2px">${escHtml(s)}</span>`).join('')}</div>
    <h4 style="margin-top:16px;margin-bottom:6px;font-size:.82rem;color:var(--text-muted);text-transform:uppercase">${t('extraction.refList')}</h4>
    <table class="metric-table">
      <tr><th>${t('extraction.colNum')}</th><th>${t('extraction.colTitle')}</th><th>${t('extraction.colAuthor')}</th><th>${t('extraction.colYear')}</th></tr>
      ${refs.slice(0,20).map(r => `<tr>
        <td class="mono">[${r.reference_number}]</td>
        <td>${escHtml(r.title||'')}</td>
        <td class="mono" style="font-size:.75rem">${escHtml((r.author||'').slice(0,40))}</td>
        <td>${r.year||''}</td>
      </tr>`).join('')}
    </table>`;
}

function renderValidationPanel() {
  if (!S.validation) return;
  const body = $('body-validation');
  const vr = S.validation.reference_validations || [];
  const pass = vr.filter(r => r.is_valid).length;
  const fail = vr.length - pass;
  const metrics = S.summary?.deterministic_metrics || {};
  const c3 = metrics.C3;
  const c5 = metrics.C5 ?? (vr.length ? pass / vr.length : null);

  body.innerHTML = `
    <div class="stat-row">
      <div class="stat-box"><div class="stat-val" style="color:var(--success)">${pass}</div><div class="stat-key">${t('validation.passed')}</div></div>
      <div class="stat-box"><div class="stat-val" style="color:var(--danger)">${fail}</div><div class="stat-key">${t('validation.failed')}</div></div>
      <div class="stat-box"><div class="stat-val">${vr.length}</div><div class="stat-key">${t('validation.total')}</div></div>
      <div class="stat-box"><div class="stat-val">${pct(c5)}</div><div class="stat-key">${t('validation.C5')}</div></div>
      ${c3 != null ? `<div class="stat-box"><div class="stat-val">${pct(c3)}</div><div class="stat-key">${t('validation.C3')}</div></div>` : ''}
    </div>
    <table class="metric-table" style="margin-top:16px">
      <tr><th>${t('validation.colKey')}</th><th>${t('validation.colTitle')}</th><th>${t('validation.colYear')}</th><th>${t('validation.colStatus')}</th><th>${t('validation.colConf')}</th></tr>
      ${vr.slice(0,30).map(r => `<tr>
        <td class="mono">${r.key}</td>
        <td style="font-size:.78rem">${escHtml(r.comparison?.bib_title || '')}</td>
        <td>${r.comparison?.bib_year || ''}</td>
        <td><span class="valid-badge ${r.is_valid ? 'pass' : 'fail'}">${r.is_valid ? t('validation.pass') : t('validation.fail')}</span></td>
        <td class="mono">${(r.confidence||0).toFixed(2)}</td>
      </tr>`).join('')}
    </table>`;
}

function renderC6Panel() {
  if (!S.c6) return;
  const body = $('body-c6');
  const d = S.c6;
  const cons = d.contradictions || [];

  body.innerHTML = `
    <div class="stat-row">
      <div class="stat-box"><div class="stat-val">${d.total_pairs}</div><div class="stat-key">${t('c6.totalPairs')}</div></div>
      <div class="stat-box"><div class="stat-val" style="color:var(--success)">${d.support}</div><div class="stat-key">${t('c6.support')}</div></div>
      <div class="stat-box"><div class="stat-val" style="color:var(--danger)">${d.contradict}</div><div class="stat-key">${t('c6.contradict')}</div></div>
      <div class="stat-box"><div class="stat-val">${d.insufficient}</div><div class="stat-key">${t('c6.insufficient')}</div></div>
      <div class="stat-box"><div class="stat-val ${d.auto_fail ? 'fail' : ''}">${pct(d.contradiction_rate)}</div><div class="stat-key">${t('c6.rate')} ${d.auto_fail ? 'AUTO-FAIL' : ''}</div></div>
    </div>
    ${d.missing_abstract_count ? `<p class="empty-msg" style="margin-top:8px">${t('c6.insufficientNote', d.missing_abstract_count)}</p>` : ''}
    ${cons.length === 0 ? `<p class="empty-msg" style="margin-top:12px">${t('c6.noContradictions')}</p>` : `
      <h4 style="margin:14px 0 8px;font-size:.82rem;color:var(--text-muted);text-transform:uppercase">${t('c6.listTitle')}</h4>
      <div class="contradiction-list">
        ${cons.map(c => `<div class="contradiction-item">
          <div class="marker">${escHtml(c.citation||'')} → ${escHtml(c.llm_judgment||'')}</div>
          <div class="sentence">${escHtml(c.sentence||'').slice(0,200)}</div>
          <div class="note">${escHtml(c.note||'').slice(0,150)}</div>
        </div>`).join('')}
      </div>`}
  `;
}

function renderTemporalPanel() {
  if (!S.analysis) return;
  const td = S.analysis.temporal || {};
  const st = S.analysis.structural || {};
  const metrics = S.summary?.deterministic_metrics || {};

  // Metrics table
  $('temporal-metrics').innerHTML = `
    <div class="stat-row" style="margin-top:16px">
      <div class="stat-box"><div class="stat-val">${td.T1_year_span ?? '?'} ${t('keypapers.years')}</div><div class="stat-key">${t('temporal.T1')}</div></div>
      <div class="stat-box"><div class="stat-val">${td.T3_peak_year_ratio != null ? pct(td.T3_peak_year_ratio) : 'N/A'}</div><div class="stat-key">${t('temporal.T3')}</div></div>
      <div class="stat-box"><div class="stat-val">${td.T4_temporal_continuity != null ? td.T4_temporal_continuity + ' ' + t('keypapers.years') : 'N/A'}</div><div class="stat-key">${t('temporal.T4')}</div></div>
      <div class="stat-box"><div class="stat-val">${td.T5_trend_alignment != null ? fmt3(td.T5_trend_alignment) : 'N/A'}</div><div class="stat-key">${t('temporal.T5')}</div></div>
    </div>
    <div class="stat-row" style="margin-top:8px">
      <div class="stat-box"><div class="stat-val">${st.S1_section_count??'?'}</div><div class="stat-key">${t('temporal.S1')}</div></div>
      <div class="stat-box"><div class="stat-val">${st.S2_citation_density!=null?fmt1(st.S2_citation_density):'?'}</div><div class="stat-key">${t('temporal.S2')}</div></div>
      <div class="stat-box"><div class="stat-val">${st.S3_citation_gini!=null?fmt3(st.S3_citation_gini):'?'}</div><div class="stat-key">${t('temporal.S3')}</div></div>
      <div class="stat-box"><div class="stat-val">${st.S4_zero_citation_section_rate!=null?pct(st.S4_zero_citation_section_rate):'?'}</div><div class="stat-key">${t('temporal.S4')}</div></div>
    </div>`;

  // Chart
  renderTemporalChart(td, S.trendBaseline);
}

function renderTemporalChart(temporal, trendBaseline) {
  const container = $('temporal-chart');
  if (!container) return;
  if (!S.temporalChart) S.temporalChart = echarts.init(container);

  const yearDist = temporal.year_distribution || {};
  const surveyYears = Object.keys(yearDist).sort();
  const surveyCounts = surveyYears.map(y => yearDist[y] || 0);

  const trendData = trendBaseline?.yearly_counts || {};
  const trendYears = Object.keys(trendData).sort();

  // Normalize trend to same scale as survey
  const maxSurvey = Math.max(...surveyCounts, 1);
  const maxTrend = Math.max(...trendYears.map(y => trendData[y] || 0), 1);
  const scale = maxSurvey / maxTrend;

  const option = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: [t('temporal.barName'), t('temporal.lineName')], bottom: 4 },
    xAxis: { type: 'category', data: [...new Set([...surveyYears, ...trendYears])].sort() },
    yAxis: [
      { type: 'value', name: t('temporal.y1'), nameTextStyle: { fontSize: 11 } },
      { type: 'value', name: t('temporal.y2'), nameTextStyle: { fontSize: 11 }, axisLabel: { show: false } },
    ],
    series: [
      { name: t('temporal.barName'), type: 'bar', data: surveyYears.map((y, i) => [y, surveyCounts[i]]),
        itemStyle: { color: '#4E8BAF' } },
      { name: t('temporal.lineName'), type: 'line', yAxisIndex: 1,
        data: trendYears.map(y => [y, (trendData[y]||0) * scale]),
        lineStyle: { color: '#C0684A', width: 2 }, symbol: 'circle', symbolSize: 5,
        itemStyle: { color: '#C0684A' } },
    ],
  };
  S.temporalChart.setOption(option, { notMerge: true });
}

function renderGraphPanel() {
  if (!S.validation || !S.graphAnalysis) return;

  const ga = S.graphAnalysis?.citation_graph_analysis || {};
  const meta = ga.meta || {};
  const dc = ga.summary?.density_connectivity || {};
  const metrics = S.summary?.deterministic_metrics || {};

  $('graph-metrics').innerHTML = `
    <div class="stat-row" style="margin-top:12px">
      <div class="stat-box"><div class="stat-val">${meta.n_nodes??'?'}</div><div class="stat-key">${t('graph.nodes')}</div></div>
      <div class="stat-box"><div class="stat-val">${meta.n_edges??'?'}</div><div class="stat-key">${t('graph.edges')}</div></div>
      <div class="stat-box"><div class="stat-val">${fmt3(metrics.G1??dc.density_global)}</div><div class="stat-key">${t('graph.G1')}</div></div>
      <div class="stat-box"><div class="stat-val">${metrics.G2??dc.n_weak_components??'?'}</div><div class="stat-key">${t('graph.G2')}</div></div>
      <div class="stat-box"><div class="stat-val">${fmt3(metrics.G3??dc.lcc_frac)}</div><div class="stat-key">${t('graph.G3')}</div></div>
      <div class="stat-box"><div class="stat-val">${pct(metrics.G4)}</div><div class="stat-key">${t('graph.G4')}</div></div>
      <div class="stat-box"><div class="stat-val">${pct(metrics.G6)}</div><div class="stat-key">${t('graph.G6')}</div></div>
    </div>`;

  // vis.js network: only init when panel is actually open (container has a size)
  if (document.getElementById('panel-graph')?.open) {
    renderCitationGraph();
  }
}

const CLUSTER_PALETTE = [
  '#4E8BAF','#C0694E','#5C9E7A','#8E5E9E',
  '#B8A04E','#4E9E9E','#C06085','#6E9E4E',
  '#9E7050','#5C6EAE'
];

function renderCitationGraph() {
  const container = $('citation-graph');
  if (!container) return;
  if (S.citationNetwork) {
    S.citationNetwork.destroy();
    S.citationNetwork = null;
  }

  const vr = S.validation?.reference_validations || [];
  const edges = S.validation?.real_citation_edges || [];
  const graph = S.graphAnalysis?.citation_graph_analysis || {};
  // Preferred schema: evidence.clusters; keep backward compatibility with older summary path.
  const clusters = graph?.evidence?.clusters || graph?.summary?.cocitation_clustering?.clusters || [];
  // Optional full mapping (if future schema provides it).
  const nodeToCluster = graph?.evidence?.node_to_cluster || graph?.summary?.cocitation_clustering?.node_to_cluster || null;

  // Build paper_id → cluster_id map
  const clusterMap = {};
  if (nodeToCluster && typeof nodeToCluster === 'object') {
    Object.entries(nodeToCluster).forEach(([paperId, clusterId]) => {
      clusterMap[paperId] = clusterId;
    });
  } else {
    clusters.forEach(cl => {
      (cl.top_papers || []).forEach(tp => { clusterMap[tp.paper_id] = cl.cluster_id; });
    });
  }

  // Visualization fallback:
  // 1) If only top papers are labeled, propagate labels by neighbor majority vote.
  // 2) If still unlabeled (or no seed labels), assign component-based pseudo clusters.
  const vrKeys = new Set(vr.map(r => r.key).filter(Boolean));
  const adj = {};
  const addAdj = (a, b) => {
    if (!vrKeys.has(a) || !vrKeys.has(b) || a === b) return;
    if (!adj[a]) adj[a] = new Set();
    if (!adj[b]) adj[b] = new Set();
    adj[a].add(b);
    adj[b].add(a);
  };
  edges.forEach(e => addAdj(e.source, e.target));

  const seeded = Object.keys(clusterMap).length;
  if (seeded > 0) {
    for (let round = 0; round < 6; round++) {
      let changed = 0;
      vr.forEach(r => {
        const id = r.key;
        if (!id || clusterMap[id] != null) return;
        const ns = adj[id];
        if (!ns || ns.size === 0) return;
        const votes = {};
        ns.forEach(n => {
          const cid = clusterMap[n];
          if (cid == null) return;
          votes[cid] = (votes[cid] || 0) + 1;
        });
        const entries = Object.entries(votes);
        if (!entries.length) return;
        entries.sort((a, b) => b[1] - a[1]);
        clusterMap[id] = Number(entries[0][0]);
        changed++;
      });
      if (!changed) break;
    }
  } else if (edges.length > 0) {
    let nextCid = 0;
    const seen = new Set();
    vr.forEach(r => {
      const start = r.key;
      if (!start || seen.has(start)) return;
      const stack = [start];
      seen.add(start);
      let hasEdge = false;
      while (stack.length) {
        const cur = stack.pop();
        const ns = adj[cur];
        if (ns && ns.size) {
          hasEdge = true;
          ns.forEach(n => {
            if (!seen.has(n)) {
              seen.add(n);
              stack.push(n);
            }
          });
        }
      }
      if (!hasEdge) return;
      const stack2 = [start];
      const seen2 = new Set([start]);
      while (stack2.length) {
        const cur = stack2.pop();
        clusterMap[cur] = nextCid;
        const ns = adj[cur];
        if (!ns) continue;
        ns.forEach(n => {
          if (!seen2.has(n)) {
            seen2.add(n);
            stack2.push(n);
          }
        });
      }
      nextCid++;
    });
  }

  // Compute degrees
  const inDeg = {}, outDeg = {};
  edges.forEach(e => {
    inDeg[e.target]  = (inDeg[e.target]  || 0) + 1;
    outDeg[e.source] = (outDeg[e.source] || 0) + 1;
  });

  const nodeSize = (id) => {
    const score = 2.2 * (inDeg[id] || 0) + 1.0 * (outDeg[id] || 0);
    return Math.max(8, Math.min(40, 10 + 5.2 * Math.log1p(score)));
  };

  const hasEdges = edges.length > 0;

  const nodes = vr.map((r, i) => {
    const cid = clusterMap[r.key];
    const isolated = !(inDeg[r.key] || outDeg[r.key]);
    const color = isolated ? '#CCCCCC' : cid != null ? CLUSTER_PALETTE[cid % 10] : '#2C3E50';
    const meta = r.comparison || r.metadata || {};
    const title = `<b>${escHtml(meta.bib_title || r.key)}</b><br>` +
      `${t('graph.tooltipYear')}：${meta.bib_year||'?'}　${t('graph.tooltipValid')}：${r.is_valid?'✓':'✗'}`;
    const node = { id: r.key, label: r.key, size: nodeSize(r.key), color, title, font: { size: 9 } };
    // No-edge case: arrange in a circle so nodes don't scatter
    if (!hasEdges) {
      const N = vr.length;
      const radius = Math.max(180, N * 14);
      node.x = radius * Math.cos(2 * Math.PI * i / N);
      node.y = radius * Math.sin(2 * Math.PI * i / N);
    }
    return node;
  });

  try {
    const colorStats = nodes.reduce((acc, n) => {
      const c = n.color || 'unknown';
      acc[c] = (acc[c] || 0) + 1;
      return acc;
    }, {});
    console.info('[citation-graph] color distribution', colorStats);
  } catch (_) {}

  const edgeData = edges.map((e, i) => ({
    id: `e${i}`, from: e.source, to: e.target,
    arrows: 'to', color: { color: '#999999' }, width: 1.0,
  }));

  if (typeof vis === 'undefined') {
    container.innerHTML = `<p class="empty-msg" style="padding:20px">${t('graph.visFail')}</p>`;
    return;
  }

  const physicsOpts = hasEdges
    ? {
        solver: 'barnesHut',
        barnesHut: { gravitationalConstant: -8000, centralGravity: 0.3,
          springLength: 200, springConstant: 0.04, damping: 0.9, avoidOverlap: 0.5 },
        stabilization: { enabled: true, iterations: 800, fit: true },
        minVelocity: 0.5,
      }
    : { enabled: false };

  S.citationNetwork = new vis.Network(container,
    { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edgeData) },
    {
      physics: physicsOpts,
      interaction: { hover: true, navigationButtons: true, hideEdgesOnDrag: true },
      nodes: { shape: 'dot' },
      edges: { smooth: false },
    }
  );

  // Update node count badge
  const badge = $('graph-node-count');
  if (badge) badge.textContent = t('graph.nodeEdge', nodes.length, edgeData.length);

  // fit() after DOM has painted (container may not have final size yet)
  if (hasEdges) {
    S.citationNetwork.once('stabilized', () => S.citationNetwork.fit());
  } else {
    setTimeout(() => S.citationNetwork.fit(), 150);
  }
}

function renderKeyPapersPanel() {
  if (!S.keyPapers) return;
  const body = $('body-keypapers');
  const kp = S.keyPapers;
  const centers = kp.cluster_centers || [];
  const threshold = kp.citation_threshold || 50;

  // Edge case: no valid clusters → G4 is meaningless
  if (centers.length === 0) {
    body.innerHTML = `
      <div class="stat-row">
        <div class="stat-box"><div class="stat-val" style="color:var(--text-muted)">N/A</div><div class="stat-key">${t('keypapers.G4')}</div></div>
      </div>
      <p class="empty-msg" style="margin-top:12px">${t('keypapers.noClusterMsg')}</p>`;
    return;
  }

  const anchors = centers.filter(c => c.is_foundational_anchor);
  const nonAnchors = centers.filter(c => !c.is_foundational_anchor);

  body.innerHTML = `
    <div class="stat-row">
      <div class="stat-box"><div class="stat-val">${pct(kp.coverage_rate)}</div><div class="stat-key">${t('keypapers.G4Coverage')}</div></div>
      <div class="stat-box"><div class="stat-val">${anchors.length}</div><div class="stat-key">${t('keypapers.anchorClusters')}</div></div>
      <div class="stat-box"><div class="stat-val" style="color:var(--danger)">${nonAnchors.length}</div><div class="stat-key">${t('keypapers.noAnchorClusters')}</div></div>
      <div class="stat-box"><div class="stat-val">≥${threshold}</div><div class="stat-key">${t('keypapers.threshold')}</div></div>
    </div>
    <p style="font-size:.78rem;color:var(--text-muted);margin-top:4px">${t('keypapers.anchorDef', threshold)}</p>

    ${nonAnchors.length > 0 ? `
    <h4 style="margin:16px 0 8px;font-size:.82rem;color:var(--text-muted);text-transform:uppercase">${t('keypapers.missingTitle', nonAnchors.length)}</h4>
    <div class="paper-list">
      ${nonAnchors.map(c => `<div class="paper-item">
        <div class="paper-year">${c.center_year||'?'}</div>
        <div class="paper-info">
          <div class="paper-title">${escHtml(c.center_title||'(empty cluster)')}</div>
          <div class="paper-meta">${t('common.cited')} ${c.citation_count} ${t('keypapers.times')}　|　citation_norm: ${(c.citation_norm||0).toFixed(2)}　|　${t('keypapers.clusterSize')}: ${c.cluster_size} ${t('keypapers.papersUnit')}</div>
        </div>
      </div>`).join('')}
    </div>` : '<p class="empty-msg" style="margin-top:12px">' + t('keypapers.allAnchored') + '</p>'}

    <h4 style="margin:16px 0 8px;font-size:.82rem;color:var(--text-muted);text-transform:uppercase">${t('keypapers.allCenters', centers.length)}</h4>
    <div class="paper-list">
      ${[...centers].sort((a,b) => (b.citation_count||0) - (a.citation_count||0)).map(c => {
        const icon = c.is_foundational_anchor ? t('keypapers.anchor') : t('keypapers.noAnchor');
        return `<div class="paper-item">
          <div class="paper-year">${c.center_year||'?'}</div>
          <div class="paper-info">
            <div class="paper-title">${icon} ${escHtml(c.center_title||'(empty cluster)')}</div>
            <div class="paper-meta">${t('common.cited')} ${c.citation_count||0} ${t('keypapers.times')}　|　citation_norm: ${(c.citation_norm||0).toFixed(2)}　|　PageRank: ${(c.pagerank_score||0).toFixed(4)}　|　Cluster ${c.cluster_id}（${c.cluster_size} ${t('keypapers.papersUnit')}）</div>
          </div>
        </div>`;
      }).join('')}
    </div>
  `;
}

function renderSysInfo() {
  const body = $('body-sysinfo');
  const run = S.runJson || {};
  const sum = S.summary || {};

  body.innerHTML = `
    <table class="metric-table" style="margin-bottom:16px">
      <tr><th>${t('sysinfo.field')}</th><th>${t('sysinfo.value')}</th></tr>
      <tr><td>Run ID</td><td class="mono">${sum.run_id||'?'}</td></tr>
      <tr><td>${t('sysinfo.timestamp')}</td><td class="mono">${sum.timestamp||'?'}</td></tr>
      <tr><td>${t('sysinfo.pdfSource')}</td><td class="mono">${sum.source||'?'}</td></tr>
      <tr><td>${t('sysinfo.schemaVer')}</td><td class="mono">${sum.schema_version||'?'}</td></tr>
    </table>
    <h4 style="font-size:.82rem;color:var(--text-muted);text-transform:uppercase;margin-bottom:8px">${t('sysinfo.metricsIndex')}</h4>
    <pre class="raw-json">${escHtml(JSON.stringify(run.metrics_index||{}, null, 2))}</pre>
    <h4 style="font-size:.82rem;color:var(--text-muted);text-transform:uppercase;margin-top:16px;margin-bottom:8px">${t('sysinfo.rawSummary')}</h4>
    <pre class="raw-json">${escHtml(JSON.stringify(sum, null, 2))}</pre>`;
}

// ── Navigation helpers ────────────────────────────────────────────────────────

function jumpTo(id) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  const btn = document.querySelector(`[onclick="jumpTo('${id}')"]`);
  if (btn) btn.classList.add('active');
}

function openPanel(panelId) {
  const panel = $(panelId);
  if (panel) { panel.open = true; panel.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
}

// ── UI Helpers ───────────────────────────────────────────────────────────────

function formatDate(isoString) {
  if (!isoString) return '';
  const d = new Date(isoString);
  return d.toLocaleString('zh-CN', { 
    month: 'short', 
    day: 'numeric', 
    hour: '2-digit', 
    minute: '2-digit' 
  });
}

function renderPdfViewer() {
  const container = $('pdf-container');
  const filename = $('pdf-filename');
  if (!container) return;

  // Update filename display
  const sourceFile = S.runJson?.source_file || S.summary?.source || '';
  if (filename) {
    filename.textContent = sourceFile.split(/[\\/]/).pop() || S.evalId || 'PDF';
  }

  // Construct PDF URL from the paper directory structure
  // PDF is at: output/runs/{run_id}/{inner_run_id}/papers/{paper_id}/source.pdf
  const pdfUrl = buildPdfUrl();
  if (!pdfUrl) {
    container.innerHTML = `
      <div class="pdf-placeholder">
        <p>${t('pdf.loadFail')}</p>
        <p class="pdf-hint">${t('pdf.notFound')}</p>
      </div>`;
    return;
  }

  // Try to load PDF using object/embed tag
  container.innerHTML = `
    <object data="${pdfUrl}" type="application/pdf" width="100%" height="100%">
      <embed src="${pdfUrl}" type="application/pdf" width="100%" height="100%">
        <div class="pdf-placeholder">
          <p>${t('pdf.cannotDisplay')}</p>
          <p class="pdf-hint">${t('pdf.downloadHint', pdfUrl)}</p>
        </div>
      </embed>
    </object>`;
}

function buildPdfUrl() {
  // Use the dedicated PDF endpoint which searches in:
  // 1. papers/{paper_id}/*.pdf (copied during evaluation)
  // 2. uploads/ directory (original upload)

  const evalId = S.evalId;

  if (!evalId) return null;

  return `/api/run/${evalId}/pdf`;
}

function newEval() {
  // Reset state
  Object.assign(S, {
    phase: 'upload', evalId: null, paperId: null, innerRunId: null,
    pollTimer: null, completedFiles: [],
    summary: null, verifier: null, expert: null, reader: null, corrector: null,
    analysis: null, trendBaseline: null, validation: null, c6: null,
    keyPapers: null, graphAnalysis: null, extraction: null, runJson: null,
    radarChart: null, temporalChart: null, citationNetwork: null,
    rendered: new Set(),
  });
  // Clear rendered cards
  ['cards-factual', 'cards-depth', 'cards-readability'].forEach(id => { const e = $(id); if (e) e.innerHTML = ''; });
  ['body-extraction','body-validation','body-c6','temporal-metrics','graph-metrics','body-keypapers','body-sysinfo'].forEach(id => { const e = $(id); if (e) e.innerHTML = ''; });

  // Reset upload form
  $('upload-filename').textContent = '';
  const startBtn = $('start-btn');
  startBtn.disabled = true;
  startBtn.textContent = t('upload.start');

  // Reset PDF viewer
  const pdfContainer = $('pdf-container');
  if (pdfContainer) {
    pdfContainer.innerHTML = `
      <div class="pdf-placeholder">
        <p>${t('pdf.loading')}</p>
        <p class="pdf-hint">${t('pdf.hint')}</p>
      </div>`;
  }
  const pdfFilename = $('pdf-filename');
  if (pdfFilename) pdfFilename.textContent = '';

  // Reset scroll position
  document.querySelector('.results-content')?.scrollTo(0, 0);

  window.history.pushState({}, '', '/');
  setPhase('upload');
  loadHistory();
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Init ──────────────────────────────────────────────────────────────────────

function init() {
  updateDomI18n();
  initUpload();

  // Handle direct /run/{id} URL (history view)
  const m = window.location.pathname.match(/^\/run\/(.+)$/);
  if (m) {
    const evalId = m[1];
    S.evalId = evalId;
    setPhase('processing');
    $('progress-filename').textContent = evalId;
    renderSteps(0, []);
    startPolling(evalId, true);
  }

  // Lazy render graph when panel is opened; redraw on re-open after resize
  document.getElementById('panel-graph')?.addEventListener('toggle', () => {
    if (document.getElementById('panel-graph').open) {
      renderGraphPanel();
      // If already initialized, redraw to handle container resize while hidden
      if (S.citationNetwork) setTimeout(() => { S.citationNetwork.redraw(); S.citationNetwork.fit(); }, 50);
    }
  });
}

init();
