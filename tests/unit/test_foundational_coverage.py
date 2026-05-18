"""Unit tests for G4 (foundational_coverage_rate) — cluster-centric v2."""

import pytest
from src.tools.foundational_coverage import FoundationalCoverageAnalyzer, CITATION_THRESHOLD


def _make_cluster(cluster_id, size, top_papers):
    """Helper to build a cluster evidence dict."""
    return {
        "cluster_id": cluster_id,
        "size": size,
        "top_papers": top_papers,
    }


def _make_center(paper_id, score=0.05):
    """Helper to build a top_paper entry."""
    return {"paper_id": paper_id, "score": score}


class TestFoundationalCoverageV2:
    """Tests for the cluster-centric G4 analyzer."""

    @pytest.mark.asyncio
    async def test_all_clusters_have_anchors(self):
        """All cluster centers have citation_count >= threshold → G4 = 1.0."""
        analyzer = FoundationalCoverageAnalyzer(citation_threshold=50)

        cluster_evidence = [
            _make_cluster(0, 10, [_make_center("r1", 0.05)]),
            _make_cluster(1, 8, [_make_center("r2", 0.03)]),
            _make_cluster(2, 6, [_make_center("r3", 0.04)]),
        ]

        survey_references = [
            {"key": "r1", "title": "Paper A", "year": "2020"},
            {"key": "r2", "title": "Paper B", "year": "2021"},
            {"key": "r3", "title": "Paper C", "year": "2022"},
        ]

        ref_metadata_cache = {
            "r1": {"citation_count": 120},
            "r2": {"citation_count": 80},
            "r3": {"citation_count": 50},
        }

        result = await analyzer.analyze(
            cluster_evidence=cluster_evidence,
            ref_metadata_cache=ref_metadata_cache,
            survey_references=survey_references,
        )

        assert result.coverage_rate == 1.0
        assert len(result.matched_papers) == 3
        assert len(result.missing_key_papers) == 0
        assert result.llm_involved is False
        assert result.hallucination_risk == "none"
        assert len(result.cluster_centers) == 3
        # Verify citation_norm values
        assert result.cluster_centers[0]["citation_norm"] == 2.4   # 120 / 50
        assert result.cluster_centers[1]["citation_norm"] == 1.6   # 80 / 50
        assert result.cluster_centers[2]["citation_norm"] == 1.0   # 50 / 50

    @pytest.mark.asyncio
    async def test_partial_coverage(self):
        """Some clusters lack foundational anchors → G4 < 1.0."""
        analyzer = FoundationalCoverageAnalyzer(citation_threshold=50)

        cluster_evidence = [
            _make_cluster(0, 10, [_make_center("r1", 0.05)]),
            _make_cluster(1, 8, [_make_center("r2", 0.03)]),
            _make_cluster(2, 6, [_make_center("r3", 0.04)]),
        ]

        survey_references = [
            {"key": "r1", "title": "Paper A", "year": "2020"},
            {"key": "r2", "title": "Paper B", "year": "2021"},
            {"key": "r3", "title": "Paper C", "year": "2022"},
        ]

        ref_metadata_cache = {
            "r1": {"citation_count": 120},   # anchor
            "r2": {"citation_count": 5},     # NOT an anchor
            "r3": {"citation_count": 0},     # NOT an anchor
        }

        result = await analyzer.analyze(
            cluster_evidence=cluster_evidence,
            ref_metadata_cache=ref_metadata_cache,
            survey_references=survey_references,
        )

        assert result.coverage_rate == pytest.approx(1.0 / 3.0, abs=0.01)
        assert len(result.matched_papers) == 1
        assert len(result.missing_key_papers) == 2
        # Verify correct classification
        assert result.cluster_centers[0]["is_foundational_anchor"] is True
        assert result.cluster_centers[1]["is_foundational_anchor"] is False
        assert result.cluster_centers[2]["is_foundational_anchor"] is False

    @pytest.mark.asyncio
    async def test_no_anchors(self):
        """No cluster center meets the threshold → G4 = 0.0."""
        analyzer = FoundationalCoverageAnalyzer(citation_threshold=50)

        cluster_evidence = [
            _make_cluster(0, 5, [_make_center("r1", 0.05)]),
            _make_cluster(1, 5, [_make_center("r2", 0.03)]),
        ]

        survey_references = [
            {"key": "r1", "title": "Paper A", "year": "2020"},
            {"key": "r2", "title": "Paper B", "year": "2021"},
        ]

        ref_metadata_cache = {
            "r1": {"citation_count": 3},
            "r2": {"citation_count": 10},
        }

        result = await analyzer.analyze(
            cluster_evidence=cluster_evidence,
            ref_metadata_cache=ref_metadata_cache,
            survey_references=survey_references,
        )

        assert result.coverage_rate == 0.0
        assert len(result.matched_papers) == 0
        assert len(result.missing_key_papers) == 2

    @pytest.mark.asyncio
    async def test_empty_clusters(self):
        """No cluster evidence → coverage_rate = 0.0."""
        analyzer = FoundationalCoverageAnalyzer(citation_threshold=50)

        result = await analyzer.analyze(
            cluster_evidence=[],
            ref_metadata_cache={},
            survey_references=[],
        )

        assert result.coverage_rate == 0.0
        assert len(result.cluster_centers) == 0

    @pytest.mark.asyncio
    async def test_fallback_to_survey_references(self):
        """When ref_metadata_cache has no entry, fall back to survey_references title/year but citation_count=0."""
        analyzer = FoundationalCoverageAnalyzer(citation_threshold=50)

        cluster_evidence = [
            _make_cluster(0, 5, [_make_center("r1", 0.05)]),
        ]

        survey_references = [
            {"key": "r1", "title": "Paper A", "year": "2020"},
        ]

        # No metadata cache entry for r1
        result = await analyzer.analyze(
            cluster_evidence=cluster_evidence,
            ref_metadata_cache={},
            survey_references=survey_references,
        )

        assert result.coverage_rate == 0.0  # citation_count defaults to 0
        assert result.cluster_centers[0]["center_title"] == "Paper A"
        assert result.cluster_centers[0]["citation_count"] == 0
        assert result.cluster_centers[0]["citation_norm"] == 0.0

    @pytest.mark.asyncio
    async def test_metadata_overrides_survey_ref(self):
        """ref_metadata_cache overrides basic fields from survey_references."""
        analyzer = FoundationalCoverageAnalyzer(citation_threshold=50)

        cluster_evidence = [
            _make_cluster(0, 5, [_make_center("r1", 0.05)]),
        ]

        survey_references = [
            {"key": "r1", "title": "Old Title", "year": "2020"},
        ]

        ref_metadata_cache = {
            "r1": {"title": "Verified Title", "year": "2021", "citation_count": 100},
        }

        result = await analyzer.analyze(
            cluster_evidence=cluster_evidence,
            ref_metadata_cache=ref_metadata_cache,
            survey_references=survey_references,
        )

        assert result.coverage_rate == 1.0
        assert result.cluster_centers[0]["center_title"] == "Verified Title"
        assert result.cluster_centers[0]["center_year"] == "2021"
        assert result.cluster_centers[0]["citation_count"] == 100

    @pytest.mark.asyncio
    async def test_cluster_with_empty_top_papers(self):
        """Cluster with no top_papers should not crash."""
        analyzer = FoundationalCoverageAnalyzer(citation_threshold=50)

        cluster_evidence = [
            _make_cluster(0, 3, [_make_center("r1", 0.05)]),
            _make_cluster(1, 0, []),  # Empty cluster
        ]

        survey_references = [
            {"key": "r1", "title": "Paper A", "year": "2020"},
        ]

        ref_metadata_cache = {
            "r1": {"citation_count": 100},
        }

        result = await analyzer.analyze(
            cluster_evidence=cluster_evidence,
            ref_metadata_cache=ref_metadata_cache,
            survey_references=survey_references,
        )

        assert result.coverage_rate == 0.5  # 1 out of 2
        assert result.cluster_centers[1]["center_title"] == "(empty cluster)"
        assert result.cluster_centers[1]["is_foundational_anchor"] is False

    @pytest.mark.asyncio
    async def test_custom_threshold(self):
        """Custom citation_threshold is respected."""
        analyzer = FoundationalCoverageAnalyzer(citation_threshold=100)

        cluster_evidence = [
            _make_cluster(0, 5, [_make_center("r1", 0.05)]),
        ]

        survey_references = [{"key": "r1", "title": "Paper A", "year": "2020"}]
        ref_metadata_cache = {"r1": {"citation_count": 80}}

        result = await analyzer.analyze(
            cluster_evidence=cluster_evidence,
            ref_metadata_cache=ref_metadata_cache,
            survey_references=survey_references,
        )

        assert result.coverage_rate == 0.0  # 80 < 100
        assert result.cluster_centers[0]["citation_norm"] == 0.8
