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
  E1: { 5:'G4 ≥ 0.8，无关键文献遗漏', 4:'G4 ≥ 0.6，遗漏非核心文献',
        3:'G4 ≥ 0.4，遗漏 1-2 篇核心文献', 2:'G4 ≥ 0.2，多篇核心文献缺失', 1:'G4 < 0.2，基础文献严重缺失' },
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

const STEP_ICONS = { done: '✅', active: '', pending: '⬜', error: '❌' };
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
  return { A:'#1aae39', B:'#0075de', C:'#ca8a04', D:'#dd5b00', F:'#dc2626' }[g] || '#a39e98';
}

function scoreColor(s) {
  if (s >= 4.5) return '#1aae39';
  if (s >= 3.5) return '#0075de';
  if (s >= 2.5) return '#ca8a04';
  return '#dc2626';
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
    btn.textContent = '上传中…';
    try {
      const { eval_id } = await apiUpload(selectedFile);
      $('progress-filename').textContent = selectedFile.name;
      startEval(eval_id);
    } catch (e) {
      alert('上传失败：' + e.message);
      btn.disabled = false;
      btn.textContent = '开始评测';
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
      list.innerHTML = '<div class="history-empty">暂无评测记录</div>';
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
    if (list) list.innerHTML = '<div class="history-empty">加载历史记录失败</div>';
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
      showError(status.error || '评测过程出错');
    }
  } catch (_) {}
}

function showError(msg) {
  setPhase('processing');
  const hint = $('waiting-hint');
  hint.style.display = 'block';
  hint.innerHTML = `<span style="color:var(--danger)">❌ 评测失败：${msg}</span>`;
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
    const icon = isDone ? '✅' : isActive ? '<span class="spinner"></span>' : '⬜';

    const li = el('li', `step-item ${isDone ? 'done' : isActive ? 'active' : 'pending'}`);
    li.innerHTML = `<span class="step-icon">${icon}</span>
      <div class="step-body">
        <div class="step-label">【${String(s).padStart(2,'0')}】${STEP_LABELS[s]}</div>
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
    apiFile(id, pid, 'tools/validation.json').then(d => { S.validation = d; showPartialValidation(); });

  if (cf.includes('tools/c6_alignment.json') && !S.c6)
    apiFile(id, pid, 'tools/c6_alignment.json').then(d => { S.c6 = d; });

  if (cf.includes('tools/analysis.json') && !S.analysis)
    apiFile(id, pid, 'tools/analysis.json').then(d => { S.analysis = d; showPartialTemporal(); });

  if (cf.includes('tools/trend_baseline.json') && !S.trendBaseline)
    apiFile(id, pid, 'tools/trend_baseline.json').then(d => { S.trendBaseline = d; showPartialTemporal(); });

  if (cf.includes('tools/graph_analysis.json') && !S.graphAnalysis)
    apiFile(id, pid, 'tools/graph_analysis.json').then(d => { S.graphAnalysis = d; });

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
  hint.innerHTML = `📋 已完成证据收集：<strong>${vr.length}</strong> 条引用，验证率 <strong>${pct(c5)}</strong>`;
}

function showPartialTemporal() {
  if (!S.analysis) return;
  const t = S.analysis.temporal || {};
  const hint = $('waiting-hint');
  hint.innerHTML += `<br>🕐 时序跨度 T1=${t.T1_year_span ?? '?'} 年，趋势对齐 T5=${t.T5_trend_alignment != null ? fmt3(t.T5_trend_alignment) : '计算中…'}`;
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
  const low  = Object.entries(dims).filter(([,d]) => d.final_score < 3).map(([k]) => DIMENSIONS[k]?.label || k);
  const high = Object.entries(dims).filter(([,d]) => d.final_score >= 4).map(([k]) => DIMENSIONS[k]?.label || k);
  const parts = [];
  if (high.length) parts.push(`<strong>亮点维度：</strong>${high.join('、')}`);
  if (low.length)  parts.push(`<strong>需改进：</strong>${low.join('、')}`);
  $('summary-text').innerHTML = parts.join('<br>') || '评测完成，见维度详情。';

  // Key alerts
  const alerts = $('key-alerts');
  alerts.innerHTML = '';
  const addAlert = (cls, msg) => {
    const d = el('div', `alert-item ${cls}`);
    d.textContent = msg;
    alerts.appendChild(d);
  };

  const c6 = S.c6;
  if (c6?.auto_fail) addAlert('danger', '⛔ C6 自动失败：引用矛盾率过高，V2 被强制评为 1 分');

  const metrics = sum.deterministic_metrics || {};
  if (metrics.C5 != null && metrics.C5 < 0.3)
    addAlert('warn', `⚠ 引用验证率极低 (C5 = ${pct(metrics.C5)})，可能存在大量虚构引用`);

  const correctedDims = Object.entries(sum.corrected_scores || {}).filter(([,v]) => Math.abs((v.corrected||0) - (v.original||0)) >= 2);
  if (correctedDims.length) addAlert('warn', `⚠ ${correctedDims.map(([k])=>k).join('、')} 被 Corrector 校正幅度 ≥ 2 分`);

  const highDisagree = Object.values(sum.dimension_scores || {}).some(d => d.variance?.high_disagreement);
  if (highDisagree) addAlert('info', 'ℹ 部分维度模型间存在较大分歧（high_disagreement=true）');
}

function renderRadar(sum) {
  const dims = sum.dimension_scores || {};
  const indicators = DIM_ORDER.map(d => ({ name: DIMENSIONS[d].label, max: 5 }));
  const values = DIM_ORDER.map(d => dims[d]?.final_score ?? 0);
  const riskColors = DIM_ORDER.map(d => {
    const risk = dims[d]?.hallucination_risk;
    return risk === 'high' ? '#dc2626' : risk === 'medium' ? '#dd5b00' : '#1aae39';
  });

  const container = $('radar-chart');
  if (!S.radarChart) S.radarChart = echarts.init(container);
  S.radarChart.setOption({
    tooltip: { trigger: 'item' },
    radar: {
      indicator: indicators,
      radius: '65%',
      splitNumber: 5,
      axisName: { fontSize: 11, color: '#374151', formatter: v => v },
    },
    series: [{
      type: 'radar',
      data: [{
        value: values,
        name: '评分',
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { color: '#0075de', width: 2 },
        areaStyle: { color: 'rgba(0,117,222,.12)' },
        itemStyle: { color: (p) => riskColors[p.dataIndex] },
      }],
    }],
  });
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
    <span class="dim-name">${meta.label}</span>
    ${corrData ? '<span class="risk-badge corrected">已校正</span>' : `<span class="risk-badge ${risk}">${riskLabel(risk)}</span>`}
  `;

  const scoreDiv = el('div', 'dim-score-block');
  const pct5 = (score / 5) * 100;
  scoreDiv.innerHTML = `
    <span class="score-num" style="color:${scoreColor(score)}">${Number.isInteger(score) ? score : score.toFixed(1)}</span>
    <span class="score-denom">/5</span>
    <div class="score-bar"><div class="score-fill" style="width:${pct5}%;background:${scoreColor(score)}"></div></div>
  `;

  const evDiv = el('div', 'dim-evidence');
  evDiv.innerHTML = evidenceSummaryHtml(dimId, subScore, dimScore);

  const expandBtn = el('button', 'expand-btn');
  expandBtn.textContent = '▼';
  expandBtn.type = 'button';

  header.appendChild(titleDiv);
  header.appendChild(scoreDiv);
  header.appendChild(evDiv);
  header.appendChild(expandBtn);

  // ── Detail (level 2) ─────────────────────────────────
  const detail = el('div', 'dim-detail');
  detail.id = `detail-${dimId}`;

  // Rubric
  const rubric = RUBRICS[dimId]?.[Math.round(score)];
  if (rubric) {
    const rs = el('div', 'detail-section');
    rs.innerHTML = `<h4>Rubric 等级</h4><p>${rubric}</p>`;
    detail.appendChild(rs);
  }

  // Agent reasoning
  const reasoning = subScore?.llm_reasoning;
  if (reasoning) {
    const rs = el('div', 'detail-section');
    rs.innerHTML = `<h4>Agent 推理</h4><p>${escHtml(reasoning)}</p>`;
    detail.appendChild(rs);
  }

  // Flagged items
  const flagged = subScore?.flagged_items || [];
  if (flagged.length) {
    const fs = el('div', 'detail-section');
    fs.innerHTML = `<h4>标记项目</h4><ul class="flagged-list">${flagged.map(f => `<li>${escHtml(String(f))}</li>`).join('')}</ul>`;
    detail.appendChild(fs);
  }

  // Corrector info
  if (corrData) {
    const cs = el('div', 'detail-section');
    const v = corrData.variance || {};
    const models = (v.models_used || []).join(', ');
    const scores = (v.scores || []).join(' / ');
    cs.innerHTML = `<div class="corrector-box">
      <strong>Corrector 校正</strong>：原始分 ${corrData.original_score} → 校正分 ${corrData.corrected_score}（std=${(v.std||0).toFixed(3)}）
      <div class="model-scores">模型：${models}<br>各分：${scores}</div>
    </div>`;
    detail.appendChild(cs);
  }

  // Special: V2 contradictions inline preview
  if (dimId === 'V2' && S.c6) {
    const cs = el('div', 'detail-section');
    const rate = S.c6.contradiction_rate;
    const fail = S.c6.auto_fail;
    cs.innerHTML = `<h4>C6 引用-断言对齐</h4>
      <p>矛盾率 <strong>${pct(rate)}</strong>（${S.c6.contradict}/${S.c6.total_pairs} 对）
      ${fail ? ' <span style="color:var(--danger);font-weight:700">AUTO-FAIL</span>' : ''}</p>
      <a class="btn-outline" style="font-size:.78rem;padding:4px 10px;display:inline-block;margin-top:6px" onclick="event.stopPropagation();openPanel('panel-c6')">查看完整矛盾列表 →</a>`;
    detail.appendChild(cs);
  }

  // Special: E1 missing papers inline
  if (dimId === 'E1' && S.keyPapers) {
    const mp = (S.keyPapers.missing_key_papers || []).slice(0, 3);
    if (mp.length) {
      const ms = el('div', 'detail-section');
      ms.innerHTML = `<h4>缺失核心文献（前${mp.length}篇）</h4>` +
        mp.map(p => `<div style="font-size:.82rem;padding:3px 0"><strong>${escHtml(p.title||'')}</strong> (${p.year||'?'}, 被引 ${p.citation_count||'?'})</div>`).join('') +
        `<a class="btn-outline" style="font-size:.78rem;padding:4px 10px;display:inline-block;margin-top:6px" onclick="event.stopPropagation();openPanel('panel-keypapers')">查看完整列表 →</a>`;
      detail.appendChild(ms);
    }
  }

  // Raw toggle
  const rawBtn = el('button', 'raw-toggle-btn');
  rawBtn.textContent = '查看原始数据 ▼';
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
  return { low: '确定性', medium: 'LLM判断', high: 'LLM判断(高风险)', null: '—' }[r] || r || '—';
}

function evidenceSummaryHtml(dimId, subScore, dimScore) {
  const ev = subScore?.tool_evidence || {};
  const metrics = S.summary?.deterministic_metrics || {};

  switch (dimId) {
    case 'V1': {
      const c5 = ev.C5 ?? metrics.C5;
      return c5 != null ? `C5 = ${pct(c5)}（验证率）` : '';
    }
    case 'V2': {
      const rate = S.c6?.contradiction_rate;
      const af = S.c6?.auto_fail;
      if (af) return '<span style="color:var(--danger)">C6 自动失败</span>';
      return rate != null ? `C6 矛盾率 = ${pct(rate)}` : '';
    }
    case 'V4': return ev.c6_contradictions != null ? `${ev.c6_contradictions} 条矛盾证据` : '';
    case 'E1': {
      const g4 = ev.G4 ?? metrics.G4;
      const miss = S.keyPapers?.missing_key_papers?.length;
      return [g4 != null ? `G4 = ${pct(g4)}` : '', miss ? `${miss} 篇核心文献缺失` : ''].filter(Boolean).join('，') || '';
    }
    case 'E2': { const s5 = ev.S5 ?? metrics.S5; return s5 != null ? `S5 (NMI) = ${fmt3(s5)}` : ''; }
    case 'R1': { const t5 = ev.T5 ?? metrics.T5; return t5 != null ? `T5 趋势对齐 = ${fmt3(t5)}` : ''; }
    case 'R2': { const s3 = ev.S3 ?? S.analysis?.structural?.S3_citation_gini; return s3 != null ? `S3 (Gini) = ${fmt3(s3)}` : ''; }
    case 'R3': { const s5 = ev.S5 ?? metrics.S5; return s5 != null ? `S5 = ${fmt3(s5)}` : ''; }
    default: return '';
  }
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
      <div class="stat-box"><div class="stat-val">${refs.length}</div><div class="stat-key">参考文献</div></div>
      <div class="stat-box"><div class="stat-val">${cits.length}</div><div class="stat-key">引用实例</div></div>
      <div class="stat-box"><div class="stat-val">${sections.length}</div><div class="stat-key">章节</div></div>
    </div>
    <h4 style="margin-top:16px;margin-bottom:6px;font-size:.82rem;color:var(--text-muted);text-transform:uppercase">章节列表</h4>
    <div>${sections.map(s => `<span class="tag" style="margin:2px">${escHtml(s)}</span>`).join('')}</div>
    <h4 style="margin-top:16px;margin-bottom:6px;font-size:.82rem;color:var(--text-muted);text-transform:uppercase">参考文献（前20）</h4>
    <table class="metric-table">
      <tr><th>编号</th><th>标题</th><th>作者</th><th>年份</th></tr>
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
      <div class="stat-box"><div class="stat-val" style="color:var(--success)">${pass}</div><div class="stat-key">通过验证</div></div>
      <div class="stat-box"><div class="stat-val" style="color:var(--danger)">${fail}</div><div class="stat-key">未通过</div></div>
      <div class="stat-box"><div class="stat-val">${vr.length}</div><div class="stat-key">总计</div></div>
      <div class="stat-box"><div class="stat-val">${pct(c5)}</div><div class="stat-key">C5 验证率</div></div>
      ${c3 != null ? `<div class="stat-box"><div class="stat-val">${pct(c3)}</div><div class="stat-key">C3 孤立引用率</div></div>` : ''}
    </div>
    <table class="metric-table" style="margin-top:16px">
      <tr><th>引用键</th><th>标题</th><th>年份</th><th>状态</th><th>置信度</th></tr>
      ${vr.slice(0,30).map(r => `<tr>
        <td class="mono">${r.key}</td>
        <td style="font-size:.78rem">${escHtml(r.comparison?.bib_title || '')}</td>
        <td>${r.comparison?.bib_year || ''}</td>
        <td><span class="valid-badge ${r.is_valid ? 'pass' : 'fail'}">${r.is_valid ? '✓ 通过' : '✗ 失败'}</span></td>
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
      <div class="stat-box"><div class="stat-val">${d.total_pairs}</div><div class="stat-key">总对数</div></div>
      <div class="stat-box"><div class="stat-val" style="color:var(--success)">${d.support}</div><div class="stat-key">支持</div></div>
      <div class="stat-box"><div class="stat-val" style="color:var(--danger)">${d.contradict}</div><div class="stat-key">矛盾</div></div>
      <div class="stat-box"><div class="stat-val">${d.insufficient}</div><div class="stat-key">信息不足</div></div>
      <div class="stat-box"><div class="stat-val ${d.auto_fail ? 'fail' : ''}">${pct(d.contradiction_rate)}</div><div class="stat-key">矛盾率 ${d.auto_fail ? '⛔AUTO-FAIL' : ''}</div></div>
    </div>
    ${d.missing_abstract_count ? `<p class="empty-msg" style="margin-top:8px">⚠ ${d.missing_abstract_count} 对因缺少摘要而标记为 insufficient</p>` : ''}
    ${cons.length === 0 ? '<p class="empty-msg" style="margin-top:12px">无矛盾案例。</p>' : `
      <h4 style="margin:14px 0 8px;font-size:.82rem;color:var(--text-muted);text-transform:uppercase">矛盾案例列表</h4>
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
  const t = S.analysis.temporal || {};
  const st = S.analysis.structural || {};
  const metrics = S.summary?.deterministic_metrics || {};

  // Metrics table
  $('temporal-metrics').innerHTML = `
    <div class="stat-row" style="margin-top:16px">
      <div class="stat-box"><div class="stat-val">${t.T1_year_span ?? '?'}</div><div class="stat-key">T1 时间跨度（年）</div></div>
      <div class="stat-box"><div class="stat-val">${t.T2_foundational_retrieval_gap != null ? t.T2_foundational_retrieval_gap+'年' : 'N/A'}</div><div class="stat-key">T2 基础文献缺口</div></div>
      <div class="stat-box"><div class="stat-val">${t.T3_peak_year_ratio != null ? pct(t.T3_peak_year_ratio) : 'N/A'}</div><div class="stat-key">T3 近年引用比</div></div>
      <div class="stat-box"><div class="stat-val">${t.T4_temporal_continuity != null ? t.T4_temporal_continuity+'年' : 'N/A'}</div><div class="stat-key">T4 最大连续空白</div></div>
      <div class="stat-box"><div class="stat-val">${t.T5_trend_alignment != null ? fmt3(t.T5_trend_alignment) : 'N/A'}</div><div class="stat-key">T5 趋势对齐（r）</div></div>
    </div>
    <div class="stat-row" style="margin-top:8px">
      <div class="stat-box"><div class="stat-val">${st.S1_section_count??'?'}</div><div class="stat-key">S1 章节数</div></div>
      <div class="stat-box"><div class="stat-val">${st.S2_citation_density!=null?fmt1(st.S2_citation_density):'?'}</div><div class="stat-key">S2 引用密度</div></div>
      <div class="stat-box"><div class="stat-val">${st.S3_citation_gini!=null?fmt3(st.S3_citation_gini):'?'}</div><div class="stat-key">S3 Gini 系数</div></div>
      <div class="stat-box"><div class="stat-val">${st.S4_zero_citation_section_rate!=null?pct(st.S4_zero_citation_section_rate):'?'}</div><div class="stat-key">S4 零引用章节率</div></div>
    </div>`;

  // Chart
  renderTemporalChart(t, S.trendBaseline);
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
    legend: { data: ['综述引用分布', '领域发表趋势'], bottom: 4 },
    xAxis: { type: 'category', data: [...new Set([...surveyYears, ...trendYears])].sort() },
    yAxis: [
      { type: 'value', name: '引用数', nameTextStyle: { fontSize: 11 } },
      { type: 'value', name: '归一化趋势', nameTextStyle: { fontSize: 11 }, axisLabel: { show: false } },
    ],
    series: [
      { name: '综述引用分布', type: 'bar', data: surveyYears.map((y, i) => [y, surveyCounts[i]]),
        itemStyle: { color: '#0075de' } },
      { name: '领域发表趋势', type: 'line', yAxisIndex: 1,
        data: trendYears.map(y => [y, (trendData[y]||0) * scale]),
        lineStyle: { color: '#dd5b00', width: 2 }, symbol: 'circle', symbolSize: 5,
        itemStyle: { color: '#dd5b00' } },
    ],
  };
  S.temporalChart.setOption(option);
}

function renderGraphPanel() {
  if (!S.validation || !S.graphAnalysis) return;

  // Metrics: render once (panel can be closed)
  if (!S.rendered.has('graph-metrics')) {
    S.rendered.add('graph-metrics');
    const ga = S.graphAnalysis?.citation_graph_analysis || {};
    const meta = ga.meta || {};
    const dc = ga.summary?.density_connectivity || {};
    const metrics = S.summary?.deterministic_metrics || {};

    $('graph-metrics').innerHTML = `
      <div class="stat-row" style="margin-top:12px">
        <div class="stat-box"><div class="stat-val">${meta.n_nodes??'?'}</div><div class="stat-key">节点数</div></div>
        <div class="stat-box"><div class="stat-val">${meta.n_edges??'?'}</div><div class="stat-key">边数</div></div>
        <div class="stat-box"><div class="stat-val">${fmt3(metrics.G1??dc.density_global)}</div><div class="stat-key">G1 密度</div></div>
        <div class="stat-box"><div class="stat-val">${metrics.G2??dc.n_weak_components??'?'}</div><div class="stat-key">G2 连通分量</div></div>
        <div class="stat-box"><div class="stat-val">${fmt3(metrics.G3??dc.lcc_frac)}</div><div class="stat-key">G3 最大分量比</div></div>
        <div class="stat-box"><div class="stat-val">${pct(metrics.G4)}</div><div class="stat-key">G4 核心覆盖率</div></div>
        <div class="stat-box"><div class="stat-val">${pct(metrics.G6)}</div><div class="stat-key">G6 孤立节点率</div></div>
      </div>`;
  }

  // vis.js network: only init when panel is actually open (container has a size)
  if (document.getElementById('panel-graph')?.open) {
    renderCitationGraph();
  }
}

const CLUSTER_PALETTE = [
  '#60a5fa','#f59e0b','#34d399','#f472b6','#a78bfa',
  '#22d3ee','#fb7185','#facc15','#2dd4bf','#c084fc'
];

function renderCitationGraph() {
  const container = $('citation-graph');
  if (!container || S.citationNetwork) return;

  const vr = S.validation?.reference_validations || [];
  const edges = S.validation?.real_citation_edges || [];
  const clusters = S.graphAnalysis?.citation_graph_analysis?.summary?.cocitation_clustering?.clusters || [];

  // Build paper_id → cluster_id map
  const clusterMap = {};
  clusters.forEach(cl => {
    (cl.top_papers || []).forEach(tp => { clusterMap[tp.paper_id] = cl.cluster_id; });
  });

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
    const color = isolated ? '#a39e98' : cid != null ? CLUSTER_PALETTE[cid % 10] : '#0075de';
    const meta = r.comparison || r.metadata || {};
    const title = `<b>${escHtml(meta.bib_title || r.key)}</b><br>` +
      `年份：${meta.bib_year||'?'}　验证：${r.is_valid?'✓':'✗'}`;
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

  const edgeData = edges.map((e, i) => ({
    id: `e${i}`, from: e.source, to: e.target,
    arrows: 'to', color: { color: '#94a3b844' }, width: 0.7,
  }));

  if (typeof vis === 'undefined') {
    container.innerHTML = '<p class="empty-msg" style="padding:20px">vis.js 库加载失败，请检查网络连接。</p>';
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
  if (badge) badge.textContent = `${nodes.length} 节点 · ${edgeData.length} 边`;

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
  const missing = kp.missing_key_papers || [];
  const matched = (kp.candidate_papers || []).filter(p =>
    !(missing.some(m => m.title === p.title)));

  body.innerHTML = `
    <div class="stat-row">
      <div class="stat-box"><div class="stat-val">${pct(kp.coverage_rate)}</div><div class="stat-key">G4 覆盖率</div></div>
      <div class="stat-box"><div class="stat-val">${matched.length}</div><div class="stat-key">已覆盖</div></div>
      <div class="stat-box"><div class="stat-val" style="color:var(--danger)">${missing.length}</div><div class="stat-key">缺失</div></div>
    </div>
    ${missing.length === 0 ? '<p class="empty-msg" style="margin-top:12px">未检测到缺失核心文献。</p>' : `
      <h4 style="margin:16px 0 8px;font-size:.82rem;color:var(--text-muted);text-transform:uppercase">缺失核心文献（建议补充）</h4>
      <div class="paper-list">
        ${missing.slice(0,20).map(p => `<div class="paper-item">
          <div class="paper-year">${p.year||'?'}</div>
          <div class="paper-info">
            <div class="paper-title">${escHtml(p.title||'')}</div>
            <div class="paper-meta">被引 ${p.citation_count??'?'} 次　${escHtml(p.venue||'')}</div>
          </div>
        </div>`).join('')}
      </div>`}
  `;
}

function renderSysInfo() {
  const body = $('body-sysinfo');
  const run = S.runJson || {};
  const sum = S.summary || {};

  body.innerHTML = `
    <table class="metric-table" style="margin-bottom:16px">
      <tr><th>字段</th><th>值</th></tr>
      <tr><td>Run ID</td><td class="mono">${sum.run_id||'?'}</td></tr>
      <tr><td>时间戳</td><td class="mono">${sum.timestamp||'?'}</td></tr>
      <tr><td>PDF 来源</td><td class="mono">${sum.source||'?'}</td></tr>
      <tr><td>Schema 版本</td><td class="mono">${sum.schema_version||'?'}</td></tr>
    </table>
    <h4 style="font-size:.82rem;color:var(--text-muted);text-transform:uppercase;margin-bottom:8px">指标定义（metrics_index）</h4>
    <pre class="raw-json">${escHtml(JSON.stringify(run.metrics_index||{}, null, 2))}</pre>
    <h4 style="font-size:.82rem;color:var(--text-muted);text-transform:uppercase;margin-top:16px;margin-bottom:8px">run_summary.json 原始数据</h4>
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
        <p>📄 无法加载 PDF 预览</p>
        <p class="pdf-hint">未找到 PDF 文件路径</p>
      </div>`;
    return;
  }

  // Try to load PDF using object/embed tag
  container.innerHTML = `
    <object data="${pdfUrl}" type="application/pdf" width="100%" height="100%">
      <embed src="${pdfUrl}" type="application/pdf" width="100%" height="100%">
        <div class="pdf-placeholder">
          <p>无法直接显示 PDF</p>
          <p class="pdf-hint">浏览器不支持 PDF 预览，请<a href="${pdfUrl}" target="_blank">点击下载</a></p>
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
  startBtn.textContent = '开始评测';

  // Reset PDF viewer
  const pdfContainer = $('pdf-container');
  if (pdfContainer) {
    pdfContainer.innerHTML = `
      <div class="pdf-placeholder">
        <p>PDF 预览加载中…</p>
        <p class="pdf-hint">如果无法显示，请检查文件路径</p>
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
