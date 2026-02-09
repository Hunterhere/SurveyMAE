"""Unit tests for state definitions."""

import pytest
from src.core.state import SurveyState, EvaluationRecord, DebateMessage


class TestEvaluationRecord:
    """Tests for EvaluationRecord TypedDict."""

    def test_create_evaluation_record(self):
        """Test creating a valid evaluation record."""
        record = EvaluationRecord(
            agent_name="verifier",
            dimension="factuality",
            score=8.5,
            reasoning="Claims are well-supported",
            evidence="Citation [1] confirms...",
            confidence=0.9,
        )

        assert record["agent_name"] == "verifier"
        assert record["dimension"] == "factuality"
        assert record["score"] == 8.5
        assert record["confidence"] == 0.9

    def test_evaluation_record_optional_fields(self):
        """Test that evidence is optional."""
        record = EvaluationRecord(
            agent_name="expert",
            dimension="depth",
            score=7.0,
            reasoning="Good technical depth",
            evidence=None,
            confidence=0.8,
        )

        assert record["evidence"] is None


class TestDebateMessage:
    """Tests for DebateMessage TypedDict."""

    def test_create_debate_message(self):
        """Test creating a valid debate message."""
        message = DebateMessage(
            sender="debate_moderator",
            content="Discuss the score discrepancy",
            round_idx=1,
        )

        assert message["sender"] == "debate_moderator"
        assert message["round_idx"] == 1


class TestSurveyState:
    """Tests for SurveyState TypedDict."""

    def test_create_survey_state(self):
        """Test creating a valid survey state."""
        state: SurveyState = {
            "source_pdf_path": "/path/to/survey.pdf",
            "parsed_content": "# Survey Title\n\nContent...",
            "evaluations": [],
            "debate_history": [],
            "sections": {},
            "current_round": 0,
            "consensus_reached": False,
            "final_report_md": "",
            "metadata": {"source": "survey.pdf"},
        }

        assert state["source_pdf_path"] == "/path/to/survey.pdf"
        assert state["current_round"] == 0
        assert state["consensus_reached"] is False

    def test_survey_state_with_evaluations(self):
        """Test survey state with evaluations."""
        evaluations: list[EvaluationRecord] = [
            {
                "agent_name": "verifier",
                "dimension": "factuality",
                "score": 8.0,
                "reasoning": "Well supported",
                "evidence": None,
                "confidence": 0.85,
            }
        ]

        state: SurveyState = {
            "source_pdf_path": "/path/to/survey.pdf",
            "parsed_content": "Content...",
            "evaluations": evaluations,
            "debate_history": [],
            "sections": {},
            "current_round": 0,
            "consensus_reached": False,
            "final_report_md": "",
            "metadata": {},
        }

        assert len(state["evaluations"]) == 1
        assert state["evaluations"][0]["score"] == 8.0
