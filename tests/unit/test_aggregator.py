"""Unit tests for the aggregator and workflow components."""

from src.graph.nodes.aggregator import (
    generate_report,
    aggregate_scores,
)
from src.core.state import SurveyState


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
