"""Integration tests for the evaluation agents.

These tests make real API calls and require valid API keys in .env.
Use @pytest.mark.integration to skip these tests in CI.
"""

import pytest
import os
from src.agents.verifier import VerifierAgent
from src.agents.expert import ExpertAgent
from src.agents.reader import ReaderAgent
from src.agents.corrector import CorrectorAgent
from src.core.state import SurveyState


@pytest.mark.integration
class TestVerifierAgentIntegration:
    """Integration tests for VerifierAgent with real LLM."""

    @pytest.fixture
    def agent(self):
        return VerifierAgent()

    @pytest.fixture
    def sample_state(self):
        return SurveyState(
            source_pdf_path="test_paper.pdf",
            parsed_content="This is a test survey about machine learning [1]. "
            "Deep learning has achieved great success [2].",
            evaluations=[],
            debate_history=[],
            sections={},
            current_round=0,
            consensus_reached=False,
            final_report_md="",
            metadata={},
        )

    @pytest.mark.asyncio
    async def test_evaluate_with_real_llm(self, agent, sample_state):
        """Test evaluation with real LLM API call."""
        # Skip if no API key
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("No OPENAI_API_KEY available")

        result = await agent.evaluate(sample_state)

        assert result["agent_name"] == "verifier"
        assert result["dimension"] == "factuality"
        assert 0 <= result["score"] <= 10
        assert "reasoning" in result


@pytest.mark.integration
class TestExpertAgentIntegration:
    """Integration tests for ExpertAgent with real LLM."""

    @pytest.fixture
    def agent(self):
        return ExpertAgent()

    @pytest.fixture
    def sample_state(self):
        return SurveyState(
            source_pdf_path="test_paper.pdf",
            parsed_content="This survey covers neural networks [1] and transformers [2].",
            evaluations=[],
            debate_history=[],
            sections={},
            current_round=0,
            consensus_reached=False,
            final_report_md="",
            metadata={"domain": "computer science"},
        )

    @pytest.mark.asyncio
    async def test_evaluate_with_real_llm(self, agent, sample_state):
        """Test evaluation with real LLM API call."""
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("No OPENAI_API_KEY available")

        result = await agent.evaluate(sample_state)

        assert result["agent_name"] == "expert"
        assert result["dimension"] == "depth"


@pytest.mark.integration
class TestReaderAgentIntegration:
    """Integration tests for ReaderAgent with real LLM."""

    @pytest.fixture
    def agent(self):
        return ReaderAgent()

    @pytest.fixture
    def sample_state(self):
        return SurveyState(
            source_pdf_path="test_paper.pdf",
            parsed_content="This survey discusses various deep learning methods.",
            evaluations=[],
            debate_history=[],
            sections={},
            current_round=0,
            consensus_reached=False,
            final_report_md="",
            metadata={},
        )

    @pytest.mark.asyncio
    async def test_evaluate_with_real_llm(self, agent, sample_state):
        """Test evaluation with real LLM API call."""
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("No OPENAI_API_KEY available")

        result = await agent.evaluate(sample_state)

        assert result["agent_name"] == "reader"
        assert result["dimension"] == "coverage"


@pytest.mark.integration
class TestCorrectorAgentIntegration:
    """Integration tests for CorrectorAgent with real LLM."""

    @pytest.fixture
    def agent(self):
        return CorrectorAgent()

    @pytest.fixture
    def sample_state(self):
        return SurveyState(
            source_pdf_path="test_paper.pdf",
            parsed_content="This survey covers machine learning topics.",
            evaluations=[],
            debate_history=[],
            sections={},
            current_round=0,
            consensus_reached=False,
            final_report_md="",
            metadata={},
        )

    @pytest.mark.asyncio
    async def test_evaluate_single_model(self, agent, sample_state):
        """Test evaluation with single model (no multi-model voting)."""
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("No OPENAI_API_KEY available")

        # Use single model (no pool)
        agent._llm_pool = {}

        result = await agent.evaluate(sample_state)

        assert result["agent_name"] == "corrector"
        assert result["dimension"] == "bias"
        assert 0 <= result["score"] <= 10
