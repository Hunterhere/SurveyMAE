"""Unit tests for the evaluation agents.

These tests mock LLM calls to test agent logic in isolation.
For integration tests with real LLM calls, see tests/integration/test_agents.py.
"""

import pytest
from unittest.mock import MagicMock, patch
from src.agents.verifier import VerifierAgent
from src.agents.expert import ExpertAgent
from src.agents.reader import ReaderAgent
from src.agents.corrector import CorrectorAgent
from src.core.state import SurveyState, EvaluationRecord


def create_mock_agent(agent_class):
    """Create an agent with mocked LLM."""
    with patch('src.agents.base.ChatOpenAI') as mock_llm:
        mock_instance = MagicMock()
        mock_llm.return_value = mock_instance
        agent = agent_class()
        return agent


class TestVerifierAgent:
    """Tests for VerifierAgent."""

    @pytest.fixture
    def agent(self):
        return create_mock_agent(VerifierAgent)

    @pytest.fixture
    def sample_state(self):
        return SurveyState(
            source_pdf_path="test_paper.pdf",
            parsed_content="Test content with citations [1], [2].",
            evaluations=[],
            debate_history=[],
            sections={},
            current_round=0,
            consensus_reached=False,
            final_report_md="",
            metadata={},
        )

    def test_agent_initialization(self, agent):
        """Test agent can be initialized."""
        assert agent.name == "verifier"
        assert agent._citation_checker is not None

    def test_extract_claims_and_citations(self, agent):
        """Test citation extraction."""
        content = "This is a test [1] with multiple [2, 3] citations [4-6]."
        result = agent._extract_claims_and_citations(content)
        assert "[1]" in result
        assert "[2, 3]" in result
        assert "[4-6]" in result

    def test_parse_verification_response(self, agent):
        """Test response parsing."""
        response = """
        Factuality Score: 8.5

        The survey shows good factual accuracy.
        Evidence: All claims are properly cited.
        """
        score, reasoning, evidence = agent._parse_verification_response(response)
        assert score == 8.5
        assert "factual accuracy" in reasoning.lower()


class TestExpertAgent:
    """Tests for ExpertAgent."""

    @pytest.fixture
    def agent(self):
        return create_mock_agent(ExpertAgent)

    @pytest.fixture
    def sample_state(self):
        return SurveyState(
            source_pdf_path="test_paper.pdf",
            parsed_content="Test content about machine learning [1].",
            evaluations=[],
            debate_history=[],
            sections={},
            current_round=0,
            consensus_reached=False,
            final_report_md="",
            metadata={"domain": "computer science"},
        )

    def test_agent_initialization(self, agent):
        """Test agent can be initialized."""
        assert agent.name == "expert"
        assert agent._citation_checker is not None
        assert agent._graph_analyzer is not None


class TestReaderAgent:
    """Tests for ReaderAgent."""

    @pytest.fixture
    def agent(self):
        return create_mock_agent(ReaderAgent)

    @pytest.fixture
    def sample_state(self):
        return SurveyState(
            source_pdf_path="test_paper.pdf",
            parsed_content="Test survey content.",
            evaluations=[],
            debate_history=[],
            sections={},
            current_round=0,
            consensus_reached=False,
            final_report_md="",
            metadata={},
        )

    def test_agent_initialization(self, agent):
        """Test agent can be initialized."""
        assert agent.name == "reader"
        assert agent._citation_checker is not None
        assert agent._citation_analyzer is not None

    def test_parse_reader_response_with_percentage(self, agent):
        """Test parsing response with percentage."""
        response = """
        Coverage: 85%

        Most reader questions are answered.
        """
        score, reasoning, evidence = agent._parse_reader_response(response)
        assert score == 8.5  # 85 / 10

    def test_parse_reader_response_with_score(self, agent):
        """Test parsing response with score."""
        response = """
        Coverage Score: 7.5

        The survey covers most topics.
        """
        score, reasoning, evidence = agent._parse_reader_response(response)
        assert score == 7.5


class TestCorrectorAgent:
    """Tests for CorrectorAgent with multi-model voting."""

    @pytest.fixture
    def agent(self):
        return create_mock_agent(CorrectorAgent)

    def test_agent_initialization(self, agent):
        """Test agent can be initialized."""
        assert agent.name == "corrector"
        assert agent.multi_model_config is not None

    def test_majority_vote(self, agent):
        """Test majority voting logic."""
        # Test with clear majority
        scores = [7.0, 7.0, 8.0, 7.0]
        result = agent._majority_vote(scores)
        assert result == 7.0

    def test_majority_vote_tie(self, agent):
        """Test majority voting with tie."""
        scores = [7.0, 8.0]
        result = agent._majority_vote(scores)
        assert result in [7.0, 8.0]

    def test_filter_extremes(self, agent):
        """Test extreme score filtering."""
        scores = [2.0, 5.0, 6.0, 7.0, 9.0]
        filtered = agent._filter_extremes(scores)
        # With IQR filtering, extreme values should be removed
        assert len(filtered) <= len(scores)

    def test_filter_extremes_small(self, agent):
        """Test extreme filtering with small list."""
        scores = [5.0, 6.0]
        filtered = agent._filter_extremes(scores)
        assert filtered == scores

    def test_calculate_confidence(self, agent):
        """Test confidence calculation."""
        # High agreement = high confidence
        scores = [7.0, 7.0, 7.0]
        confidence = agent._calculate_confidence(scores)
        assert confidence > 0.8

        # Low agreement = lower confidence
        scores = [3.0, 7.0, 5.0]
        confidence = agent._calculate_confidence(scores)
        assert confidence < 0.8

    def test_parse_corrector_response(self, agent):
        """Test corrector response parsing."""
        response = """
        Balance Score: 8.5

        The survey shows good balance.
        """
        score, reasoning, evidence = agent._parse_corrector_response(response)
        assert score == 8.5

    def test_parse_corrector_response_with_bias(self, agent):
        """Test parsing response with bias keywords."""
        response = """
        Balance: 6.0

        Some works are over-represented.
        Evidence: The survey heavily cites [1, 2, 3].
        """
        score, reasoning, evidence = agent._parse_corrector_response(response)
        assert score == 6.0
        assert evidence is not None
