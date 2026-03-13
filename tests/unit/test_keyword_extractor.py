"""Unit tests for keyword extraction."""

import pytest
from src.tools.keyword_extractor import KeywordExtractor


class TestFallbackKeywordExtraction:
    """Tests for fallback keyword extraction (no LLM)."""

    def test_basic_extraction(self):
        """Test basic keyword extraction from title."""
        extractor = KeywordExtractor()

        keywords = extractor._fallback_extract(
            "A Survey on Retrieval Augmented Generation for LLMs",
            "This survey covers retrieval augmented generation.",
        )

        # Should extract some keywords
        assert len(keywords) > 0
        # Should include "retrieval augmented"
        assert any("retrieval" in k.lower() for k in keywords)

    def test_no_input(self):
        """Test with empty input."""
        extractor = KeywordExtractor()

        keywords = extractor._fallback_extract("", "")

        # Should return empty or limited keywords
        assert isinstance(keywords, list)

    def test_stopwords_removed(self):
        """Test that stopwords are removed."""
        extractor = KeywordExtractor()

        keywords = extractor._fallback_extract(
            "A Survey on Deep Learning for Natural Language Processing",
            "The study focuses on neural networks and transformers.",
        )

        # Should not contain common stopwords
        stopwords = {"a", "an", "the", "on", "for", "and", "or", "of", "in", "to"}
        for kw in keywords:
            assert kw.lower() not in stopwords


class TestKeywordParsing:
    """Tests for LLM response parsing."""

    def test_json_array_parsing(self):
        """Test parsing JSON array from LLM response."""
        extractor = KeywordExtractor()

        response = '["retrieval augmented generation", "RAG LLM", "knowledge retrieval"]'
        keywords = extractor._parse_keywords(response)

        assert len(keywords) == 3
        assert "retrieval augmented generation" in keywords

    def test_markdown_code_block(self):
        """Test parsing from markdown code block."""
        extractor = KeywordExtractor()

        response = """```json
["retrieval augmented generation", "RAG", "dense passage retrieval"]
```"""
        keywords = extractor._parse_keywords(response)

        assert len(keywords) == 3

    def test_invalid_json(self):
        """Test handling of invalid JSON."""
        extractor = KeywordExtractor()

        response = "This is not JSON"
        keywords = extractor._parse_keywords(response)

        # Should fall back to splitting by delimiter
        assert isinstance(keywords, list)

    def test_empty_response(self):
        """Test handling of empty response."""
        extractor = KeywordExtractor()

        keywords = extractor._parse_keywords("")

        assert isinstance(keywords, list)


class TestKeywordExtractionResult:
    """Tests for KeywordExtractionResult dataclass."""

    def test_result_structure(self):
        """Test result has expected fields."""
        from src.tools.keyword_extractor import KeywordExtractionResult

        result = KeywordExtractionResult(
            keywords=["kw1", "kw2"],
            llm_involved=True,
            hallucination_risk="low",
        )

        assert result.keywords == ["kw1", "kw2"]
        assert result.llm_involved is True
        assert result.hallucination_risk == "low"
