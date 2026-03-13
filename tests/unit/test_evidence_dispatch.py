"""Unit tests for evidence_dispatch module."""

import pytest
from src.graph.nodes.evidence_dispatch import (
    build_verifier_evidence,
    build_expert_evidence,
    build_reader_evidence,
    assemble_evidence_report,
    build_metric_definitions,
    VERIFIER_METRICS,
    EXPERT_METRICS,
    READER_METRICS,
)


class TestMetricDefinitions:
    """Tests for metric definitions."""

    def test_verifier_metrics(self):
        """Test verifier metric definitions."""
        metrics = build_metric_definitions("verifier")

        assert "C3" in metrics
        assert "C5" in metrics
        assert metrics["C3"]["llm_involved"] is False
        assert metrics["C5"]["llm_involved"] is False

    def test_expert_metrics(self):
        """Test expert metric definitions."""
        metrics = build_metric_definitions("expert")

        assert "G1" in metrics
        assert "G4" in metrics
        assert metrics["G4"]["llm_involved"] is True
        assert metrics["G4"]["hallucination_risk"] == "low"

    def test_reader_metrics(self):
        """Test reader metric definitions."""
        metrics = build_metric_definitions("reader")

        assert "T1" in metrics
        assert "T5" in metrics
        assert metrics["T5"]["llm_involved"] is True


class TestVerifierEvidence:
    """Tests for verifier evidence building."""

    def test_normal_case(self):
        """Test normal verification evidence."""
        evidence = {
            "validation": {
                "orphan_ref_rate": 0.1,
                "metadata_verify_rate": 0.85,
                "references": [{"key": "r1"}, {"key": "r2"}],
                "unverified_references": [{"key": "r3"}],
            }
        }

        result = build_verifier_evidence(evidence)

        assert "metrics" in result
        assert result["metrics"]["C3"]["value"] == 0.1
        assert result["metrics"]["C5"]["value"] == 0.85

    def test_warning_low_verify_rate(self):
        """Test warning when verify rate is low."""
        evidence = {
            "validation": {
                "metadata_verify_rate": 0.5,
                "references": [{"key": f"r{i}"} for i in range(10)],
                "unverified_references": [{"key": f"r{i}"} for i in range(5)],
            }
        }

        result = build_verifier_evidence(evidence)

        # Should have warning
        assert len(result["warnings"]) > 0
        assert "C5" in result["warnings"][0]


class TestExpertEvidence:
    """Tests for expert evidence building."""

    def test_normal_case(self):
        """Test normal expert evidence."""
        evidence = {
            "graph_analysis": {
                "density_connectivity": {
                    "density_global": 0.3,
                    "n_weak_components": 2,
                    "lcc_frac": 0.8,
                    "n_isolates": 1,
                },
                "cocitation_clustering": {
                    "n_clusters": 3,
                },
            }
        }

        foundational = {
            "coverage_rate": 0.7,
            "missing_key_papers": [{"title": "Missing Paper", "citation_count": 1000}],
        }

        result = build_expert_evidence(evidence, foundational)

        assert result["metrics"]["G1"]["value"] == 0.3
        assert result["metrics"]["G4"]["value"] == 0.7

    def test_warning_low_coverage(self):
        """Test warning when coverage is low."""
        evidence = {
            "graph_analysis": {
                "density_connectivity": {
                    "density_global": 0.3,
                    "n_weak_components": 2,
                    "lcc_frac": 0.8,
                    "n_isolates": 0,  # No isolates to avoid G6 warning
                },
                "cocitation_clustering": {"n_clusters": 3},
            }
        }

        foundational = {
            "coverage_rate": 0.4,
            "missing_key_papers": [{"title": "P1"}, {"title": "P2"}, {"title": "P3"}],
        }

        result = build_expert_evidence(evidence, foundational)

        assert len(result["warnings"]) > 0
        assert "G4" in result["warnings"][0]


class TestReaderEvidence:
    """Tests for reader evidence building."""

    def test_normal_case(self):
        """Test normal reader evidence."""
        evidence = {
            "analysis": {
                "T1_year_span": 10,
                "T2_foundational_retrieval_gap": 2,
                "T3_peak_year_ratio": 0.4,
                "T4_temporal_continuity": 1,
                "T5_trend_alignment": 0.75,
                "S1_section_count": 8,
                "S2_citation_density": 2.5,
                "S3_citation_gini": 0.3,
                "S4_zero_citation_section_rate": 0.1,
                "year_distribution": {2020: 5, 2021: 10, 2022: 8},
            }
        }

        field_trend = {"yearly_counts": {"2020": 100, "2021": 150, "2022": 200}}

        result = build_reader_evidence(evidence, field_trend)

        assert result["metrics"]["T1"]["value"] == 10
        assert result["metrics"]["T5"]["value"] == 0.75

    def test_warning_temporal_gap(self):
        """Test warning for large temporal gap."""
        evidence = {
            "analysis": {
                "T1_year_span": 10,
                "T2_foundational_retrieval_gap": None,
                "T3_peak_year_ratio": 0.4,
                "T4_temporal_continuity": 5,  # Large gap
                "T5_trend_alignment": None,
                "S1_section_count": 8,
                "S2_citation_density": 2.5,
                "S3_citation_gini": 0.3,
                "S4_zero_citation_section_rate": 0.1,
                "year_distribution": {},
            }
        }

        result = build_reader_evidence(evidence, None)

        assert len(result["warnings"]) > 0
        assert "T4" in result["warnings"][0]

    def test_warning_low_trend_alignment(self):
        """Test warning for low trend alignment."""
        evidence = {
            "analysis": {
                "T1_year_span": 10,
                "T2_foundational_retrieval_gap": None,
                "T3_peak_year_ratio": 0.4,
                "T4_temporal_continuity": 1,
                "T5_trend_alignment": 0.2,  # Low alignment
                "S1_section_count": 8,
                "S2_citation_density": 2.5,
                "S3_citation_gini": 0.3,
                "S4_zero_citation_section_rate": 0.1,
                "year_distribution": {},
            }
        }

        result = build_reader_evidence(evidence, None)

        assert len(result["warnings"]) > 0
        assert "T5" in result["warnings"][0]


class TestEvidenceReportAssembly:
    """Tests for complete evidence report assembly."""

    def test_verifier_report(self):
        """Test verifier report assembly."""
        tool_evidence = {
            "validation": {
                "orphan_ref_rate": 0.1,
                "metadata_verify_rate": 0.9,
                "references": [],
                "unverified_references": [],
            }
        }

        report = assemble_evidence_report("verifier", tool_evidence)

        assert "Metric Definitions" in report
        assert "C3" in report
        assert "C5" in report

    def test_expert_report(self):
        """Test expert report assembly."""
        tool_evidence = {
            "graph_analysis": {
                "density_connectivity": {"density_global": 0.3},
                "cocitation_clustering": {"n_clusters": 3},
            }
        }
        additional = {
            "foundational_result": {
                "coverage_rate": 0.7,
                "missing_key_papers": [],
            }
        }

        report = assemble_evidence_report("expert", tool_evidence, additional)

        assert "G1" in report
        assert "G4" in report

    def test_reader_report(self):
        """Test reader report assembly."""
        tool_evidence = {
            "analysis": {
                "T1_year_span": 10,
                "T5_trend_alignment": 0.7,
            }
        }

        report = assemble_evidence_report("reader", tool_evidence)

        assert "T1" in report
        assert "T5" in report
