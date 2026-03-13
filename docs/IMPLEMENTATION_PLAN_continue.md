# SurveyMAE Plan_v2 实施计划

本文档详细列出将 SurveyMAE 从当前状态推进到完全符合 Plan_v2 Phase 1 & Phase 2 要求的实施计划。

---

## 一、实施进度总览

### 1.1 任务完成状态

| 任务 | 状态 | 说明 |
|------|------|------|
| TODO 1: 扩展 evidence_collection 节点 | ✅ 已完成 | 实现完整工具调用链 |
| TODO 2: 配置外部化 | ✅ 已完成 | YAML 配置已添加 |
| TODO 3: 聚类算法切换 | ✅ 已完成 | 支持 cocitation/louvain/spectral |
| TODO 4: 端到端测试 | 🔄 待验证 | 需要真实 PDF 运行 |
| TODO 5: G1/G5 null 问题调查 | 🔄 待处理 | 外部 API 限流导致 |

### 1.2 已完成的修改

**evidence_collection.py**:
- ✅ 完整工具调用链实现（7个步骤）
- ✅ 从配置读取参数
- ✅ 传递 clustering_config 到图分析器

**citation_graph_analysis.py**:
- ✅ 添加 `clustering_algorithm` 配置项
- ✅ 添加 `clustering_seed` 配置项
- ✅ 实现 `_louvain_clustering()` 方法
- ✅ 实现 `_spectral_clustering()` 方法
- ✅ 算法选择逻辑

**config/main.yaml**:
- ✅ `evidence` 配置段已完整定义

---

## 二、待处理问题

### 2.1 G1/G5 返回 null 问题

**问题描述**: 运行后 G1 (density) 和 G5 (clusters) 仍返回 null/None

**根本原因**: `_build_citation_edges()` 返回空列表，因为外部 API (Semantic Scholar) 限流导致 `ref_metadata_cache` 中没有 `references` 字段

**涉及文件**:
- `src/graph/nodes/evidence_collection.py` - `_build_citation_edges()` 函数
- `src/tools/citation_checker.py` - 引用验证逻辑

**可能的解决方案**:
1. 增加 API 重试机制
2. 添加缓存机制避免重复请求
3. 使用本地缓存的引用数据
4. 降级处理：无边数据时使用节点度统计

### 2.2 聚类算法单元测试覆盖

**问题描述**: 新增的 louvain/spectral 聚类方法缺少单元测试

**涉及文件**:
- `tests/unit/test_citation_graph_analysis.py`

**待添加测试**:
- `test_louvain_clustering()` - 测试 Louvain 聚类
- `test_spectral_clustering()` - 测试 Spectral 聚类
- `test_clustering_config_loading()` - 测试配置加载

---

## 三、历史问题诊断（已解决）

### 3.1 原始问题（已修复）

| 组件 | 原状态 | 现状态 |
|------|--------|--------|
| PDF 解析 | ✅ 正常 | ✅ 正常 |
| Agent 评估 | ✅ 正常 | ✅ 正常 |
| 工具指标 | ❌ 空 | ✅ 有值（C3/C5/T1-T5/S1-S4） |
| 引用图分析 | ❌ 空 | ✅ 部分可用（G1/G5 待 API） |
| 多模型投票 | ✅ 正常 | ✅ 正常 |
| 报告生成 | ✅ 正常 | ✅ 正常 |

### 3.2 修复的历史问题

1. **ImportError**: `CitationGraphAnalysis` → `CitationGraphAnalyzer`
2. **AttributeError**: validation 为 None 时的处理
3. **Missing Parameter**: `compute_section_cluster_alignment` 缺少 `cluster_evidence` 参数
4. **Config Loading**: 添加 EvidenceConfig 类并正确加载

---

## 四、待办清单

### TODO 1: 扩展 evidence_collection 节点为完整工具执行链 ✅

### TODO 2: 添加配置外部化（config/main.yaml）✅

### TODO 3: 聚类算法切换支持 ✅

### TODO 4: 端到端集成测试验证 🔄

### TODO 5: G1/G5 null 问题调查 🔄

### TODO 6: 聚类算法单元测试覆盖 🔄

---

## 五、测试发现的 Bug 记录

### Bug 1: numpy.float64 序列化错误 🔴 (P0)

**错误信息**:
```
TypeError: Type is not msgpack serializable: numpy.float64
```

**发生位置**: LangGraph checkpointer 在 reporter 节点完成后保存状态时

**根本原因**: 某个地方返回了 numpy.float64 类型，LangGraph 的 msgpack 序列化器无法处理。可能来源：
- sklearn 的 `SpectralClustering.fit_predict()` 返回 numpy 类型
- 其他 sklearn/numpy 操作

**修复方案**:
```python
# 方案1: 在 compile_workflow 中禁用 checkpointer
# src/graph/builder.py
checkpointer = checkpointer or MemorySaver()
if checkpointer is False:
    compiled = workflow.compile()  # 无 checkpointer
else:
    compiled = workflow.compile(checkpointer=checkpointer)

# 方案2: 添加类型转换函数
def convert_numpy_types(obj):
    """Convert numpy types to Python native types."""
    import numpy as np
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, (np.float64, np.float32)):
        return float(obj)
    elif isinstance(obj, (np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, dict):
        return {k: convert_numpy_types(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [convert_numpy_types(i) for i in obj]
    return obj
```

---

### Bug 2: G1/G5 返回 None 🔴 (P0)

**错误信息**:
```
G1 (density): None
G5 (cocitation_clusters): None
```

**根本原因**: `_build_citation_edges()` 返回空列表，因为 ref_metadata_cache 中没有 references 字段

**修复方案**:
```python
# src/graph/nodes/evidence_collection.py
def _build_citation_edges(ref_metadata_cache):
    edges = []

    # 尝试从 metadata 获取引用
    for ref_id, metadata in ref_metadata_cache.items():
        refs = metadata.get("references", [])
        if isinstance(refs, list):
            for target_id in refs:
                if target_id in ref_metadata_cache:
                    edges.append((ref_id, target_id))

    # 降级处理：如果没有边，使用基于标题相似性的伪边
    if not edges:
        logger.warning("No citation edges found, using fallback")
        # 可以基于标题相似性或其他特征构建伪边

    return edges
```

---

### Bug 3: LiteratureResult 缺少 venue 属性 🟡 (P1)

**错误信息**:
```
'LiteratureResult' object has no attribute 'venue'
```

**发生位置**: Step 4: Retrieving candidate key papers

**修复方案**:
```python
# src/tools/literature_search.py
@dataclass
class LiteratureResult:
    paper_id: str
    title: str
    authors: List[str]
    year: Optional[int]
    citation_count: int
    url: str
    venue: Optional[str] = None  # 添加这个字段
```

---

### Bug 4: KeywordExtractor 继承问题 🟡 (P1)

**错误信息**:
```
Keyword extraction failed: Can't instantiate abstract class BaseAgent without an implementation for abstract method 'evaluate'
```

**修复方案**:
```python
# 方案1: 不继承 BaseAgent
class KeywordExtractor:
    ...

# 方案2: 实现 evaluate 方法
class KeywordExtractor(BaseAgent):
    async def evaluate(self, state: SurveyState) -> Dict[str, Any]:
        # 实现具体逻辑
        pass
```

---

### Bug 5: UnboundLocalError 🟢 (P2)

**错误信息**:
```
UnboundLocalError: cannot access local variable 'sys' where it is not associated with a value
```

**修复方案**: 在 main.py 开头添加 `import sys`

---

## 六、G1/G5 Null 问题 Debug 计划

### 5.1 问题描述

运行 `uv run python -m src.main test_survey2.pdf` 后：
- G1 (density_global): `null`
- G5 (n_clusters): `null` 或 0
- S5 (nmi/ari): `null`

### 5.2 根本原因分析

**调用链追踪**:

```
evidence_collection.py
  └─ _build_citation_edges(ref_metadata_cache)
       └─ 遍历 ref_metadata_cache 中的 references 字段
       └─ 问题: ref_metadata_cache 为空或没有 references 字段

原因:
1. CitationChecker.validate_references() 调用外部 API (Semantic Scholar)
2. API 返回数据中 references 字段为空或被截断
3. 可能原因: API 限流、网络问题、认证失败
```

### 5.3 Debug 步骤

**Step 1: 验证 ref_metadata_cache 数据结构**

```python
# 在 evidence_collection.py 中添加调试日志
logger.info(f"ref_metadata_cache keys: {list(ref_metadata_cache.keys())[:5]}")
for ref_id, meta in list(ref_metadata_cache.items())[:3]:
    logger.info(f"  {ref_id}: {list(meta.keys())}, references={meta.get('references', 'N/A')}")
```

**Step 2: 检查 API 响应**

```python
# 在 citation_checker.py 中添加
logger.info(f"API response: {response.status_code}, data_keys={response.json().keys()}")
```

**Step 3: 验证 _build_citation_edges 函数**

```python
# 在 evidence_collection.py 中添加
edges = _build_citation_edges(ref_metadata_cache)
logger.info(f"Built {len(edges)} citation edges")
```

### 5.4 可能的修复方案

**方案 1: 添加 API 重试机制**

```python
# citation_checker.py
async def validate_references_with_retry(references, max_retries=3):
    for attempt in range(max_retries):
        try:
            result = await validate_once(references)
            if result.get("references"):
                return result
        except RateLimitError:
            await asyncio.sleep(2 ** attempt)  # exponential backoff
    return {"references": [], "validation": {}}
```

**方案 2: 降级处理 - 无边时使用度统计**

```python
# evidence_collection.py
def _build_edges_from_node_metadata(ref_metadata_cache, references):
    """Build edges from reference metadata, fallback to degree-based."""
    edges = []

    # Try to get references from metadata
    for ref_id, metadata in ref_metadata_cache.items():
        refs = metadata.get("references", [])
        if isinstance(refs, list):
            for target_id in refs:
                if target_id in ref_metadata_cache:
                    edges.append((ref_id, target_id))

    # If no edges, create from paper titles as fallback
    if not edges and references:
        # Use first author-year as pseudo-id
        for ref in references:
            key = ref.get("key", "")
            # Generate pseudo-edges based on co-occurrence in sections
            pass

    return edges
```

**方案 3: 使用本地缓存数据**

```python
# 添加本地缓存层
CACHE_DIR = Path("./cache/citation_graph")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def load_cached_references(paper_id: str) -> Optional[dict]:
    cache_file = CACHE_DIR / f"{paper_id}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    return None
```

### 5.5 涉及文件

| 文件 | 修改内容 |
|------|----------|
| `src/graph/nodes/evidence_collection.py` | 添加调试日志，改进降级处理 |
| `src/tools/citation_checker.py` | 添加 API 重试机制 |
| `src/tools/citation_metadata.py` | 检查 references 字段提取 |

### 5.6 验证方式

```bash
# 运行后检查日志
uv run python -m src.main test_survey2.pdf 2>&1 | grep -E "ref_metadata_cache|Built.*edges"

# 预期输出:
# ref_metadata_cache keys: ['[1]', '[2]', ...]
#   [1]: ['key', 'title', 'year', 'references'], references=['paper_id_1', ...]
# Built 150 citation edges

# 检查输出文件
cat output/runs/*/papers/*/02_evidence_collection.json | python -c "import json,sys; d=json.load(sys.stdin); print('G1:', d['output']['tool_evidence']['graph_analysis'].get('G1_density'))"
```

---

## 六、聚类算法单元测试计划

### 6.1 待添加测试

| 测试函数 | 描述 |
|----------|------|
| `test_louvain_clustering` | 测试 Louvain 聚类方法 |
| `test_spectral_clustering` | 测试 Spectral 聚类方法 |
| `test_clustering_algorithm_config` | 测试配置加载和传递 |
| `test_clustering_fallback` | 测试依赖缺失时的降级 |

### 6.2 涉及文件

| 文件 | 修改内容 |
|------|----------|
| `tests/unit/test_citation_graph_analysis.py` | 添加聚类测试用例 |

### 6.3 测试代码示例

```python
def test_louvain_clustering():
    """Test Louvain clustering method."""
    analyzer = CitationGraphAnalyzer()

    # Create test data
    nodes = ["A", "B", "C", "D", "E", "F"]
    out_adj = {
        "A": {"B", "C"},
        "B": {"A", "C"},
        "C": {"A", "B"},
        "D": {"E", "F"},
        "E": {"D", "F"},
        "F": {"D", "E"},
    }
    pagerank = {n: 1.0/6 for n in nodes}

    result = analyzer._louvain_clustering(
        nodes=nodes,
        out_adj=out_adj,
        pagerank=pagerank,
        topk_clusters=5,
        topk_papers=3,
        seed=42,
    )

    # Should find 2 clusters
    assert result["summary"]["n_clusters"] == 2
    assert result["summary"]["clustering_method"] == "louvain"
```

---

## 七、历史计划（保留参考）

### TODO 1: 扩展 evidence_collection 节点

### TODO 1: 扩展 evidence_collection 节点

#### 涉及文件

| 文件路径 | 修改内容 |
|----------|----------|
| `src/graph/nodes/evidence_collection.py` | 完全重写，实现完整工具调用链 |
| `src/core/state.py` | 可能需要添加错误处理字段 |

#### 实现逻辑

```
evidence_collection 节点执行流程：

1. [CitationChecker.validate]
   ├─ 输入: source_pdf
   ├─ 调用: checker.extract_citations_with_context_from_pdf()
   ├─ 调用: checker.validate_references() - 外部 API 验证
   ├─ 输出: validation (C3: orphan_ref_rate, C5: metadata_verify_rate)
   └─ 输出: ref_metadata_cache (标题/年份/被引次数/引用列表/venue)

2. [关键词提取 - KeywordExtractor]
   ├─ 输入: parsed_content 中的标题/摘要/章节标题
   ├─ 调用: extractor.extract_keywords()
   ├─ 输出: topic_keywords (3-5 组检索关键词)
   └─ 共享给: T2/T5/G4 使用

3. [field_trend_baseline 检索 - LiteratureSearch]
   ├─ 输入: topic_keywords
   ├─ 调用: search_field_trend() x 3-5 组 query
   ├─ 输出: field_trend_baseline (各年份领域发表量)
   └─ 用途: T2, T5 计算

4. [candidate_key_papers 检索 - LiteratureSearch]
   ├─ 输入: topic_keywords
   ├─ 调用: search_top_cited() - 按被引次数排序
   ├─ 输出: candidate_key_papers (top-30 高被引论文)
   └─ 用途: G4 计算

5. [时序分析 - CitationAnalyzer]
   ├─ 输入: ref_metadata_cache (年份字段)
   ├─ 调用: analyzer.compute_temporal_metrics(references, field_trend_baseline)
   ├─ 输出: T1-T5 指标 (year_span, foundational_gap, peak_ratio, continuity, trend_alignment)
   └─ 输出: S1-S4 指标 (section_count, citation_density, gini, zero_rate)

6. [引用图分析 - CitationGraphAnalysis]
   ├─ 输入: ref_metadata_cache (引用列表构建边)
   ├─ 调用: graph_analyzer.analyze(references, edges)
   ├─ 输出: G1-G6 指标 (density, components, lcc, clusters, isolates)
   └─ 输出: S5 指标 (section_cluster_alignment - NMI/ARI)

7. [核心文献覆盖分析 - FoundationalCoverageAnalyzer]
   ├─ 输入: topic_keywords, survey_references, ref_metadata_cache
   ├─ 调用: analyzer.analyze(topic_keywords, references, cache)
   ├─ 输出: G4 指标 (foundational_coverage_rate)
   └─ 输出: missing_key_papers, suspicious_centrality
```

#### 代码修改要点

**文件**: `src/graph/nodes/evidence_collection.py`

```python
# 需要添加的导入
from src.tools.citation_checker import CitationChecker
from src.tools.citation_analysis import CitationAnalyzer
from src.tools.citation_graph_analysis import CitationGraphAnalysis
from src.tools.keyword_extractor import KeywordExtractor
from src.tools.literature_search import LiteratureSearch
from src.tools.foundational_coverage import FoundationalCoverageAnalyzer

# 需要实现的步骤
async def run_evidence_collection(state: SurveyState) -> Dict[str, Any]:
    # 1. CitationChecker - 提取 + 验证
    checker = CitationChecker()
    extraction = checker.extract_citations_with_context_from_pdf(source_pdf)
    references = checker.extract_references_from_pdf(source_pdf)
    validation = checker.validate_references(extraction, verify_sources=["semantic_scholar", "openalex"])
    ref_metadata_cache = build_cache_from_validation(validation)

    # 2. 关键词提取
    extractor = KeywordExtractor()
    title = extract_title_from_parsed(parsed_content)
    abstract = extract_abstract_from_parsed(parsed_content)
    kw_result = await extractor.extract_keywords(title, abstract, section_headings)
    topic_keywords = kw_result.keywords

    # 3. field_trend_baseline
    lit_search = LiteratureSearch()
    field_trend = {}
    for kw in topic_keywords[:3]:
        result = lit_search.search_field_trend(kw, year_range=(2015, 2025))
        merge_trend(field_trend, result)

    # 4. candidate_key_papers
    candidate_papers = []
    for kw in topic_keywords[:3]:
        papers = await lit_search.search_top_cited(kw, top_k=30)
        candidate_papers.extend(papers)

    # 5. 时序/结构分析
    analyzer = CitationAnalyzer()
    temporal_metrics = analyzer.compute_temporal_metrics(references, field_trend)
    structural_metrics = analyzer.compute_structural_metrics(references)

    # 6. 引用图分析
    graph_analyzer = CitationGraphAnalysis()
    edges = build_citation_edges(ref_metadata_cache)
    graph_metrics = graph_analyzer.analyze(references, edges)
    s5_metrics = graph_analyzer.compute_section_cluster_alignment(references, sections)

    # 7. G4 核心文献覆盖
    g4_analyzer = FoundationalCoverageAnalyzer()
    g4_result = await g4_analyzer.analyze(topic_keywords, references, ref_metadata_cache)

    # 组装 tool_evidence
    tool_evidence = {
        "extraction": extraction,
        "validation": {
            "orphan_ref_rate": validation.get("orphan_ref_rate"),
            "metadata_verify_rate": validation.get("metadata_verify_rate"),
            "references": references,
        },
        "analysis": {**temporal_metrics, **structural_metrics},
        "graph_analysis": {**graph_metrics, "foundational_coverage": g4_result},
    }

    return {
        "tool_evidence": tool_evidence,
        "ref_metadata_cache": ref_metadata_cache,
        "topic_keywords": topic_keywords,
        "field_trend_baseline": field_trend,
        "candidate_key_papers": candidate_papers,
    }
```

#### 预期验证结果

运行后 `02_evidence_collection.json` 应包含：

```json
{
  "tool_evidence": {
    "validation": {
      "orphan_ref_rate": 0.05,
      "metadata_verify_rate": 0.85
    },
    "analysis": {
      "T1_year_span": 52,
      "T2_foundational_retrieval_gap": 1,
      "T3_peak_year_ratio": 0.65,
      "T4_temporal_continuity": 0,
      "T5_trend_alignment": 0.78,
      "S1_section_count": 8,
      "S2_citation_density": 3.2,
      "S3_citation_gini": 0.31,
      "S4_zero_citation_section_rate": 0.1
    },
    "graph_analysis": {
      "G1_density": 0.012,
      "G2_components": 3,
      "G3_lcc_frac": 0.85,
      "G4_coverage_rate": 0.72,
      "G5_clusters": 6,
      "G6_isolates": 12,
      "S5_nmi": 0.65
    }
  },
  "topic_keywords": ["retrieval augmented generation", "RAG LLM", "dense passage retrieval"],
  "field_trend_baseline": {"2020": 120, "2021": 250, ...},
  "candidate_key_papers": [...]
}
```

---

### TODO 2: 添加配置外部化

#### 涉及文件

| 文件路径 | 修改内容 |
|----------|----------|
| `config/main.yaml` | 添加 evidence 配置段 |
| `src/core/config.py` | 添加 EvidenceConfig 类 |
| `src/tools/foundational_coverage.py` | 从配置读取 top_k |
| `src/tools/literature_search.py` | 从配置读取 year_range |

#### 实现逻辑

**config/main.yaml 新增配置段**：

```yaml
# Evidence Collection Configuration
evidence:
  # G4 (Foundational Coverage) related
  foundational_top_k: 30              # Number of top-cited papers to retrieve
  foundational_match_threshold: 0.85 # Title matching threshold (rapidfuzz score)

  # T-series (Temporal) related
  trend_query_count: 5              # Number of query groups for field trend
  trend_year_range: [2015, 2025]    # Year range for trend retrieval

  # S5 (Section-Cluster Alignment) related
  clustering_algorithm: "louvain"    # louvain | spectral | leiden
  clustering_seed: 42                # Fixed random seed

  # Sampling related
  citation_sample_size: 15           # Number of citation-claim pairs to sample

  # Fallback/Degradation settings
  api_timeout_seconds: 30
  fallback_order: ["semantic_scholar", "openalex", "crossref"]
```

**src/core/config.py 新增**：

```python
@dataclass
class EvidenceConfig:
    """Evidence collection configuration."""
    foundational_top_k: int = 30
    foundational_match_threshold: float = 0.85
    trend_query_count: int = 5
    trend_year_range: tuple[int, int] = (2015, 2025)
    clustering_algorithm: str = "louvain"
    clustering_seed: int = 42
    citation_sample_size: int = 15
    api_timeout_seconds: int = 30
    fallback_order: list[str] = field(default_factory=lambda: ["semantic_scholar", "openalex"])
```

#### 预期验证结果

- `config/main.yaml` 包含新的 `evidence:` 配置段
- 工具类可从配置读取参数
- 不需要硬编码值

---

### TODO 3: 端到端集成测试

#### 涉及文件

| 文件路径 | 修改内容 |
|----------|----------|
| `tests/integration/test_full_pipeline.py` | 新建全流程测试 |

#### 实现逻辑

测试应覆盖：

```python
@pytest.mark.integration
async def test_full_evaluation_pipeline():
    """Test complete evaluation pipeline with all tools."""
    # 1. 准备测试 PDF
    pdf_path = "test_survey2.pdf"

    # 2. 创建 workflow
    workflow = create_workflow()

    # 3. 执行评估
    result = await workflow.ainvoke({"source_pdf_path": pdf_path})

    # 4. 验证输出
    assert result["tool_evidence"]["validation"]["metadata_verify_rate"] is not None
    assert result["tool_evidence"]["analysis"]["T1_year_span"] is not None
    assert result["topic_keywords"]
    assert result["field_trend_baseline"]

    # 5. 验证 Agent 输出包含工具证据
    for agent in ["verifier", "expert", "reader"]:
        assert agent in result["agent_outputs"]
        # 检查评分是否基于工具证据
```

#### 预期验证结果

```
pytest tests/integration/test_full_pipeline.py -v

test_full_pipeline.py::test_full_evaluation_pipeline PASSED
  - tool_evidence.validation.C3 not None
  - tool_evidence.validation.C5 not None
  - tool_evidence.analysis.T1-T5 not None
  - tool_evidence.graph_analysis.G1-G6 not None
  - topic_keywords populated
  - field_trend_baseline populated
```

---

## 四、执行顺序

| 步骤 | 任务 | 优先级 | 预计工作量 |
|------|------|--------|------------|
| 1 | 扩展 evidence_collection 节点 | P0 | 2-3 小时 |
| 2 | 添加配置外部化 | P1 | 1 小时 |
| 3 | 端到端集成测试 | P1 | 1 小时 |

**建议**: 按顺序执行，每个任务完成后运行测试验证。

---

## 五、风险与注意事项

1. **API 限流**: 完整工具链涉及多个外部 API 调用，需注意 rate limit
   - 建议: 使用 cache 机制，避免重复请求
   - 建议: 设置合理的 timeout

2. **LLM 调用成本**: 关键词提取和候选清洗使用 LLM
   - 建议: 使用 gpt-4o-mini 等低成本模型

3. **工具依赖**: 多个工具需要协同工作
   - 建议: 做好错误处理，单个工具失败不应阻断整个 pipeline

---

## 六、验证检查点

完成每项任务后，检查以下内容：

### evidence_collection 扩展后

```bash
# 查看中间结果
cat output/runs/*/papers/*/02_evidence_collection.json | python -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d['output'].get('tool_evidence',{}).get('analysis',{}), indent=2))"

# 应该看到 T1-T5, S1-S4 指标
```

### 配置添加后

```bash
# 验证配置加载
uv run python -c "from src.core.config import load_config; c=load_config(); print(c.evidence.foundational_top_k)"
# 输出: 30
```

### 端到端测试后

```bash
# 运行完整 pipeline 并检查报告
uv run python -m src.main test_survey2.pdf -o output/test_report.md
# 报告中应显示具体指标数值（非 N/A）
```

---

## 七、相关文档

- [SurveyMAE_Plan_v2.md](docs/SurveyMAE_Plan_v2.md) - 完整设计文档
- [SurveyMAE_Implementation_Supplement.md](docs/SurveyMAE_Implementation_Supplement.md) - 实现补充说明
- [DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) - 开发指南
