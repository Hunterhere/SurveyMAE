"""Unit tests for C6 citation-sentence alignment."""

import pytest
from src.tools.citation_checker import CitationChecker, ReferenceEntry


class TestC6CitationAlignment:
    """Tests for C6 citation-sentence alignment functionality."""

    @pytest.fixture
    def checker(self):
        """Create a CitationChecker instance."""
        return CitationChecker()

    def test_build_c6_prompt(self, checker):
        """Test C6 prompt building."""
        pairs = [
            {
                "citation_marker": "[1]",
                "sentence": "This paper proposes a novel method for X.",
                "abstract": "We propose a novel method for X that achieves state-of-the-art results.",
                "ref_key": "1",
                "ref_title": "Paper 1",
                "has_abstract": True,
            },
            {
                "citation_marker": "[2]",
                "sentence": "Previous work [2] has limitations.",
                "abstract": "We present a comprehensive study of Y.",
                "ref_key": "2",
                "ref_title": "Paper 2",
                "has_abstract": True,
            },
        ]
        prompt = checker._build_c6_prompt(pairs)

        assert "Pair 1" in prompt
        assert "Pair 2" in prompt
        assert "support/contradict/insufficient" in prompt
        assert "[[1]]" in prompt  # Note: citation markers are wrapped in brackets

    def test_parse_c6_response_support(self, checker):
        """Test parsing C6 response with support judgment."""
        pairs = [
            {
                "citation_marker": "[1]",
                "sentence": "This paper proposes a novel method.",
                "abstract": "We propose a novel method.",
                "ref_key": "1",
                "ref_title": "Paper 1",
                "has_abstract": True,
            },
        ]
        response = "Pair 1: support"
        results = checker._parse_c6_response(response, pairs)

        assert len(results) == 1
        assert results[0]["llm_judgment"] == "support"

    def test_parse_c6_response_contradict(self, checker):
        """Test parsing C6 response with contradict judgment."""
        pairs = [
            {
                "citation_marker": "[1]",
                "sentence": "This method achieves 99% accuracy.",
                "abstract": "Our method achieves 80% accuracy.",
                "ref_key": "1",
                "ref_title": "Paper 1",
                "has_abstract": True,
            },
        ]
        response = "Pair 1: contradict (sentence claims 99% but abstract says 80%)"
        results = checker._parse_c6_response(response, pairs)

        assert len(results) == 1
        assert results[0]["llm_judgment"] == "contradict"

    def test_parse_c6_response_insufficient(self, checker):
        """Test parsing C6 response with insufficient judgment."""
        pairs = [
            {
                "citation_marker": "[1]",
                "sentence": "This paper uses method X.",
                "abstract": "",
                "ref_key": "1",
                "ref_title": "Paper 1",
                "has_abstract": False,
            },
        ]
        response = "Pair 1: insufficient"
        results = checker._parse_c6_response(response, pairs)

        assert len(results) == 1
        assert results[0]["llm_judgment"] == "insufficient"

    def test_contradiction_rate_calculation(self):
        """Test contradiction rate calculation logic."""
        # Test case: 80 support, 10 contradict, 10 insufficient = 90 total pairs
        # But only 90 are valid (support + contradict), so rate = 10/90
        support = 80
        contradict = 10
        insufficient = 10

        valid_count = support + contradict
        contradiction_rate = contradict / valid_count if valid_count > 0 else 0.0

        # Rate = 10/90 ≈ 0.111
        assert abs(contradiction_rate - 0.111) < 0.001  # Approximately 11.1%
        assert contradiction_rate >= 0.05  # auto-fail threshold

    def test_auto_fail_threshold(self):
        """Test auto-fail threshold logic."""
        threshold = 0.05

        # Test cases: (contradiction_rate, expected_auto_fail)
        test_cases = [
            (0.001, False),  # < 1%
            (0.009, False),  # < 1%
            (0.01, False),   # 1%
            (0.02, False),   # 2%
            (0.03, False),   # 3%
            (0.04, False),   # 4%
            (0.05, True),    # 5% - at threshold
            (0.10, True),    # 10%
            (0.20, True),    # 20%
        ]

        for rate, expected in test_cases:
            auto_fail = rate >= threshold
            assert auto_fail == expected, f"Failed for rate={rate}, expected={expected}"

    def test_batch_grouping(self):
        """Test batch grouping logic."""
        batch_size = 10

        # Test: 25 pairs
        pairs = [{"i": i} for i in range(25)]
        batches = [pairs[i:i + batch_size] for i in range(0, len(pairs), batch_size)]

        assert len(batches) == 3  # 10 + 10 + 5
        assert len(batches[0]) == 10
        assert len(batches[1]) == 10
        assert len(batches[2]) == 5

    def test_abstract_missing_handling(self):
        """Test handling of missing abstracts."""
        pairs = [
            {"has_abstract": True, "abstract": "Has abstract"},
            {"has_abstract": False, "abstract": ""},
            {"has_abstract": True, "abstract": "Has abstract too"},
            {"has_abstract": False, "abstract": ""},
        ]

        insufficient_pairs = [p for p in pairs if not p["has_abstract"]]
        pairs_with_abstract = [p for p in pairs if p["has_abstract"]]

        assert len(insufficient_pairs) == 2
        assert len(pairs_with_abstract) == 2
