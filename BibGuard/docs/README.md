# BibGuard 模块文档

> BibGuard 仓库可复用模块的使用文档

## 快速导航

| 模块 | 文件 | 说明 |
|------|------|------|
| BibParser | [BIBPARSER.md](BIBPARSER.md) | BibTeX 文件解析器 |
| TexParser | [TEXPARSER.md](TEXPARSER.md) | LaTeX 引用提取器 |
| Fetcher | [FETCHERS.md](FETCHERS.md) | 多数据源 API 调用 |
| MetadataComparator | [METADATA_COMPARATOR.md](METADATA_COMPARATOR.md) | 元数据比较器 |
| TextNormalizer | [TEXT_NORMALIZER.md](TEXT_NORMALIZER.md) | 文本标准化工具 |

## 快速开始

### 1. 安装依赖

```bash
pip install bibtexparser requests unidecode beautifulsoup4
```

### 2. 选择模块

- **只需解析 BibTeX** → [BibParser](BIBPARSER.md)
- **只需解析 LaTeX 引用** → [TexParser](TEXPARSER.md)
- **只需文本标准化** → [TextNormalizer](TEXT_NORMALIZER.md)
- **需要完整幻觉检测** → [REUSE_GUIDE.md](REUSE_GUIDE.md)

### 3. 代码示例

```python
# 解析 BibTeX
from src.parsers.bib_parser import BibParser

parser = BibParser()
entries = parser.parse_file("refs.bib")

# 获取元数据
from src.fetchers import ArxivFetcher

fetcher = ArxivFetcher()
meta = fetcher.fetch_by_id("2301.00001")

# 比较相似度
from src.analyzers.metadata_comparator import MetadataComparator

comparator = MetadataComparator()
result = comparator.compare_with_arxiv(entry, meta)
```

## 模块依赖关系

```
                    ┌──────────────────────────────────────┐
                    │         TextNormalizer               │
                    │   (无外部依赖，仅 unidecode)         │
                    └──────────────────────────────────────┘
                                      ▲
                                      │
                    ┌─────────────────┴─────────────────┐
                    │                                   │
              ┌─────┴─────┐                    ┌───────┴───────┐
              │ BibParser │                    │   Fetcher     │
              │ bibtexparser│                  │   modules     │
              └─────┬─────┘                    │   requests    │
                    │                          └───────┬───────┘
                    │                                  │
                    └──────────────┬───────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────────────┐
                    │      MetadataComparator              │
                    │  (元数据比较，幻觉检测核心)           │
                    └──────────────────────────────────────┘
```

## 推荐使用场景

| 场景 | 推荐模块 | 文档 |
|------|---------|------|
| 解析参考文献数据库 | BibParser | [BIBPARSER.md](BIBPARSER.md) |
| 检查引用是否被使用 | TexParser | [TEXPARSER.md](TEXPARSER.md) |
| 获取论文元数据 | Fetcher 模块 | [FETCHERS.md](FETCHERS.md) |
| 验证引用准确性 | MetadataComparator | [METADATA_COMPARATOR.md](METADATA_COMPARATOR.md) |
| 文本相似度计算 | TextNormalizer | [TEXT_NORMALIZER.md](TEXT_NORMALIZER.md) |
| 完整幻觉检测 | 组合使用 | [REUSE_GUIDE.md](REUSE_GUIDE.md) |

## 开源协议

如使用本仓库代码，请注明来源：

> 本项目复用了 [BibGuard](https://github.com/thinkwee/BibGuard) 的代码。

详细协议说明见 [REUSE_GUIDE.md](REUSE_GUIDE.md)。

## 相关链接

- **GitHub**: https://github.com/thinkwee/BibGuard
- **主文档**: [README.md](../README.md)
