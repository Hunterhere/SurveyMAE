"""Unit tests for the aggregator and workflow components."""

import pytest

from src.graph.nodes.aggregator import (
    generate_report,
    aggregate_scores,
)
from src.core.state import SurveyState


_MINIMAL_TOOL_EVIDENCE = {
    "validation": {
        "C3_orphan_ref_rate": 0.1,
        "C5_metadata_verify_rate": 0.9,
        "total_refs": 1,
    },
    "c6_alignment": {"contradiction_rate": 0.0},
    "analysis": {
        "T1_year_span": 5,
        "T2_foundational_retrieval_gap": 2,
        "T4_temporal_continuity": 1,
        "T5_trend_alignment": 0.8,
        "year_distribution": {2020: 1, 2021: 2},
    },
    "graph_analysis": {
        "G4_coverage_rate": 0.7,
        "S5_nmi": 0.6,
        "G6_isolates": 0,
    },
}


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
            "llm_score": 4.0,
            "llm_variance": None,
            "overall_score": 4.0,
            "consensus_reached": True,
        }

        state = SurveyState(
            source_pdf_path="test_paper.pdf",
            parsed_content="",
            section_headings=[],
            tool_evidence=_MINIMAL_TOOL_EVIDENCE,
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
        assert "4.00/5" in report
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
            "llm_score": 3.88,
            "llm_variance": None,
            "overall_score": 3.88,
            "consensus_reached": True,
        }

        state = SurveyState(
            source_pdf_path="test_paper.pdf",
            parsed_content="",
            section_headings=[],
            tool_evidence=_MINIMAL_TOOL_EVIDENCE,
            ref_metadata_cache={},
            topic_keywords=[],
            field_trend_baseline={},
            candidate_key_papers=[],
            evaluations=[],
            debate_history=[],
            sections={},
            agent_outputs={
                "verifier": {
                    "sub_scores": {
                        "V1_citation_existence": {
                            "score": 4.0,
                            "llm_reasoning": "ok",
                            "tool_evidence": {"metadata_verify_rate": 0.9},
                            "hallucination_risk": "low",
                            "flagged_items": [],
                            "variance": None,
                        }
                    }
                },
                "expert": {
                    "sub_scores": {
                        "E1_foundational_coverage": {
                            "score": 4.0,
                            "llm_reasoning": "ok",
                            "tool_evidence": {"foundational_coverage_rate": 0.7},
                            "hallucination_risk": "low",
                            "flagged_items": [],
                            "variance": None,
                        }
                    }
                },
                "reader": {
                    "sub_scores": {
                        "R1_timeliness": {
                            "score": 4.0,
                            "llm_reasoning": "ok",
                            "tool_evidence": {"metrics": {"T5": 0.8}},
                            "hallucination_risk": "low",
                            "flagged_items": [],
                            "variance": None,
                        }
                    }
                },
            },
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

    def test_generate_report_includes_grade(self):
        """Test that grade is included in report."""
        aggregation_result = {
            "aggregated_scores": {
                "factuality": {"overall": 4.5, "confidence": 0.85, "sub_scores": {}}
            },
            "deterministic_score": None,
            "llm_score": 4.5,
            "llm_variance": None,
            "overall_score": 4.5,
            "grade": "A",
            "consensus_reached": True,
        }

        state = SurveyState(
            source_pdf_path="",
            parsed_content="",
            section_headings=[],
            tool_evidence=_MINIMAL_TOOL_EVIDENCE,
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

        assert "Grade: A" in report

    @pytest.mark.asyncio
    async def test_aggregate_scores_uses_five_point_scale(self):
        """Overall score should stay on 0-5 scale (no x2 conversion)."""
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
            agent_outputs={
                "verifier": {
                    "agent_name": "verifier",
                    "dimension": "factuality",
                    "sub_scores": {
                        "V1_citation_existence": {
                            "score": 4.0,
                            "llm_involved": True,
                            "hallucination_risk": "low",
                            "tool_evidence": {},
                            "llm_reasoning": "ok",
                            "flagged_items": [],
                            "variance": None,
                        }
                    },
                    "overall_score": 4.0,
                    "confidence": 1.0,
                    "evidence_summary": "",
                }
            },
            aggregated_scores={},
            current_round=0,
            consensus_reached=False,
            final_report_md="",
            metadata={},
        )

        result = await aggregate_scores(state)
        assert result["overall_score"] == 4.0
        assert result["grade"] == "B"
