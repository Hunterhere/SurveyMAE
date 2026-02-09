"""Unit tests for citation checker."""

import pytest
from src.tools.citation_checker import CitationChecker


class TestCitationChecker:
    """Tests for CitationChecker class."""

    @pytest.fixture
    def checker(self):
        """Create a CitationChecker instance."""
        return CitationChecker()

    def test_extract_citations_basic(self, checker):
        """Test basic citation extraction."""
        text = "Previous work [1] has shown that [2, 3] and [4-6] are important."
        citations = checker.extract_citations(text)

        assert "[1]" in citations
        assert "[2, 3]" in citations
        assert "[4-6]" in citations

    def test_extract_citations_numbers(self, checker):
        """Test extracting citation numbers."""
        text = "Studies [1], [2-5], and [7, 9, 10] support this."
        numbers = checker.extract_citation_numbers(text)

        assert 1 in numbers
        # [2-5] should include 2, 3, 4, 5
        assert 2 in numbers
        assert 3 in numbers
        assert 4 in numbers
        assert 5 in numbers
        # [7, 9, 10] should include 7, 9, 10
        assert 7 in numbers
        assert 9 in numbers
        assert 10 in numbers

    def test_extract_citations_duplicates(self, checker):
        """Test that duplicate citations are handled."""
        text = "[1] is important [1] and [1] again."
        citations = checker.extract_citations(text)

        assert len(citations) == 1
        assert "[1]" in citations

    def test_parse_reference_list(self, checker):
        """Test parsing a reference list."""
        refs_text = """
[1] Smith, J. (2020). Title One. Journal of Something.
[2] Doe, A. (2021). Title Two. Another Journal.
[3] Brown, B. (2022). Title Three. Different Journal.
"""
        refs = checker.parse_reference_list(refs_text)

        assert len(refs) == 3
        assert 1 in refs
        assert "Smith" in refs[1]
        assert 2 in refs
        assert "Doe" in refs[2]

    def test_validate_citations_without_refs(self, checker):
        """Test validation without reference list."""
        text = "Previous work [1] and [2] shows this."
        result = checker.validate_citations(text)

        assert result["total_citations"] == 2
        assert result["unique_citations"] == 2
        assert result["invalid_citations"] == []  # No refs to compare
        assert result["has_reference_list"] is False

    def test_validate_citations_with_refs(self, checker):
        """Test validation with reference list."""
        text = "Previous work [1] and [2] shows this."
        refs = {1: "Smith et al.", 3: "Other paper"}
        result = checker.validate_citations(text, refs)

        assert result["total_citations"] == 2
        assert result["invalid_citations"] == [2]  # Citation 2 has no ref
        assert result["has_reference_list"] is True

    def test_get_citation_context(self, checker):
        """Test getting context around citations."""
        text = "This is a sentence. [1] This is after. More text here."
        contexts = checker.get_citation_context(text, "[1]")

        assert len(contexts) == 1
        assert "[1]" in contexts[0]
        assert "before" in contexts[0] or "This is a sentence" in contexts[0]
