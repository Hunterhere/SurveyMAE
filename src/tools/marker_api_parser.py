"""Marker API PDF Parser.

Provides high-quality PDF-to-Markdown conversion via Datalab Marker API.
Compatible interface with PDFParser. Uses disk cache to avoid repeat API costs.

Implementation notes:
- output_format="json" + include_markdown_in_chunks=True returns per-block "markdown" fields.
  The full markdown text must be reconstructed via _extract_markdown_from_json().
  (result.markdown is None in JSON mode; result.json["markdown"] top-level key does not exist.)
- Section headings come from block_type=="SectionHeader" blocks.
  Text is extracted from the block's "markdown" field (stripped of # and --- decorators).
"""

import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("surveymae.tools.marker_api_parser")


class MarkerApiParser:
    """Marker API-based PDF parser for high-quality document structure extraction.

    与 PDFParser 接口兼容，作为 pymupdf4llm 的替代方案。
    通过 Datalab Marker API 获得更准确的：
    - 页眉/页脚/页码过滤（通过 additional_config 显式配置）
    - 章节标题识别（通过 json 输出的 block_type=SectionHeader）
    - 多栏布局阅读顺序

    单次 API 调用通过 output_format="json" + include_markdown_in_chunks=True
    同时获取 JSON 结构和 Markdown 文本（成本最优）。
    Markdown 文本通过 _extract_markdown_from_json() 从各 block 的 "markdown" 字段拼接重建。
    磁盘缓存避免重复 API 调用产生费用（缓存 key = SHA256(path+size+mtime+mode)）。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://www.datalab.to",
        mode: str = "accurate",
        include_markdown_in_chunks: bool = True,
        additional_config: Optional[Dict] = None,
        max_poll_attempts: int = 60,
        poll_interval_seconds: int = 2,
        request_timeout_seconds: int = 300,
        cache_dir: str = "./output/pdf_cache",
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.mode = mode
        self.include_markdown_in_chunks = include_markdown_in_chunks
        self.additional_config = additional_config or {
            "keep_pageheader_in_output": False,
            "keep_pagefooter_in_output": False,
        }
        self.max_poll_attempts = max_poll_attempts
        self.poll_interval_seconds = poll_interval_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.cache_dir = cache_dir

    def parse(self, pdf_path: str) -> str:
        """解析 PDF 为 Markdown。接口与 PDFParser.parse() 兼容。"""
        markdown, _ = self.parse_with_structure(pdf_path)
        return markdown

    def parse_cached(self, pdf_path: str) -> str:
        """与 PDFParser.parse_cached() 兼容。缓存内建于 parse_with_structure()。"""
        return self.parse(pdf_path)

    def parse_with_structure(self, pdf_path: str) -> Tuple[str, Dict]:
        """返回 (markdown, json_structure)。单次 API 调用同时获取两种格式。

        json_structure 包含 Marker API 的 block 层级（block_type, section_hierarchy 等）。
        Markdown 通过 _extract_markdown_from_json() 从各 block 的 "markdown" 字段重建。
        命中磁盘缓存时不产生 API 费用。
        """
        from datalab_sdk import DatalabClient, ConvertOptions

        path = self._validate_path(pdf_path)
        cache_path = self._get_cache_path(path)

        if cache_path.exists():
            logger.info("Marker API disk cache hit: %s", pdf_path)
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return cached["markdown"], cached["json_structure"]

        logger.info("Calling Marker API (mode=%s): %s", self.mode, pdf_path)
        client = DatalabClient(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.request_timeout_seconds,
        )
        options = ConvertOptions(
            output_format="json",
            mode=self.mode,
            include_markdown_in_chunks=self.include_markdown_in_chunks,
            additional_config=self.additional_config,
        )

        result = client.convert(str(path), options=options)

        json_data = result.json if (hasattr(result, "json") and result.json) else {}

        # Reconstruct markdown from per-block "markdown" fields.
        # When output_format="json", result.markdown is None; the markdown is embedded
        # in each block's "markdown" field (set by include_markdown_in_chunks=True).
        markdown = _extract_markdown_from_json(json_data) if isinstance(json_data, dict) else ""

        quality = getattr(result, "parse_quality_score", None)
        page_count = getattr(result, "page_count", 0)
        if quality is not None and quality < 3.0:
            logger.warning(
                "⚠️ [QUALITY] Marker API parse_quality_score=%.1f < 3.0 for %s. "
                "考虑用 accurate 模式重试或人工检查文档质量。",
                quality,
                pdf_path,
            )
        else:
            logger.info(
                "Marker API success: quality=%s pages=%d chars=%d",
                quality,
                page_count,
                len(markdown),
            )

        cache_data = {
            "markdown": markdown,
            "json_structure": json_data,
            "page_count": page_count,
            "parse_quality_score": quality,
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache_data, ensure_ascii=False), encoding="utf-8")

        return markdown, json_data

    async def aparse(self, pdf_path: str) -> str:
        """异步版本，在线程池中运行 parse()，兼容 PDFParser.aparse()。"""
        return await asyncio.to_thread(self.parse, pdf_path)

    def _validate_path(self, pdf_path: str) -> Path:
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Expected PDF file, got: {path.suffix}")
        return path

    def _get_cache_path(self, path: Path) -> Path:
        stat = path.stat()
        fingerprint = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{self.mode}|json"
        digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:12]
        return Path(self.cache_dir) / f"{path.stem}_{digest}_marker.json"


def _extract_markdown_from_json(json_structure: Dict) -> str:
    """从 Marker API JSON 结构重建完整 Markdown 文本。

    当 output_format="json" + include_markdown_in_chunks=True 时，
    markdown 存储在每个非 Page block 的 "markdown" 字段，顶级 result.json 无 "markdown" 键。
    此函数遍历所有 block，按文档顺序拼接各 block 的 "markdown" 字段。

    Args:
        json_structure: result.json 字典（含 "children" 层级）。

    Returns:
        完整 Markdown 字符串。
    """
    parts: List[str] = []

    def _traverse(node: object) -> None:
        if isinstance(node, dict):
            block_type = node.get("block_type", "")
            # Page blocks are wrappers; their markdown comes from child blocks
            if block_type != "Page" and "markdown" in node:
                md = node.get("markdown") or ""
                if md.strip():
                    parts.append(md)
            for child in node.get("children", []):
                _traverse(child)
        elif isinstance(node, list):
            for item in node:
                _traverse(item)

    _traverse(json_structure)
    return "\n\n".join(parts)


def extract_section_headings_from_json(json_structure: Dict) -> List[str]:
    """从 Marker API JSON 结构中提取章节标题列表。

    遍历 block 层级，收集所有 block_type == "SectionHeader" 节点的文本。
    文本从 block 的 "markdown" 字段提取（去除 # 前缀和 --- 装饰符）。

    Args:
        json_structure: Marker API 返回的 JSON 结构（result.json 字段）。

    Returns:
        按文档顺序排列、去重的章节标题列表。
    """
    headings: List[str] = []
    seen: set = set()

    def _traverse(node: object) -> None:
        if isinstance(node, dict):
            if node.get("block_type") == "SectionHeader":
                # Extract text from "markdown" field (e.g. "# --- Introduction ---")
                md = node.get("markdown", "").strip()
                # Strip leading # markers (one or more)
                text = re.sub(r"^#+\s*", "", md)
                # Strip leading/trailing --- decorators
                text = text.strip("-").strip()
                if text and text not in seen:
                    headings.append(text)
                    seen.add(text)
            for child in node.get("children", []):
                _traverse(child)
        elif isinstance(node, list):
            for item in node:
                _traverse(item)

    _traverse(json_structure)
    return headings
