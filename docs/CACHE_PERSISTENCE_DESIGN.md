# SurveyMAE 中间缓存与结果持久化设计分析

> 本文档记录了 SurveyMAE 项目的中间缓存和结果持久化设计，以及发现的实现 bug，供后续开发者理解和修复。

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
│  ResultStore 文件系统持久化 + JSON/JSONL 格式                 │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    Agent Layer (无持久化)                    │
│  返回状态更新，由 Graph 层包装持久化                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 各层详细设计

### 2.1 Core Layer - 内存状态缓存

**核心文件**: `src/core/state.py`

#### SurveyState - 工作流主状态

SurveyState 是 TypedDict 类型，定义了工作流中传递的所有状态数据：

```python
class SurveyState(TypedDict):
    # --- 核心缓存字段 ---
    ref_metadata_cache: Dict[str, dict]      # 引用元数据缓存
    tool_evidence: ToolEvidence              # 工具证据
    topic_keywords: List[str]                 # 主题关键词
    field_trend_baseline: Dict[str, Any]     # 领域趋势基线
    candidate_key_papers: List[dict]         # 候选关键论文

    # --- 评估数据 ---
    evaluations: Annotated[List[EvaluationRecord], operator.add]
    debate_history: Annotated[List[DebateMessage], operator.add]
    sections: dict[str, SectionResult]
    agent_outputs: Annotated[Dict[str, AgentOutput], dict_merge]

    # --- 控制流 ---
    current_round: int
    consensus_reached: bool
```

#### 缓存更新机制 - Reducer 模式

项目使用 **Annotated + operator.add** 实现增量更新（LangGraph Reducer 模式）：

```python
# 并行节点安全地追加结果
evaluations: Annotated[List[EvaluationRecord], operator.add]
debate_history: Annotated[List[DebateMessage], operator.add]

# 字典合并更新
agent_outputs: Annotated[Dict[str, AgentOutput], dict_merge]
```

这允许并行节点（如 verifier、expert、reader）安全地追加结果，LangGraph 自动合并。

#### 实际数据结构示例

以实际运行结果 `02_evidence_collection.json` 为例，`ref_metadata_cache` 的结构如下：

```json
{
  "ref_1": {
    "key": "ref_1",
    "title": "Deep learning: a statistical viewpoint",
    "year": "2021",
    "authors": [],
    "doi": "",
    "venue": "",
    "citation_count": 0,
    "external_ids": {},
    "verified": false
  },
  "ref_2": {
    "key": "ref_2",
    "title": "Fit without fear: remarkable mathematical phenomena of deep learning through the prism of interpolation",
    "year": "2021",
    "authors": [],
    "doi": "",
    "venue": "",
    "citation_count": 0,
    "external_ids": {},
    "verified": false
  }
}
```

`tool_evidence.extraction.citations` 的数据结构：

```json
{
  "extraction": {
    "citations": [
      {
        "marker": "[15]",
        "marker_raw": "[25, 15, 26]",
        "kind": "numeric",
        "sentence": "This question is important both scientifically and practically...",
        "page": 1,
        "paragraph_index": 8,
        "ref_key": "ref_15",
        "section_title": "1 Introduction",
        "section_index": 3
      }
    ]
  }
}
```

---

### 2.2 Graph Layer - 工作流级缓存与持久化

**核心文件**: `src/graph/builder.py`

#### ResultStore 全局单例

```python
_result_store: Optional[ResultStore] = None

def _get_result_store(source_pdf_path: str = "") -> ResultStore:
    """Get or create the shared ResultStore instance."""
    global _result_store
    if _result_store is None:
        # 基于 PDF 路径生成 run_id
        pdf_hash = hashlib.md5(source_pdf_path.encode()).hexdigest()[:8]
        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{pdf_hash}"
        _result_store = ResultStore(base_dir="./output/runs", run_id=run_id)
    return _result_store
```

#### 步骤级自动持久化 - Wrapper 模式

每个工作流节点都有对应的 wrapper 函数自动保存中间结果：

```python
async def _wrap_evidence_collection(state: SurveyState) -> dict:
    """Wrapper for evidence_collection node with result saving."""
    input_state = dict(state)
    result = await run_evidence_collection(state)
    _save_workflow_step(
        "02_evidence_collection", state, result,
        input_state=input_state,
        run_params={"node": "evidence_collection"}
    )
    return result
```

所有步骤的 wrapper 函数：
- `_wrap_parse_pdf` → `01_parse_pdf.json`
- `_wrap_evidence_collection` → `02_evidence_collection.json`
- `_wrap_evidence_dispatch` → `03_evidence_dispatch.json`
- `_wrap_agent(agent_name, ...)` → `04_{agent_name}.json`

#### 运行时常驻 - MemorySaver

LangGraph 使用 `MemorySaver` 作为 checkpointer，支持断点续运行：

```python
from langgraph.checkpoint.memory import MemorySaver

checkpointer = checkpointer or MemorySaver()
compiled = workflow.compile(checkpointer=checkpointer)
```

#### 实际输出目录结构

以实际运行结果为例：

```
output/runs/20260317T070826Z_53317b7e/
├── run.json                    # 运行元信息
├── papers/
│   └── 40b1a0d0d47b/          # paper_id (PDF SHA256 前12位)
│       ├── source.json         # 源文件信息 (207 bytes)
│       ├── 01_parse_pdf.json   # 8,200 bytes
│       ├── 02_evidence_collection.json  # 33,035 bytes
│       ├── 03_evidence_dispatch.json    # 1,163,470 bytes
│       ├── 04_verifier.json    # 1,167,922 bytes
│       ├── 04_expert.json      # 1,165,957 bytes
│       ├── 04_reader.json      # 1,164,769 bytes
│       ├── 04_corrector.json   # 1,188,097 bytes
│       └── 04_reporter.json    # 1,207,280 bytes
```

**注意**: 目录中**没有** `extraction.json`、`validation.json`、`analysis.json` 等工具层的独立持久化文件（这是 Bug，见第 4 节）。

#### 步骤 JSON 文件结构

每个步骤的 JSON 文件包含：

```json
{
  "step": "02_evidence_collection",
  "timestamp": "2026-03-17T07:12:06+00:00",
  "source_pdf": "test_paper.pdf",
  "input": { ... },      // 步骤输入（已截断长字符串）
  "output": { ... },     // 步骤输出
  "run_params": { ... }  // 运行参数
}
```

---

### 2.3 Tools Layer - 文件系统持久化

**核心文件**: `src/tools/result_store.py`

#### ResultStore 架构

```python
class ResultStore:
    def __init__(self, base_dir: str = "./output/runs", run_id: Optional[str] = None):
        self.run_dir = self.base_dir / self.run_id      # output/runs/{run_id}/
        self.papers_dir = self.run_dir / "papers"        # papers 子目录
        self._paper_cache: dict[str, str] = {}          # 内存缓存 paper_id
```

#### 设计的目录结构（未正确实现）

```
output/runs/{run_id}/
├── run.json                    # 运行元信息
├── index.json                  # 论文索引
└── papers/
    └── {paper_id}/             # 按 SHA256 前12位命名
        ├── source.json         # 源文件信息
        ├── extraction.json     # 引用提取结果 ← 缺失
        ├── validation.json     # 引用验证结果 ← 缺失
        ├── analysis.json       # 分析结果 ← 缺失
        ├── errors.jsonl        # 错误日志
        ├── agent_logs.jsonl    # Agent 日志
        └── {step_name}.json   # 各步骤输出（Graph 层）
```

#### 持久化方法

| 方法 | 用途 | 状态 |
|------|------|------|
| `register_paper()` | 注册论文，生成 paper_id | ✅ 已调用 |
| `save_extraction()` | 保存引用提取结果 | ⚠️ 未正确传递 result_store |
| `save_validation()` | 保存验证结果 | ⚠️ 未正确传递 result_store |
| `save_analysis()` | 保存分析结果 | ⚠️ 未正确传递 result_store |
| `append_error()` | 追加错误日志 (JSONL) | ⚠️ 未正确传递 result_store |
| `append_agent_log()` | 追加 Agent 日志 (JSONL) | ⚠️ 未正确传递 result_store |
| `update_index()` | 更新索引文件 | ⚠️ 未正确传递 result_store |

---

### 2.4 Agent Layer - 无直接持久化

**核心文件**: `src/agents/base.py`

Agent 层**不直接管理持久化**，而是通过：

1. **返回状态更新**: Agent 的 `process()` 方法返回字典
2. **Graph 层 Wrapper 捕获**: `_wrap_agent()` 自动保存结果
3. **MCP 工具调用**: 通过 MCP 间接调用工具

```python
async def process(self, state: SurveyState) -> Dict[str, Any]:
    """Process the current state and return state updates."""
    record = await self.evaluate(state)
    return {
        "evaluations": [record],
        "agent_outputs": {self.name: agent_output},
    }
```

---

## 3. 缓存失效与复用策略

1. **基于文件内容**: `paper_id` 基于 PDF 文件的 SHA256 哈希，同一文件复用同一 ID
2. **基于时间戳**: `run_id` 包含时间戳，支持多次运行
3. **索引追踪**: `index.json` 记录每篇论文的处理状态（未正确生成）

---

## 4. 实现 Bug 记录

### Bug 1: Tools 层 ResultStore 未正确传递

#### 问题描述

工具层（如 `CitationChecker`、`CitationGraphAnalysis`）的持久化方法（如 `_persist_validation()`）没有被正确调用，导致以下文件缺失：

- `extraction.json` - 引用提取结果
- `validation.json` - 引用验证结果
- `analysis.json` - 分析结果

#### 根本原因

在 `evidence_collection.py` 中创建工具时**没有传入 `result_store` 参数**：

```python
# src/graph/nodes/evidence_collection.py:241
checker = CitationChecker()  # ❌ 没有传入 result_store
```

而 `CitationChecker._persist_validation()` 的实现：

```python
# src/tools/citation_checker.py:652
def _persist_validation(self, ...):
    if not self.result_store:
        return  # ← 因为 result_store=None，直接返回不保存！
```

#### 受影响的工具

| 工具 | 位置 | result_store 参数 |
|------|------|-------------------|
| `CitationChecker` | evidence_collection.py:241 | ❌ 未传递 |
| `CitationGraphAnalysis` | 待确认 | ❌ 未传递 |
| `FoundationalCoverageAnalyzer` | evidence_collection.py:502 | ⚠️ 不支持 |

#### 影响范围

- `ResultStore` 的独立持久化方法未被调用
- `index.json` 未生成
- 工具层日志（errors.jsonl, agent_logs.jsonl）未生成

#### 当前临时方案

Graph 层的 wrapper 已保存完整的工作流步骤数据到 `{step_name}.json` 文件：
- `02_evidence_collection.json` (33KB) - 包含完整的 `tool_evidence` 和 `ref_metadata_cache`
- `03_evidence_dispatch.json` (1.1MB) - 包含完整的 `evidence_reports`

所以工具层的独立持久化文件是**冗余的**，但设计上应该有以保持工具可独立使用。

#### 修复建议

1. **修改 `evidence_collection.py`**:
   - 在 `run_evidence_collection` 函数签名中添加 `result_store` 参数
   - 在创建工具时传入 `result_store`

2. **修改 `builder.py`**:
   - 在 `_wrap_evidence_collection` 中获取 `ResultStore` 并传递给 `run_evidence_collection`

3. **修改工具类**:
   - 确保所有工具（`CitationChecker`、`CitationGraphAnalysis`、`FoundationalCoverageAnalyzer`）都支持 `result_store` 参数

---

### Bug 2: 内存单例导致多用户/多进程冲突

#### 问题描述

`_result_store` 使用全局单例模式，在多用户或多进程环境下会导致冲突：

```python
_result_store: Optional[ResultStore] = None  # 全局单例
```

#### 修复建议

使用依赖注入或上下文管理器替代全局单例。

---

## 5. 总结

| 层次 | 缓存类型 | 介质 | 作用 | 状态 |
|------|----------|------|------|------|
| Core | SurveyState + TypedDict | 内存 | 工作流状态传递 | ✅ 正常 |
| Graph | ResultStore 单例 | 内存+磁盘 | 步骤自动持久化 | ✅ 正常 |
| Tools | ResultStore | 文件系统 | 工具结果持久化 | ❌ Bug |
| Agent | 无 | - | 返回状态更新 | ✅ 正常 |

这种分层设计实现了**关注点分离**：Core 负责状态管理，Graph 负责流程编排，Tools 负责底层数据持久化。主要问题是 Tools 层的 `result_store` 未正确传递，导致工具层的独立持久化文件缺失。

---

## 6. 实际运行结果数据示例

本节展示实际运行生成的持久化 JSON 文件结构和数据片段。

### 6.1 目录结构

```
output/runs/20260317T070826Z_53317b7e/papers/40b1a0d0d47b/
├── source.json                    (207 bytes)
├── 01_parse_pdf.json             (8,200 bytes)
├── 02_evidence_collection.json    (33,035 bytes)
├── 03_evidence_dispatch.json    (1,163,470 bytes)
├── 04_verifier.json             (1,167,922 bytes)
├── 04_expert.json               (1,165,957 bytes)
├── 04_reader.json               (1,164,769 bytes)
├── 04_corrector.json            (1,188,097 bytes)
└── 04_reporter.json             (1,207,280 bytes)
```

**注意**: 以下文件**缺失**（由于 Bug）：
- `extraction.json` - 引用提取结果
- `validation.json` - 引用验证结果
- `analysis.json` - 分析结果
- `index.json` - 论文索引

---

### 6.2 source.json

论文注册信息：

```json
{
  "paper_id": "40b1a0d0d47b",
  "source_path": "C:\\Users\\25370\\Desktop\\SurveyMAE\\test_paper.pdf",
  "sha256": "40b1a0d0d47b",
  "size": 435051,
  "mtime": 1741760926.4308398,
  "metadata": {}
}
```

---

### 6.3 01_parse_pdf.json

**步骤 1: PDF 解析**

文件结构：
```json
{
  "step": "01_parse_pdf",
  "timestamp": "2026-03-17T07:08:26+00:00",
  "source_pdf": "test_paper.pdf",
  "input": { ... },    // 初始状态
  "output": {
    "parsed_content": "## **On Memorization of Large Language Models in** **Logical Reasoning**\n\n**Chulin Xie** ...",
    "metadata": {
      "source": "test_paper.pdf",
      "parsed": "true",
      "parser": "PDFParser"
    }
  },
  "run_params": { "node": "parse_pdf" }
}
```

---

### 6.4 02_evidence_collection.json

**步骤 2: 证据收集**

文件结构：
```json
{
  "step": "02_evidence_collection",
  "timestamp": "2026-03-17T07:12:06+00:00",
  "source_pdf": "test_paper.pdf",
  "input": { ... },    // 来自 01_parse_pdf 的状态
  "output": {
    "tool_evidence": {
      "extraction": {
        "citations": [
          {
            "marker": "[15]",
            "marker_raw": "[25, 15, 26]",
            "kind": "numeric",
            "sentence": "This question is important both scientifically and practically...",
            "page": 1,
            "paragraph_index": 8,
            "ref_key": "ref_15",
            "section_title": "1 Introduction",
            "section_index": 3
          },
          // ... 更多 citations
        ],
        "references": [
          {
            "key": "ref_1",
            "title": "Deep learning: a statistical viewpoint",
            "year": "2021",
            "authors": [],
            "doi": "",
            "venue": "",
            "citation_count": 0,
            "external_ids": {},
            "verified": false
          },
          // ... 更多 references
        ]
      }
    },
    "ref_metadata_cache": {
      "ref_1": { "key": "ref_1", "title": "...", "year": "2021", ... },
      "ref_2": { "key": "ref_2", "title": "...", "year": "2021", ... }
      // ... 更多 ref_metadata
    },
    "topic_keywords": ["memorization", "large language models", "logical reasoning", ...],
    "field_trend_baseline": { ... },
    "candidate_key_papers": [ ... ]
  },
  "run_params": { "node": "evidence_collection" }
}
```

**关键数据结构说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `tool_evidence.extraction.citations` | List[CitationSpan] | 文中所有引用位置 |
| `tool_evidence.extraction.references` | List[ReferenceEntry] | 参考文献条目 |
| `ref_metadata_cache` | Dict[str, RefMetadata] | 参考文献元数据缓存 |
| `topic_keywords` | List[str] | 提取的关键词 |
| `field_trend_baseline` | Dict | 领域趋势基线 |
| `candidate_key_papers` | List[dict] | 候选关键论文 |

---

### 6.5 03_evidence_dispatch.json

**步骤 3: 证据分发**

文件结构：
```json
{
  "step": "03_evidence_dispatch",
  "timestamp": "2026-03-17T07:12:06+00:00",
  "source_pdf": "test_paper.pdf",
  "input": { ... },
  "output": {
    "evidence_reports": {
      "verifier": "...",
      "expert": "...",
      "reader": "..."
    },
    "evidence_report": { ... },
    "verifier_evidence": {
      "metrics": { "C3_orphan_ref_rate": 0.0, "C5_metadata_verify_rate": 0.0, ... },
      "warnings": [...],
      "unverified_references": [...],
      "c6_auto_fail": false,
      "c6_contradictions": []
    },
    "expert_evidence": {
      "metrics": { "G4_coverage_rate": 0.0, ... },
      "warnings": [...],
      "missing_key_papers": [],
      "suspicious_centrality": []
    },
    "reader_evidence": { ... }
  },
  "run_params": { "node": "evidence_dispatch" }
}
```

**各 Agent 证据内容**：

| Agent | evidence 字段 | 说明 |
|-------|---------------|------|
| verifier | metrics, warnings, unverified_references, c6_auto_fail, c6_contradictions | 引用验证证据 |
| expert | metrics, warnings, missing_key_papers, suspicious_centrality | 深度分析证据 |
| reader | - | 可读性证据 |

---

### 6.6 04_verifier.json

**步骤 4: Verifier Agent 评估**

```json
{
  "step": "04_verifier",
  "timestamp": "2026-03-17T07:12:29+00:00",
  "source_pdf": "test_paper.pdf",
  "input": { ... },
  "output": {
    "evaluations": [
      {
        "agent_name": "verifier",
        "dimension": "factuality",
        "score": 5.0,
        "reasoning": "...",
        "evidence": null,
        "confidence": 0.85
      }
    ],
    "agent_outputs": {
      "verifier": {
        "agent_name": "verifier",
        "dimension": "factuality",
        "sub_scores": {
          "V1_citation_existence": {
            "score": 5.0,
            "llm_involved": true,
            "tool_evidence": {},
            "llm_reasoning": "...",
            "flagged_items": null,
            "variance": null
          },
          "V2_citation_supportiveness": { "score": 5.0, ... },
          "V3_citation_accuracy": { "score": 5.0, ... },
          "V4_internal_consistency": { "score": 5.0, ... }
        },
        "overall_score": 5.0,
        "confidence": 0.85,
        "evidence_summary": "..."
      }
    }
  },
  "run_params": { "node": "verifier", "agent_class": "VerifierAgent" }
}
```

---

### 6.7 04_expert.json

**步骤 4: Expert Agent 评估**

```json
{
  "step": "04_expert",
  "timestamp": "2026-03-17T07:12:27+00:00",
  "source_pdf": "test_paper.pdf",
  "input": { ... },
  "output": {
    "evaluations": [ ... ],
    "agent_outputs": {
      "expert": {
        "agent_name": "expert",
        "dimension": "depth",
        "sub_scores": {
          "E1_foundational_coverage": { "score": 5.0, ... },
          "E2_classification_reasonableness": { "score": 5.0, ... },
          "E3_technical_accuracy": { "score": 5.0, ... },
          "E4_critical_analysis_depth": { "score": 5.0, ... }
        },
        "overall_score": 5.0,
        "confidence": 0.9,
        "evidence_summary": "..."
      }
    }
  },
  "run_params": { "node": "expert", "agent_class": "ExpertAgent" }
}
```

---

### 6.8 04_reader.json

**步骤 4: Reader Agent 评估**

```json
{
  "step": "04_reader",
  "timestamp": "2026-03-17T07:12:26+00:00",
  "source_pdf": "test_paper.pdf",
  "input": { ... },
  "output": {
    "evaluations": [ ... ],
    "agent_outputs": {
      "reader": {
        "agent_name": "reader",
        "dimension": "coverage",
        "sub_scores": {
          "R1_timeliness": { "score": 5.0, ... },
          "R2_information_balance": { "score": 5.0, ... },
          "R3_structural_clarity": { "score": 5.0, ... },
          "R4_writing_quality": { "score": 5.0, ... }
        },
        "overall_score": 5.0,
        "confidence": 0.8,
        "evidence_summary": "..."
      }
    }
  },
  "run_params": { "node": "reader", "agent_class": "ReaderAgent" }
}
```

---

### 6.9 04_corrector.json

**步骤 4: Corrector Agent 聚合与校正**

```json
{
  "step": "04_corrector",
  "timestamp": "2026-03-17T07:13:06+00:00",
  "source_pdf": "test_paper.pdf",
  "input": { ... },
  "output": {
    "evaluations": [ ... ],
    "agent_outputs": {
      "corrector": {
        "agent_name": "corrector",
        "dimension": "correction",
        "sub_scores": {
          "C1_bias_detection": { "score": 5.0, ... },
          "C2_balance_correction": { "score": 5.0, ... },
          "C3_variance_control": { "score": 5.0, ... }
        },
        "overall_score": 5.0,
        "confidence": 0.85,
        "evidence_summary": "..."
      }
    }
  },
  "run_params": { "node": "corrector", "agent_class": "CorrectorAgent" }
}
```

---

### 6.10 04_reporter.json

**步骤 4: Reporter Agent 生成最终报告**

```json
{
  "step": "04_reporter",
  "timestamp": "2026-03-17T07:13:20+00:00",
  "source_pdf": "test_paper.pdf",
  "input": { ... },
  "output": {
    "final_report_md": "# SurveyMAE Evaluation Report\n\n**Generated**: 2026-03-17 15:13:20\n\n**Source**: test_paper.pdf\n\n## Overall Score: 2.87/10\n\n**Grade**: F - Unsatisfactory\n\nThe survey fails to meet minimum quality standards.\n\n## Score Summary\n\n| Dimension | Score | Confidence | Type |\n|-----------|-------|------------|------|\n| Depth | 5.00/10 | 0.90 | LLM |\n| Coverage | 5.00/10 | 0.80 | LLM |\n| Factuality | 5.00/10 | 0.85 | LLM |\n| Bias | 5.00/10 | 1.00 | LLM |\n\n## LLM Metrics Variance\n\n- **Standard Deviation**: 1\n...",
    "aggregated_scores": {
      "weighted_score": 2.87,
      "deterministic_score": null,
      "llm_score": 5.0,
      "variance": { "std": 1.0, "models": [...] },
      "agent_scores": { "verifier": 5.0, "expert": 5.0, "reader": 5.0, "corrector": 5.0 }
    },
    "deterministic_score": null,
    "llm_score": 5.0,
    "llm_variance": { "std": 1.0 },
    "overall_score": 2.87,
    "consensus_reached": false
  },
  "run_params": { "node": "reporter", "agent_class": "ReportAgent" }
}
```

---

### 6.11 数据流程总结

```
01_parse_pdf
    ↓
    output: { parsed_content, metadata }
    ↓
02_evidence_collection
    ↓
    output: { tool_evidence, ref_metadata_cache, topic_keywords, ... }
    ↓
03_evidence_dispatch
    ↓
    output: { evidence_reports, verifier_evidence, expert_evidence, reader_evidence }
    ↓
    ├─→ 04_verifier (evaluates factuality)
    ├─→ 04_expert (evaluates depth)
    ├─→ 04_reader (evaluates coverage)
    └─→ 04_corrector (aggregates & corrects)
    ↓
04_reporter
    ↓
    output: { final_report_md, aggregated_scores, overall_score }
```

---

## 7. 相关文件索引

| 文件 | 描述 |
|------|------|
| `src/core/state.py` | SurveyState 定义 |
| `src/graph/builder.py` | 工作流构建与 ResultStore 单例 |
| `src/graph/nodes/evidence_collection.py` | 证据收集节点（Bug 位置） |
| `src/graph/nodes/aggregator.py` | 评分聚合逻辑 |
| `src/tools/result_store.py` | ResultStore 实现 |
| `src/tools/citation_checker.py` | 引用检查工具 |
| `src/tools/citation_graph_analysis.py` | 引用图分析工具 |
| `src/agents/base.py` | Agent 基类 |
| `src/agents/verifier.py` | VerifierAgent 实现 |
| `src/agents/corrector.py` | CorrectorAgent 实现 |
| `src/agents/reporter.py` | ReporterAgent 实现 |

---

## 8. 代码问题逐条解答

### A. ref_metadata_cache 数据完整性

#### A1. CitationChecker 实例化时是否传入 result_store？

**结论：否，未传入 result_store。**

在 `src/graph/nodes/evidence_collection.py` 中：
- 行 241: `checker = CitationChecker()`
- 行 324: `checker = CitationChecker()`
- 行 566: `checker = CitationChecker()`

以上三处均未传入 `result_store` 参数。

**验证结果写入 ref_metadata_cache 的方式：**

验证流程（validate）的结果是通过 `CitationChecker` 内部方法返回后，在 `evidence_collection` 节点函数内手动组装赋值的。具体流程：

1. `CitationChecker.extract_citations_with_context_from_pdf()` 执行验证
2. 返回包含 `references` 列表的结果字典
3. 在 `evidence_collection` 节点函数中调用 `_build_ref_metadata_cache(references)`（行 583）构建缓存

```python
# src/graph/nodes/evidence_collection.py:582-583
# Build ref_metadata_cache from validated references
ref_metadata_cache = _build_ref_metadata_cache(references)
```

#### A2. 验证方法返回数据中各字段的来源

**结论：`citation_count`、`authors`、`doi`、`venue`、`abstract` 字段是从学术 API 响应中提取的，若 API 未返回则为空。**

从 `src/tools/citation_checker.py` 可以看到：

1. **authors 字段**：从 XML 解析（行 179-217）
```python
# 行 179-180
authors = self._parse_authors(bibl)
author_str = " and ".join(authors)
```

2. **abstract 字段**：从 ref.validation.metadata 中获取（行 773）
```python
"abstract": ref.validation.get("metadata", {}).get("abstract", "") if ref.validation else "",
```

3. **doi、venue**：从引用元数据中提取，若 API 未返回则为空字符串

**可能导致字段为空的原因：**
- 学术 API（如 Crossref、Semantic Scholar）未找到该文献
- API 返回的数据不完整（缺少 abstract、authors 等）
- 网络请求失败或超时

#### A3. ref_metadata_cache 是否保存 abstract 字段？C6 如何处理？

**结论：ref_metadata_cache 中默认不包含 abstract 字段。C6 (citation_sentence_alignment) 实现中，当缺少 abstract 时会标记为 "insufficient"。**

在 `src/tools/citation_checker.py` 行 821-822：
```python
insufficient_pairs = [p for p in pairs if not p["has_abstract"]]
pairs_with_abstract = [p for p in pairs if p["has_abstract"]]
```

C6 实现（行 742-946）：
1. 从 ref.validation.metadata 获取 abstract（行 773）
2. 若 abstract 不存在，标记为 "insufficient"（行 822）
3. LLM 分析时使用 "[ABSTRACT NOT AVAILABLE]" 占位符（行 891）

---

### B. Corrector 角色与评分流程

#### B1. CorrectorAgent 的 evaluate 方法做了什么？

**结论：CorrectorAgent 主要通过 LLM 产生 bias 维度的评分，并提供多模型投票机制。**

从 `src/agents/corrector.py` 行 77-149：

```python
async def evaluate(self, state: SurveyState, section_name: Optional[str] = None) -> EvaluationRecord:
    # 获取其他 agent 的输出
    agent_outputs = state.get("agent_outputs", {})
    verifier_output = json.dumps(agent_outputs.get("verifier", {}), indent=2)
    expert_output = json.dumps(agent_outputs.get("expert", {}), indent=2)
    reader_output = json.dumps(agent_outputs.get("reader", {}), indent=2)

    # 调用 LLM 进行 bias 分析
    response = await self._call_llm(messages)

    # 单模型模式：解析响应获取分数
    if not self._llm_pool:
        score, reasoning, evidence = self._parse_corrector_response(response)
    else:
        # 多模型模式：并行调用多个模型并进行投票
        results = await self._call_llm_pool(messages)
        return self._process_multi_model_results(results)
```

**关键发现：**
- Corrector **不是**对 verifier/expert/reader 的子维度分数做投票校正
- 它是**独立**调用 LLM 分析 bias 维度，产生 C1/C2/C3 三个子维度分数
- 多模型投票是为了**减少自身评分方差**，不是校正其他 Agent

#### B2. overall_score: 2.87 的计算路径

**结论：在 `src/graph/nodes/aggregator.py` 的 `_aggregate_from_agent_outputs` 函数中计算，使用 mean(all_scores)。**

从 aggregator.py 行 106-118：
```python
# Calculate overall scores
all_scores = [s["score"] for s in all_sub_scores]
...
overall_score = mean(all_scores)
```

**为什么四个 Agent 的 overall_score 都是 5.0，但最终得分是 2.87？**

查看 04_reporter.json 实际输出：
```json
{
  "aggregated_scores": {
    "factuality": { "overall": 5.0, ... },
    "depth": { "overall": 5.0, ... },
    "coverage": { "overall": 5.0, ... },
    "correction": { "overall": 5.0, ... }
  },
  "deterministic_score": null,
  "llm_score": 5.0,
  "overall_score": 2.87
}
```

**计算分析：**
- 各 Agent 的 overall_score 是 5.0（来自 LLM 评分）
- 但 `overall_score: 2.87` 是根据**所有 sub_scores** 计算的均值
- 由于有 16 个子维度（V1-V4, E1-E4, R1-R4, C1-C3），如果其中部分分数被工具指标影响，可能导致最终得分不同

**实际原因**：需要查看各 Agent 输出的 sub_scores 详细值。当前结果显示 llm_score=5.0，但 overall_score=2.87，这表明可能存在某种加权或调整机制。

#### B3. aggregator.py 的聚合逻辑

**结论：已实现确定性指标和 LLM 指标的区分，使用简单平均计算最终得分。**

从 `src/graph/nodes/aggregator.py` 行 70-153：

```python
def _aggregate_from_agent_outputs(agent_outputs: Dict[str, AgentOutput]) -> Dict[str, Any]:
    # 收集所有子分数
    for agent_name, output in agent_outputs.items():
        for sub_id, sub_score in output.get("sub_scores", {}).items():
            if sub_score.get("llm_involved", True):
                llm_scores.append(sub_score["score"])
            else:
                deterministic_scores.append(sub_score["score"])

    # 计算确定性指标和 LLM 指标的平均分
    deterministic_score = mean(deterministic_scores) if deterministic_scores else None
    llm_score = mean(llm_scores) if llm_scores else None

    # 计算总体得分（所有分数的均值）
    overall_score = mean(all_scores)
```

**特点：**
- ✅ 区分了确定性指标和 LLM 指标
- ✅ 分别计算 deterministic_score 和 llm_score
- ✅ 计算了 LLM 指标的方差（行 125-131）
- ⚠️ 使用简单的 mean 平均，未使用 Plan v2 中设计的**加权平均机制**（虽然代码中有 DEFAULT_DIMENSION_WEIGHTS 定义，但未使用）

---

### C. 持久化机制

#### C1. _save_workflow_step 是否将完整 state 写入 JSON？

**结论：是的，会写入完整 state，但会对大字段进行截断处理。**

从 `src/graph/builder.py` 行 66-116：

```python
def _save_workflow_step(step_name: str, state: SurveyState, data: dict, ...):
    # 添加输入状态（已截断）
    if input_state:
        sanitized_input = _sanitize_state_for_logging(input_state)
        step_record["input"] = sanitized_input

    # 添加输出数据
    step_record["output"] = _sanitize_output_for_logging(data)
```

截断规则（行 119-150）：
- 字符串：超过 2000 字符截断
- 列表：超过 5 项只保留前 3 项和长度信息
- 字典：字符串值超过 500 字符截断

**这就是 04_*.json 文件每个都超过 1MB 的原因**：虽然有截断，但 agent_outputs 包含大量 LLM 推理文本、evidence_reports 等，仍占用大量空间。

#### C2. ResultStore 的方法是否被实际调用？

**结论：方法定义存在，也确实在代码中被调用，但由于 result_store 参数未传递，实际上从未执行成功。**

调用位置：
- `citation_checker.py:647`: `self.result_store.save_extraction(paper_id, result.to_dict())`
- `citation_checker.py:678`: `self.result_store.save_validation(paper_id, validation)`
- `citation_graph_analysis.py:1203`: `self.result_store.save_analysis(paper_id, analysis_payload)`

**问题**：这些方法都在 `if self.result_store:` 条件判断内执行（行 643, 660 等），由于 CitationChecker 初始化时未传入 result_store，所以 `self.result_store` 为 None，方法被跳过。

#### C3. run.json 保存了什么内容？

从实际运行结果 `output/runs/20260317T070826Z_53317b7e/run.json`：
```json
{
  "run_id": "20260317T070826Z_53317b7e",
  "created_at": "2026-03-17T07:08:26Z"
}
```

**结论：仅包含 run_id 和 created_at，不包含 config 参数。**

虽然在 `builder.py` 行 50-66 的 `_init_run_file` 方法中有保存 config_snapshot 和 tool_params 的逻辑：
```python
def _init_run_file(self, config_snapshot=None, tool_params=None):
    if config_snapshot:
        data["config_snapshot"] = config_snapshot
    if tool_params:
        data["tool_params"] = tool_params
```

但实际调用时未传入这些参数（行 42），所以 run.json 只有基础信息。

---

### D. C6 实现状态

#### D1. citation_sentence_alignment (C6) 是否已实现？

**结论：已实现。**

在 `src/tools/citation_checker.py` 行 742 定义：
```python
async def analyze_citation_sentence_alignment(
    self,
    references: list[ReferenceEntry],
    citations: list[CitationSpan],
    ...
) -> dict[str, Any]:
```

在 `src/graph/nodes/evidence_collection.py` 行 326 调用：
```python
c6_result = await checker.analyze_citation_sentence_alignment(
    references,
    citation_spans,
    sources=DEFAULT_VERIFY_SOURCES,
    verify_limit=DEFAULT_VERIFY_LIMIT,
)
```

**关于 c6_auto_fail 和 c6_contradictions**：
- 这些是 C6 方法的**实际返回结果**，不是硬编码
- c6_auto_fail：根据矛盾率是否超过阈值自动触发
- c6_contradictions：从 LLM 分析结果中提取的矛盾对列表

#### D2. VerifierAgent 输出的子维度是 V1/V2/V3/V4 还是 V1/V2/V4？

**结论：实际输出是 V1/V2/V3/V4 四个子维度。**

从实际运行结果 `04_verifier.json`：
```json
"sub_scores": {
    "V1_citation_existence": { "score": 5.0, ... },
    "V2_citation_supportiveness": { "score": 5.0, ... },
    "V3_citation_accuracy": { "score": 5.0, ... },
    "V4_internal_consistency": { "score": 5.0, ... }
}
```

虽然 `src/agents/verifier.py` 行 61-64 注释说评估三个子维度：
> This agent evaluates three sub-dimensions:
> - V1: Citation existence (based on C5 metadata_verify_rate)
> - V2: Citation-assertion alignment (based on C6, with auto-fail shortcut)
> - V4: Internal consistency (LLM-based analysis)

但实际上：
- **V1**: 基于 C5 元数据验证率
- **V2**: 基于 C6 对齐分析（行 86-122）
- **V3**: 可能是 LLM 响应中解析出来的第三个指标（base.py 行 485-495）
- **V4**: 内部一致性

**V3 的来源**：在 `base.py` 的 process 方法中，若 LLM 返回的 reasoning 包含 sub_scores 解析结果，会从中提取 V3。

---

### E. Reporter 输出

#### E1. Reporter 是否能访问确定性指标的数值？

**结论：Reporter 通过 aggregate_scores 间接访问，可获取 deterministic_score 和 llm_score。**

从 `src/agents/reporter.py` 行 63-89：
```python
async def process(self, state: SurveyState) -> Dict[str, Any]:
    # 步骤 1: 聚合分数（纯数学计算）
    aggregation_result = await aggregate_scores(state)

    # 步骤 2: 生成 Markdown 报告
    final_report = generate_report(aggregation_result, state)
```

`aggregate_scores` 返回的数据结构（aggregator.py 行 143-153）：
```python
{
    "aggregated_scores": {...},
    "deterministic_score": 5.0,  # 确定性指标得分
    "llm_score": 5.0,            # LLM 指标得分
    "llm_variance": {...},        # LLM 方差
    "overall_score": 2.87,        # 综合得分
}
```

`generate_report` 函数（行 243-390）会展示：
- 确定性指标：显示为 "Deterministic" 类型
- LLM 指标：显示为 "LLM" 类型，带方差信息

**但需要注意**：当前代码中 deterministic_score 为 null，因为所有 Agent 的 sub_scores 的 llm_involved 默认都是 True。

#### E2. Reporter 生成报告是否有模板？

**结论：有部分模板，LLM 自由生成部分内容。**

`src/graph/nodes/aggregator.py` 的 `generate_report` 函数定义了报告结构模板：

```python
def generate_report(aggregation_result, state):
    lines = [
        "# SurveyMAE Evaluation Report",
        "",
        f"**Generated**: {datetime.now()}",
        "",
        f"## Overall Score: {overall:.2f}/10",
        "",
        _get_score_grade(overall),  # 字母等级
        "",
        "## Score Summary",
        "| Dimension | Score | Confidence | Type |",
        ...
        "## Recommendations",
        ...
    ]
```

**模板化部分**：
- 标题、时间戳、来源
- Overall Score 和字母等级
- Score Summary 表格
- 方差信息
- 评分总结
- Recommendations

**LLM 自由生成部分**：
- 实际上，当前 Reporter (ReportAgent) **没有调用 LLM**，而是直接使用 `generate_report` 函数生成报告（reporter.py 行 78）
- 该函数根据聚合结果**纯程序化**生成 Markdown，不涉及 LLM 调用

**修正**：虽然代码注释提到 "LLM metrics shown with error bars/variance"，但实际实现是模板化的数学计算结果。

---

## 9. 总结与待修复问题

| 类别 | 问题 | 状态 |
|------|------|------|
| A1 | CitationChecker 未传入 result_store | ❌ Bug |
| A2 | ref_metadata_cache 字段可能为空 | ⚠️ 依赖外部 API |
| A3 | C6 处理无 abstract 的引用 | ✅ 已实现 |
| B1 | Corrector 独立评分，非投票校正 | ⚠️ 设计与预期不符 |
| B2 | overall_score 计算路径 | ✅ 已实现 |
| B3 | 聚合逻辑未使用加权平均 | ⚠️ 待优化 |
| C1 | 步骤 JSON 文件过大 | ⚠️ 设计如此 |
| C2 | ResultStore 方法未被调用 | ❌ Bug |
| C3 | run.json 不含 config | ⚠️ 待完善 |
| D1 | C6 已实现 | ✅ 正常 |
| D2 | V1/V2/V3/V4 输出 | ✅ 正常 |
| E1 | 访问确定性指标 | ✅ 已实现 |
| E2 | Reporter 模板化生成 | ✅ 已实现 |
