"""Corrector Agent (v3 - Multi-Model Voting Correction).

According to Plan v3, Corrector:
- No longer produces independent C1/C2/C3 scoring dimensions
- Acts as a pure corrector: performs multi-model voting on high hallucination risk sub-dimensions
- Only votes on 7 sub-dimensions: V4, E2, E3, E4, R2, R3, R4
- Does NOT modify original agent_outputs, stores corrections in corrector_output
"""

import asyncio
import logging
import statistics
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage
from src.agents.base import BaseAgent, MultiModelConfig
from src.core.config import AgentConfig, load_config
from src.core.mcp_client import MCPManager
from src.core.state import (
    SurveyState,
    EvaluationRecord,
    AgentOutput,
    CorrectorOutput,
    CorrectionRecord,
    VarianceRecord,
)
from src.core.log import create_progress
from src.graph.nodes.evidence_dispatch import get_corrector_targets, AGENT_REGISTRY

logger = logging.getLogger("surveymae.agents.corrector")


class CorrectorAgent(BaseAgent):
    """Corrector agent that performs multi-model voting correction.

    According to Plan v3:
    - Does NOT produce independent scoring dimensions (no C1/C2/C3)
    - Performs multi-model voting on 7 high-risk sub-dimensions
    - Returns CorrectorOutput with correction records
    - Original agent_outputs remain unchanged
    """

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        mcp: Optional[MCPManager] = None,
    ):
        """Initialize the CorrectorAgent.

        Args:
            config: Agent configuration (includes multi_model from config/models.yaml).
            mcp: Optional MCP manager for reference check tools.
        """
        if config is None:
            config = AgentConfig(name="corrector")

        # Use multi_model from config for voting
        multi_model_config = config.multi_model
        if multi_model_config is None:
            multi_model_config = MultiModelConfig(models=[], use_parallel=False) #FIXME: set default value

        super().__init__(
            name="corrector",
            config=config,
            mcp=mcp,
            multi_model_config=multi_model_config,
        )

        # Load corrector models from config
        self._corrector_models = []
        if multi_model_config and multi_model_config.models:
            self._corrector_models = multi_model_config.models

    async def evaluate(
        self,
        state: SurveyState,
        section_name: Optional[str] = None,
    ) -> EvaluationRecord:
        """Legacy evaluate method - returns placeholder for compatibility.

        According to Plan v3, Corrector does not produce independent scores.
        Use process() for multi-model voting correction.

        Args:
            state: The current workflow state.
            section_name: Optional specific section to evaluate.

        Returns:
            Placeholder EvaluationRecord.
        """
        return EvaluationRecord(
            agent_name=self.name,
            dimension="correction",
            score=5.0,
            reasoning="Corrector no longer produces independent scores. Use process() for voting correction.",
            evidence=None,
            confidence=1.0,
        )

    async def process(self, state: SurveyState) -> Dict[str, Any]:
        """Perform multi-model voting correction on high-risk sub-dimensions.

        According to Plan v3:
        - Only votes on 7 high-risk sub-dimensions: V4, E2, E3, E4, R2, R3, R4
        - Skips low-risk dimensions: V1, V2 (threshold-based), E1, R1
        - Returns CorrectorOutput with correction records
        - Does NOT modify original agent_outputs

        Args:
            state: Current workflow state with agent_outputs.

        Returns:
            Dict containing corrector_output.
        """
        import json
        from statistics import median

        agent_outputs = state.get("agent_outputs", {})
        tool_evidence = state.get("tool_evidence", {})

        if not agent_outputs:
            logger.warning("No agent_outputs found in state")
            return {
                "corrector_output": {
                    "corrections": {},
                    "skipped_dimensions": [],
                    "skip_reason": "no agent_outputs",
                    "total_model_calls": 0,
                    "failed_calls": 0,
                }
            }

        # Identify dimensions to vote on
        dimensions_to_vote = self._identify_voting_dimensions(agent_outputs, tool_evidence)
        skipped = self._get_skipped_dimensions(agent_outputs, tool_evidence)

        logger.info(f"Corrector voting on {len(dimensions_to_vote)} dimensions: {dimensions_to_vote}")
        logger.info(f"Skipping {len(skipped)} low-risk dimensions: {skipped}")

        # Perform voting for each dimension
        corrections: Dict[str, CorrectionRecord] = {}
        total_calls = 0
        failed_calls = 0

        if dimensions_to_vote and self._corrector_models:
            # Create voting tasks for all dimensions x models
            task_meta = []  # list of (dim_id, model_cfg)
            coros = []
            for dim_id in dimensions_to_vote:
                dim_info = self._get_dimension_info(dim_id, agent_outputs)
                for model_cfg in self._corrector_models:
                    task_meta.append((dim_id, model_cfg))
                    coros.append(self._vote_dimension(dim_id, dim_info, model_cfg))

            # Execute all voting tasks concurrently with gather
            if coros:
                progress = create_progress()
                with progress:
                    progress_task = progress.add_task("[cyan]多模型投票", total=len(coros))

                    # Collect results as they complete
                    dim_results: Dict[str, List[tuple]] = {}
                    results = await asyncio.gather(*coros, return_exceptions=True)
                    for (dim_id, model_cfg), result in zip(task_meta, results):
                        if isinstance(result, Exception):
                            logger.warning(f"Model {model_cfg.model} failed for {dim_id}: {result}")
                            failed_calls += 1
                        else:
                            if dim_id not in dim_results:
                                dim_results[dim_id] = []
                            dim_results[dim_id].append((model_cfg.model, result))
                            total_calls += 1
                        progress.update(progress_task, advance=1)

                # Aggregate results for each dimension
                for dim_id, model_results in dim_results.items():
                    if len(model_results) >= 2:  # Need at least 2 models
                        scores = [r[1] for r in model_results]
                        models_used = [r[0] for r in model_results]

                        corrected_score = median(scores)
                        std = statistics.stdev(scores) if len(scores) > 1 else 0.0

                        # Get original score
                        dim_info = self._get_dimension_info(dim_id, agent_outputs)
                        original_score = dim_info.get("score", 5.0)
                        original_agent = dim_info.get("agent", "unknown")

                        variance: VarianceRecord = {
                            "models_used": models_used,
                            "scores": scores,
                            "median": corrected_score,
                            "std": std,
                            "high_disagreement": std > 1.0 or (max(scores) - min(scores)) > 2,
                        }

                        corrections[dim_id] = {
                            "original_agent": original_agent,
                            "original_score": original_score,
                            "corrected_score": corrected_score,
                            "variance": variance,
                        }
                        logger.info(f"  {dim_id}: {original_score} -> {corrected_score} (std={std:.2f})")
                    else:
                        logger.warning(f"  {dim_id}: insufficient model results, skipping")

        corrector_output: CorrectorOutput = {
            "corrections": corrections,
            "skipped_dimensions": skipped,
            "skip_reason": "low hallucination_risk, threshold-based scoring",
            "total_model_calls": total_calls,
            "failed_calls": failed_calls,
        }

        return {"corrector_output": corrector_output}

    def _identify_voting_dimensions(self, agent_outputs: Dict[str, AgentOutput], tool_evidence: Dict[str, Any]) -> List[str]:
        """Identify which sub-dimensions need voting using registry-driven approach.

        Args:
            agent_outputs: The agent_outputs dict from state.
            tool_evidence: The tool_evidence dict for checking C6.auto_fail.

        Returns:
            List of sub_ids that need multi-model voting.
        """
        targets = get_corrector_targets(agent_outputs, tool_evidence)
        # Flatten to list of sub_ids
        voting_dims = []
        for agent_name, sub_ids in targets.items():
            voting_dims.extend(sub_ids)
        return voting_dims

    def _get_skipped_dimensions(self, agent_outputs: Dict[str, AgentOutput], tool_evidence: Dict[str, Any]) -> List[str]:
        """Get list of dimensions that are skipped using registry-driven approach.

        Args:
            agent_outputs: The agent_outputs dict from state.
            tool_evidence: The tool_evidence dict for checking C6.auto_fail.

        Returns:
            List of sub_ids that are skipped.
        """
        targets = get_corrector_targets(agent_outputs, tool_evidence)
        # All sub-dimensions across all agents
        all_sub_ids = set()
        for agent_def in AGENT_REGISTRY.values():
            for sub_dim in agent_def.sub_dimensions:
                all_sub_ids.add(sub_dim.sub_id)
        # Voting dims from registry
        voting_dims = set()
        for sub_ids in targets.values():
            voting_dims.update(sub_ids)
        # Skipped = all - voting
        return list(all_sub_ids - voting_dims)

    def _get_dimension_info(self, dim_id: str, agent_outputs: Dict[str, AgentOutput]) -> Dict[str, Any]:
        """Get dimension info from agent_outputs."""
        for agent_name, output in agent_outputs.items():
            if dim_id in output.get("sub_scores", {}):
                sub_score = output["sub_scores"][dim_id]
                return {
                    "score": sub_score.get("score", 5.0),
                    "agent": agent_name,
                    "tool_evidence": sub_score.get("tool_evidence", {}),
                    "llm_reasoning": sub_score.get("llm_reasoning", ""),
                }
        return {"score": 5.0, "agent": "unknown", "tool_evidence": {}, "llm_reasoning": ""}

    async def _vote_dimension(
        self,
        dim_id: str,
        dim_info: Dict[str, Any],
        model_cfg: Any,
    ) -> float:
        """Vote on a single dimension using a specific model."""
        import re, json
        rubric = self._get_rubric(dim_id)
        tool_evidence = dim_info.get("tool_evidence", {})
        llm_reasoning = dim_info.get("llm_reasoning", "")

        prompt = f"""You are re-scoring a survey evaluation dimension as part of a multi-model voting process.

## Dimension: {dim_id}

## Rubric:
{rubric}

## Tool Evidence:
{json.dumps(tool_evidence, indent=2) if tool_evidence else "No tool evidence available."}

## Original Agent Assessment:
Agent: {dim_info.get('agent', 'unknown')}
Score: {dim_info.get('score', 5.0)}/5
Reasoning: {llm_reasoning[:500] if llm_reasoning else 'No reasoning available.'}

Based on the rubric, tool evidence, and your own judgment, provide your score (1-5).
Output ONLY a JSON object: {{"score": <number>}}
"""
        lc_messages = [HumanMessage(content=prompt)]
        try:
            # Find the matching LLM in the pool by model name
            llm = None
            for key, pool_llm in self._llm_pool.items():
                if model_cfg.model in key:
                    llm = pool_llm
                    break
            if llm is None:
                llm = self.llm  # fallback to primary LLM

            response = await llm.ainvoke(lc_messages)
            content = response.content if hasattr(response, "content") else str(response)
            match = re.search(r'"score"\s*:\s*(\d+(?:\.\d+)?)', content)
            if match:
                return float(match.group(1))
            return 5.0
        except Exception as e:
            logger.warning(f"Failed to vote on {dim_id} with model {model_cfg.model}: {e}")
            raise

    def _get_rubric(self, dim_id: str) -> str:
        """Get rubric text for a dimension from AGENT_REGISTRY.

        Args:
            dim_id: Sub-dimension ID (e.g., V4, E2, R3).

        Returns:
            Rubric string for the dimension.
        """
        for agent_def in AGENT_REGISTRY.values():
            for sub_dim in agent_def.sub_dimensions:
                if sub_dim.sub_id == dim_id:
                    return sub_dim.rubric
        return "Rate this dimension from 1-5 based on quality."

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
        vote_info = (
            f"[Based on {len(scores)} model evaluations with majority voting. Scores: {scores}]"
        )

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
        # Max std for range of 5 is about 1.25
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
                        score = max(0.0, min(5.0, score))
                    except ValueError:
                        pass

            if any(
                kw in line_lower
                for kw in ["over-represented", "under-represented", "bias", "imbalance"]
            ):
                if evidence is None:
                    evidence = line

        return score, reasoning, evidence

    async def compute_variance(
        self,
        agent_outputs: Dict[str, Any],
        state: SurveyState,
    ) -> Dict[str, Any]:
        """Compute variance for LLM-involved metrics across agents.

        This method:
        1. Takes agent_outputs from Verifier/Expert/Reader
        2. For each sub-dimension, calls multiple models to re-score
        3. Computes variance statistics
        4. Returns updated agent_outputs with variance info

        Args:
            agent_outputs: Dict of agent_name -> AgentOutput
            state: Current workflow state

        Returns:
            Updated agent_outputs with variance information filled in.
        """
        if not self._llm_pool:
            logger.warning("No LLM pool configured, skipping variance computation")
            return agent_outputs

        # Collect all sub-scores that need variance computation
        subscores_to_compute = []
        for agent_name, output in agent_outputs.items():
            for sub_id, sub_score in output.get("sub_scores", {}).items():
                if sub_score.get("llm_involved", True):
                    subscores_to_compute.append(
                        {
                            "agent": agent_name,
                            "sub_id": sub_id,
                            "sub_score": sub_score,
                        }
                    )

        if not subscores_to_compute:
            logger.info("No LLM-involved sub-scores to compute variance for")
            return agent_outputs

        logger.info(f"Computing variance for {len(subscores_to_compute)} sub-scores")

        # For each sub-score, call multiple models to compute variance
        for item in subscores_to_compute:
            agent_name = item["agent"]
            sub_id = item["sub_id"]
            sub_score = item["sub_score"]

            # Build prompt for re-scoring
            prompt = self._build_rescore_prompt(
                agent_name=agent_name,
                sub_id=sub_id,
                sub_score=sub_score,
                state=state,
            )

            messages = self._create_messages(
                self._load_prompt(
                    "corrector", agent_name="corrector", section="variance_computation"
                ),
                prompt,
            )

            # Call multiple models
            results = await self._call_llm_pool(messages)

            # Extract scores from each model
            scores = []
            for result in results:
                if "error" in result:
                    continue
                try:
                    parsed = self._parse_corrector_response(result.get("response", ""))
                    scores.append(parsed[0])
                except Exception as e:
                    logger.warning(f"Failed to parse model response: {e}")

            if len(scores) >= 2:
                # Compute variance
                variance_info = {
                    "models_used": [r.get("model", "unknown") for r in results if "error" not in r],
                    "scores": scores,
                    "aggregated": statistics.median(scores),
                    "std": statistics.stdev(scores) if len(scores) > 1 else 0.0,
                    "range": [min(scores), max(scores)],
                }

                # Update the sub_score with variance
                agent_outputs[agent_name]["sub_scores"][sub_id]["variance"] = variance_info

        return agent_outputs

    def _build_rescore_prompt(
        self,
        agent_name: str,
        sub_id: str,
        sub_score: Dict[str, Any],
        state: SurveyState,
    ) -> str:
        """Build a prompt for re-scoring a sub-dimension.

        Args:
            agent_name: Original agent name (verifier, expert, reader)
            sub_id: Sub-dimension ID (e.g., V1, E1, R1)
            sub_score: Current sub-score data
            state: Current workflow state

        Returns:
            Prompt string for re-scoring.
        """
        # Get relevant evidence
        tool_evidence = sub_score.get("tool_evidence", {})
        llm_reasoning = sub_score.get("llm_reasoning", "")

        prompt = f"""Please re-evaluate the following sub-dimension:

Agent: {agent_name}
Sub-dimension: {sub_id}

Previous reasoning:
{llm_reasoning}

Tool evidence used:
{tool_evidence}

Please provide a score from 1-5 for this sub-dimension and explain your reasoning.
Output in JSON format: {{"score": <number>, "reasoning": "<explanation>"}}
"""
        return prompt
