"""Score Aggregation Node.

This module provides:
1. aggregate_scores - Pure mathematical aggregation (calculates weighted scores,
   separates deterministic vs LLM-involved metrics, computes variance)
2. generate_report - Report generation with variance display (deterministic metrics
   with solid lines, LLM metrics with error bars)
"""

import logging
from datetime import datetime
from statistics import mean, median, stdev
from typing import Any

from src.core.state import AgentOutput, EvaluationRecord, SurveyState

logger = logging.getLogger("surveymae.graph.nodes.aggregator")

# Default weights for agent dimensions
DEFAULT_DIMENSION_WEIGHTS = {
    "factuality": 1.0,  # Verifier
    "depth": 1.0,  # Expert
    "coverage": 1.0,  # Reader
    "bias": 0.8,  # Corrector
}


async def aggregate_scores(state: SurveyState) -> dict[str, Any]:
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
    agent_outputs: dict[str, AgentOutput],
    corrector_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
        weights_config = (
            getattr(cfg.aggregation, "weights", {}) if hasattr(cfg, "aggregation") else {}
        )
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


def _aggregate_from_evaluations(evaluations: list[EvaluationRecord]) -> dict[str, Any]:
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
    dim_scores: dict[str, list[EvaluationRecord]] = {}
    for eval_record in evaluations:
        dim = eval_record.get("dimension", "unknown")
        if dim not in dim_scores:
            dim_scores[dim] = []
        dim_scores[dim].append(eval_record)

    # Calculate aggregated scores per dimension
    aggregated: dict[str, dict] = {}
    all_scores = []
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


def generate_report(aggregation_result: dict[str, Any], state: SurveyState) -> str:
    """Generate markdown report with variance-aware display (v3 format).

    This function creates a final report that:
    1. Shows header with overall score and grade
    2. Shows evidence dashboard with deterministic metrics
    3. Shows agent assessment with tool_evidence, llm_reasoning, flagged_items
    4. Shows key findings with recommendations
    5. Shows footer

    Args:
        aggregation_result: Result from aggregate_scores (v3 format with dimension_scores)
        state: Current workflow state

    Returns:
        Markdown formatted report.
    """
    source_pdf = state.get("source_pdf_path", "")
    tool_evidence = state.get("tool_evidence", {})
    agent_outputs = state.get("agent_outputs", {})
    corrector_output = state.get("corrector_output", {})
    dimension_scores = aggregation_result.get("dimension_scores", {})

    sections = []

    # Header
    sections.append(_render_header(source_pdf, aggregation_result))

    # Section 1: Evidence Dashboard
    sections.append(_render_evidence_dashboard(tool_evidence))

    # Section 2: Agent Assessment
    sections.append(
        _render_agent_assessment(agent_outputs, dimension_scores, corrector_output, tool_evidence)
    )

    # Section 3: Key Findings
    sections.append(_render_key_findings(dimension_scores, tool_evidence, agent_outputs))

    # Footer
    sections.append(_render_footer())

    return "\n\n".join(sections)


def _render_header(source_pdf: str, aggregation_result: dict[str, Any]) -> str:
    """Render report header with overall score and grade."""
    overall = aggregation_result.get("overall_score", 0.0)
    grade = aggregation_result.get("grade", "F")

    return f"""# SurveyMAE Evaluation Report

**Source**: {source_pdf or "N/A"} | **Generated**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Overall Score**: {overall:.2f}/10 (Grade: {grade})

---"""


def _render_evidence_dashboard(tool_evidence: dict[str, Any]) -> str:
    """Render Section 1: Evidence Dashboard with deterministic metrics."""
    lines = ["## 1. Evidence Dashboard", ""]

    # Citation Integrity
    validation = tool_evidence.get("validation", {})
    c6 = tool_evidence.get("c6_alignment", {})
    analysis = tool_evidence.get("analysis", {})
    graph = tool_evidence.get("graph_analysis", {})

    # Extract values
    c3 = validation.get("C3_orphan_ref_rate")
    c5 = validation.get("C5_metadata_verify_rate")
    c6_rate = c6.get("contradiction_rate")

    # Generate notes based on thresholds
    c3_note = _threshold_note(c3, [(0.10, "Low orphan rate"), (0.20, ""), (0, "High orphan rate")])
    c5_note = _threshold_note(
        c5, [(0.90, "Strong verification"), (0.70, ""), (0, "Many unverified refs")]
    )
    c6_note = _threshold_note(
        c6_rate, [(0.9, "Auto-fail triggered"), (0.1, "Some contradictions"), (0.05, "Very few contradictions"), (0, "")]
    )

    lines.extend(
        [
            "### Citation Integrity",
            "| Metric | Value | Note |",
            "|--------|-------|------|",
            f"| C3 Orphan Ref Rate | {c3:.2f} | {c3_note} |",
            f"| C5 Metadata Verify Rate | {c5:.2f} | {c5_note} |",
            f"| C6 Contradiction Rate | {c6_rate:.3f} | {c6_note} |",
            "",
        ]
    )

    # Temporal Coverage (analysis is flat: T1-T5 are direct keys)
    t1 = analysis.get("T1_year_span")
    t2 = analysis.get("T2_foundational_retrieval_gap")
    t4 = analysis.get("T4_temporal_continuity")
    t5 = analysis.get("T5_trend_alignment")
    year_dist = analysis.get("year_distribution", {})
    if year_dist:
        years = list(year_dist.keys())
        year_range = f"({min(years)}-{max(years)})" if years else "(N/A-N/A)"
    else:
        year_range = "(N/A-N/A)"

    t2_note = _threshold_note(
        t2, [(2, "Covers foundational period"), (5, ""), (0, "May miss early work")]
    )
    t4_note = _threshold_note(
        t4, [(1, "No significant gap"), (3, ""), (0, "Significant temporal gap")]
    )
    t5_note = _threshold_note(
        t5, [(0.7, "Well-aligned with field"), (0.4, ""), (0, "Misaligned with field trend")]
    )

    lines.extend(
        [
            "### Temporal Coverage",
            "| Metric | Value | Note |",
            "|--------|-------|------|",
            f"| T1 Year Span | {t1} years {year_range} | |",
            f"| T2 Foundational Gap | {t2} years | {t2_note} |",
            f"| T4 Max Citation Gap | {t4} years | {t4_note} |",
            f"| T5 Trend Alignment | {t5:.2f} | {t5_note} |",
            "",
        ]
    )

    # Structure & Graph (graph_analysis is flat)
    g4 = graph.get("G4_coverage_rate")
    s5 = graph.get("S5_nmi")
    g6_isolates = graph.get("G6_isolates", 0)
    total_refs = max(tool_evidence.get("validation", {}).get("total_refs", 1), 1)
    g6 = g6_isolates / total_refs if total_refs > 0 else 0

    g4_note = _threshold_note(
        g4, [(0.7, "Strong coverage"), (0.4, ""), (0, "Many key papers missing")]
    )
    s5_note = _threshold_note(
        s5, [(0.7, "Well-organized structure"), (0.4, ""), (0, "Weak structure-content alignment")]
    )
    g6_note = _threshold_note(
        g6, [(0.10, "Low isolation"), (0.25, ""), (0, "Many isolated references")]
    )

    lines.extend(
        [
            "### Structure & Graph",
            "| Metric | Value | Note |",
            "|--------|-------|------|",
            f"| G4 Foundational Coverage | {g4:.2f} | {g4_note} |",
            f"| S5 Section-Cluster Alignment | {s5:.2f} | {s5_note} |",
            f"| G6 Isolated Node Ratio | {g6:.2f} | {g6_note} |",
            "",
        ]
    )

    return "\n".join(lines)


def _threshold_note(value: float | None, thresholds: list[tuple]) -> str:
    """Generate deterministic note based on threshold rules.

    Args:
        value: metric value (float)
        thresholds: list of (threshold, note) pairs, sorted descending

    Returns:
        The note for the first threshold that value exceeds.
    """
    if value is None:
        return "N/A"
    for threshold, note in thresholds:
        if value >= threshold:
            return note
    return thresholds[-1][1] if thresholds else ""


def _render_agent_assessment(
    agent_outputs: dict[str, Any],
    dimension_scores: dict[str, Any],
    corrector_output: dict[str, Any],
    tool_evidence: dict[str, Any],
) -> str:
    """Render Section 2: Agent Assessment with scores, evidence, reasoning, and flagged items."""
    lines = ["## 2. Agent Assessment", ""]

    # Agent order and mapping
    agent_info = {
        "verifier": {"title": "Factuality", "dimension": "factuality"},
        "expert": {"title": "Depth", "dimension": "depth"},
        "reader": {"title": "Coverage", "dimension": "readability"},
    }

    corrections = corrector_output.get("corrections", {}) if corrector_output else {}

    for agent_name, info in agent_info.items():
        if agent_name not in agent_outputs:
            continue

        output = agent_outputs[agent_name]
        sub_scores = output.get("sub_scores", {})

        lines.append(f"### {info['title']} ({agent_name.capitalize()}Agent)")
        lines.append("")

        # Score table with tool_evidence and variance badge
        lines.append("| Sub-dimension | Score | Evidence |")
        lines.append("|---------------|-------|----------|")

        for sub_id, sub_data in sub_scores.items():
            score = sub_data.get("score", 5.0)
            tool_ev = sub_data.get("tool_evidence", {})

            # Format tool evidence summary
            evidence_summary = _format_tool_evidence(sub_id, tool_ev)

            # Variance badge
            variance_badge = ""
            if sub_id in corrections:
                variance = corrections[sub_id].get("variance", {})
                std = variance.get("std", 0.0)
                high_disagreement = variance.get("high_disagreement", False)
                if high_disagreement:
                    variance_badge = f" *(corrected, HIGH VARIANCE std={std:.2f})*"
                else:
                    variance_badge = f" *(corrected, std={std:.2f})*"

            dim_name = sub_id.replace("_", " ").title()
            lines.append(
                f"| {dim_name} | {score:.0f}/5{variance_badge} | {evidence_summary} |"
            )

        lines.append("")

        # Agent Analysis: reasoning from lowest-scoring dimension
        lowest_dim = min(sub_scores.items(), key=lambda x: x[1].get("score", 5.0))
        lowest_id, lowest_data = lowest_dim
        reasoning = lowest_data.get("llm_reasoning", "")
        if reasoning:
            lines.append(f"**Agent Analysis** ({lowest_id}):")
            lines.append(f"{reasoning}")
            lines.append("")

        # Flagged Items: collect all flagged items from this agent
        all_flagged = []
        for sub_id, sub_data in sub_scores.items():
            flagged = sub_data.get("flagged_items")
            if flagged:
                all_flagged.extend(flagged if isinstance(flagged, list) else [flagged])

        lines.append("**Flagged Items:**")
        if all_flagged:
            for item in all_flagged:
                lines.append(f"- {item}")
        else:
            lines.append("- No specific items flagged.")
        lines.append("")

        # Special: Missing key papers for ExpertAgent
        if agent_name == "expert":
            missing_papers = tool_evidence.get("key_papers", {}).get("missing_key_papers", [])
            if missing_papers:
                lines.append("**Missing Key Papers:**")
                for paper in missing_papers[:5]:  # Limit to 5
                    title = paper.get("title", "Unknown")
                    year = paper.get("year", "N/A")
                    lines.append(f"- {title} ({year})")
            else:
                lines.append("**Missing Key Papers:**")
                lines.append("- No missing key papers detected.")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def _format_tool_evidence(sub_id: str, tool_ev: dict[str, Any]) -> str:
    """Format tool_evidence for display in score table."""
    if not tool_ev:
        return "N/A"

    # Try to extract key metrics based on dimension
    if "V1" in sub_id:
        value = tool_ev.get("value") or tool_ev.get("metadata_verify_rate")
        if value:
            return f"C5={value:.2f}"
    elif "V2" in sub_id:
        sample = tool_ev.get("sample_size")
        supported = tool_ev.get("supported_count")
        if sample and supported:
            return f"{supported}/{sample} supported"
    elif "E1" in sub_id:
        value = tool_ev.get("value") or tool_ev.get("foundational_coverage_rate")
        if value:
            return f"G4={value:.2f}"
    elif "E2" in sub_id:
        value = tool_ev.get("value") or tool_ev.get("section_cluster_alignment")
        if value:
            return f"S5={value:.2f}"
    elif "R1" in sub_id:
        metrics = tool_ev.get("metrics", {})
        t5 = metrics.get("T5")
        if t5:
            return f"T5={t5:.2f}"
    elif "R2" in sub_id:
        metrics = tool_ev.get("metrics", {})
        s3 = metrics.get("S3")
        if s3:
            return f"S3={s3:.2f}"
    elif "R3" in sub_id:
        metrics = tool_ev.get("metrics", {})
        s5 = metrics.get("S5")
        if s5:
            return f"S5={s5:.2f}"

    # Fallback: just stringify
    return str(tool_ev)[:50]


def _render_key_findings(
    dimension_scores: dict[str, Any],
    tool_evidence: dict[str, Any],
    agent_outputs: dict[str, Any],
) -> str:
    """Render Section 3: Key Findings with areas requiring attention and strengths."""
    lines = ["## 3. Key Findings & Recommendations", ""]

    # Areas Requiring Attention: dimensions with score < 3.5
    low_scores = [
        (dim_id, data)
        for dim_id, data in dimension_scores.items()
        if data.get("final_score", 5.0) < 3.5
    ]
    low_scores.sort(key=lambda x: x[1].get("final_score", 5.0))  # Sort ascending

    if low_scores:
        lines.append("### Areas Requiring Attention")
        lines.append("")

        for dim_id, data in low_scores:
            score = data.get("final_score", 5.0)
            agent = data.get("agent", "unknown")

            # Get reasoning from agent_outputs
            reasoning = ""
            for agent_name, output in agent_outputs.items():
                sub_scores = output.get("sub_scores", {})
                if dim_id in sub_scores:
                    reasoning = sub_scores[dim_id].get("llm_reasoning", "")
                    break

            # Generate recommendation based on dimension
            recommendation = _generate_dimension_recommendation(
                dim_id, tool_evidence, agent_outputs
            )

            lines.append(f"**{dim_id}** (Score: {score:.1f}/5, Agent: {agent})")
            if reasoning:
                lines.append(f"Agent assessment: {reasoning}")
            lines.append(f"Recommendation: {recommendation}")
            lines.append("")

    # Strengths: dimensions with score >= 4.0
    strengths = [
        (dim_id, data)
        for dim_id, data in dimension_scores.items()
        if data.get("final_score", 5.0) >= 4.0
    ]
    strengths.sort(key=lambda x: x[1].get("final_score", 5.0), reverse=True)  # Sort descending

    if strengths:
        lines.append("### Strengths")
        lines.append("")

        for dim_id, data in strengths:
            score = data.get("final_score", 5.0)
            # Get supporting evidence
            evidence = _get_strength_evidence(dim_id, tool_evidence, agent_outputs)
            lines.append(f"- **{dim_id}** ({score:.1f}/5): {evidence}")

        lines.append("")

    return "\n".join(lines)


def _generate_dimension_recommendation(
    dim_id: str, tool_evidence: dict, agent_outputs: dict
) -> str:
    """Generate recommendation based on dimension ID."""
    # Recommendations based on dimension prefix
    if dim_id.startswith("V1"):
        validation = tool_evidence.get("validation", {})
        unverified = validation.get("unverified_references", [])
        if unverified:
            return f"Verify unverified references, particularly: {', '.join(unverified[:3])}"
        return "Verify unverified references."
    elif dim_id.startswith("V2"):
        c6 = tool_evidence.get("c6_alignment", {})
        contradictions = c6.get("contradictions", [])
        if contradictions:
            notes = [c.get("note", "")[:50] for c in contradictions[:3]]
            return f"Review flagged citation-claim contradictions: {'; '.join(notes)}"
        return "Review citation-claim alignment."
    elif dim_id.startswith("E1"):
        key_papers = tool_evidence.get("key_papers", {})
        missing = key_papers.get("missing_key_papers", [])
        if missing:
            titles = [p.get("title", "")[:30] for p in missing[:3]]
            return f"Consider adding key papers: {'; '.join(titles)}"
        return "Review foundational coverage."
    elif dim_id.startswith("E4"):
        return "Add comparative analysis, method limitations, and open questions."
    elif dim_id.startswith("R1"):
        t5 = tool_evidence.get("analysis", {}).get("temporal", {}).get("T5_trend_alignment")
        if t5:
            return f"Improve temporal coverage; current trend alignment is T5={t5:.2f}."
        return "Improve temporal coverage."
    elif dim_id.startswith("R2"):
        s3 = tool_evidence.get("analysis", {}).get("structural", {}).get("S3_citation_gini")
        if s3:
            return f"Balance citation distribution across sections (current Gini={s3:.2f})."
        return "Balance information across sections."
    elif dim_id.startswith("R3"):
        return "Improve structural organization."
    elif dim_id.startswith("R4"):
        return "Review writing quality issues."
    else:
        return "Review and improve this aspect."


def _get_strength_evidence(dim_id: str, tool_evidence: dict, agent_outputs: dict) -> str:
    """Get supporting evidence for a strength."""
    if dim_id.startswith("V4"):
        return "No internal contradictions detected"
    elif dim_id.startswith("V1"):
        c5 = tool_evidence.get("validation", {}).get("C5_metadata_verify_rate")
        if c5 and c5 >= 0.9:
            return f"Strong verification rate (C5={c5:.2f})"
    elif dim_id.startswith("E3"):
        return "Technical descriptions are accurate"
    elif dim_id.startswith("R1"):
        t5 = tool_evidence.get("analysis", {}).get("temporal", {}).get("T5_trend_alignment")
        if t5 and t5 >= 0.7:
            return f"Well-aligned with field trend (T5={t5:.2f})"
    return "Good overall performance"


def _render_footer() -> str:
    """Render report footer."""
    return """---

*Report generated by SurveyMAE v3 - Multi-Agent Survey Evaluation Framework*
*Deterministic metrics are exact values. LLM-based scores may vary across models.*
*Dimensions marked (corrected) were re-scored via multi-model voting.*"""
