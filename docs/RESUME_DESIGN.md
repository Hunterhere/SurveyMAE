# LangGraph 断点续功能设计与实现

> 本文档记录 SurveyMAE 基于 LangGraph checkpointer 的断点续功能设计。

## 1. LangGraph 原生能力

LangGraph 通过 `checkpointer` 接口实现状态持久化：

```python
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

# 内存模式
app = workflow.compile(checkpointer=MemorySaver())

# 持久化模式（支持断点续）
app = workflow.compile(checkpointer=SqliteSaver("./checkpoints.db"))
```

### 1.1 核心概念

| 概念 | 说明 |
|------|-------|
| `thread_id` | 唯一标识一次运行会话 |
| `checkpoint_id` | 每次节点执行的唯一标识 |
| `checkpoint` | 某时刻的完整状态快照 |
| `resume** | 从断点恢复执行 |

### 1.2 状态流转

```
LangGraph 自动保存：
- 每个节点的输入
- 每个节点的输出
- 当前工作流位置

LangGraph 不保存：
- 外部文件（extraction.json 等）
- 工具层持久化状态
- index.json 状态
```

## 2. 当前实现

### 2.1 已有的状态记录

| 文件 | 内容 | 用途 |
|------|------|------|
| run.json | run_id, config | 运行元信息 |
| index.json | paper 处理状态 | 论文级进度 |
| 04_*.json | Agent 输出 | Agent 级进度 |
| run_summary.json | 最终结果 | 结果汇总 |

### 2.2 LangGraph checkpointer

当前使用 MemorySaver（内存模式）：

```python
# builder.py:584
checkpointer = checkpointer or MemorySaver()
compiled = workflow.compile(checkpointer=checkpointer)
```

## 3. 断点续设计

### 3.1 三层状态追踪

| 层级 | 状态文件 | 记录内容 |
|------|---------|---------|
| Workflow | LangGraph checkpointer | 节点输入/输出 |
| 工具层 | extraction.json 等 | 工具执行结果 |
| Agent 层 | 04_*.json | Agent 评分结果 |

### 3.2 index.json 扩展

```json
{
  "run_id": "20260319T065912Z_53317b7e",
  "papers": {
    "paper_id": {
      "status": "graph_analyzed",
      "last_node": "04_verifier",
      "checkpoint_id": "1ef2a3b4c5d6e7f8",
      "retry_count": 0,
      "source_path": "test_paper.pdf",
      "created_at": "2026-03-19T06:59:12Z",
      "updated_at": "2026-03-19T07:05:47Z"
    }
  }
}
```

### 3.3 状态枚举

| status | 说明 | 可恢复 |
|--------|------|-------|
| `parsed` | PDF 解析完成 | ✅ |
| `extracted` | 引用提取完成 | ✅ |
| `validated` | 引用验证完成 | ✅ |
| `c6_analyzed` | C6 分析完成 | ✅ |
| `analyzed` | 引用分析完成 | ✅ |
| `graph_analyzed` | 图分析完成 | ✅ |
| `dispatched` | 证据分发完成 | ✅ |
| `verifier_done` | Verifier 完成 | ✅ |
| `expert_done` | Expert 完成 | ✅ |
| `reader_done` | Reader 完成 | ✅ |
| `corrector_done` | Corrector 完成 | ✅ |
| `aggregated` | 聚合完成 | ✅ |
| `reported` | 报告生成完成 | ✅ |

### 3.4 恢复决策逻辑

```python
def should_skip_node(node_name: str, paper_status: str) -> bool:
    """判断节点是否需要跳过

    Args:
        node_name: 当前节点名
        paper_status: index.json 中的状态

    Returns:
        True 如果节点已完成，跳过执行
    """
    skip_map = {
        "parse_pdf": ["parsed", "extracted", "validated", ...],
        "evidence_collection": ["extracted", "validated", ...],
        "evidence_dispatch": [...],
        "04_verifier": [...],
    }
    return paper_status in skip_map.get(node_name, [])
```

## 4. 实现方案

### 4.1 修改 index.json 更新时机

在每个 wrapper 函数中更新状态：

```python
# builder.py
def _wrap_parse_pdf(state):
    result = await parse_pdf(...)
    store.update_index(paper_id, status="parsed", checkpoint_id=get_checkpoint_id())
    return result
```

### 4.2 恢复执行入口

```python
# main.py 或 resume 脚本
def resume_from_checkpoint(
    run_id: str,
    paper_id: str,
    checkpoint_id: str = None
):
    """从断点恢复执行

    Args:
        run_id: 运行 ID
        paper_id: 论文 ID
        checkpoint_id: LangGraph checkpoint ID（可选）
    """
    # 1. 读取 index.json 获取状态
    # 2. 确定需要跳过的节点
    # 3. 构建新 workflow 或使用原 workflow
    # 4. 调用 checkpointer 获取状态
    # 5. 继续执行
```

### 4.3 状态一致性保证

```python
# 工具层完成后更新 index.json
def after_tool_execution(tool_name: str, paper_id: str):
    status_map = {
        "citation_checker": "validated",
        "citation_analyzer": "analyzed",
        "graph_analyzer": "graph_analyzed",
    }
    store.update_index(paper_id, status=status_map[tool_name])
```

## 5. 使用示例

### 5.1 正常执行

```bash
python main.py test_paper.pdf --run-id run_001
# 生成 checkpoint 存储在内存
```

### 5.2 断点续

```bash
# 方式 1：从最后一个 checkpoint 继续
python main.py --resume --run-id run_001 --paper-id 40b1a0d0d47b

# 方式 2：指定 checkpoint
python main.py --resume --run-id run_001 --paper-id 40b1a0d0d47b --checkpoint-id 1ef2a3b4c5d6e7f8
```

### 5.3 Python API

```python
from src.graph.builder import create_workflow
from src.tools.result_store import ResultStore

# 读取状态
store = ResultStore(run_id="run_001")
index = store._read_json(store.run_dir / "index.json")
paper_status = index["papers"][paper_id]["status"]

# 继续执行
if paper_status != "reported":
    workflow = create_workflow(config)
    # 跳过已完成的节点继续执行
```

## 6. 文件变更

| 文件 | 变更 |
|------|------|
| index.json | 新增 last_node, checkpoint_id, retry_count |
| builder.py | 新增状态更新逻辑 |
| main.py | 新增 --resume 参数 |
| result_store.py | 新增状态查询方法 |

## 7. 当前代码能力分析

### 7.1 LangGraph 原生能力（已支持）

| 能力 | 状态 | 说明 |
|------|------|------|
| 节点输入/输出保存 | ✅ | MemorySaver 自动保存 |
| thread_id 恢复 | ✅ | 通过 config 传入 |
| state 恢复 | ✅ | 从 checkpointer 读取 |

### 7.2 工具层（需补充）

| 功能 | 已有基础 | 需补充 |
|------|---------|--------|
| extraction.json | ✅ 已生成 | 读取恢复 |
| validation.json | ✅ 已生成 | 读取恢复 |
| c6_alignment.json | ✅ 已生成 | 读取恢复 |
| analysis.json | ✅ 已生成 | 读取恢复 |
| graph_analysis.json | ✅ 已生成 | 读取恢复 |
| trend_baseline.json | ✅ 已生成 | 读取恢复 |
| key_papers.json | ✅ 已生成 | 读取恢复 |
| **进度判断** | ⚠️ 部分 | 从 index.json status 判断 |
| **状态恢复** | ❌ | 需实现 `_load_from_persistence()` |

### 7.3 代理层（需补充）

| 功能 | 已有基础 | 需补充 |
|------|---------|--------|
| 04_verifier.json | ✅ 已生成 | 读取恢复 |
| 04_expert.json | ✅ 已生成 | 读取恢复 |
| 04_reader.json | ✅ 已生成 | 读取恢复 |
| 04_corrector.json | ✅ 已生成 | 读取恢复 |
| 04_reporter.json | ✅ 已生成 | 读取恢复 |
| **进度判断** | ⚠️ 部分 | 从 index.json status 判断 |
| **状态恢复** | ❌ | 需实现 `_load_step_output()` |

### 7.4 必须即时记录但尚未实现的功能

| 功能 | 说明 | 优先级 |
|------|------|--------|
| **节点级进度记录** | 每个 wrapper 完成后更新 index.json 的 status | 高 |
| **checkpoint_id 关联** | 将 LangGraph checkpoint_id 与 index.json 关联 | 中 |
| **失败状态记录** | 节点失败时记录 retry_count 和 error 信息 | 中 |
| **幂等重试** | 工具/Agent 失败后的幂等重试逻辑 | 中 |

### 7.5 待实现清单

- [ ] 在每个 wrapper 函数中添加 `store.update_index()` 调用
- [ ] 实现 `_is_step_completed()` 判断函数
- [ ] 实现 `_load_from_persistence()` 从工具文件恢复
- [ ] 实现 `_load_step_output()` 从 Agent 文件恢复
- [ ] main.py 添加 `--resume` 参数
- [ ] （可选）切换到 SqliteSaver 实现跨进程持久化
