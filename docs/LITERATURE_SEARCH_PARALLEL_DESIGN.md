# Literature Search 并发多源设计方案

## 背景与问题

当前 `LiteratureSearch` 各方法对多个源采用**串行循环**：每个源请求完成后才开始下一个。以 `search_field_trend` 为例，它对 OpenAlex 还逐年发 HTTP 请求（最多 25 次），整体耗时极长。Semantic Scholar 免费额度严格限速（~1 req/s，无 API Key 约 100 req/5min），一旦触发 429/404，串行重试会进一步阻塞后续源。

**目标：**
1. 多源**并发分发**，减少总耗时
2. 单源失败有**重试**，重试耗尽后**降级**到备用源
3. 全部源失败时有**最终兜底**（返回部分结果或空结果，不抛异常）
4. 所有行为可在 `config/search_engines.yaml` **统一配置**
5. **最小化接口变更**（`LiteratureSearch` 的 public 方法签名不变）

---

## 架构设计

### 核心思路：Fan-out + Hedge + Fallback

```
调用方 (evidence_collection.py)
    │
    ▼
LiteratureSearch.search_xxx(...)          ← 接口不变
    │
    ▼
_ParallelDispatcher.dispatch(sources, op)
    │
    ├─── asyncio.gather / ThreadPoolExecutor
    │         ├── [semantic_scholar] ── with_retry(n) ── 成功→结果
    │         ├── [openalex]          ── with_retry(n) ── 成功→结果
    │         └── [crossref]          ── with_retry(n) ── 失败→降级
    │
    ▼
结果合并 (merge_strategy: first_wins | union | weighted_union)
    │
    ▼
降级检查: 若结果为空 → 依次尝试 fallback_sources
```

### 组件职责

| 组件 | 职责 |
|------|------|
| `SearchEngineConfig` | 扩展：读取并发源列表、每源重试配置、降级策略 |
| `_SourceConfig` | 单个源的运行时配置（priority, retries, timeout, enabled） |
| `_ParallelDispatcher` | 并发执行多源请求，收集成功/失败结果 |
| `LiteratureSearch` | 接口层，内部改用 dispatcher，对外签名不变 |

---

## search_engines.yaml 扩展设计

```yaml
# ============================================================
# 全局设置
# ============================================================
verify_limit: 50
api_timeout_seconds: 15

# ============================================================
# 并发策略
# ============================================================
concurrency:
  # 同时并发的最大源数量（防止同一时刻打爆所有源）
  max_concurrent_sources: 3

  # 合并策略:
  #   first_wins   - 取最先返回且非空的结果（速度最快）
  #   union        - 合并所有源结果并去重（结果最全）
  #   weighted_union - 按 priority 加权，低优先级补充高优先级缺失项
  merge_strategy: weighted_union

  # 并发超时（单源），超过视为失败，不影响其他源
  per_source_timeout_seconds: 10

# ============================================================
# 降级策略
# ============================================================
degradation:
  # 主并发源全部失败后，按此顺序逐一尝试（串行兜底）
  fallback_order:
    - crossref
    - dblp

  # 兜底也全部失败时的行为:
  #   empty   - 返回空列表（不抛异常）
  #   raise   - 抛出异常
  on_all_failed: empty

# ============================================================
# 源定义：每个源的独立配置
# ============================================================
sources:
  semantic_scholar:
    enabled: true
    priority: 1              # 数字越小优先级越高
    concurrent: true         # 是否参与主并发批次
    max_retries: 2
    retry_delay_seconds: 2.0
    retry_backoff: 2.0       # 指数退避倍率
    # 触发重试的 HTTP 状态码
    retry_on_status: [429, 500, 502, 503, 504]
    timeout_seconds: 8
    api_key: ${SEMANTIC_SCHOLAR_API_KEY}

  openalex:
    enabled: true
    priority: 2
    concurrent: true
    max_retries: 1
    retry_delay_seconds: 1.0
    retry_backoff: 1.5
    retry_on_status: [429, 500, 502, 503]
    timeout_seconds: 10
    email: ${OPENALEX_EMAIL}

  crossref:
    enabled: true
    priority: 3
    concurrent: false        # 不参与主并发，仅作 fallback
    max_retries: 2
    retry_delay_seconds: 1.0
    retry_backoff: 2.0
    retry_on_status: [429, 500, 503]
    timeout_seconds: 12
    mailto: surveymae@example.com

  arxiv:
    enabled: true
    priority: 4
    concurrent: false        # arxiv 仅在 fetch_by_arxiv_id 时使用
    max_retries: 1
    retry_delay_seconds: 3.0  # arxiv 官方要求 3s 间隔
    retry_backoff: 1.0
    retry_on_status: [429, 503]
    timeout_seconds: 15

  dblp:
    enabled: true
    priority: 5
    concurrent: false
    max_retries: 1
    retry_delay_seconds: 1.5
    retry_backoff: 1.5
    retry_on_status: [429, 500, 503]
    timeout_seconds: 10

  scholar:
    enabled: false           # 默认关闭（scraping，风险高）
    priority: 6
    concurrent: false
    max_retries: 0
    timeout_seconds: 20

# 旧字段保留兼容（被 sources.*.* 覆盖）#TODO: 旧字段删除即可，原先调用位置也要修改
fallback_order:
  - semantic_scholar
  - openalex
  - crossref
```

---

## 运行时行为详解

### 1. 并发主批次

```python
concurrent_sources = [s for s in resolved if source_cfg[s].concurrent]
# e.g. ["semantic_scholar", "openalex"]

results = await asyncio.gather(
    *[_fetch_with_retry(source, op, cfg) for source in concurrent_sources],
    return_exceptions=True,
)
```

- 每个源独立运行 `with_retry`，互不影响
- `asyncio.gather(return_exceptions=True)` 保证单源异常不中断其他源
- `per_source_timeout_seconds` 通过 `asyncio.wait_for` 强制截断慢源

### 2. 单源重试逻辑

```
attempt 1 → 失败(429) → sleep(retry_delay)
attempt 2 → 失败(500) → sleep(retry_delay * backoff)
attempt 3 → 失败      → 标记该源为 FAILED，返回空
```

仅对 `retry_on_status` 中列出的状态码重试；网络超时（`TimeoutError`）和连接错误也触发重试。

### 3. 合并策略

| 策略 | 行为 | 适用场景 |
|------|------|----------|
| `first_wins` | 取第一个有结果的源，忽略其余 | 延迟敏感，结果等价 |
| `union` | 所有源结果合并+去重（按 DOI/title） | 需要最大召回率 |
| `weighted_union` | priority 高的源结果优先保留，低优先级仅补充缺失 | **默认，平衡质量与速度** |

### 4. 降级（Fallback）流程

```
主并发批次完成
    │
    ├── 有结果？ → 返回
    │
    └── 全部失败或结果为空
            │
            ▼
        依次尝试 degradation.fallback_order（串行）
            ├── crossref → 有结果？ → 返回
            └── dblp     → 有结果？ → 返回
                │
                └── 全部失败 → on_all_failed 决策
                        ├── empty → 返回 []（记录 ERROR 日志）
                        └── raise → 抛出 AllSourcesFailedError
```

### 5. search_field_trend 专项优化

当前 OpenAlex 实现逐年发请求（25次/关键词），是最大瓶颈。优化方案：

```python
# 改为单次聚合请求，利用 OpenAlex group_by 接口
GET /works?search={kw}&filter=publication_year:2000-2025
           &group_by=publication_year&per-page=1
# 返回：{"group_by": [{"key": "2020", "count": 1234}, ...]}
```

这把 25 次串行请求压缩为 **1 次**，是该函数最重要的加速手段，与并发方案正交叠加。

---

## 接口变更最小化策略

### `LiteratureSearch` public 方法：**签名完全不变**

```python
# 调用方无需任何修改
lit_search = LiteratureSearch()
result = lit_search.search_field_trend(kw, year_range=...)
results = lit_search.search_by_keywords(kw, max_results=30)
papers = await lit_search.search_top_cited(kw, top_k=30)
```

### `SearchEngineConfig` 扩展（向后兼容）

新增字段全部有默认值，旧 YAML（不含 `sources:` 节）继续可用：

```python
@dataclass
class SourceConfig:
    enabled: bool = True
    priority: int = 99
    concurrent: bool = False
    max_retries: int = 2
    retry_delay_seconds: float = 1.0
    retry_backoff: float = 2.0
    retry_on_status: list[int] = field(default_factory=lambda: [429, 500, 502, 503, 504])
    timeout_seconds: float = 10.0
    # 源专属凭证
    api_key: Optional[str] = None
    email: Optional[str] = None
    mailto: Optional[str] = None

@dataclass
class ConcurrencyConfig:
    max_concurrent_sources: int = 3
    merge_strategy: str = "weighted_union"
    per_source_timeout_seconds: float = 10.0

@dataclass
class DegradationConfig:
    fallback_order: list[str] = field(default_factory=lambda: ["crossref", "dblp"])
    on_all_failed: str = "empty"  # "empty" | "raise"

@dataclass
class SearchEngineConfig:
    # 旧字段保留
    verify_limit: int = 50
    api_timeout_seconds: float = 15.0
    fallback_order: list[str] = ...
    semantic_scholar_api_key: Optional[str] = None
    crossref_mailto: str = "surveymae@example.com"
    openalex_email: Optional[str] = None
    # 新增
    concurrency: ConcurrencyConfig = field(default_factory=ConcurrencyConfig)
    degradation: DegradationConfig = field(default_factory=DegradationConfig)
    sources: dict[str, SourceConfig] = field(default_factory=dict)
```

### `evidence_collection.py`：**无需改动**

`DEFAULT_VERIFY_SOURCES` 从 `fallback_order` 读取（已有），新配置由 `LiteratureSearch` 内部消费。

---

## 实现步骤（建议顺序）

1. **扩展 `search_config.py`**：新增 `SourceConfig`、`ConcurrencyConfig`、`DegradationConfig`，解析新版 YAML，保持旧字段可用
2. **更新 `search_engines.yaml`**：按新格式填写，旧字段保留兼容
3. **实现 `_ParallelDispatcher`**（新模块 `src/tools/parallel_dispatcher.py`）：
   - `async dispatch(sources, op_fn, cfg) -> list[LiteratureResult]`
   - 内含单源重试 + timeout 包装
   - 内含合并策略
   - 内含降级串行兜底
4. **改造 `LiteratureSearch` 内部方法**：
   - `search_by_title`、`fetch_by_doi`、`fetch_by_arxiv_id`、`search_by_keywords` 改为调用 dispatcher（同步方法用 `asyncio.run` 或 `run_in_executor` 桥接）
   - `search_field_trend` 中的 OpenAlex 改用 `group_by` 单次请求
   - `_search_field_trend_*` 两个方法并发化
5. **测试验证**：
   - 单源 429 触发重试后成功
   - 主并发源全败，fallback 兜底返回结果
   - `on_all_failed: empty` 时不抛异常，返回 `[]`
   - `search_field_trend` 单关键词耗时 < 3s（对比优化前 ~30s）

---

## 风险与注意事项

| 风险 | 缓解措施 |
|------|----------|
| `LiteratureSearch` 现有方法是同步的，dispatcher 是 async | 同步方法内部用 `asyncio.get_event_loop().run_until_complete()` 或 `concurrent.futures` 桥接；`search_top_cited` 已是 async，直接用 `await` |
| 并发对同一源发多请求可能加速触发限速 | `concurrent: false` 的源不进入主批次；`max_concurrent_sources` 限制同时并发数 |
| OpenAlex `group_by` 接口返回格式不同 | 在 `openalex_fetcher.py` 新增 `fetch_yearly_counts(query, year_range)` 方法，隔离接口差异 |
| Windows 事件循环兼容性（`asyncio` + `nest_asyncio`） | 已有代码用 `async`，遵循现有模式即可；若同步上下文中需要运行，用 `asyncio.run()` |
