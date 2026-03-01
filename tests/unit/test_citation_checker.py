"""Unit tests for citation checker."""

from pathlib import Path

import pytest
from src.tools.citation_checker import CitationChecker, ReferenceEntry


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

    def test_extract_references_from_text(self, checker):
        """Test extracting reference entries from text."""
        text = """
Introduction text.

References
[1] Vaswani, A. and Shazeer, N. (2017). Attention Is All You Need. NeurIPS.
[2] Devlin, J. et al. (2019). BERT: Pre-training of Deep Bidirectional Transformers.
"""
        references = checker.extract_references_from_text(text)

        assert len(references) == 2
        assert references[0]["title"] == "Attention Is All You Need"
        assert references[0]["year"] == "2017"
        assert references[1]["title"].startswith("BERT")

    def test_extract_references_author_year_style(self, checker):
        """Test extracting references without numeric prefixes."""
        text = """
References
Vaswani, A., Shazeer, N. (2017). Attention Is All You Need. NeurIPS.
Devlin, J., Chang, M. (2019). BERT: Pre-training of Deep Bidirectional Transformers.
Brown, T. et al. (2020). Language Models are Few-Shot Learners.
"""
        references = checker.extract_references_from_text(text)

        assert len(references) == 3
        assert references[0]["year"] == "2017"
        assert references[1]["year"] == "2019"
        assert references[2]["year"] == "2020"

    def test_extract_references_from_pdf(self, checker):
        """Test PDF reference extraction on test_paper.pdf."""
        try:
            import pymupdf4llm  # noqa: F401
            pdf_ready = True
        except Exception:
            try:
                import pypdf  # noqa: F401
                pdf_ready = True
            except Exception:
                pdf_ready = False

        if not pdf_ready:
            pytest.skip("PDF parsing dependencies not installed")

        pdf_path = Path(__file__).resolve().parents[2] / "test_paper.pdf"
        references = checker.extract_references_from_pdf(str(pdf_path))
        assert isinstance(references, list)
        assert len(references) > 0
        assert references[0]["title"]

    def test_build_real_citation_edges_from_validation_metadata(self, checker):
        """Build real edges from validated metadata reference targets."""
        ref_a = ReferenceEntry(
            key="ref_a",
            title="Paper A",
            doi="10.1000/a",
            validation={
                "metadata": {
                    "openalex_id": "https://openalex.org/W123",
                    "reference_targets": [
                        {"openalex_id": "https://openalex.org/W456"},
                        {"doi": "10.1000/c"},
                    ],
                }
            },
        )
        ref_b = ReferenceEntry(
            key="ref_b",
            title="Paper B",
            validation={"metadata": {"openalex_id": "W456"}},
        )
        ref_c = ReferenceEntry(
            key="ref_c",
            title="Paper C",
            doi="https://doi.org/10.1000/C",
            validation={"metadata": {}},
        )

        payload = checker.build_real_citation_edges([ref_a, ref_b, ref_c])
        edges = {(item["source"], item["target"]) for item in payload["edges"]}

        assert ("ref_a", "ref_b") in edges
        assert ("ref_a", "ref_c") in edges
        assert payload["stats"]["n_edges"] == 2
        assert payload["stats"]["resolved_target_candidates"] == 2
