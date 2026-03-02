# 多智能体自动化综述评测框架设计参考

> 基于 `auto-review-writing` 仓库的 LangGraph 架构分析与最佳实践总结

## 项目概述

该仓库 [auto-review-writing](www.github.com/lira-workflow/auto-review-writing) 是一个基于 LangGraph 的学术综述自动生成系统，使用多个 AI Agent（研究者、作者、编辑、审核员）协作完成论文综述的自动化撰写与评测。

---

## ✅ 值得学习的设计

### 1. 模块化 Agent 设计

**实现方式**：每个 Agent 继承 `BaseAgent`，统一管理模型调用和缓存

```python
# 统一调用接口
class ResearcherAgent(BaseAgent):
    def analyze_paper(self, paper: Dict) -> List:
        return self.call_model(prompt=..., folder_name="analysis")

class ContentWriterAgent(BaseAgent):
    def write_content_section(self, ...):
        return self.call_model(...)
```

**优点**：

- 避免代码重复（模型调用、日志、缓存逻辑统一）
- 新增 Agent 成本低

### 2. 工作流分层嵌套

```python
# 子图独立，可复用
researcher_group = build_research_team(...)  # 独立编译的 StateGraph
workflow.add_node(RESEARCHER_GROUP, researcher_group)  # 嵌入主流程
```

**优点**：

- 子图可单独测试
- 主流程简洁，屏蔽细节

### 3. 缓存机制降低 API 调用成本

```python
def call_model(self, prompt, file_name, do_save=True, ...):
    target_file = os.path.join(self.temp_dir, file_name)

    if os.path.isfile(target_file) and not self.overwrite_response:
        data = load_json(target_file)
        return AIMessage(**data)  # 读取缓存

    response = self.model.invoke(messages)
    if do_save:
        save_to_json(response.model_dump(mode="json"), target_file)
    return response
```

**优点**：

- 调试时避免重复 API 调用
- 支持断点续跑

### 4. 并行处理加速分析

```python
from joblib import Parallel, delayed

with tqdm_joblib(tqdm(desc="Analyzing", total=len(papers))):
    results = Parallel(n_jobs=n_jobs, backend="threading")(
        delayed(researcher_agent.analyze_paper)(paper) for paper in papers
    )
```

**优点**：

- 充分利用多核 CPU
- 进度条与并行任务集成

### 5. 消息历史管理

```python
def filter_messages(self, messages: List) -> List:
    # 1. 移除系统消息
    # 2. 限制消息数量 (max_memory_items)
    # 3. 限制 token 长度 (context_size)
    # 4. 从最新消息开始保留
```

**优点**：

- 防止上下文过长
- 统一管理消息裁剪策略

### 6. 版本化的实验设置

```python
setting_name = f"_{ft}_{models}"  # 如 "_ft_same_ret"
setting_name += "_ret" if use_retriever else ""
setting_name += "_noresearch" if researcher_model == "none" else ""
```

**优点**：

- 不同实验配置自动生成唯一标识
- 结果文件组织清晰

### 7. 迭代修订循环

```python
# 审核不通过 → 返回重做
if revision_count <= max_revisions and not verdict:
    goto = "write_content"  # 重试
else:
    goto = "edit_content"   # 通过
```

**优点**：

- 支持多轮迭代改进
- 控制修订次数防止无限循环

---

## ❌ 应该避免或改善的设计

### 1. 节点函数职责不清（应分离）

**问题**：每个节点同时处理「业务逻辑 + 状态更新 + 流程控制」

```python
# 当前设计（不推荐）
def review_content(state: LiRAState) -> Command:
    # 业务逻辑...
    verdict = reviewer_agent.review_component(...)

    # 状态更新
    update = {"messages": new_messages, discussion: review_messages}

    # 流程控制（应该由图定义）
    goto = destinations[state["to_review_now"]][target_index]
    return Command(update=update, goto=goto)
```

**建议**：官方推荐模式

```python
# 推荐设计（节点只返回状态）
def review_content(state: LiRAState) -> dict:
    verdict = reviewer_agent.review_component(...)
    return {"verdict": verdict, "messages": new_messages}

# 流程控制由图定义
graph.add_conditional_edges(
    "review_content",
    lambda state: "write_content" if not state["verdict"] else "edit_content"
)
```

### 2. 消息历史无限增长（应限制）

**问题**：所有消息都追加到 `messages`，即使 `filter_messages` 存在，但依赖调用方主动使用

```python
# 当前：每次都追加到 messages
new_messages = state["messages"] + [new_content]
```

**建议**：使用独立的 State 字段而非依赖 `messages`

```python
class State(TypedDict):
    outline: str
    outline_discussion: List[BaseMessage]  # 仅当前任务相关
    draft_review: str
```

### 3. State 类型注解不完整（应完善）

**问题**：`LiRAState` 部分字段缺少类型或默认值

**建议**：

```python
class LiRAState(MessagesState):
    topic: str
    papers: List[Dict[str, str]]
    paper_groups: List[List[Dict]]
    draft_outlines: List[dict]
    revision_count_outline: Annotated[int, Field(ge=0)]
    outline_discussion: Annotated[List[BaseMessage], Field(default_factory=list)]
```

### 4. 硬编码的流程控制（应解耦）

**问题**：所有跳转逻辑分散在节点内部

```python
# 难以一眼看清流程
destinations = {
    "outline": [DRAFT_OUTLINE, WRITE_CONTENT],
    "draft review": [WRITE_CONTENT, EDIT_CONTENT],
    "edited review": [EDIT_CONTENT, END],
}
```

**建议**：使用 `StateGraph` 的 API 集中定义

```python
graph.add_edge("setup", "analyze")
graph.add_edge("analyze", "prepare_groups")
graph.add_conditional_edges("review_content", should_continue)
```

### 5. 检查点存储过于简单（应增强）

**问题**：仅使用 `MemorySaver`，进程结束即丢失

```python
memory = MemorySaver()  # 内存存储
```

**建议**：支持持久化存储

```python
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver

# 持久化到磁盘
checkpointer = SqliteSaver(sqlite_path)

# 或使用 PostgreSQL（生产环境）
checkpointer = PostgresSaver(conn_string)
```

### 6. 缺少错误处理（应增强健壮性）

**问题**：未见到 try-except 处理 LLM 调用异常

**建议**：

```python
from langgraph.errors import NodeInterrupt

def analyze_paper(state: State) -> dict:
    try:
        result = model.invoke(messages)
        return {"result": result}
    except RateLimitError:
        raise NodeInterrupt("API 速率限制，请稍后重试")
    except Exception as e:
        logger.error(f"分析失败: {e}")
        return {"error": str(e)}
```

### 7. 缺少可观测性（应集成 LangSmith）

**问题**：未使用 LangSmith 进行调试和可视化

**建议**：

```python
from langsmith import Client
from langchain.callbacks import LangChainTracer

# 配置追踪
tracer = LangChainTracer(project_name="auto-review")

# 执行时传入回调
for event in app.stream(inputs, config, callbacks=[tracer]):
    ...
```

---

## 📋 推荐架构模板

``` bash
多智能体评测框架/
├── core/
│   ├── base_agent.py      # 统一 Agent 基类（缓存、日志、LLM 调用）
│   ├── state.py           # TypedDict State 定义
│   └── exceptions.py      # 自定义异常
├── agents/
│   ├── researcher.py      # 分析论文
│   ├── writer.py          # 生成内容
│   ├── reviewer.py        # 审核内容
│   └── editor.py          # 编辑润色
├── workflow/
│   ├── builder.py         # 工作流构建
│   └── nodes/             # 节点函数（纯函数）
├── utils/
│   ├── cache.py           # 缓存管理
│   ├── parallel.py        # 并行处理
│   └── evaluation.py      # 评估指标
└── config/
    └── settings.yaml      # 实验配置
```

---

## 核心原则

| 原则 | 说明 |
| ------ | ------ |
| **节点纯函数化** | 节点只处理业务逻辑，流程控制由图定义 |
| **状态最小化** | 每个节点只传必要字段，不依赖消息历史 |
| **关注点分离** | 子图独立编译，主流程清晰 |
| **可观测性** | 集成 LangSmith 追踪执行路径 |
| **可恢复性** | 使用持久化 checkpointer |

---

## LangGraph 官方推荐模式 vs 本仓库实现对比

### 官方核心模式

```python
from langgraph.graph import StateGraph, MessagesState, START, END
from typing_extensions import TypedDict

class State(TypedDict):
    messages: List

def node_a(state: State) -> dict:
    return {"text": state["text"] + "a"}

graph = StateGraph(State)
graph.add_node("node_a", node_a)
graph.add_edge(START, "node_a")
graph.add_edge("node_a", END)
app = graph.compile()
```

### 本仓库实现特点

| 方面 | 本仓库 | 官方推荐 |
| ------ | -------- | --------- |
| State 定义 | `LiRAState(MessagesState)` ✅ | ✅ 符合 |
| 节点返回值 | `Command` 对象 ❌ | 返回 dict ✅ |
| 条件分支 | 节点内 `Command(goto=...)` | `add_conditional_edges()` |
| 子图使用 | ✅ 使用嵌套子图 | ✅ 官方支持 |
| Checkpointer | `MemorySaver` | ✅ 符合 |

---

## 改进建议速查表

| 问题 | 当前实现 | 建议改进 |
| ------ | --------- | --------- |
| 节点职责混合 | `Command(update=, goto=)` | 节点只返回 dict |
| 流程控制分散 | 各节点内部定义 | 集中在 `builder.py` |
| 消息历史膨胀 | 追加到 `messages` | 独立 State 字段 |
| 类型注解缺失 | 部分字段无类型 | 完善 TypedDict |
| 状态存储 | 内存存储 | Sqlite/Postgres |
| 异常处理 | 无 | NodeInterrupt |
| 调试追踪 | 无 | LangSmith 集成 |

---

*文档生成时间: 2026-01-28*
*参考仓库: https://github.com/lira-workflow/automated-review-writing*
