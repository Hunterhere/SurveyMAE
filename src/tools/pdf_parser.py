"""PDF Parser Tool.

Provides PDF to Markdown conversion using pymupdf4llm.
Can be exposed as an MCP server for distributed tool access.
"""

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class PDFParser:
    """PDF parsing utility for converting PDF documents to text/markdown.

    This class wraps pymupdf4llm for PDF extraction and provides
    a clean interface for the SurveyMAE framework.

    Attributes:
        extract_images: Whether to extract embedded images.
        page_range: Optional range of pages to extract (e.g., "1-10").
    """

    _CACHE: dict[tuple, str] = {}
    _CACHE_LIMIT = 128
    _DEFAULT_CACHE_DIR = os.getenv("SURVEYMAE_PDF_CACHE_DIR", "./output/pdf_cache")

    def __init__(
        self,
        extract_images: bool = False,
        page_range: Optional[str] = None,
    ):
        """Initialize the PDF parser.

        Args:
            extract_images: Whether to extract images from PDF.
            page_range: Optional page range (e.g., "1-10" or "1,3,5").
        """
        self.extract_images = extract_images
        self.page_range = page_range

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

    def _to_markdown_with_pymupdf4llm(self, pymupdf4llm, path: Path) -> str:
        """Handle pymupdf4llm API differences across versions."""
        try:
            return pymupdf4llm.to_markdown(
                input_path=str(path),
                extract_images=self.extract_images,
            )
        except TypeError:
            import fitz

            with fitz.open(str(path)) as doc:
                return pymupdf4llm.to_markdown(
                    doc,
                    extract_images=self.extract_images,
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

    async def aparse(self, pdf_path: str) -> str:
        """Async wrapper for parse method.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            The extracted content as a markdown string.
        """
        # pymupdf4llm is synchronous, so we just call the sync version
        return self.parse(pdf_path)


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
