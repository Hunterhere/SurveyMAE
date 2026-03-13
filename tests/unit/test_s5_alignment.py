"""Unit tests for S5 (section-cluster alignment) calculation."""

import pytest
from src.tools.citation_graph_analysis import CitationGraphAnalyzer


class TestSectionClusterAlignment:
    """Tests for compute_section_cluster_alignment method."""

    def test_perfect_alignment(self):
        """Test case where sections perfectly match clusters."""
        analyzer = CitationGraphAnalyzer()

        # Section A has refs [r1, r2], Section B has refs [r3, r4]
        # Clusters: cluster 0 has [r1, r2], cluster 1 has [r3, r4]
        section_ref_counts = {
            "Section A": {"r1": 5, "r2": 3},
            "Section B": {"r3": 4, "r4": 2},
        }

        references = [
            {"key": "r1", "id": "r1"},
            {"key": "r2", "id": "r2"},
            {"key": "r3", "id": "r3"},
            {"key": "r4", "id": "r4"},
        ]

        cluster_evidence = [
            {"cluster_id": 0, "top_papers": [{"paper_id": "r1"}, {"paper_id": "r2"}]},
            {"cluster_id": 1, "top_papers": [{"paper_id": "r3"}, {"paper_id": "r4"}]},
        ]

        result = analyzer.compute_section_cluster_alignment(
            section_ref_counts=section_ref_counts,
            references=references,
            cluster_evidence=cluster_evidence,
        )

        # Perfect alignment should give NMI = 1.0
        assert result["status"] == "success"
        assert result["nmi"] == 1.0
        assert result["ari"] == 1.0

    def test_no_alignment(self):
        """Test case where sections have no alignment with clusters."""
        analyzer = CitationGraphAnalyzer()

        # Section A has refs [r1, r2], Section B has refs [r3, r4]
        # But all refs are in ONE cluster
        section_ref_counts = {
            "Section A": {"r1": 5, "r2": 3},
            "Section B": {"r3": 4, "r4": 2},
        }

        references = [
            {"key": "r1", "id": "r1"},
            {"key": "r2", "id": "r2"},
            {"key": "r3", "id": "r3"},
            {"key": "r4", "id": "r4"},
        ]

        cluster_evidence = [
            {
                "cluster_id": 0,
                "top_papers": [
                    {"paper_id": "r1"},
                    {"paper_id": "r2"},
                    {"paper_id": "r3"},
                    {"paper_id": "r4"},
                ],
            },
        ]

        result = analyzer.compute_section_cluster_alignment(
            section_ref_counts=section_ref_counts,
            references=references,
            cluster_evidence=cluster_evidence,
        )

        # No alignment should give NMI close to 0
        assert result["status"] == "success"
        assert result["nmi"] == 0.0

    def test_partial_alignment(self):
        """Test case with partial alignment."""
        analyzer = CitationGraphAnalyzer()

        section_ref_counts = {
            "Section A": {"r1": 5, "r2": 3},
            "Section B": {"r3": 4, "r4": 2},
        }

        references = [
            {"key": "r1", "id": "r1"},
            {"key": "r2", "id": "r2"},
            {"key": "r3", "id": "r3"},
            {"key": "r4", "id": "r4"},
        ]

        # r1 and r3 in cluster 0, r2 and r4 in cluster 1
        # This is mixed, not perfect
        cluster_evidence = [
            {"cluster_id": 0, "top_papers": [{"paper_id": "r1"}, {"paper_id": "r3"}]},
            {"cluster_id": 1, "top_papers": [{"paper_id": "r2"}, {"paper_id": "r4"}]},
        ]

        result = analyzer.compute_section_cluster_alignment(
            section_ref_counts=section_ref_counts,
            references=references,
            cluster_evidence=cluster_evidence,
        )

        assert result["status"] == "success"
        # Partial alignment can give any value from 0 to 1
        assert 0.0 <= result["nmi"] <= 1.0

    def test_insufficient_data(self):
        """Test with insufficient common references."""
        analyzer = CitationGraphAnalyzer()

        section_ref_counts = {
            "Section A": {"r1": 5},
        }

        references = [
            {"key": "r1", "id": "r1"},
            {"key": "r2", "id": "r2"},
        ]

        # Only r1 is in both sections and clusters
        cluster_evidence = [
            {"cluster_id": 0, "top_papers": [{"paper_id": "r1"}]},
            {"cluster_id": 1, "top_papers": [{"paper_id": "r2"}]},
        ]

        result = analyzer.compute_section_cluster_alignment(
            section_ref_counts=section_ref_counts,
            references=references,
            cluster_evidence=cluster_evidence,
        )

        # Should fail due to insufficient data
        assert result["status"] == "insufficient_data"
        assert result["common_ref_count"] == 1

    def test_with_canonical_map(self):
        """Test with canonical mapping."""
        analyzer = CitationGraphAnalyzer()

        section_ref_counts = {
            "Section A": {"r1": 5, "r2": 3},
            "Section B": {"r3": 4},
        }

        references = [
            {"key": "r1", "id": "r1"},
            {"key": "r2", "id": "r2"},
            {"key": "r3", "id": "r3"},
        ]

        # Map r1, r2, r3 to canonical IDs
        canonical_map = {"r1": "canonical1", "r2": "canonical1", "r3": "canonical2"}

        cluster_evidence = [
            {"cluster_id": 0, "top_papers": [{"paper_id": "canonical1"}]},
            {"cluster_id": 1, "top_papers": [{"paper_id": "canonical2"}]},
        ]

        result = analyzer.compute_section_cluster_alignment(
            section_ref_counts=section_ref_counts,
            references=references,
            cluster_evidence=cluster_evidence,
            canonical_map=canonical_map,
        )

        assert result["status"] == "success"
