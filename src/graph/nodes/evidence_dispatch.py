"""Evidence dispatch module for assembling Evidence Reports.

This module handles the creation of Evidence Reports for each agent,
including:
- Metric definitions and calculations
- Full metric values
- Anomaly flags and highlights
"""

import logging
from typing import Any, Dict, List, Optional

from src.core.state import SurveyState

logger = logging.getLogger(__name__)


# Metric definitions for each agent
VERIFIER_METRICS = {
    "C3": {
        "name": "orphan_ref_rate",
        "description": "Uncited references / total references. High rate indicates 'name-only' citations.",
        "llm_involved": False,
    },
    "C5": {
        "name": "metadata_verify_rate",
        "description": "Proportion of references verified via external academic API. Higher is better.",
        "llm_involved": False,
    },
    "C6": {
        "name": "citation_sentence_alignment",
        "description": "Contradiction rate between survey sentences and cited paper abstracts. Lower is better.",
        "llm_involved": True,
        "hallucination_risk": "low",
    },
}

EXPERT_METRICS = {
    "G1": {
        "name": "graph_density",
        "description": "Actual edges / possible maximum edges. Measures literature interconnectedness.",
        "llm_involved": False,
    },
    "G2": {
        "name": "connected_component_count",
        "description": "Number of disconnected components. Lower means more cohesive.",
        "llm_involved": False,
    },
    "G3": {
        "name": "max_component_ratio",
        "description": "Largest component size / total nodes. Higher means literature is well-connected.",
        "llm_involved": False,
    },
    "G4": {
        "name": "foundational_coverage_rate",
        "description": "Coverage of field's foundational papers. Retrieved via academic API + LLM filtering.",
        "llm_involved": True,
        "hallucination_risk": "low",
    },
    "G5": {
        "name": "cluster_count",
        "description": "Number of citation clusters. Indicates sub-topic diversity.",
        "llm_involved": False,
    },
    "G6": {
        "name": "isolated_node_ratio",
        "description": "Isolated papers / total papers. High ratio may indicate off-topic references.",
        "llm_involved": False,
    },
    "S5": {
        "name": "section_cluster_alignment",
        "description": "NMI between section assignments and citation clusters. High alignment indicates well-organized structure.",
        "llm_involved": False,
    },
}

READER_METRICS = {
    "T1": {
        "name": "year_span",
        "description": "Max reference year - min reference year. Shows temporal breadth.",
        "llm_involved": False,
    },
    "T2": {
        "name": "foundational_retrieval_gap",
        "description": "Years between survey's earliest citation and field's foundational work. Smaller is better.",
        "llm_involved": True,
        "hallucination_risk": "low",
    },
    "T3": {
        "name": "peak_year_ratio",
        "description": "Ratio of citations in last 3 years. In CS/AI, high is normal.",
        "llm_involved": False,
    },
    "T4": {
        "name": "temporal_continuity",
        "description": "Longest gap in years with no citations. Large gaps (>3 years) are suspicious.",
        "llm_involved": False,
    },
    "T5": {
        "name": "trend_alignment",
        "description": "Pearson correlation between survey citations and field publication trend. Higher means better alignment.",
        "llm_involved": True,
        "hallucination_risk": "low",
    },
    "S1": {
        "name": "section_count",
        "description": "Total number of sections.",
        "llm_involved": False,
    },
    "S2": {
        "name": "citation_density",
        "description": "Total citations / total paragraphs.",
        "llm_involved": False,
    },
    "S3": {
        "name": "citation_gini",
        "description": "Gini coefficient of citations across sections. High doesn't mean bad - key sections can be denser.",
        "llm_involved": False,
    },
    "S4": {
        "name": "zero_citation_section_rate",
        "description": "Sections with no citations / total sections.",
        "llm_involved": False,
    },
}


def build_metric_definitions(agent_name: str) -> Dict[str, Dict[str, Any]]:
    """Get metric definitions for an agent."""
    if agent_name == "verifier":
        return VERIFIER_METRICS
    elif agent_name == "expert":
        return EXPERT_METRICS
    elif agent_name == "reader":
        return READER_METRICS
    return {}


def build_verifier_evidence(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Build Evidence Report for VerifierAgent.

    Args:
        evidence: Tool evidence containing validation results.

    Returns:
        Formatted evidence report.
    """
    validation = evidence.get("validation", {})
    graph_analysis = evidence.get("graph_analysis", {})

    # Extract C3, C5
    orphan_rate = validation.get("orphan_ref_rate")
    verify_rate = validation.get("metadata_verify_rate")

    # Extract C6 (citation_sentence_alignment)
    c6_result = graph_analysis.get("C6", {})

    # Build warnings
    warnings = []
    if verify_rate is not None and verify_rate < 0.7:
        warnings.append(
            f"⚠ C5 only {verify_rate:.0%}, {int((1 - verify_rate) * len(validation.get('references', [])))} unverified references need review"
        )

    # C6 auto_fail check
    c6_auto_fail = c6_result.get("auto_fail", False)
    contradiction_rate = c6_result.get("contradiction_rate", 0.0)
    contradictions = c6_result.get("contradictions", [])

    if c6_auto_fail:
        warnings.append(
            f"🚨 C6 auto_fail triggered: contradiction_rate={contradiction_rate:.1%} >= threshold. "
            f"V2 dimension will be auto-scored as 1 (minimum)."
        )

    # Get unverified references for sampling
    unverified_refs = validation.get("unverified_references", [])

    return {
        "metrics": {
            "C3": {
                "value": orphan_rate,
                "definition": VERIFIER_METRICS["C3"]["description"],
            },
            "C5": {
                "value": verify_rate,
                "definition": VERIFIER_METRICS["C5"]["description"],
            },
            "C6": {
                "value": c6_result.get("contradiction_rate"),
                "definition": VERIFIER_METRICS["C6"]["description"],
                "auto_fail": c6_auto_fail,
                "support": c6_result.get("support", 0),
                "contradict": c6_result.get("contradict", 0),
                "insufficient": c6_result.get("insufficient", 0),
            },
        },
        "warnings": warnings,
        "unverified_references": unverified_refs[:10],  # Sample for agent
        "c6_auto_fail": c6_auto_fail,
        "c6_contradictions": contradictions[:10],  # Sample for agent review
    }


def build_expert_evidence(
    evidence: Dict[str, Any], foundational_result: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Build Evidence Report for ExpertAgent.

    Args:
        evidence: Tool evidence containing graph analysis.
        foundational_result: Result from G4 analysis.

    Returns:
        Formatted evidence report.
    """
    graph = evidence.get("graph_analysis", {})

    # Extract G metrics
    density = graph.get("density_connectivity", {}).get("density_global")
    components = graph.get("density_connectivity", {}).get("n_weak_components")
    lcc_frac = graph.get("density_connectivity", {}).get("lcc_frac")
    isolates = graph.get("density_connectivity", {}).get("n_isolates")
    clusters = graph.get("cocitation_clustering", {}).get("n_clusters")

    # Build warnings
    warnings = []
    if isolates and density and isolates / (density + 1) > 0.1:
        warnings.append(f"⚠ G6 high: {isolates} isolated papers")

    if foundational_result:
        coverage = foundational_result.get("coverage_rate")
        if coverage is not None and coverage < 0.6:
            warnings.append(
                f"⚠ G4={coverage:.0%}, missing_key_papers contains {len(foundational_result.get('missing_key_papers', []))} high-impact papers"
            )

    return {
        "metrics": {
            "G1": {"value": density, "definition": EXPERT_METRICS["G1"]["description"]},
            "G2": {"value": components, "definition": EXPERT_METRICS["G2"]["description"]},
            "G3": {"value": lcc_frac, "definition": EXPERT_METRICS["G3"]["description"]},
            "G4": {
                "value": foundational_result.get("coverage_rate") if foundational_result else None,
                "definition": EXPERT_METRICS["G4"]["description"],
            },
            "G5": {"value": clusters, "definition": EXPERT_METRICS["G5"]["description"]},
            "G6": {"value": isolates, "definition": EXPERT_METRICS["G6"]["description"]},
        },
        "warnings": warnings,
        "missing_key_papers": foundational_result.get("missing_key_papers", [])[:5]
        if foundational_result
        else [],
        "suspicious_centrality": foundational_result.get("suspicious_centrality", [])[:5]
        if foundational_result
        else [],
    }


def build_reader_evidence(
    evidence: Dict[str, Any], field_trend: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Build Evidence Report for ReaderAgent.

    Args:
        evidence: Tool evidence containing analysis.
        field_trend: Field trend baseline data.

    Returns:
        Formatted evidence report.
    """
    analysis = evidence.get("analysis", {})

    # Extract T and S metrics
    year_span = analysis.get("T1_year_span")
    foundational_gap = analysis.get("T2_foundational_retrieval_gap")
    peak_ratio = analysis.get("T3_peak_year_ratio")
    continuity = analysis.get("T4_temporal_continuity")
    trend_alignment = analysis.get("T5_trend_alignment")

    section_count = analysis.get("S1_section_count")
    density = analysis.get("S2_citation_density")
    gini = analysis.get("S3_citation_gini")
    zero_rate = analysis.get("S4_zero_citation_section_rate")

    # Build warnings
    warnings = []
    if continuity is not None and continuity >= 3:
        warnings.append(f"⚠ T4={continuity} years gap, may have missed developments in that period")
    if trend_alignment is not None and trend_alignment < 0.3:
        warnings.append(
            f"⚠ T5={trend_alignment:.2f}, citation trend significantly deviates from field trend"
        )

    # Include field trend baseline if available
    baseline_data = None
    if field_trend:
        baseline_data = field_trend.get("yearly_counts")

    return {
        "metrics": {
            "T1": {"value": year_span, "definition": READER_METRICS["T1"]["description"]},
            "T2": {"value": foundational_gap, "definition": READER_METRICS["T2"]["description"]},
            "T3": {"value": peak_ratio, "definition": READER_METRICS["T3"]["description"]},
            "T4": {"value": continuity, "definition": READER_METRICS["T4"]["description"]},
            "T5": {"value": trend_alignment, "definition": READER_METRICS["T5"]["description"]},
            "S1": {"value": section_count, "definition": READER_METRICS["S1"]["description"]},
            "S2": {"value": density, "definition": READER_METRICS["S2"]["description"]},
            "S3": {"value": gini, "definition": READER_METRICS["S3"]["description"]},
            "S4": {"value": zero_rate, "definition": READER_METRICS["S4"]["description"]},
        },
        "warnings": warnings,
        "field_trend_baseline": baseline_data,
        "year_distribution": analysis.get("year_distribution"),
    }


def assemble_evidence_report(
    agent_name: str,
    tool_evidence: Dict[str, Any],
    additional_data: Optional[Dict[str, Any]] = None,
) -> str:
    """Assemble complete Evidence Report for an agent.

    Args:
        agent_name: Name of the agent (verifier, expert, reader).
        tool_evidence: Tool evidence data.
        additional_data: Additional data (field_trend, foundational_result, etc.).

    Returns:
        Formatted markdown evidence report.
    """
    definitions = build_metric_definitions(agent_name)

    if agent_name == "verifier":
        report_data = build_verifier_evidence(tool_evidence)
    elif agent_name == "expert":
        foundational = additional_data.get("foundational_result") if additional_data else None
        report_data = build_expert_evidence(tool_evidence, foundational)
    elif agent_name == "reader":
        trend = additional_data.get("field_trend") if additional_data else None
        report_data = build_reader_evidence(tool_evidence, trend)
    else:
        report_data = {}

    # Build markdown report
    lines = ["## Evidence Report\n"]

    # Add metric definitions section
    lines.append("### Metric Definitions\n")
    for metric_id, defn in definitions.items():
        lines.append(f"**{metric_id} ({defn['name']})**: {defn['description']}")
        if defn.get("llm_involved"):
            lines.append(
                f"  - LLM involved: Yes (risk: {defn.get('hallucination_risk', 'unknown')})"
            )
        lines.append("")

    # Add metric values section
    lines.append("### Metric Values\n")
    metrics = report_data.get("metrics", {})
    for metric_id, data in metrics.items():
        value = data.get("value")
        if value is not None:
            if isinstance(value, float):
                lines.append(f"- **{metric_id}**: {value:.3f}")
            else:
                lines.append(f"- **{metric_id}**: {value}")
        else:
            lines.append(f"- **{metric_id}**: N/A")
    lines.append("")

    # Add warnings
    warnings = report_data.get("warnings", [])
    if warnings:
        lines.append("### Warnings & Highlights\n")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    # Add additional data
    if agent_name == "expert":
        missing = report_data.get("missing_key_papers", [])
        if missing:
            lines.append("### Missing Key Papers\n")
            for paper in missing:
                title = paper.get("title", "Unknown")[:60]
                citations = paper.get("citation_count", 0)
                lines.append(f"- [{title}...] (citations: {citations})")
            lines.append("")

    if agent_name == "reader":
        trend = report_data.get("field_trend_baseline")
        if trend:
            lines.append("### Field Trend Baseline (sample)\n")
            sorted_years = sorted(trend.keys())[-5:]  # Last 5 years
            for year in sorted_years:
                lines.append(f"- {year}: {trend[year]} papers")
            lines.append("")

    return "\n".join(lines)


async def run_evidence_dispatch(state: SurveyState) -> Dict[str, Any]:
    """Node function for evidence dispatch.

    This node:
    1. Gets tool_evidence from state
    2. Assembles Evidence Reports for each agent (verifier, expert, reader)
    3. Stores the reports in state for agents to use

    Args:
        state: Current workflow state with tool_evidence.

    Returns:
        Updated state with evidence_reports for each agent.
    """
    logger.info("Running evidence dispatch node...")
    tool_evidence = state.get("tool_evidence", {})
    field_trend = state.get("field_trend_baseline", {})
    graph_analysis = tool_evidence.get("graph_analysis", {})
    foundational_result = graph_analysis.get("foundational_coverage", {})

    result = {}

    # Assemble evidence for each agent

    # For now, we'll create a combined evidence that agents can parse
    verifier_evidence = build_verifier_evidence(tool_evidence)
    expert_evidence = build_expert_evidence(tool_evidence, foundational_result)
    reader_evidence = build_reader_evidence(tool_evidence, field_trend)

    result["evidence_reports"] = {
        "verifier": assemble_evidence_report("verifier", tool_evidence),
        "expert": assemble_evidence_report("expert", tool_evidence, {"foundational_result": foundational_result}),
        "reader": assemble_evidence_report("reader", tool_evidence, {"field_trend": field_trend}),
    }

    # Also provide singular key for compatibility
    result["evidence_report"] = result["evidence_reports"]

    # Also store structured evidence for easier access
    result["verifier_evidence"] = verifier_evidence
    result["expert_evidence"] = expert_evidence
    result["reader_evidence"] = reader_evidence

    return result
