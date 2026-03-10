"""Bias Correction Agent (CorrectorAgent).

Analyzes and detects systematic biases in the survey.
Evaluates balance, fairness, and potential viewpoints being over/under-represented.
Implements multi-vendor model parallel invocation and majority voting.
"""

import logging
import os
import statistics
from typing import Any, Dict, List, Optional

from src.agents.base import BaseAgent, MultiModelConfig
from src.core.config import AgentConfig, LLMConfig
from src.core.mcp_client import MCPManager
from src.core.state import SurveyState, EvaluationRecord

logger = logging.getLogger(__name__)


# Default multi-model configuration for bias correction
DEFAULT_MULTI_MODELS = [
    LLMConfig(provider="openai", model="gpt-4o", temperature=0.1),
    LLMConfig(provider="openai", model="gpt-4o-mini", temperature=0.1),
    LLMConfig(provider="openai", model="gpt-4o", temperature=0.5),
]


class CorrectorAgent(BaseAgent):
    """Agent that detects and evaluates systematic biases in the survey.

    This agent:
    - Analyzes citation distribution and balance
    - Detects potential viewpoint biases
    - Identifies over-represented or under-represented perspectives
    - Evaluates fairness in presenting conflicting views
    - Uses multi-vendor model parallel invocation
    - Applies majority voting to reduce bias and variance

    Dimensions evaluated:
    - bias: Overall bias score (lower is more balanced)
    - balance: Balance in presenting different viewpoints
    - representation: Fair representation of different works/perspectives
    - objectivity: Objectivity in presenting facts vs. opinions
    """

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        mcp: Optional[MCPManager] = None,
        multi_model_config: Optional[MultiModelConfig] = None,
    ):
        """Initialize the CorrectorAgent.

        Args:
            config: Agent configuration.
            mcp: Optional MCP manager for reference check tools.
            multi_model_config: Optional multi-model configuration for parallel voting.
        """
        # Create default multi-model config if not provided
        if multi_model_config is None:
            multi_model_config = MultiModelConfig(
                models=DEFAULT_MULTI_MODELS,
                use_parallel=True,
            )

        super().__init__(
            name="corrector",
            config=config or AgentConfig(name="corrector"),
            mcp=mcp,
            multi_model_config=multi_model_config,
        )

    async def evaluate(
        self,
        state: SurveyState,
        section_name: Optional[str] = None,
    ) -> EvaluationRecord:
        """Evaluate bias and balance in the survey content.

        Uses multi-model parallel invocation and majority voting for stability.

        Args:
            state: The current workflow state.
            section_name: Optional specific section to evaluate.

        Returns:
            EvaluationRecord with bias and balance scores.
        """
        content = state.get("parsed_content", "")

        # Load the bias correction prompt
        system_prompt = self._load_prompt(
            "corrector",
            agent_name=self.name,
            section=section_name or "entire survey",
        )

        user_content = f"""
        Survey Content:
        ---
        {content[:10000]}
        ---

        Please analyze this survey for potential biases:
        1. Examine citation distribution - are some works over-represented?
        2. Check for balance in presenting different viewpoints
        3. Identify any systematic biases (geographic, temporal, methodological)
        4. Evaluate objectivity vs. opinion
        5. Rate the overall bias/balance (0-10, where 10 = perfectly balanced)

        Provide specific examples of bias or imbalance if found.
        """

        messages = self._create_messages(system_prompt, user_content)

        # Use multi-model parallel invocation if configured
        if self._llm_pool:
            # Call multiple models in parallel
            results = await self._call_llm_pool(messages)
            return self._process_multi_model_results(results)
        else:
            # Fallback to single model
            response = await self._call_llm(messages)
            score, reasoning, evidence = self._parse_corrector_response(response)

            return EvaluationRecord(
                agent_name=self.name,
                dimension="bias",
                score=score,
                reasoning=reasoning,
                evidence=evidence,
                confidence=0.75,
            )

    def _process_multi_model_results(
        self,
        results: List[Dict[str, Any]],
    ) -> EvaluationRecord:
        """Process results from multiple models using majority voting.

        Args:
            results: List of results from different models.

        Returns:
            Aggregated EvaluationRecord.
        """
        # Extract scores from each model
        scores = []
        reasonings = []
        evidences = []

        for result in results:
            if "error" in result:
                logger.warning(f"Model {result.get('model')} failed: {result.get('error')}")
                continue

            response = result.get("response", "")
            score, reasoning, evidence = self._parse_corrector_response(response)

            scores.append(score)
            reasonings.append(reasoning)
            if evidence:
                evidences.append(evidence)

        if not scores:
            # All models failed
            return EvaluationRecord(
                agent_name=self.name,
                dimension="bias",
                score=0.0,
                reasoning="All models failed to evaluate",
                evidence=None,
                confidence=0.0,
            )

        # Apply majority voting
        final_score = self._majority_vote(scores)

        # Filter out extreme scores for reasoning
        filtered_scores = self._filter_extremes(scores)
        if filtered_scores:
            avg_score = statistics.mean(filtered_scores)
            # Use median for robustness
            median_score = statistics.median(scores)
            # Combine final score from voting with average
            final_score = (final_score + median_score) / 2

        # Combine reasoning from multiple models
        combined_reasoning = self._combine_reasonings(reasonings, scores)

        # Combine evidences
        combined_evidence = "; ".join(set(evidences)) if evidences else None

        # Calculate confidence based on agreement
        confidence = self._calculate_confidence(scores)

        return EvaluationRecord(
            agent_name=self.name,
            dimension="bias",
            score=final_score,
            reasoning=combined_reasoning,
            evidence=combined_evidence,
            confidence=confidence,
        )

    def _majority_vote(self, scores: List[float]) -> float:
        """Apply majority voting to scores.

        Args:
            scores: List of scores from different models.

        Returns:
            Voted score.
        """
        if not scores:
            return 5.0

        # Round scores to nearest integer for voting
        rounded = [round(s) for s in scores]

        # Count occurrences
        from collections import Counter
        counter = Counter(rounded)

        # Get the most common score
        most_common = counter.most_common(1)[0][0]

        # Return as float
        return float(most_common)

    def _filter_extremes(self, scores: List[float]) -> List[float]:
        """Filter out extreme scores using interquartile range.

        Args:
            scores: List of scores.

        Returns:
            Filtered list of scores.
        """
        if len(scores) < 3:
            return scores

        sorted_scores = sorted(scores)
        q1 = sorted_scores[len(sorted_scores) // 4]
        q3 = sorted_scores[3 * len(sorted_scores) // 4]
        iqr = q3 - q1

        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr

        return [s for s in scores if lower <= s <= upper]

    def _combine_reasonings(
        self,
        reasonings: List[str],
        scores: List[float],
    ) -> str:
        """Combine reasoning from multiple models.

        Args:
            reasonings: List of reasoning strings.
            scores: Corresponding scores.

        Returns:
            Combined reasoning.
        """
        if not reasonings:
            return "No reasoning available"

        if len(reasonings) == 1:
            return reasonings[0]

        # Find the reasoning from the median score
        median_score = statistics.median(scores)
        median_idx = None

        for i, s in enumerate(scores):
            if abs(s - median_score) < 0.5:
                median_idx = i
                break

        if median_idx is not None:
            base_reasoning = reasonings[median_idx]
        else:
            base_reasoning = reasonings[0]

        # Add note about multi-model voting
        vote_info = f"[Based on {len(scores)} model evaluations with majority voting. Scores: {scores}]"

        return f"{base_reasoning}\n\n{vote_info}"

    def _calculate_confidence(self, scores: List[float]) -> float:
        """Calculate confidence based on score agreement.

        Args:
            scores: List of scores.

        Returns:
            Confidence score [0, 1].
        """
        if not scores:
            return 0.0

        if len(scores) == 1:
            return 0.75

        # Calculate standard deviation
        std = statistics.stdev(scores) if len(scores) > 1 else 0

        # Lower std = higher confidence
        # Max std for range of 10 is about 2.5
        confidence = max(0.5, 1.0 - (std / 3.0))

        return confidence

    def _parse_corrector_response(self, response: str) -> tuple:
        """Parse the bias correction response.

        Args:
            response: The raw response from the corrector LLM.

        Returns:
            Tuple of (score, reasoning, evidence).
        """
        lines = response.strip().split("\n")

        score = 5.0
        reasoning = response
        evidence = None

        for line in lines:
            line_lower = line.lower()
            if any(keyword in line_lower for keyword in ["balance", "bias score", "rating"]):
                if ":" in line:
                    try:
                        score = float(line.split(":")[-1].strip())
                        score = max(0.0, min(10.0, score))
                    except ValueError:
                        pass

            if any(kw in line_lower for kw in ["over-represented", "under-represented", "bias", "imbalance"]):
                if evidence is None:
                    evidence = line

        return score, reasoning, evidence
