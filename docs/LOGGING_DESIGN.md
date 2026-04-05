# SurveyMAE 日志系统设计方案

> 基于: LOGGING_SYSTEM_ANALYSIS.md, DEVELOPER_GUIDE.md, SurveyMAE_Plan_v3.md
> 创建时间: 2026/04/05
> 更新时间: 2026/04/05
> 目的: 为 Claude Code 提供实施规范

---

## 一、问题定义

### 1.1 用户视角的核心问题

SurveyMAE 一次完整评测涉及 7 个 workflow 节点、几十次 LLM 调用（9+ 供应商）、近百次学术 API 调用、多步骤持久化。运行时间通常 1-10 分钟。用户面对的核心问题：

1. **现在跑到哪了？** — 需要 pipeline 进度指示
2. **卡住了吗？** — 需要知道当前正在等待什么（哪个 API、哪个模型）
3. **哪步出了问题？** — 失败时需要快速定位是网络问题、模型问题还是数据问题
4. **结果可信吗？** — 需要了解降级/fallback 是否发生、数据覆盖率如何

### 1.2 当前系统的主要缺陷

| 问题 | 影响 |
|------|------|
| `basicConfig()` 仅输出到控制台，无 FileHandler | 运行结束后无法回溯日志 |
| 无独立日志文件 | 无法事后调试 |
| `errors.jsonl` / `agent_logs.jsonl` 的 `append_*` 方法几乎未被调用 | 结构化错误记录形同虚设 |
| 日志信息缺少关键上下文（耗时、数量、结果摘要） | 用户看到 "Step 1: Extracting..." 后不知道这步做了什么 |
| 无统一的日志初始化入口 | 散落的 `logging.getLogger(__name__)` 无法统一控制 |
| 长耗时步骤无进度反馈 | citation_validate 可能耗时 20s+，用户以为系统卡死 |

### 1.3 与前端的关系

日志系统和前端可视化的共通目标是**分层向用户展示信息**。日志系统是前端的"数据源原型"：控制台 INFO 输出对应前端的进度条/步骤卡片，DEBUG 日志对应前端的展开详情面板，WARNING 对应前端的黄色警示标记。设计好日志层级，前端设计会自然对齐。

---

## 二、输出目录结构调整

### 2.1 设计约束

目录结构需要同时支持两种使用模式：

- **单篇模式（当前）：** `uv run python -m src.main survey.pdf`
- **批量模式（计划中）：** `uv run python -m src.main paper1.pdf paper2.pdf paper3.pdf`

一次 run 可评测多篇 PDF，它们共享同一个 config 快照和 run_id，但每篇 PDF 的工具输出和节点输出是独立的。

### 2.2 调整后结构

```
output/runs/{run_id}/
├── run.json                              # run 级共享：config 快照 + metrics_index
├── index.json                            # run 级共享：所有 paper 状态索引
│
├── papers/{paper_id}/                    # 每篇 PDF 独立目录
│   ├── run_summary.json                  # 该篇 PDF 的评测结果摘要（run 级）
│   │
│   ├── nodes/                            # workflow 步骤增量输出
│   │   ├── 01_parse_pdf.json
│   │   ├── 02_evidence_collection.json
│   │   ├── 03_evidence_dispatch.json
│   │   ├── 04_verifier.json
│   │   ├── 04_expert.json
│   │   ├── 04_reader.json
│   │   ├── 05_corrector.json
│   │   ├── 06_aggregator.json
│   │   └── 07_reporter.json
│   │
│   └── tools/                            # 工具层独立持久化
│       ├── source.json
│       ├── extraction.json
│       ├── validation.json
│       ├── c6_alignment.json
│       ├── analysis.json
│       ├── graph_analysis.json
│       ├── trend_baseline.json
│       └── key_papers.json
│
└── logs/                                 # run 级共享
    └── run.log                           # 本次运行的完整 DEBUG 日志
```

### 2.3 分层职责

| 文件 | 层级 | 说明 |
|------|------|------|
| `run.json` | run 级 | config 快照、metrics_index 定义、schema_version。一次 run 内所有 PDF 共享同一 config |
| `index.json` | run 级 | 所有 paper 的 paper_id → status 映射。批量运行时记录每篇的处理进度 |
| `run_summary.json` | run 级 | 单篇 PDF 的 deterministic_metrics、agent_scores、corrected_scores、overall_score、grade |
| `nodes/*.json` | paper 级 | 该篇 PDF 的 workflow 步骤增量输出 |
| `tools/*.json` | paper 级 | 该篇 PDF 的工具原始输出 |
| `logs/run.log` | run 级 | 整个 run 的日志（含所有 PDF 的处理日志） |

### 2.4 对 ResultStore 的影响

`ResultStore` 路径调整：

```python
# 旧路径（tools 和 nodes 混在一起）
store.base_dir / "papers" / paper_id / "validation.json"
store.base_dir / "papers" / paper_id / "01_parse_pdf.json"

# 新路径（tools 和 nodes 分离）
store.base_dir / "papers" / paper_id / "tools" / "validation.json"
store.base_dir / "papers" / paper_id / "nodes" / "01_parse_pdf.json"
```

新增 `save_node_step(paper_id, step_name, data)` 方法用于写入 nodes/ 目录。

### 2.5 批量模式下的日志前缀

批量处理时，进度和日志需要区分当前处理的是哪篇 PDF。规范：

- `log_pipeline_step()` 在批量模式下自动添加 paper 标识前缀
- `logger.debug()` / `logger.warning()` 等日志消息中，通过 logger name 或消息前缀区分
- 进度条的 description 包含当前 PDF 文件名

---

## 三、日志分级设计

### 3.1 级别定义与语义

| 级别 | 默认输出到 | 语义定义 | 判断标准 |
|------|-----------|---------|---------|
| `ERROR` | 控制台 + 文件 | **流程中断或数据缺失** — 该错误导致某个核心步骤完全失败，最终报告将缺少关键信息 | 问自己：这个错误发生后，最终报告的可信度是否受损？ |
| `WARNING` | 控制台 + 文件 | **已降级但用户应知晓** — 系统采取了 fallback 策略，结果仍可用但可能不完整 | 问自己：用户是否需要知道这件事来正确解读结果？ |
| `INFO` | 控制台 + 文件 | **Pipeline 进度里程碑** — 用户需要看到的进度节点和关键结果数字 | 问自己：如果这条日志不存在，用户是否会觉得系统卡住了？ |
| `DEBUG` | 仅文件 | **调试细节** — 网络调用参数/响应、state 变更、prompt 摘要、中间计算 | 问自己：这条信息只有在排查问题时才需要吗？ |

### 3.2 控制台 vs 文件的分流

```
控制台（stderr）: INFO + WARNING + ERROR — 通过 rich 渲染，面向运行时用户
文件（run.log）:  DEBUG + INFO + WARNING + ERROR — 纯文本，面向事后调试
```

verbose 模式（`-v`）：控制台也输出 DEBUG。

### 3.3 第三方库日志抑制

```python
logging.getLogger("langchain").setLevel(logging.WARNING)
logging.getLogger("langgraph").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("anthropic").setLevel(logging.WARNING)
```

---

## 四、Rich 库集成方案

### 4.1 选型理由

| 方案 | 优势 | 劣势 | 结论 |
|------|------|------|------|
| `colorlog` | 轻量，纯颜色 | 无进度条、无动态渲染 | 功能不足 |
| `rich` | 颜色 + 进度条 + traceback 美化，生态成熟 | 需要区分 rich 渲染与 logging 的协作 | **选用** |
| `loguru` | API 简洁 | 替换整个 logging 架构，迁移成本高 | 不适合 |
| `textual` | 完整 TUI | 过度工程化 | 不适合 |

### 4.2 核心架构：Rich Console + logging 双通道

**关键设计决策：控制台输出分两个通道。**

```
┌─────────────────────────────────────────────────┐
│                  控制台 (stderr)                  │
│                                                   │
│  通道 A: rich.console.Console                     │
│  ├── 进度条 (Progress)                            │
│  ├── 步骤信息 (log_pipeline_step / log_substep)   │
│  └── 最终汇总 (Rule + 统计)                       │
│                                                   │
│  通道 B: RichHandler → logging                    │
│  ├── WARNING (黄色自动着色)                       │
│  ├── ERROR (红色自动着色 + rich traceback)         │
│  └── DEBUG (灰色, 仅 verbose 模式)                │
│                                                   │
│  ⚠ 通道 A 和 B 共享同一个 Console 实例            │
│    → rich 自动处理进度条与日志消息的交错渲染       │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│              文件 (run.log)                       │
│  FileHandler → 纯文本，所有级别                   │
│  ├── 格式: "HH:MM:SS [LEVEL  ] module | msg"  │
│  └── 不含 rich markup / ANSI 颜色码              │
└─────────────────────────────────────────────────┘
```

**为什么 INFO 走 Console 而不走 RichHandler：** pipeline 进度信息（步骤编号、结果摘要、进度条）需要精确控制格式和样式（粗体步骤名、右对齐耗时、进度条动态刷新），RichHandler 的自动格式化会破坏布局。WARNING/ERROR 是偶发事件，用 RichHandler 自动渲染即可。

### 4.3 Console 实例管理

**全局唯一 Console 实例。** 进度条和日志必须共享同一个 Console，否则它们会互相覆盖。

```python
# src/core/log.py

from rich.console import Console

console = Console(stderr=True)

def get_console() -> Console:
    """获取全局 Console 实例。"""
    return console
```

### 4.4 RichHandler 配置

```python
from rich.logging import RichHandler

def _create_rich_handler(verbose: bool) -> RichHandler:
    """
    创建控制台日志 handler。

    非 verbose: 仅 WARNING+（INFO 由 Console 直接输出）
    verbose:    DEBUG+
    """
    handler = RichHandler(
        console=console,
        level=logging.DEBUG if verbose else logging.WARNING,
        show_path=False,
        show_time=False,
        markup=True,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
    )
    return handler
```

### 4.5 Pipeline 进度输出

pipeline 级别的 INFO 输出直接调用 Console，以获得完整的格式控制：

```python
# src/core/log.py

def log_pipeline_step(
    step: str, total: int, name: str,
    detail: str = "", elapsed: float | None = None,
) -> None:
    """
    输出 pipeline 步骤信息到控制台 + 文件。

    示例:
        [01/07] parse_pdf              │ 47 refs, 12 sections           2.3s
    """
    ...

def log_substep(
    name: str, detail: str,
    elapsed: float | None = None, is_last: bool = False,
) -> None:
    """
    输出子步骤信息（缩进 + 树状符号）。

    示例:
        ├── citation_validate    │ C3=8.51% C5=89.36%              18.7s
        └── key_papers           │ top-30, 匹配 19 篇 (63.3%)       5.4s
    """
    ...
```

**这些函数内部同时做两件事：**
1. 调用 `console.print(...)` 输出到控制台（带 rich 格式）
2. 调用 `_file_logger.info(...)` 写入日志文件（纯文本）

### 4.6 进度条：长耗时迭代操作

#### 4.6.1 识别需要进度条的操作

| 操作 | 位置 | 迭代对象 | 典型数量 | 单次耗时 | 总耗时 |
|------|------|---------|---------|---------|--------|
| 引用元数据验证 | `citation_checker._verify_references()` | 每条 reference | 40-100 | 0.3-1s (API) | 10-30s |
| C6 批处理对齐 | `citation_checker.analyze_citation_sentence_alignment()` | 每个 batch (10对) | 15-30 batch | 0.5-1s (LLM) | 5-15s |
| 核心文献检索 | `foundational_coverage.py` | 每组 keyword query | 3-5 | 1-3s (API) | 3-15s |
| Corrector 多模型投票 | `corrector._vote_all_dimensions()` | 每个维度 × 每个模型 | 7×3=21 | 1-3s (LLM) | 10-30s |

**不需要进度条：** PDF 解析（单次 1-3s）、图分析计算（CPU < 1s）、时序/结构指标（CPU < 1s）、单次 Agent 评估（单次 LLM 3-5s）、Evidence dispatch（内存 < 1s）。

#### 4.6.2 进度条工具函数

```python
# src/core/log.py

from rich.progress import (
    Progress, SpinnerColumn, TextColumn,
    BarColumn, MofNCompleteColumn, TimeElapsedColumn,
)

def create_progress(quiet: bool = False) -> Progress:
    """
    创建共享 Console 的进度条。

    Args:
        quiet: 若为 True，返回一个不渲染的 Progress（API 兼容但不输出），
               用于 quiet 模式下抑制进度条。

    用法:
        progress = create_progress()
        with progress:
            task = progress.add_task("验证引用", total=47)
            for ref in references:
                await validate(ref)
                progress.update(task, advance=1)

    特性:
        - transient=False: 完成后保留在终端中，方便回看和截图
        - 共享全局 Console: WARNING/ERROR 自动在进度条上方插入
    """
    if quiet:
        return Progress(
            SpinnerColumn(),
            TextColumn(""),
            BarColumn(bar_width=None),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=Console(stderr=True, quiet=True),
            transient=False,
        )
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=30),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )
```

#### 4.6.3 进度条使用模式

**场景 1：引用元数据验证**

```python
# src/tools/citation_checker.py

from src.core.log import create_progress

async def _verify_references(self, references, ...):
    progress = create_progress()
    with progress:
        task = progress.add_task("验证引用", total=len(references))
        for ref in references:
            if not (ref.title or ref.doi or ref.arxiv_id):
                progress.update(task, advance=1)
                continue
            result = await checker.verify_bib_entry(...)
            ref.validation = result.to_dict()
            progress.update(task, advance=1)
    # 进度条完成后保留在终端，后续由节点层 log_substep 输出汇总
```

**场景 2：C6 批处理对齐**

```python
async def analyze_citation_sentence_alignment(self, ...):
    progress = create_progress()
    with progress:
        task = progress.add_task("C6 对齐分析", total=n_batches)
        for batch in batches:
            results = await self._process_c6_batch(batch)
            progress.update(task, advance=1)
```

**场景 3：Corrector 多模型投票**

```python
async def _vote_all_dimensions(self, dimensions, evidence, ...):
    progress = create_progress()
    with progress:
        task = progress.add_task("多模型投票", total=len(dimensions) * len(models))
        for dim in dimensions:
            for model in models:
                score = await self._vote_single(dim, model, evidence)
                progress.update(task, advance=1)
```

#### 4.6.4 进度条与日志的交互规则

1. **进度条运行期间，WARNING/ERROR 自动在进度条上方插入** — 因为 RichHandler 和 Progress 共享同一个 Console，rich 库自动处理。
2. **进度条结束后，由节点层 `log_substep()` 输出汇总** — 进度条负责实时反馈，汇总由 substep 报告。
3. **`transient=False`** — 完成后进度条保留在终端中，方便用户回看和截图。
4. **使用 `advance=1`** — 避免并发时的竞态条件。

### 4.7 最终汇总

```python
# src/core/log.py

from rich.rule import Rule

def log_run_summary(stats: "RunStats", total_elapsed: float) -> None:
    """
    输出运行结束的最终汇总。

    效果:
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        总耗时 51.2s │ LLM 调用 28 次 │ API 调用 94 次
    """
    console.print(Rule())
    console.print(
        f"总耗时 {total_elapsed:.1f}s │ "
        f"LLM 调用 {stats.llm_calls} 次 │ "
        f"API 调用 {stats.api_calls} 次"
    )
```

### 4.8 Rich Traceback

`RichHandler(rich_tracebacks=True)` 自动美化异常堆栈。手动捕获的异常用 `logger.error(..., exc_info=True)` 触发 rich traceback 渲染。纯文本 traceback 同时写入 run.log。

---

## 五、日志记录准则（面向 Claude Code 的规范）

### 5.1 总体原则

**不要无差别记录。** 每条日志都应该回答一个具体问题。

**logging 与 Console 的分工：**
- `logger.warning(...)` / `logger.error(...)` → RichHandler 自动着色
- `log_pipeline_step(...)` / `log_substep(...)` → Console 精确控制格式
- `logger.debug(...)` → FileHandler（verbose 时也走 RichHandler）
- `logger.info(...)` → FileHandler（文件中记录纯文本版进度）

### 5.2 Workflow 节点层（`src/graph/`）

**职责：报告进度和关键结果数字，面向用户。**

- 节点开始/结束用 `log_pipeline_step()`
- 子步骤完成用 `log_substep()`
- 同时用 `logger.info()` 写入文件
- 节点失败用 `logger.error()`

### 5.3 Agent 层（`src/agents/`）

**职责：记录 LLM 交互摘要，面向调试。**

- Agent 启动/完成用 `logger.debug()`
- LLM 调用前/后记录 `logger.debug()`：provider/model/tokens/latency
- LLM 调用失败用 `logger.warning()`，最终失败用 `logger.error()`
- **不要记录完整 prompt 或完整 response**

### 5.4 工具层（`src/tools/`）

**职责：记录 API 交互和数据处理结果，面向调试。**

- 总结果由节点层 `log_substep()` 报告，工具层用 `logger.debug()`
- API 超时/限流用 `logger.warning()` 含降级策略
- **迭代操作使用 `create_progress()` 进度条**
- 批量操作记录汇总而非逐条

### 5.5 核心框架层（`src/core/`）

- 配置加载用 `logger.info()`
- MCP 连接成功 `logger.info()`，失败 `logger.error()`
- 环境变量缺失：有默认值用 `logger.warning()`，必须用 `logger.error()`

### 5.6 WARNING 必须包含降级策略

```python
# ✅ 好
logger.warning("Semantic Scholar 超时 (ref #23) → 降级到 OpenAlex... 成功")
logger.warning("C6 batch 5/8: 2/10 对异常 → 矛盾率基于 298/312 对计算")

# ❌ 差
logger.warning("API call failed")
```

### 5.7 ERROR 必须包含可操作信息

```python
# ✅ 好
logger.error("PDF 解析失败: 未提取到引用 | file=%s backend=%s\n"
             "  → 建议: 检查 GROBID 服务 (grobid_url=%s)",
             pdf_path, backend, grobid_url)

# ❌ 差
logger.error("Evaluation failed: %s", str(e))
```

### 5.8 不应该记录日志的场景

- 正常的逐条处理中间步骤 — 用进度条替代
- 纯计算步骤
- 符合预期的空值处理 — 在汇总中体现
- getter/setter 调用
- 配置项使用默认值

---

## 六、实现规范

### 6.1 依赖

```toml
# pyproject.toml
[project]
dependencies = [
    "rich>=13.0",
]
```

### 6.2 `src/core/log.py` 公共 API

```python
"""
SurveyMAE 日志与控制台输出系统。

架构:
    控制台 = Console 直接输出（进度、步骤面板） + RichHandler（WARNING/ERROR）
    文件   = FileHandler（全级别纯文本）

用法:
    from src.core.log import setup_logging, get_console, create_progress
    from src.core.log import log_pipeline_step, log_substep, log_run_summary
    from src.core.log import get_run_stats, track_step
"""

import logging
import threading
from pathlib import Path
from contextlib import contextmanager

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (
    Progress, SpinnerColumn, TextColumn,
    BarColumn, MofNCompleteColumn, TimeElapsedColumn,
)
from rich.rule import Rule

_LOG_NAMESPACE = "surveymae"
console = Console(stderr=True)


def setup_logging(
    run_dir: str | Path | None = None,
    verbose: bool = False,
    log_level: str | None = None,
    quiet: bool = False,
) -> logging.Logger:
    """
    初始化日志系统。

    行为:
        1. 创建 "surveymae" 根 logger，级别 DEBUG
        2. 添加 RichHandler（级别由 log_level/quiet/verbose 决定）
        3. 若 run_dir 提供，创建 FileHandler → {run_dir}/logs/run.log
        4. 抑制第三方库日志到 WARNING
        5. 初始化全局 RunStats

    日志级别确定逻辑:
        1. log_level 显式指定 → 使用该级别
        2. quiet=True → WARNING（抑制进度输出）
        3. verbose=True → DEBUG
        4. 默认 → INFO（RichHandler=WARNING，INFO 走 Console）
    """
    ...


def get_console() -> Console:
    """获取全局 Console 实例。"""
    return console


def create_progress(quiet: bool = False) -> Progress:
    """
    创建共享 Console 的进度条。transient=False。

    Args:
        quiet: 若为 True，返回一个不渲染的 Progress（API 兼容但不输出），
               用于 quiet 模式下抑制进度条。

    用法:
        with create_progress() as progress:
            task = progress.add_task("验证引用", total=47)
            for ref in refs:
                await validate(ref)
                progress.update(task, advance=1)
    """
    if quiet:
        return Progress(
            SpinnerColumn(),
            TextColumn(""),
            BarColumn(bar_width=None),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=Console(stderr=True, quiet=True),
            transient=False,
        )
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=30),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )


def log_pipeline_step(
    step: str, total: int, name: str,
    detail: str = "", elapsed: float | None = None,
) -> None:
    """输出 pipeline 步骤到控制台 + 文件。"""
    ...


def log_substep(
    name: str, detail: str,
    elapsed: float | None = None, is_last: bool = False,
) -> None:
    """输出缩进子步骤到控制台 + 文件。"""
    ...


def log_run_summary(stats: "RunStats", total_elapsed: float) -> None:
    """输出运行最终汇总（分隔线 + 统计）。"""
    ...


@contextmanager
def track_step(logger: logging.Logger, step_label: str):
    """上下文管理器，自动记录步骤耗时到文件 logger。"""
    ...


class RunStats:
    """单次运行的统计计数器，线程安全。"""

    __slots__ = (
        "_lock", "llm_calls", "llm_tokens_in", "llm_tokens_out",
        "api_calls", "warnings", "errors",
    )

    def __init__(self) -> None:
        self._lock: threading.Lock
        self.llm_calls: int
        self.api_calls: int
        self.llm_tokens_in: int
        self.llm_tokens_out: int
        self.warnings: int
        self.errors: int

    def record_llm(self, tokens_in: int = 0, tokens_out: int = 0) -> None: ...
    def record_api(self) -> None: ...
    def record_warning(self) -> None: ...
    def record_error(self) -> None: ...
    def summary(self) -> dict: ...


def get_run_stats() -> RunStats:
    """获取全局 RunStats 实例。"""
    ...
```

### 6.3 模块级 Logger 命名规范

所有模块使用 `surveymae.` 前缀：

```python
# src/graph/builder.py
logger = logging.getLogger("surveymae.graph")

# src/agents/base.py
logger = logging.getLogger("surveymae.agents.base")

# src/agents/corrector.py
logger = logging.getLogger("surveymae.agents.corrector")

# src/agents/expert.py
logger = logging.getLogger("surveymae.agents.expert")

# src/agents/reader.py
logger = logging.getLogger("surveymae.agents.reader")

# src/agents/reporter.py
logger = logging.getLogger("surveymae.agents.reporter")

# src/agents/verifier.py
logger = logging.getLogger("surveymae.agents.verifier")

# src/core/mcp_client.py
logger = logging.getLogger("surveymae.core.mcp_client")

# src/graph/nodes/aggregator.py
logger = logging.getLogger("surveymae.graph.nodes.aggregator")

# src/graph/nodes/debate.py
logger = logging.getLogger("surveymae.graph.nodes.debate")

# src/graph/nodes/evidence_collection.py
logger = logging.getLogger("surveymae.graph.nodes.evidence_collection")

# src/graph/nodes/evidence_dispatch.py
logger = logging.getLogger("surveymae.graph.nodes.evidence_dispatch")

# src/tools/citation_analysis.py
logger = logging.getLogger("surveymae.tools.citation_analysis")

# src/tools/citation_checker.py
logger = logging.getLogger("surveymae.tools.citation_checker")

# src/tools/citation_graph_analysis.py
logger = logging.getLogger("surveymae.tools.citation_graph_analysis")

# src/tools/citation_metadata.py
logger = logging.getLogger("surveymae.tools.citation_metadata")

# src/tools/foundational_coverage.py
logger = logging.getLogger("surveymae.tools.foundational_coverage")

# src/tools/keyword_extractor.py
logger = logging.getLogger("surveymae.tools.keyword_extractor")

# src/tools/literature_search.py
logger = logging.getLogger("surveymae.tools.literature_search")

# src/tools/parallel_dispatcher.py
logger = logging.getLogger("surveymae.tools.parallel_dispatcher")

# src/tools/pdf_parser.py
logger = logging.getLogger("surveymae.tools.pdf_parser")

# src/tools/fetchers/dblp_fetcher.py
logger = logging.getLogger("surveymae.tools.fetchers.dblp")
```

**禁止** `logging.getLogger(__name__)`（`__name__` 前缀是 `src.` 而非 `surveymae.`）。

### 6.4 main.py 集成

```python
from src.core.log import setup_logging

def main():
    args = parse_args()
    run_id = generate_run_id()
    run_dir = Path(args.output_dir) / "runs" / run_id

    # 确定日志级别（优先级: --log-level > -q > -v > 默认）
    logger = setup_logging(
        run_dir=run_dir,
        verbose=args.verbose,
        log_level=args.log_level,
        quiet=args.quiet,
    )

    # 批量模式 vs 单篇模式
    if len(args.pdf_paths) == 1:
        logger.info("SurveyMAE 评测启动 | PDF: %s", args.pdf_paths[0])
    else:
        logger.info("SurveyMAE 批量评测启动 | %d 篇 PDF", len(args.pdf_paths))

    for i, pdf_path in enumerate(args.pdf_paths):
        if len(args.pdf_paths) > 1:
            console.print(Rule(f"[{i+1}/{len(args.pdf_paths)}] {Path(pdf_path).name}"))
        await run_evaluation(pdf_path, config, run_dir)
```

---

## 七、迁移计划

### 7.1 迁移步骤（按顺序执行）

**Step 1: 安装依赖 + 创建日志基础设施**
- `uv add rich`
- 创建 `src/core/log.py`，实现全部公共 API
- 不改动任何现有代码

**Step 2: 修改 main.py 入口**
- 删除 `logging.basicConfig(...)`
- 删除 verbose 旧实现
- 接入 `setup_logging()`

**Step 3: 调整 ResultStore 路径**
- `papers/{paper_hash}/` 保留，内部拆分为 `nodes/` 和 `tools/` 子目录
- `run_summary.json` 从 run 级移到 `papers/{paper_id}/` 下
- 更新 `_save_workflow_step()` → 写入 `papers/{paper_id}/nodes/`
- 更新各 `save_*` 方法 → 写入 `papers/{paper_id}/tools/`
- 确保所有测试通过

**Step 4: 替换各模块 logger**
- 全局搜索 `logging.getLogger(__name__)` → `logging.getLogger("surveymae.xxx")`
- 全局搜索 `print(` → logger 调用

**Step 5: 重写日志消息**
- 节点层 → 改用 `log_pipeline_step()` / `log_substep()`
- 重点: `evidence_collection.py`、`base.py`、`citation_checker.py`、`fetchers/*.py`

**Step 6: 添加进度条**
- `citation_checker._verify_references()` — 引用验证循环
- `citation_checker.analyze_citation_sentence_alignment()` — C6 批处理
- `foundational_coverage.py` — 关键文献检索
- `corrector._vote_all_dimensions()` — 多模型投票循环

**Step 7: 集成 RunStats**
- `base.py._call_llm()` → `record_llm()`
- 各 fetcher API 调用 → `record_api()`
- reporter 节点末尾 → `log_run_summary()`

**Step 8: 激活 errors.jsonl**
- `logger.error(...)` 处同时调用 `result_store.append_error()`

### 7.2 不做的事情

| 不做 | 原因 |
|------|------|
| JSON Lines 格式日志 | 已有 JSON 文件记录结构化数据 |
| 日志轮转 | 每次运行独立 run.log |
| logging.yaml | 当前只需 verbose 开关 |
| `rich.live.Live` 动态面板 | 过度复杂，Progress 足够 |
| LangGraph 持久化 Checkpoint | 与日志无关 |

---

## 八、CLI 参数设计

### 8.1 现有参数保留

```
pdf_path          → 改为 nargs="+"，支持多文件
-c / --config     → 不变
-o / --output-dir → 不变（批量模式下指定输出目录）
```

### 8.2 新增日志控制参数

```python
# src/main.py 新增参数

parser.add_argument(
    "-v", "--verbose",
    help="Enable verbose logging (show DEBUG on console)",
    action="store_true",
)

parser.add_argument(
    "--log-level",
    help="Set console log level (default: INFO, overrides -v)",
    choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    default=None,
)

parser.add_argument(
    "-q", "--quiet",
    help="Quiet mode: console only shows WARNING+, suppress progress bars",
    action="store_true",
)
```

**优先级规则：**
- `--log-level` 显式指定时，覆盖 `-v` 和 `-q`
- `-q` 和 `-v` 互斥（argparse `mutually_exclusive_group`）
- 默认（无参数）：控制台 INFO + 进度条

**`setup_logging` 适配：**

```python
def setup_logging(
    run_dir: str | Path | None = None,
    verbose: bool = False,
    log_level: str | None = None,   # 新增：显式日志级别
    quiet: bool = False,             # 新增：静默模式
) -> logging.Logger:
    """
    日志级别确定逻辑:
        1. log_level 显式指定 → 使用该级别
        2. quiet=True → WARNING
        3. verbose=True → DEBUG
        4. 默认 → INFO（RichHandler 设为 WARNING，INFO 走 Console 直接输出）
    """
    ...
```

### 8.3 quiet 模式与进度条

`quiet=True` 时：
- RichHandler 级别设为 WARNING（只显示警告和错误）
- `log_pipeline_step()` / `log_substep()` 不输出到控制台（仍写入文件）
- `create_progress()` 返回一个 **no-op Progress**（不渲染，但 API 兼容）
- 适用场景：CI/CD 环境、批量脚本、日志重定向到文件

### 8.4 批量模式的 CLI 用法

```bash
# 单篇
uv run python -m src.main survey.pdf

# 多篇
uv run python -m src.main paper1.pdf paper2.pdf paper3.pdf

# 静默批量（CI 环境）
uv run python -m src.main paper1.pdf paper2.pdf -q

# 调试特定问题
uv run python -m src.main survey.pdf --log-level DEBUG
```

`pdf_path` 改为 `nargs="+"`：

```python
parser.add_argument(
    "pdf_paths",
    nargs="+",
    help="Path(s) to survey PDF file(s) to evaluate",
)
```

---

## 九、验收标准

### 9.1 单篇模式

```
SurveyMAE 评测启动 | PDF: test_survey2.pdf

[01/07] parse_pdf              │ 47 refs, 12 sections                 2.3s
[02/07] evidence_collection    │ 证据收集中...
  ⠋ 验证引用 ██████████████████████████████ 47/47  0:00:18
  ├── citation_validate        │ C3=8.51% C5=89.36% (42/47)          18.7s
  ⠋ C6 对齐分析 ████████████████████████████ 31/31  0:00:06
  ├── C6_alignment             │ 312 对, 矛盾率 3.8%, auto_fail=No    6.2s
  ├── keyword_extract          │ 4 组检索词                            0.8s
  ├── trend_baseline           │ 2015-2025 趋势就绪                    3.1s
  └── key_papers               │ top-30 候选, 匹配 19 篇 (63.3%)       5.4s
[02/07] evidence_collection    │ 完成                                 34.2s
[03/07] evidence_dispatch      │ Evidence Report 组装完成
[04/07] agent_eval             │ 3 Agent 并行评估中...
  ├── VerifierAgent            │ V1=4 V2=4 V4=5                       4.2s
  ├── ExpertAgent              │ E1=4 E2=4 E3=5 E4=4                  3.8s
  └── ReaderAgent              │ R1=4 R2=3 R3=4 R4=3                  4.1s
[05/07] corrector_eval         │ 7 维度 × 3 模型 投票
  ⠋ 多模型投票 ██████████████████████████████ 21/21  0:00:08
  ├── V4: 5→4 (std=0.47)  E3: 5→3 (std=1.25)
  └── 2 维度分数被校正                                                8.6s
[06/07] aggregator             │ 总分 7.6/10, 等级 B
[07/07] reporter               │ 报告已保存
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
总耗时 51.2s │ LLM 调用 28 次 │ API 调用 94 次
```

### 9.2 批量模式

```
SurveyMAE 批量评测启动 | 3 篇 PDF

[1/3] test_survey2.pdf ─────────────────────────────────────────
  [01/07] parse_pdf            │ 47 refs, 12 sections             2.3s
  ...
  [07/07] reporter             │ 报告已保存
  ── test_survey2.pdf 完成 │ 总分 7.6/10, 等级 B │ 51.2s ──

[2/3] another_survey.pdf ───────────────────────────────────────
  [01/07] parse_pdf            │ 32 refs, 8 sections              1.8s
  ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
批量评测完成 │ 3/3 篇 │ 总耗时 142.5s │ LLM 调用 84 次 │ API 调用 282 次
```

### 9.3 通用说明

- 进度条完成后**保留在终端中**（`transient=False`），方便回看和截图
- WARNING 在进度条期间触发时，自动在进度条上方以黄色插入
- `run.log` 记录纯文本全级别日志（含 DEBUG）
- `-q` 模式下无控制台进度输出，仅 WARNING/ERROR

---

## 十、灵活性说明

1. **步骤编号 + 名称 + 关键数字 + 耗时** — 必须保留
2. **进度条必须用 `create_progress()`** — 确保共享 Console
3. **树状缩进可调整** — `├──` `└──` 是参考样式
4. **中英文保持一致** — 统一即可
5. **批量模式下每篇 PDF 的输出格式与单篇一致** — 外层加 paper 编号和分隔线

---

## 十一、公共 API 清单

| 函数/类 | 用途 | 调用方 |
|---------|------|--------|
| `setup_logging(run_dir, verbose, log_level, quiet)` | 初始化日志系统 | `main.py` |
| `get_console()` | 获取全局 Console | 需直接 Console 输出的模块 |
| `create_progress(quiet)` | 创建进度条 | 工具层迭代操作 |
| `log_pipeline_step(step, total, name, detail, elapsed)` | 输出 pipeline 步骤 | 节点层 |
| `log_substep(name, detail, elapsed, is_last)` | 输出子步骤 | 节点层 |
| `log_run_summary(stats, total_elapsed)` | 输出最终汇总 | reporter 节点 |
| `track_step(logger, label)` | 耗时记录上下文管理器 | 各层 |
| `RunStats` | 调用计数器 | `base.py`, fetchers |
| `get_run_stats()` | 获取全局计数器 | 各层 |

---

## 十二、实施状态

> 更新时间: 2026/04/05

### 12.1 完成状态

| 任务 | 状态 | 说明 |
|------|------|------|
| Step 1: 添加 rich 依赖 + 创建 src/core/log.py | ✅ 完成 | `uv add rich` 已执行；`src/core/log.py` 已创建并实现全部公共 API |
| Step 2: 重构 main.py | ✅ 完成 | `basicConfig` 替换为 `setup_logging()`；`-v`/`-q`/`--log-level` 参数已添加；`run_id` 统一生成逻辑 |
| Step 3: ResultStore 路径重构 | ✅ 完成 | `papers/{id}/tools/` 和 `papers/{id}/nodes/` 分离；`save_node_step()` 方法已添加 |
| Step 4: 模块 logger 前缀替换 | ✅ 完成 | 全部 22 个模块已替换为 `surveymae.xxx` 前缀 |
| Step 5: FileHandler 日志落地 | ✅ 完成 | `logs/run.log` 在 `setup_logging(run_dir=...)` 时自动创建 |
| Step 6: RunStats 集成 | ✅ 完成 | `base.py` LLM 调用 + 5 个 fetcher API 调用已集成 |
| Step 7: 进度条 | ✅ 完成 | `citation_checker._verify_references()` 已添加进度条 |
| Step 8: 文档更新 | ✅ 完成 | LOGGING_DESIGN.md 已更新 |

### 12.2 新建文件

| 文件 | 说明 |
|------|------|
| `src/core/log.py` | 日志基础设施核心模块（约 280 行） |

### 12.3 修改文件

| 文件 | 主要变更 |
|------|---------|
| `pyproject.toml` | 添加 `rich>=13.0` 依赖 |
| `src/main.py` | `basicConfig` → `setup_logging()`；统一 `run_dir` 生成；CLI 参数重构；`run_evaluation` 返回 `(report, run_dir)` |
| `src/graph/builder.py` | logger 前缀；`create_workflow(run_dir)` 参数；`_save_workflow_step()` 使用 `nodes/`；全局 `_result_store` 支持 `run_dir` |
| `src/tools/result_store.py` | `tools/` 和 `nodes/` 子目录分离；`save_node_step()` 方法；`_tools_dir()` / `_nodes_dir()` 辅助方法 |
| `src/agents/base.py` | 导入 `get_run_stats`；`_call_llm()` 和 `_call_llm_pool()` 中集成 `record_llm()` |
| `src/tools/fetchers/semantic_scholar_fetcher.py` | 导入 `get_run_stats`；所有 HTTP 成功响应后调用 `record_api()` |
| `src/tools/fetchers/openalex_fetcher.py` | 同上 |
| `src/tools/fetchers/crossref_fetcher.py` | 同上 |
| `src/tools/fetchers/arxiv_fetcher.py` | 同上 |
| `src/tools/fetchers/dblp_fetcher.py` | 同上 |
| `src/tools/citation_checker.py` | 导入 `create_progress`；`_verify_references()` 中添加进度条 |

### 12.4 目录结构变更

```
output/runs/{run_id}/
├── run.json / index.json / run_summary.json（不变）
├── logs/run.log              ← 新增：完整 DEBUG 日志（每次运行新建）
└── papers/{paper_id}/
    ├── source.json
    ├── nodes/                ← 新增目录（原直接放在 paper_id/ 下）
    │   ├── 01_parse_pdf.json
    │   ├── 02_evidence_collection.json
    │   └── ...
    └── tools/                ← 新增目录（原直接放在 paper_id/ 下）
        ├── extraction.json
        ├── validation.json
        └── ...
```

### 12.5 待完成

| 任务 | 说明 |
|------|------|
| `evidence_collection.py` 节点层进度日志 | `log_pipeline_step()` / `log_substep()` 接入节点入口 |
| Corrector 多模型投票进度条 | `corrector._vote_all_dimensions()` 中添加进度条 |
| `evidence_collection.py` 中的 `log_substep` 调用 | C3/C5/C6/T/G 步骤完成后输出子步骤汇总 |
| 端到端测试 | 用真实 PDF 运行完整评测流程，验证日志输出和文件落地 |
| `errors.jsonl` 激活 | 在 `base.py` 和关键工具的 `except` 块中调用 `result_store.append_error()` |
