# SciSage 架构分析：多智能体自动化综述评测框架设计指南

> 基于 SciSage 论文生成仓库的架构分析与设计建议

---

## 一、项目概述

[SciSage](https://github.com/FlagOpen/SciSage) 是一个基于 LLM 的自动化论文生成系统，采用 LangGraph 工作流编排。其架构对于构建**多智能体自动化综述评测框架**具有重要参考价值。

---

## 二、值得学习的设计模式

### 2.1 模块化解耦设计

**实现方式**：
```
┌─────────────────────────────────────────────────────────────┐
│                     核心模块划分                            │
├─────────────────────────────────────────────────────────────┤
│  query_understanding    →  查询类型分类、语言处理           │
│  paper_outline_opt      →  大纲生成与优化                   │
│  section_writer_opt     →  章节内容生成                     │
│  section_reflection     →  章节级反思与迭代                 │
│  paper_global_reflection→  全文一致性反思                   │
│  paper_poolish_opt      →  终稿润色                         │
└─────────────────────────────────────────────────────────────┘
```

**优点**：
- 每个模块职责单一，可独立测试和替换
- 便于并行开发和维护
- 错误定位清晰

**启示**：
> 在综述评测框架中，可将模块划分为：文献检索智能体、批判性分析智能体、综合评估智能体、质量评分智能体等。

---

### 2.2 渐进式反思机制 (Iterative Reflection)

**核心代码** (`section_reflection_opt.py`):
```python
# 条件反射循环
workflow.add_conditional_edges(
    "reflect_section",
    should_continue_improvement,
    {
        "continue": "reflect_section",  # 继续反思
        "accept": END,                   # 接受结果
        "terminate": END                 # 终止
    }
)
```

**设计模式**：
```
初始版本 → 模型评估 → 反馈 → 改进 → 评估 → ... → 最终版本
          ↑                                    │
          └────────────────────────────────────┘
```

**启示**：
> 综述评测应支持多轮迭代：文献筛选 → 质量评估 → 专家评审 → 修订 → 终稿

---

### 2.3 多模型协作评估 (Consensus Mechanism)

**实现方式** (`section_reflection_opt.py`):
```python
# 并行多模型评估
results = await asyncio.gather(
    evaluate_section(content, model="model_1"),
    evaluate_section(content, model="model_2"),
    evaluate_section(content, model="model_3")
)
consensus = merge_results(results)
```

**优点**：
- 减少单一模型偏差
- 提高评估可靠性
- 可配置模型数量

**启示**：
> 综述质量评估可采用多评委制：不同专家视角、不同模型能力维度

---

### 2.4 信号量池并发控制

**实现方式** (`configuration.py`):
```python
class GlobalSemaphorePool:
    rag_semaphore = asyncio.Semaphore(2)           # RAG 请求并发
    section_reflection_semaphore = asyncio.Semaphore(3)  # 反思并发
    section_name_refine_semaphore = asyncio.Semaphore(2) # 润色并发
```

**优点**：
- 防止服务过载
- 资源分配可控
- 避免 LLM API 速率限制

**启示**：
> 综述框架中，文献检索、专家评审等环节需严格控制并发

---

### 2.5 LCEL 链式组合

**实现方式** (`paper_outline_opt.py`):
```python
# 简洁的管道定义
chain = prompt | default_llm | parser
# 等价于
chain = RunnableSequence(first=prompt, middle=[default_llm], last=parser)
```

**优点**：
- 代码简洁直观
- 易于组合和扩展
- 支持流式处理

**启示**：
> 综述流程中的文献筛选 → 摘要提取 → 质量评分 可用 LCEL 串联

---

### 2.6 状态管理规范

**State 定义模式** (`paper_understant_query.py`):
```python
@dataclass
class QueryProcessingState:
    original_query: str
    language: str
    query_type: str
    intent: str
    rewritten_query: str
    confidence: float
```

**优点**：
- 类型安全
- 自动补全支持
- 便于调试

**启示**：
> 综述框架应定义明确的 State：文献状态、评分状态、综合状态等

---

### 2.7 自定义 LangChain 兼容模型

**实现方式** (`local_model_langchain.py`):
```python
class LocalChatModel(BaseChatModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        # 自定义生成逻辑
        return ChatResult(generations=[generation])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        # 异步生成
        return self._generate(...)
```

**优点**：
- 统一接口调用本地/远程模型
- 可复用 LangChain 生态工具

**启示**：
> 综述评测框架应支持：GPT/Claude/本地模型 的统一接口

---

## 三、应避免或改善的设计

### 3.1 主流程缺乏 LangGraph 编排

**现状** (`main_workflow_opt_for_paper.py`):
```python
class PaperGenerationPipeline:
    async def generate_paper(self):
        # 手动编排流程
        state = await self.process_query_async(state)
        state = await self.generate_outline(state)
        state = await self.process_sections(state)
        # ... 手动调用
```

**问题**：
- 流程硬编码，缺乏灵活性
- 难以动态调整工作流
- 缺少状态持久化

**建议**：
```
┌──────────────────────────────────────────────┐
│  改进：使用 LangGraph 编排主流程              │
├──────────────────────────────────────────────┤
│  StateGraph                                 │
│  ├── START                                  │
│  ├── query_understanding → outline_gen      │
│  ├── outline_gen → section_writer           │
│  ├── section_writer → section_reflection    │
│  ├── section_reflection → global_reflection │
│  ├── global_reflection → abstract_gen       │
│  ├── abstract_gen → polish                  │
│  └── polish → END                           │
└──────────────────────────────────────────────┘
```

---

### 3.2 手写重试逻辑

**现状** (`main_workflow_opt_for_paper.py`):
```python
@with_retry_and_fallback
async def some_operation():
    ...
```

**问题**：
- 与框架解耦
- 难以配置和监控
- 重试策略不灵活

**建议**：
```python
# 使用 langgraph.retry
workflow = StateGraph(State)
workflow.add_node(
    "critical_operation",
    retry(operation, max_attempts=3, delay=1000)
)
```

---

### 3.3 状态持久化缺失

**现状**：
- 无 Checkpoint 机制
- 任务中断后无法恢复
- 进度无法追踪

**建议**：
```python
# 使用 langgraph.checkpoint
from langgraph.checkpoint.memory import MemorySaver

checkpointer = MemorySaver()
compiled = workflow.compile(checkpointer=checkpointer)

# 恢复状态
result = compiled.invoke(input, config={"configurable": {"thread_id": "task_123"}})
```

---

### 3.4 错误处理不够健壮

**现状**：
- 部分函数错误处理简单
- 没有统一的错误分类
- 缺少降级策略

**建议**：
```python
class AgentError(Exception):
    pass

class RateLimitError(AgentError):
    pass

class ContextOverflowError(AgentError):
    pass

# 统一的错误处理装饰器
def error_handler(func):
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except RateLimitError:
            return fallback_strategy()
    return wrapper
```

---

### 3.5 配置管理分散

**现状**：
- `configuration.py` 定义配置
- 部分配置硬编码在模块中
- 缺少环境区分（dev/prod）

**建议**：
```python
# 统一的配置管理
class Config:
    MODELS: Dict[str, ModelConfig] = {...}
    SEMAPHORES: SemaphoreConfig = {...}
    RETRY_POLICY: RetryPolicy = {...}

# 支持环境变量覆盖
config = Config.from_env()
```

---

### 3.6 缺乏 Agent 级别的抽象

**现状**：
- 只有 Node/StateGraph，没有 Agent 概念
- 每个模型只是工具调用，没有"角色"
- 缺少规划能力

**问题**：
- 无法实现真正的多智能体协作
- 缺少记忆和上下文管理

**建议**：
```python
from langgraph.prebuilt import create_react_agent

# 定义工具
tools = [search_literature, extract_insights, score_quality]

# 创建智能体
agent = create_react_agent(model="qwen", tools=tools)

# 智能体可自主决策下一步行动
await agent.ainvoke({"task": "评估这篇综述的质量"})
```

---

## 四、多智能体综述评测框架设计建议

### 4.1 推荐架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    综述评测框架架构                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │ 文献检索    │    │ 质量初筛    │    │ 深度分析    │         │
│  │ Agent       │───▶│ Agent       │───▶│ Agent       │         │
│  └─────────────┘    └─────────────┘    └─────────────┘         │
│       │                  │                  │                   │
│       ▼                  ▼                  ▼                   │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │ 数据库      │    │ 评分模型    │    │ 批判性思考  │         │
│  │ (向量库)    │    │             │    │             │         │
│  └─────────────┘    └─────────────┘    └─────────────┘         │
│                           │                                    │
│                           ▼                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    综合评审 Agent                        │   │
│  │  ├── 多模型投票                                          │   │
│  │  ├── 冲突解决                                            │   │
│  │  └── 最终评分                                            │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           │                                    │
│                           ▼                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    报告生成 Agent                        │   │
│  │  ├── 结构化输出                                          │   │
│  │  ├── 可视化建议                                          │   │
│  │  └── 置信度标注                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 核心设计原则

| 原则 | 说明 | 来源 |
|------|------|------|
| **渐进式评审** | 多轮迭代，每轮基于反馈改进 | SciSage 反思机制 |
| **多专家评估** | 多模型/多角度评估，取共识 | SciSage 多模型协作 |
| **资源可控** | 信号量限制并发，保护 API | SciSage SemaphorePool |
| **状态可追溯** | 每步状态可记录、可恢复 | 建议使用 Checkpoint |
| **模块可插拔** | 评估指标、评审标准可配置 | SciSage 模块化 |

### 4.3 关键技术选型建议

| 功能 | 推荐方案 | 理由 |
|------|----------|------|
| 工作流编排 | LangGraph StateGraph | 与 LangChain 无缝集成 |
| Agent 构建 | create_react_agent | 开箱即用的 ReAct 模式 |
| 状态持久化 | langgraph.checkpoint | 支持断点续传 |
| 并发控制 | asyncio.Semaphore | 简单有效 |
| 输出解析 | PydanticOutputParser | 类型安全 |
| 本地模型 | 自定义 BaseChatModel | 统一接口 |

---

## 五、总结

### 值得继承
1. ✅ 模块化解耦的设计思路
2. ✅ 渐进式反思迭代机制
3. ✅ 多模型协作评估模式
4. ✅ 信号量并发控制
5. ✅ LCEL 简洁链式调用
6. ✅ 自定义 LangChain 兼容模型

### 需要改进
1. ❌ 主流程应使用 LangGraph 编排
2. ❌ 用 langgraph.retry 替代手写重试
3. ❌ 增加 Checkpoint 持久化
4. ❌ 统一错误处理机制
5. ❌ 配置管理集中化
6. ❌ 引入真正的 Agent 抽象

---

> 本文档可作为设计多智能体综述评测框架的参考提示词。建议结合实际需求，选择性继承 SciSage 的设计经验。
