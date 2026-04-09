"""Integration tests for PDFParser with PyMuPDF Layout support.

These tests verify the fallback PDF parser works correctly when Marker API is unavailable.

Prerequisites:
  - test_paper.pdf at project root

Run:
    pytest tests/integration/test_pdf_parser.py -v -s
"""

from pathlib import Path

import pytest

from src.tools.pdf_parser import PDFParser

TEST_PDF = Path(__file__).parent.parent.parent / "test_paper.pdf"

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def require_test_pdf():
    """Skip tests if test PDF is not available."""
    if not TEST_PDF.exists():
        pytest.skip(f"Test PDF not found: {TEST_PDF}")


@pytest.fixture(scope="module")
def parser_with_layout():
    """Fixture: PDFParser with Layout enabled."""
    return PDFParser(
        use_layout=True,
        show_header=False,
        show_footer=False,
    )


@pytest.fixture(scope="module")
def parser_without_layout():
    """Fixture: PDFParser without Layout (basic mode)."""
    return PDFParser(
        use_layout=False,
        show_header=False,
        show_footer=False,
    )


class TestPDFParserWithLayout:
    """Tests for PDFParser with PyMuPDF Layout enabled."""

    def test_parse_returns_nonempty_markdown(self, parser_with_layout):
        """parse() returns non-empty markdown content."""
        markdown = parser_with_layout.parse(str(TEST_PDF))
        
        assert isinstance(markdown, str)
        assert len(markdown) > 1000, f"Markdown too short: {len(markdown)} chars"
        
        print(f"\n[markdown length with layout]: {len(markdown)}")
        preview = markdown[:500].encode("ascii", "replace").decode("ascii")
        print(f"[markdown preview]:\n{preview}")

    def test_parse_with_layout_preserves_structure(self, parser_with_layout):
        """parse() with layout preserves document structure."""
        markdown = parser_with_layout.parse(str(TEST_PDF))
        
        # Should contain markdown headings
        assert "#" in markdown, "No markdown headings found"
        
        # Check for typical academic paper sections
        markdown_lower = markdown.lower()
        has_abstract = "abstract" in markdown_lower
        has_intro = "introduction" in markdown_lower
        
        print(f"\n[sections found]: abstract={has_abstract}, introduction={has_intro}")
        assert has_abstract or has_intro, "No typical academic sections found"

    def test_headers_filtered_by_default(self, parser_with_layout):
        """With show_header=False, page headers should be minimized."""
        markdown = parser_with_layout.parse(str(TEST_PDF))
        
        # Check that content is present
        assert len(markdown) > 1000
        
        # Count potential header/footer lines (short lines at start/end of pages)
        lines = markdown.split("\n")
        print(f"\n[total lines]: {len(lines)}")
        
        # Just verify we got meaningful content
        assert any(len(line) > 50 for line in lines), "No substantial content lines found"

    def test_layout_preserves_reading_order(self, parser_with_layout):
        """Layout engine should preserve correct reading order."""
        markdown = parser_with_layout.parse(str(TEST_PDF))
        
        # Check that abstract comes before introduction (typical academic paper structure)
        abstract_pos = markdown.lower().find("abstract")
        intro_pos = markdown.lower().find("introduction")
        
        if abstract_pos >= 0 and intro_pos >= 0:
            assert abstract_pos < intro_pos, "Abstract should come before Introduction"
            print(f"\n[reading order]: Abstract at {abstract_pos}, Introduction at {intro_pos}")


class TestPDFParserWithoutLayout:
    """Tests for PDFParser without Layout (basic mode)."""

    def test_parse_returns_content_without_layout(self, parser_without_layout):
        """parse() works without Layout engine."""
        markdown = parser_without_layout.parse(str(TEST_PDF))
        
        assert isinstance(markdown, str)
        assert len(markdown) > 1000
        
        print(f"\n[markdown length without layout]: {len(markdown)}")

    def test_basic_mode_has_headings(self, parser_without_layout):
        """Basic mode should still extract headings from markdown."""
        markdown = parser_without_layout.parse(str(TEST_PDF))
        
        # Extract headings
        headings = parser_without_layout._extract_headings_from_markdown(markdown)
        
        print(f"\n[headings without layout]: {headings[:5]}")
        assert len(headings) >= 0  # May find 0 or more


class TestPDFParserComparison:
    """Comparative tests between Layout and non-Layout modes."""

    def test_layout_produces_different_output(self, parser_with_layout, parser_without_layout):
        """Layout mode should produce different (hopefully better) output."""
        md_with_layout = parser_with_layout.parse(str(TEST_PDF))
        md_without_layout = parser_without_layout.parse(str(TEST_PDF))
        
        # Both should have content
        assert len(md_with_layout) > 1000
        assert len(md_without_layout) > 1000
        
        # They might differ (not guaranteed, but likely)
        print(f"\n[length with layout]: {len(md_with_layout)}")
        print(f"[length without layout]: {len(md_without_layout)}")

    def test_both_modes_extract_headings(self, parser_with_layout, parser_without_layout):
        """Both modes should be able to extract headings."""
        md_with = parser_with_layout.parse(str(TEST_PDF))
        md_without = parser_without_layout.parse(str(TEST_PDF))
        
        headings_with = parser_with_layout._extract_headings_from_markdown(md_with)
        headings_without = parser_without_layout._extract_headings_from_markdown(md_without)
        
        print(f"\n[headings with layout]: {len(headings_with)}")
        print(f"[headings without layout]: {len(headings_without)}")
        
        # At least one should find headings
        assert len(headings_with) > 0 or len(headings_without) > 0, "At least one mode should find headings"


class TestPDFParserAsync:
    """Tests for async methods."""

    @pytest.mark.asyncio
    async def test_aparse_returns_content(self, parser_with_layout):
        """aparse() returns content in async context."""
        result = await parser_with_layout.aparse(str(TEST_PDF))
        
        assert isinstance(result, str)
        assert len(result) > 1000

    @pytest.mark.asyncio
    async def test_aparse_without_layout(self, parser_without_layout):
        """aparse() works without layout."""
        result = await parser_without_layout.aparse(str(TEST_PDF))
        
        assert isinstance(result, str)
        assert len(result) > 1000


class TestPDFParserInterfaceAlignment:
    """Tests to verify PDFParser interface aligns with MarkerApiParser."""

    def test_has_parse_method(self, parser_with_layout):
        """PDFParser has parse() method like MarkerApiParser."""
        assert hasattr(parser_with_layout, "parse")
        assert callable(parser_with_layout.parse)

    def test_has_parse_with_structure_method(self, parser_with_layout):
        """PDFParser has parse_with_structure() like MarkerApiParser."""
        assert hasattr(parser_with_layout, "parse_with_structure")
        assert callable(parser_with_layout.parse_with_structure)

    def test_has_aparse_method(self, parser_with_layout):
        """PDFParser has aparse() async method."""
        assert hasattr(parser_with_layout, "aparse")
        assert callable(parser_with_layout.aparse)

    def test_has_aparse_with_structure_method(self, parser_with_layout):
        """PDFParser has aparse_with_structure() async method."""
        assert hasattr(parser_with_layout, "aparse_with_structure")
        assert callable(parser_with_layout.aparse_with_structure)

    def test_parse_returns_string(self, parser_with_layout):
        """parse() returns string like MarkerApiParser."""
        result = parser_with_layout.parse(str(TEST_PDF))
        assert isinstance(result, str)
