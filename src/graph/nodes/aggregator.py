"""Score Aggregation Node.

Aggregates multiple evaluation scores into final assessment.
Generates comprehensive markdown reports.

# TODO: 重构职责
# - 接收 ReporterAgent 输出的结构化 JSON
# - 解析 JSON 中的维度评分数据
# - 进行统计计算（均值、方差、加权平均）
# - 填充评分表格
# - 渲染最终 Markdown 报告
#
# 新接口设计:
# async def aggregate_scores(state: SurveyState, reporter_output: dict = None):
#     # reporter_output 优先，否则回退到 state["evaluations"]
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from statistics import mean, median, stdev

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
    source_pdf = state.get("source_pdf_path", "")
    metadata = state.get("metadata", {})

    if not evaluations:
        logger.warning("No evaluations to aggregate")
        return {
            "final_report_md": "# SurveyMAE Evaluation Report\n\nNo evaluations were performed.",
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
            "score_range": {
                "min": round(min(scores), 2),
                "max": round(max(scores), 2),
            },
            "agents": [e.get("agent_name") for e in evals],
            "confidence": round(mean(confidences), 2),
        }

    # Calculate overall score (weighted by confidence)
    total_weight = sum(d["confidence"] for d in aggregated.values())
    overall_score = sum(d["score"] * d["confidence"] for d in aggregated.values()) / total_weight if total_weight > 0 else 0

    # Generate markdown report
    report = _generate_report(
        aggregated=aggregated,
        overall_score=overall_score,
        evaluations=evaluations,
        source_pdf=source_pdf,
        metadata=metadata,
    )

    return {
        "final_report_md": report,
        "consensus_reached": True,
        "aggregated_scores": aggregated,
        "overall_score": round(overall_score, 2),
    }


def _generate_report(
    aggregated: Dict[str, Dict],
    overall_score: float,
    evaluations: List[EvaluationRecord],
    source_pdf: str,
    metadata: Dict[str, str],
) -> str:
    """Generate a comprehensive markdown evaluation report.

    Args:
        aggregated: Dictionary of dimension-to-score mappings.
        overall_score: The overall evaluation score.
        evaluations: List of individual evaluation records.
        source_pdf: Source PDF path.
        metadata: Survey metadata.

    Returns:
        Markdown formatted report string.
    """
    lines = [
        "# SurveyMAE Evaluation Report",
        "",
        f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"**Source**: {source_pdf or 'N/A'}",
        "",
        f"## Overall Score: {overall_score:.2f}/10",
        "",
        _get_score_grade(overall_score),
        "",
    ]

    # Score summary table
    lines.extend([
        "## Score Summary",
        "",
        "| Dimension | Score | Confidence | # Agents |",
        "|-----------|-------|------------|----------|",
    ])

    for dim, data in aggregated.items():
        conf = data.get("confidence", 0)
        num = data.get("num_agents", 0)
        lines.append(f"| {dim} | {data['score']:.2f}/10 | {conf:.2f} | {num} |")

    lines.extend(["", "## Detailed Dimension Analysis", ""])

    # Detailed analysis per dimension
    for dim, data in aggregated.items():
        lines.extend([
            f"### {dim.title()}",
            "",
            f"**Score**: {data['score']:.2f}/10",
            "",
        ])

        # Statistics
        stats = data.get("statistics", {})
        if stats:
            lines.extend([
                f"- Mean: {stats.get('mean', 'N/A')}",
                f"- Median: {stats.get('median', 'N/A')}",
                f"- Range: [{stats.get('min', 'N/A')} - {stats.get('max', 'N/A')}]",
                f"- Std Dev: {stats.get('std', 'N/A')}",
                "",
            ])

        # Agent contributions
        lines.append(f"**Evaluating Agents**: {', '.join(data['agents'])}")
        lines.append("")

    # Detailed agent evaluations
    lines.extend(["", "## Agent Evaluations", ""])

    # Group by agent
    agent_evals: Dict[str, List[EvaluationRecord]] = {}
    for eval_record in evaluations:
        agent = eval_record.get("agent_name", "Unknown")
        if agent not in agent_evals:
            agent_evals[agent] = []
        agent_evals[agent].append(eval_record)

    for agent, agent_evaluations in agent_evals.items():
        lines.extend([
            f"### {agent.title()}Agent",
            "",
        ])

        for eval_record in agent_evaluations:
            dim = eval_record.get("dimension", "unknown")
            score = eval_record.get("score", 0.0)
            reasoning = eval_record.get("reasoning", "")
            evidence = eval_record.get("evidence")
            confidence = eval_record.get("confidence", 0.0)

            lines.extend([
                f"#### {dim.title()} (Score: {score:.1f}/10, Confidence: {confidence:.2f})",
                "",
            ])

            # Truncate reasoning if too long
            if reasoning:
                if len(reasoning) > 1000:
                    reasoning = reasoning[:1000] + "..."
                lines.extend([
                    f"**Assessment**: {reasoning}",
                    "",
                ])

            if evidence:
                if len(evidence) > 500:
                    evidence = evidence[:500] + "..."
                lines.extend([
                    f"**Evidence**: {evidence}",
                    "",
                ])

    # Recommendations
    lines.extend(["", "## Recommendations", ""])
    recommendations = _generate_recommendations(aggregated, overall_score)
    lines.extend(recommendations)

    # Footer
    lines.extend([
        "",
        "---",
        "",
        "*Report generated by SurveyMAE - Multi-Agent Survey Evaluation Framework*",
    ])

    return "\n".join(lines)


def _get_score_grade(score: float) -> str:
    """Convert numerical score to letter grade and description.

    Args:
        score: Numerical score [0-10].

    Returns:
        Grade description string.
    """
    if score >= 9:
        return "**Grade**: A - Excellent\n\nThe survey demonstrates outstanding quality across all evaluation dimensions."
    elif score >= 8:
        return "**Grade**: B - Good\n\nThe survey shows strong quality with minor areas for improvement."
    elif score >= 7:
        return "**Grade**: C - Satisfactory\n\nThe survey meets basic requirements but has notable weaknesses."
    elif score >= 6:
        return "**Grade**: D - Needs Improvement\n\nThe survey has significant issues that should be addressed."
    else:
        return "**Grade**: F - Unsatisfactory\n\nThe survey fails to meet minimum quality standards."


def _generate_recommendations(
    aggregated: Dict[str, Dict],
    overall_score: float,
) -> List[str]:
    """Generate recommendations based on evaluation results.

    Args:
        aggregated: Aggregated dimension scores.
        overall_score: Overall evaluation score.

    Returns:
        List of recommendation strings.
    """
    recommendations = []

    # Check each dimension for low scores
    low_score_dims = []
    for dim, data in aggregated.items():
        if data["score"] < 7.0:
            low_score_dims.append((dim, data["score"]))

    if low_score_dims:
        recommendations.append("**Areas Requiring Attention:**")
        for dim, score in low_score_dims:
            recommendations.append(f"- **{dim.title()}** (Score: {score:.1f}/10) - Consider improving this aspect.")

    # Check for high variance
    high_variance_dims = []
    for dim, data in aggregated.items():
        stats = data.get("statistics", {})
        if stats.get("std", 0) > 1.5:
            high_variance_dims.append(dim)

    if high_variance_dims:
        recommendations.append("")
        recommendations.append("**High Variance Detected:**")
        recommendations.append("The following dimensions show high disagreement between evaluators:")
        for dim in high_variance_dims:
            recommendations.append(f"- {dim.title()}")

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
