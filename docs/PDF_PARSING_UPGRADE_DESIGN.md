# SurveyMAE PDF 解析精度提升设计文档（Marker API 版）

> **版本**: v1.3-marker  
> **日期**: 2026-04-08  
> **目标读者**: Claude Code 自动实施  
> **对应代码版本**: Phase 2 完成后  
> **关联文档**: `DEVELOPER_GUIDE.md` (v3.1)

---

## 1. 背景与问题陈述

### 1.1 当前架构

SurveyMAE 的 PDF 解析流程为：

```
PDF → PDFParser (pymupdf4llm) → Markdown → CitationChecker → 结构化引用/章节/引文上下文
```

PDF 解析是整个评测管线的第一步（`01_parse_pdf`），其输出 `parsed_content` 和 `section_headings` 被后续所有步骤依赖。解析精度问题会级联传播至下游全部分析模块。

### 1.2 已确认的两个核心问题

#### 问题 A：文档结构解析失真

**现象**：pymupdf4llm 将页眉文本（如 `"Natl Sci Rev, 2024, Vol. 11, nwae403"`）错误地标记为 markdown 标题（`#` / `##`）。

**根因**：pymupdf4llm 基于字体大小的简单启发式判断标题，但学术论文的页眉字体往往与正文章节标题字体大小接近甚至更大。

**影响链路**：
- `CitationChecker._extract_markdown_headings()` 从 markdown 中提取 heading candidates，页眉被混入
- `CitationChecker._extract_citations_with_context_mupdf()` 使用 heading candidates 作为白名单过滤章节标题，但当白名单本身被污染时失效
- 章节识别错误直接影响 **S1**（section_count）、**S2**（citation_density）、**S3**（citation_gini）、**S4**（zero_citation_section_rate）、**S5**（section-cluster alignment）
- `_extract_title_and_abstract()` 在 `evidence_collection.py` 中使用正则从 markdown 前几行提取标题和摘要，页眉干扰导致提取失败

#### 问题 B：引用文献元数据解析失真

**现象**：从 markdown 中用正则方法解析参考文献列表，字段拆分（title、authors、venue、year）准确率低。

**根因**：
- `_find_reference_block()` 基于 heading 关键词定位 reference 区块，对非标准格式容易定位错误
- `_split_reference_entries()` 和 `_parse_reference_entries()` 完全依赖正则匹配，对不同引用格式（IEEE numbered、APA author-year、Nature style 等）泛化能力差
- `_extract_title()` 优先找引号包裹的文本，但很多格式的论文标题不加引号
- `_extract_authors()` 依赖年份位置做切割，容易将 venue 名误识为作者

**影响链路**：
- **C5**（metadata_verify_rate）：解析出的 title 不准确导致外部 API 查不到匹配，降低验证率
- 引用图边构建（`build_real_citation_edges`）质量下降
- **G4**（foundational coverage）依赖准确的 ref_metadata_cache

### 1.3 项目中已有的 GROBID 基础

> **重要提示（for Claude Code）**：项目中已经存在 GROBID 集成代码，请在实施前先查阅以下现有代码：
> - `src/tools/citation_checker.py` 中的 `GrobidReferenceExtractor` 类
> - `_extract_references_with_backend()` 方法中的 GROBID-first / mupdf-fallback 逻辑
> - `DEVELOPER_GUIDE.md` 的 "GROBID（可选后端）部署" 章节
> - `config/main.yaml` 中的 `citation.backend` 配置项
> - 环境变量 `GROBID_URL`（默认 `http://localhost:8070`）

当前 GROBID 是 **可选后端**，仅用于 reference 提取，且处于 `auto` 模式（GROBID 不可用时静默回退到 mupdf 正则解析）。

---

## 2. 技术选型论证

### 2.1 Marker API 云服务 —— 解决文档结构解析（问题 A）

**选型理由**：
- **自动去除页眉/页脚/页码**：Marker 使用 `Surya` 布局检测模型识别文档区域，能自动区分页眉、正文、标题等，从根本上解决问题 A。通过 `additional_config={"keep_pageheader_in_output": false}` 明确配置丢弃页眉
- **多栏布局支持**：学术论文双栏是主场景，Marker 在复杂布局（表格、公式、多栏）上的解析精度业界领先
- **阅读顺序正确**：基于布局模型推断阅读顺序，避免双栏交错，输出 `section_hierarchy` 层级信息可直接用于章节识别
- **JSON 结构化输出**：除 Markdown 外，支持 `output_format="json"` 输出包含 `block_type`（如 `SectionHeader`, `Text`, `PageHeader`, `PageFooter`）的层级结构，便于精确提取章节边界
- **同时获取 Markdown 和 JSON**：通过 `include_markdown_in_chunks=true` 参数，单次 API 调用即可同时获得结构化 JSON（用于章节识别）和完整 Markdown（用于 LLM 输入），成本最优

**成本与约束警告（必读）**：
- **按量付费**：Marker API 是 Datalab 提供的商业云服务，按页计费（具体费率参考 [定价页面](https://www.datalab.to/plans)）。新账户包含 $5 试用额度
- **异步轮询机制**：Marker API 采用"提交-轮询"模式（先 POST 获取 `request_check_url`，再轮询直到 `status=complete`）
- **网络依赖**：必须配置有效的 `DATALAB_API_KEY` 环境变量，且运行环境需能访问 `https://www.datalab.to/api/v1/convert`
- **无预设页数限制**：Marker API 未公开最大页数限制，不在上传前做页数检查。如 API 返回页数过大错误，再提示用户

**Marker API 不解决什么**：
- 引用列表仍为纯文本，**不做字段级拆分**（不区分 title/author/venue/year）
- 因此 Marker **不能替代 GROBID** 处理引用元数据

### 2.2 GROBID —— 解决引用元数据解析（问题 B）

**选型理由**：
- **专为学术文献设计**：引用解析 F1 约 0.87-0.90，字段级 F1 达 0.95
- **结构化 TEI-XML 输出**：每条引用直接拆分为 title、authors（含 forename/surname）、year、DOI、venue 等结构化字段
- **Consolidation 能力**：可通过 CrossRef/biblio-glutton 自动补全 DOI/PMID
- **Header 提取**：可提取文献的 title、abstract、authors、affiliations、keywords 等头部元数据
- **项目已有基础**：`GrobidReferenceExtractor` 已实现，仅需升级和扩展

**GROBID 不解决什么**：
- 全文布局检测和结构化不如 Marker
- 对表格、公式等非文本元素处理弱

### 2.3 双通道互补架构

```
                              PDF 文件
                                │
                 ┌──────────────┼──────────────┐
                 ▼                             ▼
         Marker API 通道                  GROBID 通道
    (正文结构 & 章节标题)          (引用元数据 & Header)
                 │                             │
                 ▼                             ▼
    parsed_content (Markdown)       references (结构化)
    section_headings (from JSON)      header_metadata
    引文上下文句子                   (title, abstract, authors)
                 │                             │
                 └──────────────┬──────────────┘
                                ▼
                    合并后的 CitationExtractionResult
```

**核心原则**：对同一 PDF 执行两次独立解析，各取所长，合并结果。Marker API 负责正文内容和结构（单次调用同时获取 JSON 结构和 Markdown 文本），GROBID 负责引用列表和文献头部元数据。

---

## 3. Marker API 集成方案

### 3.1 云服务调用方式

Marker API 通过 RESTful API 调用，**不支持本地部署**。

**官方文档**：`https://documentation.datalab.to/api-reference/convert-document`

**调用流程**：
```python
# 1. 提交转换请求（POST）
POST https://www.datalab.to/api/v1/convert
Headers: X-API-Key: {DATALAB_API_KEY}
Body: multipart/form-data
  - file: <PDF文件>
  - output_format: "json"                           # 获取结构化数据
  - include_markdown_in_chunks: true                # 关键：同时返回 markdown
  - mode: "accurate"                                # 推荐学术论文使用
  - additional_config: '{"keep_pageheader_in_output": false, "keep_pagefooter_in_output": false}'

# 2. 获取轮询 URL（Response）
{
  "status": "processing",
  "request_check_url": "https://www.datalab.to/api/v1/convert/result/<request_id>",
  ...
}

# 3. 轮询查询结果（GET）
GET https://www.datalab.to/api/v1/convert/result/<request_id>
Headers: X-API-Key: {DATALAB_API_KEY}

# 4. 完成时返回
{
  "status": "complete",
  "output_format": "json",
  "json": {
    "children": [...],           // 结构化 blocks（含 section_hierarchy）
    "markdown": "...",           // 完整的 markdown 文本
    "metadata": {...}
  },
  "page_count": 10,
  "parse_quality_score": 4.5,
  "cost_breakdown": {"total_cost_cents": 25}
}
```

**关键参数组合**（成本最优）：

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| `mode` | `"accurate"` | 学术论文通常有复杂布局（表格、公式），最高精度模式 |
| `output_format` | `"json"` | 获取结构化 blocks 和章节层级 |
| `include_markdown_in_chunks` | `true` | **关键**：在 JSON 响应中**同时包含** markdown 文本，无需二次调用 |
| `additional_config` | `{"keep_pageheader_in_output": false, "keep_pagefooter_in_output": false}` | **关键**：明确丢弃页眉页脚 |

**质量评分利用**：
Marker 返回 `parse_quality_score`（0-5 分），建议实施**质量门控**：
- 分数 < 3.0 时，可自动重试 `accurate` 模式或告警人工检查

### 3.2 新建 `MarkerApiParser` 类

**文件位置**：`src/tools/marker_api_parser.py`

**职责**：
- 封装 Marker API 异步轮询调用（提交→轮询→获取结果）
- 提供与现有 `PDFParser` 兼容的接口（`parse()` → 返回 Markdown 字符串）
- 处理 API 错误、超时、限流、页数限制错误，**必须在日志中明确提醒降级**
- 实现磁盘缓存（避免重复调用 API 产生费用）

**设计要点**：

```python
class MarkerApiParser:
    """Marker API-based PDF parser for high-quality document structure extraction.

    与 PDFParser 接口兼容，作为 pymupdf4llm 的替代方案。
    通过 Datalab Marker API 获得更准确的：
    - 页眉/页脚/页码过滤（通过 additional_config 显式配置）
    - 章节标题识别（通过 json 输出的 section_hierarchy）
    - 多栏布局阅读顺序

    异步轮询机制：提交后立即返回轮询 URL，需轮询直到 status=complete。
    单次 API 调用通过 include_markdown_in_chunks=true 同时获取 JSON 结构和 Markdown 文本。
    所有 API 调用必须包含 DATALAB_API_KEY 认证。
    """

    def __init__(self, api_key: str, mode: str = "accurate", 
                 include_markdown_in_chunks: bool = True, ...):
        ...

    def parse(self, pdf_path: str) -> str:
        """解析 PDF 为 Markdown。接口与 PDFParser.parse() 兼容。
        内部调用 parse_with_structure() 但仅返回 markdown 字符串。
        """
        ...

    def parse_with_structure(self, pdf_path: str) -> Tuple[str, Dict]:
        """返回 (markdown, json_structure)。
        json_structure 包含 blocks 层级和 section_hierarchy。
        单次 API 调用同时获取两种格式（通过 include_markdown_in_chunks）。
        """
        ...

    def parse_cached(self, pdf_path: str) -> str:
        """带磁盘缓存的解析。缓存 key 应包含文件哈希和 API 参数（mode/format）。
        命中缓存时直接返回，不产生 API 费用。
        """
        ...

    async def aparse(self, pdf_path: str) -> str:
        """异步版本，使用 httpx.AsyncClient 进行轮询。"""
        ...
```

**配置管理**：

在 `config/main.yaml` 中添加 Marker API 相关配置项：

```yaml
pdf_parser:
  backend: "marker_api"              # "marker_api" | "pymupdf4llm" | "auto"
  marker_api:
    api_key: "${DATALAB_API_KEY}"    # 从环境变量读取，**必需**
    mode: "accurate"                 # "fast" | "balanced" | "accurate"
    output_format: "json"              # 必须设为 "json" 以获取结构
    include_markdown_in_chunks: true   # **关键**：同时获取 markdown
    additional_config:
      keep_pageheader_in_output: false    # **关键**：去除页眉
      keep_pagefooter_in_output: false    # **关键**：去除页脚
    max_poll_attempts: 60            # 最大轮询次数（约 2 分钟）
    poll_interval_seconds: 2         # 轮询间隔
    request_timeout_seconds: 300     # 单请求超时
  cache_dir: "./output/pdf_cache"
```

**环境变量要求**：

| 变量名 | 说明 | 必需性 |
|--------|------|--------|
| `DATALAB_API_KEY` | Datalab API 密钥（从 https://www.datalab.to 获取） | **使用 Marker API 时必需** |
| `GROBID_URL` | GROBID 服务地址（已有） | GROBID 后端必需 |

### 3.3 替换 `PDFParser` 的调用点

> **重要提示（for Claude Code）**：在替换之前，请先用 `grep -rn "PDFParser\|pdf_parser" src/` 和 `grep -rn "parse_cached\|parse_pdf\|\.parse(" src/tools/ src/graph/` 查找所有 `PDFParser` 的调用点。以下是已知的调用点，但可能不完整：

已知调用点：
1. `src/graph/nodes/` 中的 PDF 解析节点（`01_parse_pdf` 步骤）
2. `src/tools/citation_checker.py` 的 `parse_pdf()` 方法
3. `src/tools/citation_checker.py` 的 `_extract_markdown_headings()` 方法

**替换策略**：引入工厂模式，根据配置选择解析后端：

```python
def create_pdf_parser(config=None):
    """根据配置创建 PDF 解析器实例。

    降级时必须在日志中明确说明原因。
    """
    backend = config.pdf_parser.backend if config else "auto"

    if backend == "marker_api":
        api_key = os.getenv("DATALAB_API_KEY")
        if not api_key:
            logger.warning(
                "⚠️ [DEGRADED] DATALAB_API_KEY 未设置，无法使用 Marker API。"
                "降级使用 pymupdf4llm。页眉可能被误识为标题。"
                "【影响】S1-S5 指标可能失真。"
                "【修复】获取 API Key: https://www.datalab.to/plans"
            )
            return PDFParser(...)

        try:
            parser = MarkerApiParser(api_key=api_key, ...)
            return parser
        except Exception as e:
            logger.warning(
                "⚠️ [DEGRADED] Marker API 初始化失败: %s。"
                "降级使用 pymupdf4llm。页眉可能被误识为标题。", e
            )
            return PDFParser(...)

    elif backend == "pymupdf4llm":
        return PDFParser(...)

    elif backend == "auto":
        # 尝试 Marker API，失败降级到 pymupdf4llm（同上逻辑）
        ...
```

### 3.4 Marker JSON 输出的利用（进阶优化）

Marker API 的 JSON 输出包含层级化结构，可直接用于章节识别，绕过从 Markdown 中通过 `#` 标记推断章节的启发式方法。

**JSON 结构关键字段**：
```json
{
  "children": [
    {
      "block_type": "Page",
      "children": [
        {
          "block_type": "SectionHeader",
          "text": "INTRODUCTION",
          "section_hierarchy": {"1": "INTRODUCTION"},
          "polygon": [...]
        },
        {
          "block_type": "Text",
          "text": "...",
          "section_hierarchy": {"1": "INTRODUCTION"}
        }
      ]
    }
  ]
}
```

**建议**：通过 `section_hierarchy` 字段直接构建 `section_headings` 列表，避免依赖 Markdown 的 `#` 标记解析。

---

## 4. GROBID 升级方案

### 4.1 从"可选后端"升级为"默认引用解析后端"

**当前状态**：`citation.backend` 默认为 `"auto"`，GROBID 不可用时静默回退。

**目标状态**：
- 开发/测试环境：GROBID 为必需依赖，启动时检查可用性
- CI/生产环境：GROBID 仍为推荐但非强制，保留 fallback 逻辑
- 配置项 `citation.backend` 默认值改为 `"grobid"`

**修改点**：
- `_extract_references_with_backend()` 中：当 `backend == "grobid"` 且 GROBID 不可用时，**记录 WARNING 而非静默回退**
- `docker-compose.yaml`（或 `docker-compose.grobid.yaml`）中确保 GROBID 服务定义完整

### 4.2 补充 `GrobidReferenceExtractor` 的功能

> **提示（for Claude Code）**：请先查阅 `src/tools/citation_checker.py` 中现有的 `GrobidReferenceExtractor` 类，了解其当前能力和不足。

**需要补充的功能**：

#### 4.2.1 Venue（期刊/会议名）提取

当前 `_parse_references()` 提取了 title、authors、year、DOI、arxiv_id，但**缺少 venue**。

TEI-XML 中 venue 信息位于：
```xml
<biblStruct>
  <monogr>
    <title level="j">期刊名</title>        <!-- journal -->
    <title level="m">会议/书名</title>      <!-- monograph/conference -->
  </monogr>
</biblStruct>
```

需要在 `_parse_references()` 中添加 venue 提取逻辑，并将其写入 `ReferenceEntry`。

> **提示（for Claude Code）**：`ReferenceEntry` dataclass 当前没有 `venue` 字段，需要添加。同时检查 `ReferenceEntry.to_dict()` 和所有消费 `ReferenceEntry` 的下游代码。

#### 4.2.2 启用 Consolidation

在 `GrobidReferenceExtractor.__init__()` 中，`consolidate` 参数默认为 `False`。启用后（`consolidateCitations=1`），GROBID 会自动通过 CrossRef 补全 DOI。

**修改方式**：
- 配置项 `citation.grobid_consolidate` 默认改为 `true`
- 注意 consolidation 会增加 GROBID 处理时间（因为需要外部 API 调用），考虑将 `grobid_timeout_s` 适当增大

#### 4.2.3 Header Metadata 提取

新增方法从 GROBID TEI-XML 中提取文献头部元数据（title、abstract、authors、keywords），用于替代 `evidence_collection.py` 中基于正则的 `_extract_title_and_abstract()`。

GROBID 提供独立的 header 提取 API endpoint：`POST /api/processHeaderDocument`

**TEI-XML header 结构**：
```xml
<teiHeader>
  <fileDesc>
    <titleStmt>
      <title level="a" type="main">论文标题</title>
    </titleStmt>
    <publicationStmt>
      <publisher>出版社</publisher>
    </publicationStmt>
  </fileDesc>
  <profileDesc>
    <abstract>
      <p>摘要文本</p>
    </abstract>
    <textClass>
      <keywords>
        <term>关键词1</term>
        <term>关键词2</term>
      </keywords>
    </textClass>
  </profileDesc>
</teiHeader>
```

### 4.3 GROBID 部署

```bash
# Docker 一行启动
docker run --rm -d -p 8070:8070 --name grobid grobid/grobid:0.8.2

# 或使用项目已有的 docker-compose
docker compose -f docker-compose.grobid.yaml up -d
```

配置：
```yaml
# config/main.yaml
citation:
  backend: "grobid"           # 默认使用 GROBID
  grobid_url: "http://localhost:8070"
  grobid_timeout_s: 60        # consolidation 需要更长时间
  grobid_consolidate: true    # 启用 CrossRef DOI 补全
```

---

## 5. 合并策略与数据流

### 5.1 `extract_citations_with_context_from_pdf` 改造

这是 `CitationChecker` 中的核心方法，当前流程为：

```
1. _extract_citations_with_context_mupdf(pdf_path)  → citations + sections（基于 PyMuPDF）
2. _extract_references_with_backend(pdf_path)        → references（GROBID 或 mupdf 正则）
3. _link_citations_to_references(citations, references)
```

改造后流程：

```
1. _extract_citations_with_context_from_marker(pdf_path)  → citations + sections（基于 Marker API 返回的 markdown/json）
2. _extract_references_with_grobid(pdf_path)              → references（GROBID 结构化解析）
3. _link_citations_to_references(citations, references)
```

> **提示（for Claude Code）**：
> - 步骤 1 的改造需要理解 `_extract_citations_with_context_mupdf()` 当前做了什么：它遍历 PyMuPDF 的 text blocks，合并段落，识别标题，分句，提取引文标记，构建 `CitationSpan` 列表和 `sections` 列表
> - Marker API 的 Markdown 输出已经去除了页眉/页脚，因此可以复用现有的 `_extract_citations_with_context_text()` 方法作为基础进行改造
> - 利用 Marker JSON 输出的 `section_hierarchy` 字段直接构建章节结构，避免从 Markdown 推断

### 5.2 `evidence_collection.py` 改造

**`_extract_title_and_abstract()` 替换**：

```python
# 当前：从 parsed_content (Markdown) 中用正则提取
title, abstract = _extract_title_and_abstract(parsed_content)

# 改造后：优先从 GROBID header 提取，fallback 到 Markdown 正则
title, abstract = _extract_title_and_abstract_grobid(pdf_path)
if not title:
    title, abstract = _extract_title_and_abstract(parsed_content)  # fallback
```

> **提示（for Claude Code）**：请查阅 `evidence_collection.py` 中 `_extract_title_and_abstract()` 的所有调用点，以及 `title` 和 `abstract` 变量在后续步骤中如何被使用。

### 5.3 `01_parse_pdf` 节点改造

> **提示（for Claude Code）**：请先在 `src/graph/nodes/` 中找到 `01_parse_pdf` 对应的实际节点实现代码。通过 `grep -rn "parse_pdf\|01_parse" src/` 确认。

该节点需要改为使用 `MarkerApiParser` 替代 `PDFParser`，将 Marker API 的 Markdown 输出写入 `parsed_content`，并将 JSON 中的 `section_hierarchy` 转换为 `section_headings`。

---

## 6. Fallback 与容错设计

### 6.1 三级降级策略

```
Level 1: Marker API + GROBID（最优，按页付费）
    ↓ DATALAB_API_KEY 未设置 或 API 调用失败（网络/余额不足/限流）
    ↓ 【日志必须明确输出降级原因、成本影响和修复步骤】
Level 2: pymupdf4llm + GROBID（本地回退）
    ↓ GROBID 不可用（Docker 未启动）
    ↓ 【日志必须明确输出降级原因和影响】
Level 3: pymupdf4llm + 正则解析（当前默认行为，完全本地）
```

### 6.2 降级日志规范（强制要求）

**每次降级必须在日志中输出以下信息**，使用 `logger.warning()` 级别：

1. **降级标识**：以 `⚠️ [DEGRADED]` 前缀开头
2. **降级原因**：具体说明哪个组件不可用（API Key 缺失/网络错误/余额不足）
3. **成本影响**：明确告知用户此次降级避免了 API 费用，但牺牲了精度
4. **修复建议**：如何获取 API Key 或启动服务

**示例日志模板**：

```python
# Marker API 不可用时（API Key 未设置）
logger.warning(
    "⚠️ [DEGRADED] DATALAB_API_KEY 环境变量未设置，Marker API 不可用。"
    "降级使用 pymupdf4llm 解析正文。"
    "【影响】页眉/页脚可能被误识为章节标题，S1-S5 指标可能失真。"
    "【成本】本次处理不产生 API 费用，但解析精度下降。"
    "【修复】1) 注册 Datalab 账号: https://www.datalab.to/plans "
    "2) 设置环境变量: export DATALAB_API_KEY=<your_key>"
)

# Marker API 调用失败时（网络/服务端错误/页数过大）
logger.warning(
    "⚠️ [DEGRADED] Marker API 调用失败（%s: %s），降级使用 pymupdf4llm。"
    "【影响】页眉可能被误识为标题，章节结构可能失真。"
    "【成本】本次降级避免了可能产生的 API 费用。"
    "【修复】检查网络连接、API Key 有效性或页数限制，或查看 https://status.datalab.to",
    error_type, error_msg
)

# GROBID 不可用时
logger.warning(
    "⚠️ [DEGRADED] GROBID 服务不可用（%s 未响应）。"
    "降级使用正则方法解析引用列表。"
    "【影响】引用元数据（title/author/venue/year）解析精度将显著下降，C5 和引用图质量受损。"
    "【修复】启动 GROBID: docker run --rm -d -p 8070:8070 grobid/grobid:0.8.2",
    grobid_url,
)
```

**在管线启动时（`01_parse_pdf` 节点开始处）也应输出一条 INFO 日志说明当前使用的解析后端组合**：

```python
logger.info(
    "PDF 解析后端: 正文=%s, 引用=%s",
    "MarkerAPI(mode=accurate)" | "pymupdf4llm",
    "GROBID(consolidate=True)" | "GROBID(consolidate=False)" | "regex-fallback",
)
```

### 6.3 错误处理原则

- **API Key 缺失**：直接降级到 pymupdf4llm，不中断管线
- **API 限流（HTTP 429）**：指数退避重试（最多 3 次），仍失败则降级
- **余额不足（HTTP 402）**：明确提示用户充值，降级到 pymupdf4llm
- **页数过大（如 HTTP 413 或其他特定错误码）**：记录具体错误，降级到 pymupdf4llm，提示用户
- **轮询超时**（超过 `max_poll_attempts`，约 2 分钟）：降级到 pymupdf4llm
- **GROBID 不可用**：记录 WARNING，降级到正则解析
- **所有降级场景都不中断管线**，确保管线始终可以跑完

### 6.4 缓存策略（关键成本优化）

- **必须实现磁盘缓存**：避免重复解析产生重复费用
- 缓存 key：PDF 文件的 SHA256 + 文件大小 + Marker API 参数（mode, output_format）
- 缓存命中时跳过 API 调用，直接返回缓存结果
- 与现有 `PDFParser._cache_key()` 和 `_default_output_path()` 设计保持一致

---

## 7. 配置变更汇总

### 7.1 `config/main.yaml` 新增/修改项

```yaml
# 修改：PDF 解析后端配置（替换 MinerU 为 Marker API）
pdf_parser:
  backend: "marker_api"          # "marker_api" | "pymupdf4llm" | "auto"
  marker_api:
    api_key: "${DATALAB_API_KEY}" # 从环境变量读取，**必需**
    mode: "accurate"              # "fast" | "balanced" | "accurate"
    output_format: "json"         # 必须设为 "json" 以获取结构
    include_markdown_in_chunks: true # **关键**：同时在 json 中返回 markdown
    additional_config:
      keep_pageheader_in_output: false    # **关键**：去除页眉
      keep_pagefooter_in_output: false    # **关键**：去除页脚
    max_poll_attempts: 60         # 最大轮询次数（约 2 分钟）
    poll_interval_seconds: 2      # 轮询间隔秒数
    request_timeout_seconds: 300  # 单请求超时
  cache_dir: "./output/pdf_cache"

# 修改：引用解析配置（保持不变）
citation:
  backend: "grobid"              # 默认改为 grobid
  grobid_url: "http://localhost:8070"
  grobid_timeout_s: 60           # 增大，因 consolidation 需更多时间
  grobid_consolidate: true       # 启用 CrossRef DOI 补全
```

### 7.2 环境变量

| 变量名 | 说明 | 必需性 |
|--------|------|--------|
| `DATALAB_API_KEY` | Datalab API 密钥（从 https://www.datalab.to 获取） | **使用 Marker API 时必需** |
| `GROBID_URL` | GROBID 服务地址（已有） | GROBID 后端必需 |

### 7.3 依赖管理

新增 Python 依赖：
```toml
# pyproject.toml 或 requirements.txt
httpx = ">=0.27.0"              # 用于异步 HTTP 轮询（项目可能已有）
```

**注意**：Marker API 是云服务，**无需安装**本地包，也**不需要**本地 GPU。

---

## 8. 代码开发规范

### 8.1 通用规范

- **PEP 8** 代码风格
- **类型注解**：所有公开方法必须有类型注解
- **Logger 命名**：必须以 `surveymae.` 前缀开头，如 `logging.getLogger("surveymae.tools.marker_api_parser")`。**禁止** `logging.getLogger(__name__)`
- **LLM 配置获取**：通过 `ModelConfig.get_tool_config()` 获取，禁止硬编码 provider→URL 映射
- **环境变量加载**：项目使用 `python-dotenv` 自动加载 `.env`，新环境变量添加到 `.env.example`

### 8.2 新文件命名与位置

| 新文件 | 位置 | 说明 |
|--------|------|------|
| `marker_api_parser.py` | `src/tools/` | Marker API 封装（含异步轮询逻辑） |
| `test_marker_api_parser.py` | `tests/unit/` | Marker API Parser 单元测试 |
| `test_grobid_header.py` | `tests/unit/` | GROBID header 提取测试 |
| `test_pdf_parsing_upgrade.py` | `tests/integration/` | 端到端集成测试 |

### 8.3 异步编程

项目使用 `asyncio` + `langchain` 的异步模式。Marker API 是**异步轮询**模式，推荐使用 `httpx.AsyncClient`：

```python
async def _poll_for_result(self, check_url: str) -> Dict:
    """轮询 Marker API 直到转换完成或超时（约 2 分钟）。"""
    async with httpx.AsyncClient() as client:
        for attempt in range(self.max_poll_attempts):
            response = await client.get(
                check_url, 
                headers={"X-API-Key": self.api_key}
            )
            data = response.json()
            if data["status"] == "complete":
                return data
            elif data["status"] == "failed":
                raise MarkerApiError(data.get("error", "Unknown error"))
            await asyncio.sleep(self.poll_interval_seconds)
        raise MarkerApiTimeout("轮询超时（约 2 分钟），请检查文档大小或重试")
```

### 8.4 结果持久化

按照现有 `ResultStore` 模式：
- Marker API 原始响应（JSON 含 blocks 结构和 markdown）应保存到 `tools/` 目录下（如 `tools/marker_output.json`）
- GROBID header 元数据应保存到 `tools/` 目录下（如 `tools/header_metadata.json`）

> **提示（for Claude Code）**：请查阅 `src/tools/result_store.py` 中的 `ResultStore` 类，了解 `save_extraction()`、`save_validation()` 等方法的接口约定，新增的持久化方法应遵循相同模式。

---

## 9. 实施优先级与步骤

### Phase 0：验证与准备（必做）

1. **注册 Datalab 账号并获取 API Key**：访问 https://www.datalab.to/plans，获取 `DATALAB_API_KEY`
2. **（可选）准备 GROBID Docker**：`docker run --rm -d -p 8070:8070 grobid/grobid:0.8.2`（供 Phase 2 使用）
3. **验证 Marker API 对 test_survey1.pdf 的效果**：
   ```python
   import os
   from datalab_sdk import DatalabClient, ConvertOptions

   client = DatalabClient(api_key=os.getenv("DATALAB_API_KEY"))
   options = ConvertOptions(
       mode="accurate",
       output_format="json",
       include_markdown_in_chunks=True,
       additional_config={"keep_pageheader_in_output": False}
   )
   result = client.convert("test_survey1.pdf", options=options)
   print(f"Quality score: {result.parse_quality_score}")
   print(f"Cost: {result.cost_breakdown}")
   # 验证：result.json.markdown 中不包含 "Natl Sci Rev" 等页眉文本
   # 验证：result.json.children 中的 section_hierarchy 正确识别章节
   ```
4. **验证成本预估**：根据 `result.cost_breakdown` 计算大规模评测时的预估费用
5. **验证页数限制**：如可能，测试大页数文档观察 API 错误响应

### Phase 1：Marker API 集成（核心改进，解决问题 A）

**目标**：提升文档结构解析精度，使用 Marker API 云服务替换现有 PDFParser

**为何先做 Marker**：
- Marker 是 PDF 解析流程的**入口**（`01_parse_pdf`），其输出 `parsed_content` 和 `section_headings` 被后续所有步骤依赖
- 先解决文档结构问题，可立即改善 S1-S5 指标的准确性
- GROBID 依赖 PDF 文件本身，与 Marker 无依赖关系，可后续叠加

**任务清单**：
- [ ] 新建 `src/tools/marker_api_parser.py`，实现 `MarkerApiParser` 类
- [ ] 实现异步轮询逻辑（POST → 获取 check_url → 轮询 GET → 返回结果），轮询约 2 分钟
- [ ] 实现 `parse()` 方法（返回 Markdown 字符串，兼容 PDFParser 接口）
- [ ] 实现 `parse_with_structure()` 方法（返回 Markdown + JSON blocks，单次 API 调用通过 `include_markdown_in_chunks` 同时获取）
- [ ] 实现磁盘缓存机制（关键：避免重复 API 调用产生费用）
- [ ] `config/main.yaml` 添加 `marker_api` 配置段（含 `include_markdown_in_chunks: true`）
- [ ] 实现 `create_pdf_parser()` 工厂方法，替换所有 `PDFParser` 直接实例化
- [ ] **在工厂方法中实现降级逻辑，当 DATALAB_API_KEY 缺失或 API 调用失败时，降级到 PDFParser 并输出带 `⚠️ [DEGRADED]` 前缀的 WARNING 日志**
- [ ] **在 `01_parse_pdf` 节点开始处输出 INFO 日志说明当前解析后端组合**
- [ ] 改造 `01_parse_pdf` 节点使用新工厂方法，从 Marker JSON 的 `section_hierarchy` 提取章节结构
- [ ] 改造 `CitationChecker.parse_pdf()` 和 `_extract_markdown_headings()` 使用新工厂方法
- [ ] 编写单元测试：mock API 响应（提交→轮询→完成），测试缓存、降级逻辑、降级日志输出
- [ ] 编写集成测试：用 test_survey1.pdf 端到端验证章节识别改善（页眉过滤效果）和 `parse_quality_score`

### Phase 2：GROBID 升级（优化引用解析，解决问题 B）

**目标**：提升引用元数据解析精度和 Header 提取能力

**为何后做 GROBID**：
- GROBID 是**独立后端**，负责引用列表解析（问题 B）和 Header 提取
- 其输入仅为 PDF 文件路径，与 Marker 的输出无关，不存在依赖顺序
- 在 Marker 稳定后叠加，便于区分两者的效果贡献

**任务清单**：

- [x] `config/main.yaml` 中 `citation.backend` 默认改为 `"grobid"`
- [x] `config/main.yaml` 中 `grobid_consolidate` 默认改为 `true`，`grobid_timeout_s` 改为 `60`
- [x] 新增 `GrobidReferenceExtractor.extract_header_metadata()` 方法，提取 title/abstract/keywords
- [x] `evidence_collection.py` 中新增 `_extract_title_and_abstract_with_grobid()`，优先使用 GROBID header，降级到 Markdown 正则
- [ ] 编写集成测试：用 test_survey1.pdf 端到端验证引用解析改善（C5 指标提升）

> **注**：`venue` 字段需求已移除。下游 `BibEntry`（`citation_metadata.py`）不含 venue 字段，故提取 venue 无实际意义。

### Phase 3：精细化（可选优化）

- [ ] 根据 `parse_quality_score` 实现自动质量门控（分数 < 3.0 时告警或重试）
- [ ] 性能优化：并行调用 Marker API 和 GROBID（两者无依赖）
- [ ] 利用 Marker JSON 的 `block_type` 信息优化引文上下文提取（精确定位 Text 块）

---

## 10. 验收标准与测试方案

### 10.1 单元测试

**原则**：单元测试不依赖外部 API（Marker API、GROBID），使用 mock/fixture。

| 测试项 | 验证内容 |
|--------|---------|
| `test_marker_api_parser_submit` | 正确提交 POST 请求，处理 multipart/form-data 和 additional_config |
| `test_marker_api_parser_polling` | 轮询逻辑正确处理 `processing` → `complete` 状态转换 |
| `test_marker_api_parser_polling_timeout` | 轮询超时（约 2 分钟）后抛出异常 |
| `test_marker_api_parser_rate_limit` | HTTP 429 时指数退避重试 |
| `test_marker_api_parser_cache_hit` | 相同 PDF 第二次调用直接返回缓存结果，不触发 HTTP 请求 |
| `test_factory_degradation_no_api_key` | DATALAB_API_KEY 未设置时，工厂返回 PDFParser 实例并输出降级日志 |
| `test_factory_degradation_api_error` | API 返回 402/500/413（页数过大）时降级到 PDFParser |
| `test_factory_degradation_log_marker` | Marker API 降级时日志包含 `⚠️ [DEGRADED]` 前缀、成本影响和修复建议 |
| `test_factory_info_log_backend` | 管线启动时输出 INFO 日志说明当前后端组合 |

### 10.2 集成测试

**使用 test_survey1.pdf（项目已有测试文件）作为验证样本。**

| 测试项 | 验收标准 |
|--------|---------|
| 页眉过滤 | Marker API 输出的 Markdown 中不包含 `"Natl Sci Rev"` 等页眉文本作为标题（通过 `additional_config` 配置） |
| 章节识别 | 从 JSON 输出的 `section_hierarchy` 构建的 sections 列表与论文实际章节结构一致 |
| 质量评分 | `parse_quality_score >= 3.0`（对 test_survey1.pdf） |
| 单请求双格式 | 仅一次 API 调用，同时获得 JSON 结构和 Markdown（验证 `include_markdown_in_chunks`） |
| 引用解析 | GROBID 解析出的 references 中，title/authors/year/venue 字段完整率 > 90%（对 test_survey1.pdf 的 154 条引用） |
| Header 提取 | 正确提取论文标题和完整 abstract（通过 GROBID） |
| 端到端管线 | 替换后端后，完整管线 `01_parse_pdf → 02_evidence_collection → ... → 07_reporter` 无报错运行通过 |
| 成本验证 | 缓存机制确保同一文件重复解析时不产生重复 API 费用 |

### 10.3 回归测试

- 使用 `backend: "pymupdf4llm"` 配置运行完整管线，确保旧路径未被破坏
- 所有现有单元测试和集成测试继续通过
- **成本测试**：运行一次 test_survey1.pdf，确认 Datalab 账户扣除的 credits 与 `cost_breakdown` 一致；再次运行相同文件，确认因缓存命中而不产生新费用

---

## 11. 官方参考文档索引

| 资源 | 地址 | 用途 |
|------|------|------|
| **Marker API 文档** | `https://documentation.datalab.to/docs/recipes/conversion/conversion-api-overview` | API 参数、mode 选择、additional_config、include_markdown_in_chunks |
| **Marker API 参考** | `https://documentation.datalab.to/api-reference/convert-document` | REST API 详细规范、轮询机制 |
| Marker GitHub | `https://github.com/datalab-to/marker` | 开源实现参考（背景了解） |
| GROBID 文档 | `https://grobid.readthedocs.io/en/latest/` | REST API、TEI 输出格式 |
| GROBID GitHub | `https://github.com/kermitt2/grobid` | 源码、Docker 部署 |
| grobid-tei-xml (PyPI) | `https://pypi.org/project/grobid-tei-xml/` | TEI-XML Python 解析库 |
| SurveyMAE DEVELOPER_GUIDE | 项目内 `DEVELOPER_GUIDE.md` | 项目约定、代码规范 |

---

## 12. 给 Claude Code 的关键提醒

1. **先读代码再写代码**：本文档提供的是设计方案而非精确接口规格。实施前请先用 `grep` 和 `cat` 查阅实际代码中的接口签名、数据结构和调用关系。文档中所有标记为"提示（for Claude Code）"的段落都指出了需要实际查阅的代码位置。

2. **成本意识**：Marker API 是**按页付费**的云服务，**必须**实现磁盘缓存（第 6.4 节）以避免重复费用。每次 API 调用都应记录成本到日志（`cost_breakdown`）。

3. **异步轮询**：Marker API 是**提交-轮询**模式（先 POST 获取 `request_check_url`，再轮询 GET 直到 `status=complete`）。轮询约 2 分钟（60 次 × 2 秒），必须实现稳健的轮询逻辑（退避、超时）。

4. **单次调用双格式**：通过 `include_markdown_in_chunks=true` 参数，**单次 API 调用**即可同时获得 JSON 结构（用于章节识别）和 Markdown（用于 LLM 输入）。这是成本最优方案，**不要**调用两次 API。

5. **页眉去除**：Marker API 通过 `additional_config={"keep_pageheader_in_output": false}` 配置去除页眉页脚，这是解决"问题 A"的关键配置，**必须**在默认配置中设置。

6. **页数限制处理**：Marker API 未公开最大页数限制，**不在上传前做预设检查**。如 API 返回页数过大错误（如 HTTP 413），捕获错误、记录日志、降级到 pymupdf4llm 并提示用户。

7. **不要破坏现有功能**：新增 `MarkerApiParser` 是**添加**替代方案，不是删除 `PDFParser`。`backend: "pymupdf4llm"` 配置下，系统行为应与改造前完全一致。

8. **降级日志是强制要求**：当 `DATALAB_API_KEY` 未设置或 API 调用失败时，**必须**降级到 `PDFParser` 并输出带 `⚠️ [DEGRADED]` 前缀的 WARNING 日志，说明降级原因、成本影响和修复步骤。

9. **GROBID 保持不变**：本方案仅替换 MinerU 为 Marker API，GROBID 作为引用解析后端的集成方案完全保持不变。

10. **环境变量**：新增必需环境变量 `DATALAB_API_KEY`，请在 `.env.example` 中添加示例。

---

## 13. Phase 1 实施记录（2026-04-09）

### 完成状态

| 任务 | 状态 | 备注 |
|------|------|------|
| 安装 `datalab-python-sdk` | ✅ 完成 | 已加入 `pyproject.toml` |
| `.env` 添加 `DATALAB_API_KEY` 字段 | ✅ 完成 | 用户已填写 key |
| `config.py` 添加 `MarkerApiConfig` / `PdfParserConfig` | ✅ 完成 | 见下文 |
| `config/main.yaml` 添加 `pdf_parser` 配置段 | ✅ 完成 | `backend: "marker_api"` |
| 新建 `src/tools/marker_api_parser.py` | ✅ 完成 | `MarkerApiParser` + `extract_section_headings_from_json` |
| `src/tools/pdf_parser.py` 添加 `create_pdf_parser()` 工厂 | ✅ 完成 | 含降级日志 |
| `src/graph/builder.py` 接入工厂 + `section_headings` | ✅ 完成 | `_get_pdf_parser()` + `_parse_pdf_node()` |
| `src/tools/citation_checker.py` 接入工厂 | ✅ 完成 | `parse_pdf()` + `_extract_markdown_headings()` |
| 集成测试 `tests/integration/test_marker_api_parser.py` | ✅ 已写 | API 返回 403，待用户验证账号后重跑 |

### 已修改文件清单

```text
pyproject.toml                                  # 新增 datalab-python-sdk>=0.1.0
.env                                            # 新增 DATALAB_API_KEY 字段（含注释）
config/main.yaml                                # 新增 pdf_parser 配置段
src/core/config.py                              # 新增 MarkerApiConfig, PdfParserConfig; SurveyMAEConfig.pdf_parser 字段
src/tools/marker_api_parser.py                  # 新建：MarkerApiParser, extract_section_headings_from_json
src/tools/pdf_parser.py                         # 新增 create_pdf_parser() 工厂函数
src/graph/builder.py                            # _get_pdf_parser() 使用工厂; _parse_pdf_node() 支持 section_headings
src/tools/citation_checker.py                   # parse_pdf(), _extract_markdown_headings() 使用工厂
tests/integration/test_marker_api_parser.py     # 新建：6 项集成测试
docs/superpowers/plans/2026-04-09-marker-api-phase1.md  # 实施计划
```

### 关键设计决策记录

1. **SDK 而非原始 HTTP**：使用 `datalab-python-sdk`（官方 Python SDK），SDK 内部处理异步轮询、重试、指数退避，无需手动实现。

2. **`asyncio.to_thread` 代替 `AsyncDatalabClient`**：`aparse()` 使用 `asyncio.to_thread(self.parse, ...)` 包装同步调用，保证与项目异步框架兼容，同时规避异步客户端 API 不确定性。

3. **`output_format="json"` + `include_markdown_in_chunks=True`**：单次 API 调用同时获取结构化 JSON（`result.json`）和 Markdown 文本（`result.json["markdown"]`），成本最优。

4. **磁盘缓存 key**：`SHA256(path.resolve() + stat.st_size + stat.st_mtime_ns + mode + "json")`，与 `PDFParser._cache_key()` 逻辑一致但格式不同（存 JSON 而非 .md）。

5. **`section_headings` 数据流**：`_parse_pdf_node()` 调用 `parse_with_structure()` 获取 JSON，再调用 `extract_section_headings_from_json()` 提取 `block_type=SectionHeader` 节点，写入 `SurveyState.section_headings`（之前此字段始终为空）。

### 待完成事项

- [ ] **集成测试**：用户确认 Datalab 账号后，运行 `pytest tests/integration/test_marker_api_parser.py -v -s` 验证 API 行为
- [x] **Phase 2**：GROBID 升级（见下节）
- [ ] **Phase 3（可选）**：质量门控、Marker + GROBID 并行调用

---

## 14. Phase 2 实施记录（2026-04-09）

### Phase 2 完成状态

| 任务 | 状态 | 备注 |
| --- | --- | --- |
| `config/main.yaml` citation backend 改为 grobid | ✅ 完成 | `backend: grobid`, `grobid_consolidate: true`, `grobid_timeout_s: 60` |
| `GrobidReferenceExtractor.extract_header_metadata()` | ✅ 完成 | 调用 `/api/processHeaderDocument`，返回 title/abstract/keywords |
| `GrobidReferenceExtractor._parse_header()` | ✅ 完成 | 解析 TEI-XML，提取 titleStmt/title + profileDesc/abstract + keywords/term |
| `evidence_collection.py` 改造 title/abstract 提取 | ✅ 完成 | 新增 `_extract_title_and_abstract_with_grobid()`，GROBID 优先，regex 降级 |
| 降级日志规范化 | ✅ 完成 | `[DEGRADED]` 前缀，含影响说明和 Fix 建议，无 unicode 图标 |
| venue 字段需求 | ❌ 移除 | `BibEntry` 不含 venue，提取无意义 |

### Phase 2 已修改文件清单

```text
config/main.yaml                        # citation.backend=grobid, consolidate=true, timeout=60
src/tools/citation_checker.py           # 新增 extract_header_metadata(), _parse_header(); 规范化降级日志
src/graph/nodes/evidence_collection.py  # 新增 _extract_title_and_abstract_with_grobid(); Step 2 GROBID 优先
```

### Phase 2 设计决策记录

1. **独立 helper 而非改造原函数**：新增 `_extract_title_and_abstract_with_grobid()` 而不修改 `_extract_title_and_abstract()`，保留 regex 路径作为纯降级备用，两者职责清晰。

2. **GROBID 不可用时静默降级**：`extract_header_metadata()` 抛出的所有异常在 helper 层捕获并输出 `[DEGRADED]` 警告，主流程不受影响。

3. **`source_pdf` 为空时跳过 GROBID**：在 `run_evidence_collection` 中先检查 `source_pdf` 存在才调用 GROBID，避免对无 PDF 的边缘情况发起无效请求。
