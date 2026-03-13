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
    """Pure mathematical aggregation of evaluation scores.

    This function:
    1. Collects agent outputs from state
    2. Separates deterministic vs LLM-involved metrics
    3. Calculates weighted scores
    4. Computes variance for LLM metrics
    5. Returns aggregated scores WITHOUT generating markdown

    Args:
        state: The current workflow state containing agent_outputs.

    Returns:
        Dict with aggregated scores, separated deterministic/LLM scores, and variance info.
    """
    # Try to get structured agent outputs first
    agent_outputs = state.get("agent_outputs", {})

    # Fallback to legacy evaluations format
    evaluations = state.get("evaluations", [])

    if not agent_outputs and not evaluations:
        logger.warning("No evaluations to aggregate")
        return {
            "aggregated_scores": {},
            "deterministic_score": None,
            "llm_score": None,
            "overall_score": 0.0,
            "consensus_reached": True,
        }

    # Aggregate from new AgentOutput format
    if agent_outputs:
        result = _aggregate_from_agent_outputs(agent_outputs)
    else:
        # Fallback to legacy format
        result = _aggregate_from_evaluations(evaluations)

    return result


def _aggregate_from_agent_outputs(agent_outputs: Dict[str, AgentOutput]) -> Dict[str, Any]:
    """Aggregate scores from structured AgentOutput format.

    This separates deterministic metrics from LLM-involved metrics
    and computes variance for each.

    Args:
        agent_outputs: Dict of agent_name -> AgentOutput

    Returns:
        Aggregated scores with separation of deterministic/LLM metrics.
    """
    # Collect all sub-scores
    all_sub_scores = []
    deterministic_scores = []
    llm_scores = []

    for agent_name, output in agent_outputs.items():
        dimension = output.get("dimension", agent_name)

        for sub_id, sub_score in output.get("sub_scores", {}).items():
            score_data = {
                "agent": agent_name,
                "dimension": dimension,
                "sub_id": sub_id,
                "score": sub_score.get("score", 5.0),
                "llm_involved": sub_score.get("llm_involved", True),
                "variance": sub_score.get("variance"),
            }
            all_sub_scores.append(score_data)

            if score_data["llm_involved"]:
                llm_scores.append(score_data["score"])
            else:
                deterministic_scores.append(score_data["score"])

    # Calculate overall scores
    all_scores = [s["score"] for s in all_sub_scores]

    if not all_scores:
        return {
            "aggregated_scores": {},
            "deterministic_score": None,
            "llm_score": None,
            "overall_score": 0.0,
            "consensus_reached": True,
        }

    overall_score = mean(all_scores)

    # Calculate deterministic and LLM scores separately
    deterministic_score = mean(deterministic_scores) if deterministic_scores else None
    llm_score = mean(llm_scores) if llm_scores else None

    # Compute variance for LLM scores
    llm_variance = None
    if len(llm_scores) > 1:
        llm_variance = {
            "std": stdev(llm_scores),
            "range": [min(llm_scores), max(llm_scores)],
            "n_scores": len(llm_scores),
        }

    # Group by dimension for detailed report
    dimension_scores = {}
    for agent_name, output in agent_outputs.items():
        dimension = output.get("dimension", agent_name)
        dimension_scores[dimension] = {
            "overall": output.get("overall_score", 0.0),
            "confidence": output.get("confidence", 0.5),
            "sub_scores": output.get("sub_scores", {}),
        }

    return {
        "aggregated_scores": dimension_scores,
        "deterministic_score": deterministic_score,
        "llm_score": llm_score,
        "llm_variance": llm_variance,
        "overall_score": overall_score,
        "total_metrics": len(all_sub_scores),
        "deterministic_count": len(deterministic_scores),
        "llm_count": len(llm_scores),
        "consensus_reached": True,
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
    """Generate markdown report with variance-aware display.

    This function creates a final report that:
    1. Shows deterministic metrics with solid values
    2. Shows LLM metrics with error bars/variance display
    3. Includes diagnostic information

    Args:
        aggregation_result: Result from aggregate_scores
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
    lines.append(f"## Overall Score: {overall:.2f}/10")
    lines.append("")
    lines.append(_get_score_grade(overall))
    lines.append("")

    # Score summary with variance indication
    lines.extend(
        [
            "## Score Summary",
            "",
            "| Dimension | Score | Confidence | Type |",
            "|-----------|-------|------------|------|",
        ]
    )

    aggregated = aggregation_result.get("aggregated_scores", {})
    for dim, data in aggregated.items():
        score = data.get("overall", data.get("score", 0.0))
        conf = data.get("confidence", 0.0)

        # Determine if this is deterministic or LLM
        sub_scores = data.get("sub_scores", {})
        if sub_scores:
            has_deterministic = any(not s.get("llm_involved", True) for s in sub_scores.values())
            has_llm = any(s.get("llm_involved", True) for s in sub_scores.values())

            if has_deterministic and has_llm:
                metric_type = "Mixed"
            elif has_deterministic:
                metric_type = "Deterministic"
            else:
                metric_type = "LLM"
        else:
            metric_type = "LLM"  # Legacy format

        lines.append(f"| {dim.title()} | {score:.2f}/10 | {conf:.2f} | {metric_type} |")

    lines.append("")

    # Variance section for LLM metrics
    llm_variance = aggregation_result.get("llm_variance")
    if llm_variance:
        lines.extend(
            [
                "## LLM Metrics Variance",
                "",
                f"- **Standard Deviation**: {llm_variance.get('std', 'N/A'):.2f}",
                f"- **Score Range**: [{llm_variance.get('range', ['N/A', 'N/A'])[0]:.1f} - {llm_variance.get('range', ['N/A', 'N/A'])[1]:.1f}]",
                f"- **Number of Metrics**: {llm_variance.get('n_scores', 'N/A')}",
                "",
            ]
        )

    # Separate deterministic vs LLM scores if available
    det_score = aggregation_result.get("deterministic_score")
    llm_score = aggregation_result.get("llm_score")

    if det_score is not None or llm_score is not None:
        lines.extend(
            [
                "## Score Breakdown",
                "",
            ]
        )
        if det_score is not None:
            lines.append(f"- **Deterministic Metrics Score**: {det_score:.2f}/10 (solid value)")
        if llm_score is not None:
            var_info = ""
            if llm_variance:
                var_info = f" ± {llm_variance.get('std', 0):.2f}"
            lines.append(f"- **LLM Metrics Score**: {llm_score:.2f}/10{var_info} (with variance)")
        lines.append("")

    # Detailed sub-scores if available
    has_sub_scores = any(data.get("sub_scores") for data in aggregated.values())

    if has_sub_scores:
        lines.extend(["", "## Detailed Sub-Scores", ""])

        for dim, data in aggregated.items():
            sub_scores = data.get("sub_scores", {})
            if not sub_scores:
                continue

            lines.append(f"### {dim.title()}")
            lines.append("")

            for sub_id, sub_data in sub_scores.items():
                score = sub_data.get("score", 0.0)
                llm_involved = sub_data.get("llm_involved", True)
                reasoning = sub_data.get("llm_reasoning", "")

                # Add indicator for metric type
                indicator = "✓" if not llm_involved else "🤖"
                lines.append(f"**{indicator} {sub_id}**: {score:.1f}/5")

                if reasoning:
                    # Truncate reasoning
                    if len(reasoning) > 200:
                        reasoning = reasoning[:200] + "..."
                    lines.append(f"  - {reasoning}")
                lines.append("")

    # Recommendations
    lines.extend(["", "## Recommendations", ""])
    recommendations = _generate_recommendations(aggregated, overall)
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


def _get_score_grade(score: float) -> str:
    """Convert numerical score to letter grade and description."""
    if score >= 9:
        return "**Grade**: A - Excellent\n\nThe survey demonstrates outstanding quality across all evaluation dimensions."
    elif score >= 8:
        return "**Grade**: B - Good\n\nThe survey shows strong quality with minor areas for improvement."
    elif score >= 7:
        return "**Grade**: C - Satisfactory\n\nThe survey meets basic requirements but has notable weaknesses."
    elif score >= 6:
        return "**Grade**: D - Needs Improvement\n\nThe survey has significant issues that should be addressed."
    else:
        return (
            "**Grade**: F - Unsatisfactory\n\nThe survey fails to meet minimum quality standards."
        )


def _generate_recommendations(
    aggregated: Dict[str, Dict],
    overall_score: float,
) -> List[str]:
    """Generate recommendations based on evaluation results."""
    recommendations = []

    # Check each dimension for low scores
    low_score_dims = []
    for dim, data in aggregated.items():
        score = data.get("overall", data.get("score", 0.0))
        if score < 7.0:
            low_score_dims.append((dim, score))

    if low_score_dims:
        recommendations.append("**Areas Requiring Attention:**")
        for dim, score in low_score_dims:
            recommendations.append(
                f"- **{dim.title()}** (Score: {score:.1f}/10) - Consider improving this aspect."
            )

    # Check for high variance in sub-scores
    high_variance_dims = []
    for dim, data in aggregated.items():
        sub_scores = data.get("sub_scores", {})
        if sub_scores:
            # Check for metrics with high variance
            for sub_id, sub_data in sub_scores.items():
                variance = sub_data.get("variance")
                if variance and variance.get("std", 0) > 1.0:
                    high_variance_dims.append(f"{dim}.{sub_id}")
                    break

    if high_variance_dims:
        recommendations.append("")
        recommendations.append("**High Variance Detected:**")
        recommendations.append("The following metrics show high disagreement between models:")
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
