"""Unit tests for the aggregator and workflow components."""

import pytest
from src.graph.nodes.aggregator import (
    generate_report,
    _get_score_grade,
    _generate_recommendations,
    aggregate_scores,
)
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
        """Test recommendations for high variance in sub-scores."""
        # High variance now is detected through sub_scores with variance > 1.0
        aggregated = {
            "factuality": {
                "overall": 7.0,
                "confidence": 0.7,
                "sub_scores": {
                    "V1": {
                        "score": 4.0,
                        "llm_involved": True,
                        "variance": {"std": 1.5, "range": [2.0, 5.0]},  # High variance
                    }
                },
            },
        }
        recommendations = _generate_recommendations(aggregated, 7.0)
        # The new logic checks sub_scores for high variance
        assert len(recommendations) > 0

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
        # Test the new API with agent_outputs format
        aggregation_result = {
            "aggregated_scores": {
                "factuality": {
                    "overall": 8.0,
                    "confidence": 0.85,
                    "sub_scores": {},
                }
            },
            "deterministic_score": None,
            "llm_score": 8.0,
            "llm_variance": None,
            "overall_score": 8.0,
            "consensus_reached": True,
        }

        state = SurveyState(
            source_pdf_path="test_paper.pdf",
            parsed_content="",
            section_headings=[],
            tool_evidence={},
            ref_metadata_cache={},
            topic_keywords=[],
            field_trend_baseline={},
            candidate_key_papers=[],
            evaluations=[],
            debate_history=[],
            sections={},
            agent_outputs={},
            aggregated_scores={},
            current_round=0,
            consensus_reached=False,
            final_report_md="",
            metadata={},
        )

        report = generate_report(aggregation_result, state)

        assert "SurveyMAE Evaluation Report" in report
        assert "Overall Score" in report
        assert "8.00" in report
        assert "test_paper.pdf" in report

    def test_generate_report_multiple_dimensions(self):
        """Test report with multiple dimensions."""
        aggregation_result = {
            "aggregated_scores": {
                "factuality": {"overall": 8.0, "confidence": 0.85, "sub_scores": {}},
                "depth": {"overall": 7.5, "confidence": 0.9, "sub_scores": {}},
                "coverage": {"overall": 8.5, "confidence": 0.8, "sub_scores": {}},
                "bias": {"overall": 7.0, "confidence": 0.75, "sub_scores": {}},
            },
            "deterministic_score": None,
            "llm_score": 7.75,
            "llm_variance": None,
            "overall_score": 7.75,
            "consensus_reached": True,
        }

        state = SurveyState(
            source_pdf_path="test_paper.pdf",
            parsed_content="",
            section_headings=[],
            tool_evidence={},
            ref_metadata_cache={},
            topic_keywords=[],
            field_trend_baseline={},
            candidate_key_papers=[],
            evaluations=[],
            debate_history=[],
            sections={},
            agent_outputs={},
            aggregated_scores={},
            current_round=0,
            consensus_reached=False,
            final_report_md="",
            metadata={},
        )

        report = generate_report(aggregation_result, state)

        assert "Factuality" in report
        assert "Depth" in report
        assert "Coverage" in report
        assert "Bias" in report

    def test_generate_report_includes_grade(self):
        """Test that grade is included in report."""
        aggregation_result = {
            "aggregated_scores": {
                "factuality": {"overall": 9.0, "confidence": 0.85, "sub_scores": {}}
            },
            "deterministic_score": None,
            "llm_score": 9.0,
            "llm_variance": None,
            "overall_score": 9.0,
            "consensus_reached": True,
        }

        state = SurveyState(
            source_pdf_path="",
            parsed_content="",
            section_headings=[],
            tool_evidence={},
            ref_metadata_cache={},
            topic_keywords=[],
            field_trend_baseline={},
            candidate_key_papers=[],
            evaluations=[],
            debate_history=[],
            sections={},
            agent_outputs={},
            aggregated_scores={},
            current_round=0,
            consensus_reached=False,
            final_report_md="",
            metadata={},
        )

        report = generate_report(aggregation_result, state)

        assert "A" in report or "Excellent" in report
