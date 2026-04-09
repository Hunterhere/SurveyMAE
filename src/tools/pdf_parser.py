"""PDF Parser Tool.

Provides PDF to Markdown conversion using pymupdf4llm with PyMuPDF Layout support.
Can be exposed as an MCP server for distributed tool access.

Note: Import pymupdf.layout before pymupdf4llm to activate Layout support:
    import pymupdf.layout  # Activates GNN-based layout analysis
    import pymupdf4llm
"""

import asyncio
import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("surveymae.tools.pdf_parser")


class PDFParser:
    """PDF parsing utility for converting PDF documents to text/markdown.

    This class wraps pymupdf4llm for PDF extraction and provides
    a clean interface for the SurveyMAE framework.
    
    Supports PyMuPDF Layout (v0.2.0+) for improved:
    - Multi-column layout handling
    - Header/footer detection and filtering
    - Table structure preservation
    - Section heading extraction

    Attributes:
        extract_images: Whether to extract embedded images.
        page_range: Optional range of pages to extract (e.g., "1-10").
        use_layout: Whether to use PyMuPDF Layout engine.
        show_header: Whether to include page headers in output.
        show_footer: Whether to include page footers in output.
    """

    _CACHE: dict[tuple, str] = {}
    _CACHE_LIMIT = 128
    _DEFAULT_CACHE_DIR = os.getenv("SURVEYMAE_PDF_CACHE_DIR", "./output/pdf_cache")

    def __init__(
        self,
        extract_images: bool = False,
        page_range: Optional[str] = None,
        use_layout: bool = True,
        show_header: bool = False,
        show_footer: bool = False,
    ):
        """Initialize the PDF parser.

        Args:
            extract_images: Whether to extract images from PDF.
            page_range: Optional page range (e.g., "1-10" or "1,3,5").
            use_layout: Whether to use PyMuPDF Layout engine (default: True).
            show_header: Whether to include page headers (default: False).
            show_footer: Whether to include page footers (default: False).
        """
        self.extract_images = extract_images
        self.page_range = page_range
        self.use_layout = use_layout
        self.show_header = show_header
        self.show_footer = show_footer

    def parse(self, pdf_path: str) -> str:
        """Parse a PDF file and return its content as markdown.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            The extracted content as a markdown string.

        Raises:
            FileNotFoundError: If the PDF file doesn't exist.
            ValueError: If the file is not a valid PDF.
        """
        path = self._validate_path(pdf_path)

        try:
            # Use pymupdf4llm for conversion
            import pymupdf4llm

            # Convert to markdown
            md_text = self._to_markdown_with_pymupdf4llm(pymupdf4llm, path)

            logger.info(f"Successfully parsed PDF: {pdf_path} ({len(md_text)} chars)")
            return md_text

        except ImportError:
            logger.warning("pymupdf4llm not available, using fallback parser")
            return self._fallback_parse(pdf_path)

        except Exception as e:
            logger.error(f"Failed to parse PDF: {e}")
            raise

    def _to_markdown_with_pymupdf4llm(self, pymupdf4llm, path: Path, **extra_kwargs) -> str:
        """Handle pymupdf4llm API differences across versions."""
        kwargs = {
            "extract_images": self.extract_images,
            **extra_kwargs,
        }
        
        # PyMuPDF4LLM v0.2.0+: to_markdown expects doc as first positional argument
        import fitz
        with fitz.open(str(path)) as doc:
            return pymupdf4llm.to_markdown(
                doc,
                **kwargs,
            )

    def parse_cached(self, pdf_path: str) -> str:
        """Parse a PDF file with in-process caching.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            The extracted content as a markdown string.
        """
        path = self._validate_path(pdf_path)
        cache_key = self._cache_key(path)

        cached = self._CACHE.get(cache_key)
        if cached is not None:
            return cached

        content = self.parse(pdf_path)
        self._CACHE[cache_key] = content

        if len(self._CACHE) > self._CACHE_LIMIT:
            self._CACHE.clear()

        return content

    def parse_to_file(
        self,
        pdf_path: str,
        output_path: Optional[str] = None,
        cache_dir: Optional[str] = None,
        overwrite: bool = False,
    ) -> str:
        """Parse a PDF file and persist the result to disk.

        Args:
            pdf_path: Path to the PDF file.
            output_path: Optional explicit output path.
            cache_dir: Optional cache directory for derived outputs.
            overwrite: Whether to overwrite if the output exists.

        Returns:
            Path to the stored parsed content file.
        """
        path = self._validate_path(pdf_path)
        output_file = (
            Path(output_path) if output_path else self._default_output_path(path, cache_dir)
        )
        output_file.parent.mkdir(parents=True, exist_ok=True)

        if output_file.exists() and not overwrite:
            return str(output_file)

        content = self.parse_cached(pdf_path)
        output_file.write_text(content, encoding="utf-8")
        return str(output_file)

    def _validate_path(self, pdf_path: str) -> Path:
        path = Path(pdf_path)

        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Expected PDF file, got: {path.suffix}")

        return path

    def _cache_key(self, path: Path) -> tuple:
        stat = path.stat()
        return (
            str(path.resolve()),
            self.extract_images,
            self.page_range or "",
            stat.st_mtime_ns,
            stat.st_size,
        )

    def _default_output_path(self, path: Path, cache_dir: Optional[str]) -> Path:
        stat = path.stat()
        cache_base = Path(cache_dir) if cache_dir else Path(self._DEFAULT_CACHE_DIR)
        cache_base = cache_base.expanduser().resolve()

        fingerprint = f"{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"
        fingerprint += f"|{self.extract_images}|{self.page_range or ''}"
        digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:12]

        filename = f"{path.stem}_{digest}.md"
        return cache_base / filename

    def _fallback_parse(self, pdf_path: str) -> str:
        """Fallback parser using pypdf if pymupdf4llm is unavailable.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            Extracted text content.
        """
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        text_parts = []

        for i, page in enumerate(reader.pages):
            # Check page range if specified
            if self.page_range:
                if not self._is_page_in_range(i):
                    continue

            text = page.extract_text()
            if text:
                text_parts.append(f"## Page {i + 1}\n\n{text}")

        return "\n\n".join(text_parts)

    def _is_page_in_range(self, page_index: int) -> bool:
        """Check if a page index is within the specified range.

        Args:
            page_index: Zero-based page index.

        Returns:
            True if the page should be extracted.
        """
        if not self.page_range:
            return True

        # Parse range like "1-10" or "1,3,5"
        ranges = self.page_range.replace(" ", "").split(",")
        page_num = page_index + 1  # Convert to 1-based

        for r in ranges:
            if "-" in r:
                start, end = r.split("-")
                if start <= str(page_num) <= end:
                    return True
            else:
                if str(page_num) == r:
                    return True

        return False

    def parse_with_structure(self, pdf_path: str) -> Tuple[str, Dict]:
        """Parse PDF and return (markdown, structure_dict).
        
        接口与 MarkerApiParser.parse_with_structure() 对齐。
        返回的结构字典包含页面信息和提取的章节标题。
        
        Args:
            pdf_path: Path to the PDF file.
            
        Returns:
            Tuple of (markdown_content, structure_dict)
        """
        path = self._validate_path(pdf_path)
        
        try:
            # Import pymupdf.layout first to activate Layout support (v0.2.0+)
            if self.use_layout:
                try:
                    import pymupdf.layout
                    logger.debug("PyMuPDF Layout engine activated")
                except ImportError:
                    logger.warning("pymupdf-layout not installed, falling back to basic extraction")
            
            import pymupdf4llm
            
            # Try to get JSON structure for section extraction
            json_structure = None
            if hasattr(pymupdf4llm, 'to_json'):
                try:
                    json_str = pymupdf4llm.to_json(
                        input_path=str(path),
                        extract_images=self.extract_images,
                        header=self.show_header,
                        footer=self.show_footer,
                    )
                    json_structure = json.loads(json_str) if isinstance(json_str, str) else json_str
                except Exception as e:
                    logger.debug(f"JSON extraction not available: {e}")
            
            # Get markdown content
            md_text = self._to_markdown_with_pymupdf4llm(
                pymupdf4llm, path,
                header=self.show_header,
                footer=self.show_footer,
            )
            
            # Build structure dict compatible with MarkerApiParser output
            structure = {
                "parser": "PDFParser",
                "use_layout": self.use_layout,
                "pages": [],
                "headings": [],
            }
            
            if json_structure:
                structure["pages"] = json_structure.get("pages", [])
                structure["headings"] = self._extract_headings_from_json(json_structure)
            else:
                # Fallback: extract headings from markdown
                structure["headings"] = self._extract_headings_from_markdown(md_text)
            
            logger.info(
                "PDFParser success: layout=%s headings=%d chars=%d",
                self.use_layout,
                len(structure["headings"]),
                len(md_text),
            )
            
            return md_text, structure
            
        except ImportError:
            logger.warning("pymupdf4llm not available, using fallback parser")
            text = self._fallback_parse(pdf_path)
            structure = {
                "parser": "PDFParser(fallback)",
                "pages": [],
                "headings": self._extract_headings_from_markdown(text),
            }
            return text, structure
        except Exception as e:
            logger.error(f"Failed to parse PDF: {e}")
            raise

    def _extract_headings_from_json(self, json_structure: Dict) -> List[str]:
        """Extract section headings from PyMuPDF4LLM JSON structure.
        
        Args:
            json_structure: JSON structure from pymupdf4llm.to_json()
            
        Returns:
            List of heading strings.
        """
        headings = []
        seen = set()
        
        pages = json_structure.get("pages", [])
        for page in pages:
            for block in page.get("blocks", []):
                # Check for heading blocks based on type or style
                block_type = block.get("type", "")
                if block_type in ("heading", "header", "h1", "h2", "h3", "h4", "h5", "h6"):
                    text = block.get("text", "").strip()
                    if text and text not in seen:
                        headings.append(text)
                        seen.add(text)
                # Also check lines within blocks for styled text
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        if span.get("flags", 0) & 2 ** 4:  # Bold flag
                            text = span.get("text", "").strip()
                            # Only include if looks like a heading (short, title case)
                            if text and 3 < len(text) < 100 and text not in seen:
                                if text[0].isupper() or text.startswith("#"):
                                    headings.append(text)
                                    seen.add(text)
        
        return headings

    def _extract_headings_from_markdown(self, markdown: str) -> List[str]:
        """Extract section headings from Markdown text.
        
        Args:
            markdown: Markdown text content.
            
        Returns:
            List of heading strings.
        """
        headings = []
        seen = set()
        
        # Match Markdown headings (# Heading ## Heading)
        heading_pattern = re.compile(r'^#{1,6}\s+(.+)$', re.MULTILINE)
        for match in heading_pattern.finditer(markdown):
            text = match.group(1).strip()
            # Remove any trailing markers
            text = re.sub(r'\s*#+$', '', text).strip()
            if text and text not in seen:
                headings.append(text)
                seen.add(text)
        
        return headings

    async def aparse(self, pdf_path: str) -> str:
        """Async wrapper for parse method.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            The extracted content as a markdown string.
        """
        # pymupdf4llm is synchronous, run in thread pool to avoid blocking
        return await asyncio.to_thread(self.parse, pdf_path)

    async def aparse_with_structure(self, pdf_path: str) -> Tuple[str, Dict]:
        """Async wrapper for parse_with_structure method.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            Tuple of (markdown_content, structure_dict)
        """
        return await asyncio.to_thread(self.parse_with_structure, pdf_path)


def create_pdf_parser(config=None) -> "PDFParser":
    """根据配置和环境变量创建 PDF 解析器实例（工厂函数）。

    优先使用 Marker API（需要 DATALAB_API_KEY），降级时使用 pymupdf4llm。
    降级时在日志中明确输出原因、影响和修复步骤。

    Args:
        config: Optional SurveyMAEConfig instance. If None, loads from default path.

    Returns:
        MarkerApiParser if Marker API is available and configured.
        PDFParser (pymupdf4llm) otherwise.
    """
    backend = "auto"
    cache_dir = "./output/pdf_cache"
    marker_base_url = "https://www.datalab.to"
    marker_mode = "accurate"
    
    # PyMuPDF4LLM default settings
    pymupdf_use_layout = True
    pymupdf_show_header = False
    pymupdf_show_footer = False

    if config is not None:
        pdf_parser_cfg = getattr(config, "pdf_parser", None)
        if pdf_parser_cfg is not None:
            backend = getattr(pdf_parser_cfg, "backend", "auto")
            cache_dir = getattr(pdf_parser_cfg, "cache_dir", cache_dir)
            marker_cfg = getattr(pdf_parser_cfg, "marker_api", None)
            if marker_cfg is not None:
                marker_base_url = getattr(marker_cfg, "base_url", marker_base_url)
                marker_mode = getattr(marker_cfg, "mode", marker_mode)
            # Load PyMuPDF4LLM settings
            pymupdf_cfg = getattr(pdf_parser_cfg, "pymupdf4llm", None)
            if pymupdf_cfg is not None:
                pymupdf_use_layout = getattr(pymupdf_cfg, "use_layout", True)
                pymupdf_show_header = getattr(pymupdf_cfg, "show_header", False)
                pymupdf_show_footer = getattr(pymupdf_cfg, "show_footer", False)

    if backend == "pymupdf4llm":
        return PDFParser(
            use_layout=pymupdf_use_layout,
            show_header=pymupdf_show_header,
            show_footer=pymupdf_show_footer,
        )

    # "marker_api" or "auto": attempt Marker API
    api_key = os.getenv("DATALAB_API_KEY")
    if not api_key:
        logger.warning(
            "⚠️ [DEGRADED] DATALAB_API_KEY 环境变量未设置，Marker API 不可用。"
            "降级使用 PyMuPDF4LLM 解析正文。"
            "【影响】页眉/页脚过滤依赖 Layout 引擎，章节标题提取基于启发式规则。"
            "【成本】本次处理不产生 API 费用。"
            "【修复】1) 注册 Datalab 账号: https://www.datalab.to/plans "
            "2) 设置环境变量: DATALAB_API_KEY=<your_key>"
        )
        return PDFParser(
            use_layout=pymupdf_use_layout,
            show_header=pymupdf_show_header,
            show_footer=pymupdf_show_footer,
        )

    try:
        from src.tools.marker_api_parser import MarkerApiParser
        return MarkerApiParser(
            api_key=api_key,
            base_url=marker_base_url,
            mode=marker_mode,
            cache_dir=cache_dir,
        )
    except Exception as e:
        logger.warning(
            "⚠️ [DEGRADED] Marker API 初始化失败: %s。降级使用 PyMuPDF4LLM。"
            "【影响】章节结构可能不如 Marker API 精确。",
            e,
        )
        return PDFParser(
            use_layout=pymupdf_use_layout,
            show_header=pymupdf_show_header,
            show_footer=pymupdf_show_footer,
        )


# MCP Server implementation for PDF Parser
def create_pdf_parser_mcp_server():
    """Create an MCP server for PDF parsing functionality.

    Returns:
        Configured MCP Server instance.
    """
    from mcp.server import Server
    from mcp.types import Tool, TextContent

    app = Server("pdf-parser")

    @app.list_tools()
    async def list_tools():
        return [
            Tool(
                name="parse_pdf",
                description="Parse a PDF file and convert it to markdown text",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pdf_path": {
                            "type": "string",
                            "description": "Path to the PDF file to parse",
                        },
                        "extract_images": {
                            "type": "boolean",
                            "description": "Whether to extract images (default: false)",
                        },
                        "page_range": {
                            "type": "string",
                            "description": "Optional page range (e.g., '1-10' or '1,3,5')",
                        },
                    },
                    "required": ["pdf_path"],
                },
            ),
            Tool(
                name="parse_pdf_to_file",
                description="Parse a PDF file and persist the markdown to disk",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pdf_path": {
                            "type": "string",
                            "description": "Path to the PDF file to parse",
                        },
                        "output_path": {
                            "type": "string",
                            "description": "Optional output file path",
                        },
                        "cache_dir": {
                            "type": "string",
                            "description": "Optional cache directory for parsed outputs",
                        },
                        "overwrite": {
                            "type": "boolean",
                            "description": "Overwrite existing output if true",
                        },
                        "extract_images": {
                            "type": "boolean",
                            "description": "Whether to extract images (default: false)",
                        },
                        "page_range": {
                            "type": "string",
                            "description": "Optional page range (e.g., '1-10' or '1,3,5')",
                        },
                    },
                    "required": ["pdf_path"],
                },
            ),
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
            if name == "parse_pdf":
                parser = PDFParser(
                    extract_images=arguments.get("extract_images", False),
                    page_range=arguments.get("page_range"),
                )
                result = parser.parse(arguments["pdf_path"])
                return [TextContent(type="text", text=result)]
            elif name == "parse_pdf_to_file":
                parser = PDFParser(
                    extract_images=arguments.get("extract_images", False),
                    page_range=arguments.get("page_range"),
                )
                output_path = parser.parse_to_file(
                    pdf_path=arguments["pdf_path"],
                    output_path=arguments.get("output_path"),
                    cache_dir=arguments.get("cache_dir"),
                    overwrite=arguments.get("overwrite", False),
                )
                return [TextContent(type="text", text=output_path)]
            else:
                return [
                    TextContent(
                        type="text",
                        text=f"Unknown tool: {name}",
                        isError=True,
                    )
                ]
        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=str(e),
                    isError=True,
                )
            ]

    return app
