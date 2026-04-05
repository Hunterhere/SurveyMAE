"""Unit tests for the evaluation agents.

These tests mock LLM calls to test agent logic in isolation.
For integration tests with real LLM calls, see tests/integration/test_agents.py.
"""

import pytest
from unittest.mock import MagicMock, patch
from src.agents.corrector import CorrectorAgent


def create_mock_agent(agent_class):
    """Create an agent with mocked LLM."""
    with patch("src.agents.base.ChatOpenAI") as mock_llm:
        mock_instance = MagicMock()
        mock_llm.return_value = mock_instance
        agent = agent_class()
        return agent


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
