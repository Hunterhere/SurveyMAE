"""Unit tests for G4 (foundational_coverage_rate) calculation."""

import pytest
from src.tools.foundational_coverage import FoundationalCoverageAnalyzer


class MockLiteratureResult:
    """Mock LiteratureResult for testing."""

    def __init__(self, title, year, citation_count, doi="", abstract=""):
        self.title = title
        self.year = year
        self.citation_count = citation_count
        self.doi = doi
        self.abstract = abstract


class TestFoundationalCoverage:
    """Tests for FoundationalCoverageAnalyzer."""

    @pytest.mark.asyncio
    async def test_full_coverage(self):
        """Test case with 100% coverage."""
        analyzer = FoundationalCoverageAnalyzer(top_k=10)

        # Survey references
        survey_references = [
            {"key": "r1", "title": "Paper A", "year": "2020"},
            {"key": "r2", "title": "Paper B", "year": "2021"},
            {"key": "r3", "title": "Paper C", "year": "2022"},
        ]

        # Candidate papers (all matched)
        mock_candidates = [
            MockLiteratureResult("Paper A", "2020", 100),
            MockLiteratureResult("Paper B", "2021", 200),
            MockLiteratureResult("Paper C", "2022", 150),
        ]

        # Mock the literature search
        class MockSearch:
            def search_by_keywords(self, keywords, max_results, sort_by):
                return mock_candidates

        analyzer.literature_search = MockSearch()

        result = await analyzer.analyze(
            topic_keywords=["test topic"],
            survey_references=survey_references,
            ref_metadata_cache={},
        )

        assert result.coverage_rate == 1.0
        assert len(result.matched_papers) == 3
        assert len(result.missing_key_papers) == 0

    @pytest.mark.asyncio
    async def test_partial_coverage(self):
        """Test case with partial coverage."""
        analyzer = FoundationalCoverageAnalyzer(top_k=10)

        survey_references = [
            {"key": "r1", "title": "Paper A", "year": "2020"},
            {"key": "r2", "title": "Paper B", "year": "2021"},
        ]

        # Only one matches
        mock_candidates = [
            MockLiteratureResult("Paper A", "2020", 100),
            MockLiteratureResult("Paper X", "2019", 500),  # Not in survey
            MockLiteratureResult("Paper Y", "2018", 300),  # Not in survey
        ]

        class MockSearch:
            def search_by_keywords(self, keywords, max_results, sort_by):
                return mock_candidates

        analyzer.lit_search = MockSearch()

        # Need to properly mock
        analyzer.literature_search = type(
            "MockSearch",
            (),
            {"search_by_keywords": lambda self, keywords, max_results, sort_by: mock_candidates},
        )()

        result = await analyzer.analyze(
            topic_keywords=["test topic"],
            survey_references=survey_references,
            ref_metadata_cache={},
        )

        # 1 out of 3 = 33%
        assert result.coverage_rate == pytest.approx(0.333, abs=0.01)
        assert len(result.matched_papers) == 1
        assert len(result.missing_key_papers) == 2

    @pytest.mark.asyncio
    async def test_no_coverage(self):
        """Test case with no coverage."""
        analyzer = FoundationalCoverageAnalyzer(top_k=10)

        survey_references = [
            {"key": "r1", "title": "Paper A", "year": "2020"},
        ]

        # None match
        mock_candidates = [
            MockLiteratureResult("Paper X", "2019", 500),
            MockLiteratureResult("Paper Y", "2018", 300),
        ]

        analyzer.literature_search = type(
            "MockSearch",
            (),
            {"search_by_keywords": lambda self, keywords, max_results, sort_by: mock_candidates},
        )()

        result = await analyzer.analyze(
            topic_keywords=["test topic"],
            survey_references=survey_references,
            ref_metadata_cache={},
        )

        assert result.coverage_rate == 0.0
        assert len(result.matched_papers) == 0
        assert len(result.missing_key_papers) == 2

    @pytest.mark.asyncio
    async def test_doi_matching(self):
        """Test DOI-based matching."""
        analyzer = FoundationalCoverageAnalyzer(top_k=10, match_threshold=0.8)

        survey_references = [
            {"key": "r1", "title": "Paper A", "doi": "10.1234/test"},
        ]

        mock_candidates = [
            MockLiteratureResult("Different Title", "2020", 100, doi="10.1234/test"),
        ]

        analyzer.literature_search = type(
            "MockSearch",
            (),
            {"search_by_keywords": lambda self, keywords, max_results, sort_by: mock_candidates},
        )()

        result = await analyzer.analyze(
            topic_keywords=["test"],
            survey_references=survey_references,
            ref_metadata_cache={},
        )

        # DOI match should work
        assert len(result.matched_papers) == 1
        assert result.matched_papers[0]["match_type"] == "doi"


class TestTitleMatching:
    """Tests for title matching logic."""

    def test_exact_match(self):
        """Test exact title matching."""
        analyzer = FoundationalCoverageAnalyzer()

        candidates = [MockLiteratureResult("Paper A", "2020", 100)]
        survey_refs = [{"key": "r1", "title": "Paper A"}]

        matched, missing = analyzer._match_references(candidates, survey_refs)

        assert len(matched) == 1

    def test_fuzzy_match(self):
        """Test fuzzy title matching."""
        analyzer = FoundationalCoverageAnalyzer(match_threshold=0.85)

        candidates = [MockLiteratureResult("Attention Is All You Need", "2017", 50000)]
        survey_refs = [{"key": "r1", "title": "Attention Is All You Need"}]

        matched, missing = analyzer._match_references(candidates, survey_refs)

        assert len(matched) == 1
        assert matched[0]["match_type"] == "title"

    def test_no_match(self):
        """Test when titles don't match."""
        analyzer = FoundationalCoverageAnalyzer()

        candidates = [MockLiteratureResult("Completely Different", "2020", 100)]
        survey_refs = [{"key": "r1", "title": "Paper A"}]

        matched, missing = analyzer._match_references(candidates, survey_refs)

        assert len(matched) == 0
        assert len(missing) == 1


class TestSuspiciousCentrality:
    """Tests for suspicious centrality detection."""

    def test_suspicious_papers(self):
        """Test detection of suspicious centrality."""
        analyzer = FoundationalCoverageAnalyzer()

        matched = [
            {
                "paper": MockLiteratureResult("Paper A", "2020", 5),
                "matched_ref": {"key": "r1"},
                "match_type": "title",
            }
        ]

        ref_cache = {
            "r1": {"citation_count": 5}  # Low external citations
        }

        suspicious = analyzer._find_suspicious_centrality(matched, ref_cache)

        assert len(suspicious) == 1
        assert suspicious[0]["title"] == "Paper A"

    def test_normal_papers(self):
        """Test that normal papers are not flagged."""
        analyzer = FoundationalCoverageAnalyzer()

        matched = [
            {
                "paper": MockLiteratureResult("Paper A", "2020", 5000),
                "matched_ref": {"key": "r1"},
                "match_type": "title",
            }
        ]

        ref_cache = {
            "r1": {"citation_count": 5000}  # High external citations
        }

        suspicious = analyzer._find_suspicious_centrality(matched, ref_cache)

        assert len(suspicious) == 0
