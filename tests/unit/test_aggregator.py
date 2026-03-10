"""Unit tests for the aggregator and workflow components."""

import pytest
from src.graph.nodes.aggregator import _generate_report, _get_score_grade, _generate_recommendations
from src.core.state import SurveyState, EvaluationRecord


class TestAggregator:
    """Tests for score aggregation and report generation."""

    def test_get_score_grade_excellent(self):
        """Test grade conversion for excellent scores."""
        grade = _get_score_grade(9.5)
        assert "A" in grade
        assert "Excellent" in grade

    def test_get_score_grade_good(self):
        """Test grade conversion for good scores."""
        grade = _get_score_grade(8.5)
        assert "B" in grade

    def test_get_score_grade_satisfactory(self):
        """Test grade conversion for satisfactory scores."""
        grade = _get_score_grade(7.0)
        assert "C" in grade

    def test_get_score_grade_needs_improvement(self):
        """Test grade conversion for needs improvement."""
        grade = _get_score_grade(6.0)
        assert "D" in grade

    def test_get_score_grade_unsatisfactory(self):
        """Test grade conversion for unsatisfactory."""
        grade = _get_score_grade(4.0)
        assert "F" in grade

    def test_generate_recommendations_low_scores(self):
        """Test recommendations for low-scoring surveys."""
        aggregated = {
            "factuality": {"score": 5.5, "statistics": {"std": 0.5}},
            "depth": {"score": 6.0, "statistics": {"std": 0.3}},
        }
        recommendations = _generate_recommendations(aggregated, 5.8)
        assert len(recommendations) > 0
        assert any("Attention" in r for r in recommendations)

    def test_generate_recommendations_high_variance(self):
        """Test recommendations for high variance."""
        aggregated = {
            "factuality": {"score": 7.0, "statistics": {"std": 2.0}},
        }
        recommendations = _generate_recommendations(aggregated, 7.0)
        assert any("Variance" in r for r in recommendations)

    def test_generate_recommendations_good_score(self):
        """Test recommendations for good overall score."""
        aggregated = {
            "factuality": {"score": 8.0, "statistics": {"std": 0.5}},
            "depth": {"score": 8.5, "statistics": {"std": 0.3}},
            "coverage": {"score": 7.5, "statistics": {"std": 0.4}},
            "bias": {"score": 8.0, "statistics": {"std": 0.2}},
        }
        recommendations = _generate_recommendations(aggregated, 8.0)
        assert len(recommendations) > 0


class TestReportGeneration:
    """Tests for markdown report generation."""

    def test_generate_report_basic(self):
        """Test basic report generation."""
        aggregated = {
            "factuality": {
                "score": 8.0,
                "statistics": {"mean": 8.0, "median": 8.0, "min": 7.5, "max": 8.5, "std": 0.5},
                "num_agents": 1,
                "agents": ["verifier"],
                "confidence": 0.85,
            }
        }
        evaluations = [
            EvaluationRecord(
                agent_name="verifier",
                dimension="factuality",
                score=8.0,
                reasoning="Good factual accuracy",
                evidence="All citations verified",
                confidence=0.85,
            )
        ]

        report = _generate_report(
            aggregated=aggregated,
            overall_score=8.0,
            evaluations=evaluations,
            source_pdf="test_paper.pdf",
            metadata={},
        )

        assert "SurveyMAE Evaluation Report" in report
        assert "Overall Score" in report
        assert "8.00" in report
        assert "VerifierAgent" in report
        assert "test_paper.pdf" in report

    def test_generate_report_multiple_dimensions(self):
        """Test report with multiple dimensions."""
        aggregated = {
            "factuality": {
                "score": 8.0,
                "statistics": {"mean": 8.0, "median": 8.0, "min": 8.0, "max": 8.0, "std": 0.0},
                "num_agents": 1,
                "agents": ["verifier"],
                "confidence": 0.85,
            },
            "depth": {
                "score": 7.5,
                "statistics": {"mean": 7.5, "median": 7.5, "min": 7.5, "max": 7.5, "std": 0.0},
                "num_agents": 1,
                "agents": ["expert"],
                "confidence": 0.9,
            },
            "coverage": {
                "score": 8.5,
                "statistics": {"mean": 8.5, "median": 8.5, "min": 8.5, "max": 8.5, "std": 0.0},
                "num_agents": 1,
                "agents": ["reader"],
                "confidence": 0.8,
            },
            "bias": {
                "score": 7.0,
                "statistics": {"mean": 7.0, "median": 7.0, "min": 7.0, "max": 7.0, "std": 0.0},
                "num_agents": 1,
                "agents": ["corrector"],
                "confidence": 0.75,
            },
        }

        evaluations = [
            EvaluationRecord(
                agent_name="verifier",
                dimension="factuality",
                score=8.0,
                reasoning="Good factual accuracy",
                evidence=None,
                confidence=0.85,
            ),
            EvaluationRecord(
                agent_name="expert",
                dimension="depth",
                score=7.5,
                reasoning="Good technical depth",
                evidence=None,
                confidence=0.9,
            ),
            EvaluationRecord(
                agent_name="reader",
                dimension="coverage",
                score=8.5,
                reasoning="Good coverage",
                evidence=None,
                confidence=0.8,
            ),
            EvaluationRecord(
                agent_name="corrector",
                dimension="bias",
                score=7.0,
                reasoning="Minor bias detected",
                evidence=None,
                confidence=0.75,
            ),
        ]

        report = _generate_report(
            aggregated=aggregated,
            overall_score=7.75,
            evaluations=evaluations,
            source_pdf="test_paper.pdf",
            metadata={},
        )

        assert "Factuality" in report
        assert "Depth" in report
        assert "Coverage" in report
        assert "Bias" in report

    def test_generate_report_includes_grade(self):
        """Test that grade is included in report."""
        aggregated = {
            "factuality": {
                "score": 9.0,
                "statistics": {"mean": 9.0, "median": 9.0, "min": 9.0, "max": 9.0, "std": 0.0},
                "num_agents": 1,
                "agents": ["verifier"],
                "confidence": 0.85,
            }
        }

        report = _generate_report(
            aggregated=aggregated,
            overall_score=9.0,
            evaluations=[],
            source_pdf="",
            metadata={},
        )

        assert "A" in report or "Excellent" in report
