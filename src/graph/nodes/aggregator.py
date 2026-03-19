"""Score Aggregation Node.

This module provides:
1. aggregate_scores - Pure mathematical aggregation (calculates weighted scores,
   separates deterministic vs LLM-involved metrics, computes variance)
2. generate_report - Report generation with variance display (deterministic metrics
   with solid lines, LLM metrics with error bars)
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from statistics import mean, median, stdev

from src.core.state import SurveyState, EvaluationRecord, AgentOutput

logger = logging.getLogger(__name__)

# Default weights for agent dimensions
DEFAULT_DIMENSION_WEIGHTS = {
    "factuality": 1.0,  # Verifier
    "depth": 1.0,  # Expert
    "coverage": 1.0,  # Reader
    "bias": 0.8,  # Corrector
}


async def aggregate_scores(state: SurveyState) -> Dict[str, Any]:
    """Pure mathematical aggregation of evaluation scores (v3 weighted).

    This function:
    1. Collects agent outputs from state
    2. Reads corrector_output for corrected scores
    3. Applies weighted aggregation
    4. Returns aggregated scores WITHOUT generating markdown

    Args:
        state: The current workflow state containing agent_outputs and corrector_output.

    Returns:
        Dict with aggregated scores (v3 format).
    """
    # Get agent outputs and corrector output
    agent_outputs = state.get("agent_outputs", {})
    corrector_output = state.get("corrector_output")

    # Fallback to legacy evaluations format
    evaluations = state.get("evaluations", [])

    if not agent_outputs and not evaluations:
        logger.warning("No evaluations to aggregate")
        return {
            "dimension_scores": {},
            "deterministic_metrics": {},
            "overall_score": 0.0,
            "grade": "F",
            "total_weight": 0.0,
        }

    # Aggregate from new AgentOutput format (v3)
    if agent_outputs:
        result = _aggregate_from_agent_outputs(agent_outputs, corrector_output)
    else:
        # Fallback to legacy format
        result = _aggregate_from_evaluations(evaluations)

    return result


def _get_grade(score: float) -> str:
    """Convert numerical score to letter grade."""
    if score >= 8.5:
        return "A"
    elif score >= 7.5:
        return "B"
    elif score >= 6.5:
        return "C"
    elif score >= 5.5:
        return "D"
    else:
        return "F"


def _aggregate_from_agent_outputs(
    agent_outputs: Dict[str, AgentOutput],
    corrector_output: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Aggregate scores from structured AgentOutput format (v3 weighted aggregation).

    This function:
    1. Reads corrector_output to get corrected scores
    2. Uses corrected scores if available, otherwise uses original scores
    3. Applies weighted aggregation based on config weights
    4. Computes overall score on 0-10 scale

    Args:
        agent_outputs: Dict of agent_name -> AgentOutput
        corrector_output: Optional corrector output with correction records

    Returns:
        Aggregated scores with weighted aggregation.
    """
    from src.core.config import load_config

    # Load weights from config
    weights_config = {}
    try:
        cfg = load_config()
        weights_config = getattr(cfg.aggregation, "weights", {}) if hasattr(cfg, "aggregation") else {}
    except Exception:
        pass

    # Default weights (fallback)
    default_weights = {
        "V1_citation_existence": 1.2,
        "V2_citation_claim_alignment": 1.5,
        "V4_internal_consistency": 1.0,
        "E1_foundational_coverage": 1.3,
        "E2_classification_reasonableness": 1.0,
        "E3_technical_accuracy": 1.2,
        "E4_critical_analysis_depth": 1.3,
        "R1_timeliness": 1.0,
        "R2_information_balance": 0.8,
        "R3_structural_clarity": 0.8,
        "R4_writing_quality": 0.7,
    }

    # Merge configs
    weights = {**default_weights, **weights_config}

    # Get corrections from corrector_output
    corrections = {}
    if corrector_output:
        corrections = corrector_output.get("corrections", {})

    # Collect all sub-scores with correction
    dimension_scores = {}  # dim_id -> DimensionScore
    all_scores_with_weights = []

    for agent_name, output in agent_outputs.items():
        dimension = output.get("dimension", agent_name)

        for sub_id, sub_score in output.get("sub_scores", {}).items():
            # Check if this dimension has a correction
            if sub_id in corrections:
                final_score = corrections[sub_id]["corrected_score"]
                source = "corrected"
                variance = corrections[sub_id].get("variance")
            else:
                final_score = sub_score.get("score", 5.0)
                source = "original"
                variance = sub_score.get("variance")

            weight = weights.get(sub_id, 1.0)
            hallucination_risk = sub_score.get("hallucination_risk", "medium")

            dimension_scores[sub_id] = {
                "dim_id": sub_id,
                "final_score": final_score,
                "source": source,
                "agent": agent_name,
                "hallucination_risk": hallucination_risk,
                "variance": variance,
                "weight": weight,
            }

            # For weighted average: score * weight
            all_scores_with_weights.append((final_score, weight))

    if not all_scores_with_weights:
        return {
            "dimension_scores": {},
            "deterministic_metrics": {},
            "overall_score": 0.0,
            "grade": "F",
            "total_weight": 0.0,
        }

    # Weighted average -> 0-10 scale
    weighted_sum = sum(score * weight for score, weight in all_scores_with_weights)
    total_weight = sum(weight for _, weight in all_scores_with_weights)
    overall_score = (weighted_sum / total_weight) * 2 if total_weight > 0 else 0.0  # 1-5 -> 0-10

    # Determine grade
    grade = _get_grade(overall_score)

    return {
        "dimension_scores": dimension_scores,
        "deterministic_metrics": {},  # First-layer metrics stored separately
        "overall_score": round(overall_score, 2),
        "grade": grade,
        "total_weight": round(total_weight, 2),
    }


def _aggregate_from_evaluations(evaluations: List[EvaluationRecord]) -> Dict[str, Any]:
    """Aggregate scores from legacy EvaluationRecord format.

    Args:
        evaluations: List of EvaluationRecord

    Returns:
        Aggregated scores.
    """
    if not evaluations:
        return {
            "aggregated_scores": {},
            "deterministic_score": None,
            "llm_score": None,
            "overall_score": 0.0,
            "consensus_reached": True,
        }

    # Group by dimension
    dim_scores: Dict[str, List[EvaluationRecord]] = {}
    for eval_record in evaluations:
        dim = eval_record.get("dimension", "unknown")
        if dim not in dim_scores:
            dim_scores[dim] = []
        dim_scores[dim].append(eval_record)

    # Calculate aggregated scores per dimension
    aggregated: Dict[str, Dict] = {}
    all_scores = []
    deterministic_scores = []
    llm_scores = []

    for dim, evals in dim_scores.items():
        scores = [e.get("score", 5.0) for e in evals]
        confidences = [e.get("confidence", 0.5) for e in evals]

        # Weighted average based on confidence
        weighted_sum = sum(s * c for s, c in zip(scores, confidences))
        total_conf = sum(confidences)
        avg_score = weighted_sum / total_conf if total_conf > 0 else mean(scores)

        # Calculate score statistics
        score_stats = {
            "mean": round(mean(scores), 2),
            "median": round(median(scores), 2),
            "min": round(min(scores), 2),
            "max": round(max(scores), 2),
            "std": round(stdev(scores), 2) if len(scores) > 1 else 0.0,
        }

        aggregated[dim] = {
            "score": round(avg_score, 2),
            "statistics": score_stats,
            "num_agents": len(evals),
            "confidence": round(mean(confidences), 2),
        }

        all_scores.append(avg_score)
        # Legacy format assumes all are LLM-involved
        llm_scores.append(avg_score)

    # Calculate overall score
    overall_score = mean(all_scores) if all_scores else 0.0
    llm_score = mean(llm_scores) if llm_scores else None

    # Compute variance
    llm_variance = None
    if len(llm_scores) > 1:
        llm_variance = {
            "std": stdev(llm_scores),
            "range": [min(llm_scores), max(llm_scores)],
            "n_scores": len(llm_scores),
        }

    return {
        "aggregated_scores": aggregated,
        "deterministic_score": None,  # Not available in legacy format
        "llm_score": llm_score,
        "llm_variance": llm_variance,
        "overall_score": overall_score,
        "total_metrics": len(all_scores),
        "deterministic_count": 0,
        "llm_count": len(llm_scores),
        "consensus_reached": True,
    }


def generate_report(aggregation_result: Dict[str, Any], state: SurveyState) -> str:
    """Generate markdown report with variance-aware display (v3 format).

    This function creates a final report that:
    1. Shows all dimension scores with source (original/corrected)
    2. Shows variance information for corrected dimensions
    3. Includes diagnostic information

    Args:
        aggregation_result: Result from aggregate_scores (v3 format with dimension_scores)
        state: Current workflow state

    Returns:
        Markdown formatted report.
    """
    source_pdf = state.get("source_pdf_path", "")
    metadata = state.get("metadata", {})

    lines = [
        "# SurveyMAE Evaluation Report",
        "",
        f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"**Source**: {source_pdf or 'N/A'}",
        "",
    ]

    # Overall score section
    overall = aggregation_result.get("overall_score", 0.0)
    grade = aggregation_result.get("grade", "F")
    lines.append(f"## Overall Score: {overall:.2f}/10")
    lines.append("")
    lines.append(f"**Grade**: {grade}")
    lines.append("")

    # Score summary table (v3: dimension_scores)
    lines.extend(
        [
            "## Score Summary",
            "",
            "| Dimension | Score | Source | Agent |",
            "|-----------|-------|--------|-------|",
        ]
    )

    dimension_scores = aggregation_result.get("dimension_scores", {})
    for dim_id, data in dimension_scores.items():
        score = data.get("final_score", 5.0)
        source = data.get("source", "original")
        agent = data.get("agent", "unknown")
        lines.append(f"| {dim_id} | {score:.1f}/5 | {source} | {agent} |")

    lines.append("")

    # Variance section for corrected dimensions
    corrected_dims = [(dim_id, data) for dim_id, data in dimension_scores.items()
                      if data.get("source") == "corrected"]
    if corrected_dims:
        lines.extend(
            [
                "## Variance (Multi-Model Voting)",
                "",
            ]
        )
        for dim_id, data in corrected_dims:
            variance = data.get("variance", {})
            if variance:
                std = variance.get("std", 0.0)
                scores = variance.get("scores", [])
                lines.append(f"- **{dim_id}**: scores={scores}, std={std:.2f}")
        lines.append("")

    # Recommendations
    lines.extend(["", "## Recommendations", ""])
    recommendations = _generate_recommendations(dimension_scores, overall)
    lines.extend(recommendations)

    # Footer
    lines.extend(
        [
            "",
            "---",
            "",
            "*Report generated by SurveyMAE - Multi-Agent Survey Evaluation Framework*",
        ]
    )

    return "\n".join(lines)


def _generate_recommendations(
    dimension_scores: Dict[str, Dict],
    overall_score: float,
) -> List[str]:
    """Generate recommendations based on evaluation results (v3 format)."""
    recommendations = []

    # Check each dimension for low scores
    low_score_dims = []
    for dim_id, data in dimension_scores.items():
        score = data.get("final_score", 5.0)
        # Score is on 1-5 scale, convert threshold: 7/10 * 5 = 3.5
        if score < 3.5:
            low_score_dims.append((dim_id, score))

    if low_score_dims:
        recommendations.append("**Areas Requiring Attention:**")
        for dim_id, score in low_score_dims:
            recommendations.append(
                f"- **{dim_id}** (Score: {score:.1f}/5) - Consider improving this aspect."
            )

    # Check for high variance in corrected dimensions
    high_variance_dims = []
    for dim_id, data in dimension_scores.items():
        if data.get("source") == "corrected":
            variance = data.get("variance", {})
            if variance and variance.get("high_disagreement", False):
                high_variance_dims.append(dim_id)

    if high_variance_dims:
        recommendations.append("")
        recommendations.append("**High Variance Detected:**")
        recommendations.append("The following dimensions show high disagreement between models:")
        for dim_id in high_variance_dims:
            recommendations.append(f"- {dim_id}")
        for item in high_variance_dims:
            recommendations.append(f"- {item}")

    # General recommendations
    if overall_score < 7.0:
        recommendations.append("")
        recommendations.append("**General Recommendations:**")
        recommendations.append("1. Review and address the low-scoring dimensions identified above.")
        recommendations.append("2. Consider seeking expert feedback on technical content.")
        recommendations.append("3. Verify all citations are accurate and properly formatted.")
    else:
        recommendations.append("")
        recommendations.append("**General Recommendations:**")
        recommendations.append("1. The survey is of acceptable quality.")
        recommendations.append("2. Minor improvements can be made in the areas noted above.")

    return recommendations
