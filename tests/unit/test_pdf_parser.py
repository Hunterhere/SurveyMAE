"""Unit tests for PDFParser with PyMuPDF Layout support."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.tools.pdf_parser import PDFParser


class TestPDFParser:
    """Tests for PDFParser class."""

    def test_init_default_values(self):
        """Test PDFParser initializes with correct default values."""
        parser = PDFParser()
        
        assert parser.extract_images is False
        assert parser.page_range is None
        assert parser.use_layout is True
        assert parser.show_header is False
        assert parser.show_footer is False

    def test_init_custom_values(self):
        """Test PDFParser initializes with custom values."""
        parser = PDFParser(
            extract_images=True,
            page_range="1-10",
            use_layout=False,
            show_header=True,
            show_footer=True,
        )
        
        assert parser.extract_images is True
        assert parser.page_range == "1-10"
        assert parser.use_layout is False
        assert parser.show_header is True
        assert parser.show_footer is True

    @patch("pathlib.Path.exists")
    @patch("pymupdf4llm.to_markdown")
    def test_parse_success(self, mock_to_markdown, mock_exists):
        """Test successful PDF parsing."""
        mock_exists.return_value = True
        mock_to_markdown.return_value = "# Test Content\n\nSome text."
        
        parser = PDFParser()
        result = parser.parse("test.pdf")
        
        assert result == "# Test Content\n\nSome text."
        mock_to_markdown.assert_called_once()

    @patch("pathlib.Path.exists")
    def test_parse_file_not_found(self, mock_exists):
        """Test parsing with non-existent file raises error."""
        mock_exists.return_value = False
        
        parser = PDFParser()
        with pytest.raises(FileNotFoundError):
            parser.parse("nonexistent.pdf")

    @patch("pathlib.Path.exists")
    def test_parse_invalid_extension(self, mock_exists):
        """Test parsing with non-PDF file raises error."""
        mock_exists.return_value = True
        
        parser = PDFParser()
        with pytest.raises(ValueError, match="Expected PDF file"):
            parser.parse("test.txt")

    @patch("pathlib.Path.exists")
    @patch("src.tools.pdf_parser.PDFParser._extract_headings_from_markdown")
    def test_parse_with_structure_returns_markdown_and_structure(self, mock_extract_headings, mock_exists):
        """Test parse_with_structure returns markdown and structure dict."""
        mock_exists.return_value = True
        mock_extract_headings.return_value = ["Introduction", "Methods"]
        
        parser = PDFParser(use_layout=True, show_header=False, show_footer=False)
        
        with patch("pymupdf4llm.to_markdown") as mock_to_markdown:
            mock_to_markdown.return_value = "# Title\n\n## Introduction\n\nContent"
            
            md, structure = parser.parse_with_structure("test.pdf")
        
        assert isinstance(md, str)
        assert isinstance(structure, dict)
        assert structure["parser"] == "PDFParser"
        assert structure["use_layout"] is True
        assert "headings" in structure
        assert "pages" in structure

    @patch("pathlib.Path.exists")
    def test_parse_with_structure_includes_headers_when_enabled(self, mock_exists):
        """Test parse_with_structure includes headers when show_header=True."""
        mock_exists.return_value = True
        
        parser = PDFParser(show_header=True, show_footer=False)
        
        with patch("pymupdf4llm.to_markdown") as mock_to_markdown:
            mock_to_markdown.return_value = "Header\n\n# Content"
            
            with patch("pymupdf4llm.to_json") as mock_to_json:
                mock_to_json.return_value = '{"pages": []}'
                
                md, structure = parser.parse_with_structure("test.pdf")
        
        # Verify to_markdown was called with header=True
        call_kwargs = mock_to_markdown.call_args[1]
        assert call_kwargs.get("header") is True
        assert call_kwargs.get("footer") is False


class TestPDFParserHeadingsExtraction:
    """Tests for heading extraction methods."""

    def test_extract_headings_from_markdown_simple(self):
        """Test extracting headings from simple markdown."""
        parser = PDFParser()
        markdown = "# Heading 1\n\n## Heading 2\n\n### Heading 3\n\nSome text."
        
        headings = parser._extract_headings_from_markdown(markdown)
        
        assert headings == ["Heading 1", "Heading 2", "Heading 3"]

    def test_extract_headings_from_markdown_with_decorators(self):
        """Test extracting headings with markdown decorators."""
        parser = PDFParser()
        markdown = "# --- Title ---\n\n## Section 1\n\nContent."
        
        headings = parser._extract_headings_from_markdown(markdown)
        
        assert "--- Title ---" in headings or "Title" in headings

    def test_extract_headings_from_markdown_no_duplicates(self):
        """Test that duplicate headings are deduplicated."""
        parser = PDFParser()
        markdown = "# Same Heading\n\n# Same Heading\n\n# Different"
        
        headings = parser._extract_headings_from_markdown(markdown)
        
        # Should deduplicate while preserving order
        assert headings.count("Same Heading") == 1
        assert "Different" in headings

    def test_extract_headings_from_json_with_blocks(self):
        """Test extracting headings from JSON structure with blocks."""
        parser = PDFParser()
        json_struct = {
            "pages": [
                {
                    "blocks": [
                        {"type": "heading", "text": "Introduction"},
                        {"type": "text", "text": "Some content"},
                        {"type": "header", "text": "Methods"},
                    ]
                }
            ]
        }
        
        headings = parser._extract_headings_from_json(json_struct)
        
        assert "Introduction" in headings
        assert "Methods" in headings
        assert "Some content" not in headings

    def test_extract_headings_from_empty_json(self):
        """Test extracting headings from empty JSON structure."""
        parser = PDFParser()
        json_struct = {"pages": []}
        
        headings = parser._extract_headings_from_json(json_struct)
        
        assert headings == []


class TestPDFParserAsync:
    """Tests for async methods."""

    @pytest.mark.asyncio
    @patch("pathlib.Path.exists")
    @patch("pymupdf4llm.to_markdown")
    async def test_aparse_calls_parse(self, mock_to_markdown, mock_exists):
        """Test aparse delegates to parse in thread pool."""
        mock_exists.return_value = True
        mock_to_markdown.return_value = "# Async Content"
        
        parser = PDFParser()
        result = await parser.aparse("test.pdf")
        
        assert result == "# Async Content"

    @pytest.mark.asyncio
    @patch("pathlib.Path.exists")
    async def test_aparse_with_structure(self, mock_exists):
        """Test aparse_with_structure returns correct format."""
        mock_exists.return_value = True
        
        parser = PDFParser()
        
        with patch("pymupdf4llm.to_markdown") as mock_to_markdown:
            mock_to_markdown.return_value = "# Title\n\n## Section"
            
            md, structure = await parser.aparse_with_structure("test.pdf")
        
        assert isinstance(md, str)
        assert isinstance(structure, dict)
        assert structure["parser"] == "PDFParser"


class TestPDFParserCache:
    """Tests for caching functionality."""

    def test_cache_key_includes_all_parameters(self):
        """Test cache key includes relevant parameters."""
        parser = PDFParser(extract_images=True, page_range="1-5")
        
        # Create a mock path object
        mock_path = MagicMock()
        mock_path.resolve.return_value = Path("/tmp/test.pdf")
        mock_path.stat.return_value.st_mtime_ns = 1234567890
        mock_path.stat.return_value.st_size = 1000
        
        key = parser._cache_key(mock_path)
        
        assert isinstance(key, tuple)
        assert len(key) == 5
        assert key[1] is True  # extract_images
        assert key[2] == "1-5"  # page_range

    def test_in_process_cache_works(self):
        """Test in-process caching stores and retrieves content."""
        parser = PDFParser()
        
        with patch.object(parser, "_validate_path") as mock_validate:
            mock_path = MagicMock()
            mock_path.resolve.return_value = Path("/tmp/test.pdf")
            mock_path.stat.return_value.st_mtime_ns = 1234567890
            mock_path.stat.return_value.st_size = 1000
            mock_validate.return_value = mock_path
            
            # First call should store in cache
            with patch("pymupdf4llm.to_markdown") as mock_to_markdown:
                mock_to_markdown.return_value = "Cached Content"
                result1 = parser.parse_cached("test.pdf")
            
            # Second call should hit cache
            result2 = parser.parse_cached("test.pdf")
            
            assert result1 == result2 == "Cached Content"
            # to_markdown should only be called once
            mock_to_markdown.assert_called_once()
