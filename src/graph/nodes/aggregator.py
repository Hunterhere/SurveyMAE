"""Score Aggregation Node.

Aggregates multiple evaluation scores into final assessment.
"""

import logging
from typing import Dict, Any, List
from statistics import mean

from src.core.config import DebateConfig
from src.core.state import SurveyState, EvaluationRecord

logger = logging.getLogger(__name__)


async def aggregate_scores(state: SurveyState) -> Dict[str, Any]:
    """Aggregate evaluation scores into a final report.

    This node combines scores from all agents using configured aggregation
    strategy and generates the final evaluation report.

    Args:
        state: The current workflow state containing all evaluations.

    Returns:
        Updated state with final report and aggregated scores.
    """
    evaluations = state.get("evaluations", [])

    if not evaluations:
        logger.warning("No evaluations to aggregate")
        return {
            "final_report_md": "# SurveyMAE Evaluation Report\n\nNo evaluations were performed.",
            "consensus_reached": True,
        }

    # Group by dimension
    dim_scores: dict[str, List[EvaluationRecord]] = {}
    for eval_record in evaluations:
        dim = eval_record.get("dimension", "unknown")
        if dim not in dim_scores:
            dim_scores[dim] = []
        dim_scores[dim].append(eval_record)

    # Calculate aggregated scores per dimension
    aggregated: dict[str, dict] = {}
    for dim, evals in dim_scores.items():
        scores = [e.get("score", 5.0) for e in evals]
        confidences = [e.get("confidence", 0.5) for e in evals]

        # Weighted average based on confidence
        weighted_sum = sum(s * c for s, c in zip(scores, confidences))
        total_conf = sum(confidences)
        avg_score = weighted_sum / total_conf if total_conf > 0 else mean(scores)

        aggregated[dim] = {
            "score": round(avg_score, 2),
            "num_agents": len(evals),
            "score_range": {
                "min": round(min(scores), 2),
                "max": round(max(scores), 2),
            },
            "agents": [e.get("agent_name") for e in evals],
        }

    # Calculate overall score
    overall_score = mean([d["score"] for d in aggregated.values()])

    # Generate markdown report
    report = _generate_report(aggregated, overall_score, evaluations)

    return {
        "final_report_md": report,
        "consensus_reached": True,
    }


def _generate_report(
    aggregated: dict,
    overall_score: float,
    evaluations: List[EvaluationRecord],
) -> str:
    """Generate a markdown evaluation report.

    Args:
        aggregated: Dictionary of dimension-to-score mappings.
        overall_score: The overall evaluation score.
        evaluations: List of individual evaluation records.

    Returns:
        Markdown formatted report string.
    """
    lines = [
        "# SurveyMAE Evaluation Report",
        "",
        f"**Overall Score**: {overall_score:.2f}/10",
        "",
        "## Dimension Scores",
        "",
        "| Dimension | Score | Agents |",
        "|-----------|-------|--------|",
    ]

    for dim, data in aggregated.items():
        agents = ", ".join(data["agents"])
        lines.append(f"| {dim} | {data['score']:.2f}/10 | {agents} |")

    lines.extend(["", "## Detailed Evidence", ""])

    # Include evidence from each evaluation
    for eval_record in evaluations:
        agent = eval_record.get("agent_name", "Unknown")
        dim = eval_record.get("dimension", "unknown")
        score = eval_record.get("score", 0.0)
        reasoning = eval_record.get("reasoning", "")
        evidence = eval_record.get("evidence")

        lines.extend([
            f"### {agent} ({dim}) - Score: {score:.1f}/10",
            "",
            f"**Reasoning**: {reasoning[:500]}...",
            "",
        ])

        if evidence:
            lines.extend([f"**Evidence**: {evidence[:500]}", ""])

    return "\n".join(lines)
