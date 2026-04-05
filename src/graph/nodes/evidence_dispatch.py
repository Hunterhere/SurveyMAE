"""Evidence Dispatch Module - Refactored.

This module handles the creation of Evidence Reports and dispatch specs for each agent.
It serves as the single source of truth for:
- Metric definitions and metadata
- Agent sub-dimension definitions and rubrics
- Short-circuit rules
- Hallucination risk assignments

Architecture (Plan v3 Refactoring Design):
- METRIC_REGISTRY: All 19 metric definitions with extract_path
- AGENT_REGISTRY: All agent definitions with sub-dimensions
- run_evidence_dispatch(): Generates dispatch_specs for downstream agents
- get_corrector_targets(): Dynamic voting targets based on hallucination_risk
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.core.state import SurveyState

logger = logging.getLogger("surveymae.graph.nodes.evidence_dispatch")


# =============================================================================
# Metric Registry - Single Source of Truth for all 19 metrics
# =============================================================================

@dataclass
class MetricDef:
    """Definition of a first-layer metric."""
    metric_id: str
    name: str
    description: str
    source: str  # Tool that produces this metric
    extract_path: str  # Path in tool_evidence to extract value
    llm_involved: bool
    hallucination_risk: str  # "none", "low", "medium", "high"
    extra_fields: List[str] = field(default_factory=list)  # Extra fields to extract (e.g., auto_fail for C6)


# METRIC_REGISTRY: All 19 metrics keyed by metric_id
# Extract paths are relative to tool_evidence
METRIC_REGISTRY: Dict[str, MetricDef] = {
    # === Citation Integrity (C-series) ===
    "C3": MetricDef(
        metric_id="C3",
        name="orphan_ref_rate",
        description="Uncited references / total references. High rate indicates 'name-only' citations.",
        source="CitationChecker",
        extract_path="validation.C3_orphan_ref_rate",
        llm_involved=False,
        hallucination_risk="none",
    ),
    "C5": MetricDef(
        metric_id="C5",
        name="metadata_verify_rate",
        description="Proportion of references verified via external academic API. Higher is better.",
        source="CitationChecker",
        extract_path="validation.C5_metadata_verify_rate",
        llm_involved=False,
        hallucination_risk="none",
    ),
    "C6": MetricDef(
        metric_id="C6",
        name="citation_sentence_alignment",
        description="Contradiction rate between survey sentences and cited paper abstracts. Lower is better.",
        source="CitationChecker.analyze_citation_sentence_alignment",
        extract_path="c6_alignment.contradiction_rate",
        llm_involved=True,
        hallucination_risk="low",
        extra_fields=["auto_fail", "contradictions", "support", "contradict", "insufficient"],
    ),

    # === Temporal Distribution (T-series) ===
    "T1": MetricDef(
        metric_id="T1",
        name="year_span",
        description="Max reference year - min reference year. Shows temporal breadth.",
        source="CitationAnalyzer.compute_temporal_metrics",
        extract_path="analysis.T1_year_span",
        llm_involved=False,
        hallucination_risk="none",
    ),
    "T2": MetricDef(
        metric_id="T2",
        name="foundational_retrieval_gap",
        description="Years between survey's earliest citation and field's foundational work. Smaller is better.",
        source="LiteratureSearch + CitationAnalyzer",
        extract_path="analysis.T2_foundational_retrieval_gap",
        llm_involved=True,
        hallucination_risk="low",
    ),
    "T3": MetricDef(
        metric_id="T3",
        name="peak_year_ratio",
        description="Ratio of citations in last 3 years. In CS/AI, high is normal.",
        source="CitationAnalyzer.compute_temporal_metrics",
        extract_path="analysis.T3_peak_year_ratio",
        llm_involved=False,
        hallucination_risk="none",
    ),
    "T4": MetricDef(
        metric_id="T4",
        name="temporal_continuity",
        description="Longest gap in years with no citations. Large gaps (>3 years) are suspicious.",
        source="CitationAnalyzer.compute_temporal_metrics",
        extract_path="analysis.T4_temporal_continuity",
        llm_involved=False,
        hallucination_risk="none",
    ),
    "T5": MetricDef(
        metric_id="T5",
        name="trend_alignment",
        description="Pearson correlation between survey citations and field publication trend. Higher means better alignment.",
        source="LiteratureSearch + CitationAnalyzer",
        extract_path="analysis.T5_trend_alignment",
        llm_involved=True,
        hallucination_risk="low",
    ),

    # === Structural Distribution (S-series) ===
    "S1": MetricDef(
        metric_id="S1",
        name="section_count",
        description="Total number of sections.",
        source="CitationAnalyzer.compute_structural_metrics",
        extract_path="analysis.S1_section_count",
        llm_involved=False,
        hallucination_risk="none",
    ),
    "S2": MetricDef(
        metric_id="S2",
        name="citation_density",
        description="Total citations / total paragraphs.",
        source="CitationAnalyzer.compute_structural_metrics",
        extract_path="analysis.S2_citation_density",
        llm_involved=False,
        hallucination_risk="none",
    ),
    "S3": MetricDef(
        metric_id="S3",
        name="citation_gini",
        description="Gini coefficient of citations across sections. High doesn't mean bad - key sections can be denser.",
        source="CitationAnalyzer.compute_structural_metrics",
        extract_path="analysis.S3_citation_gini",
        llm_involved=False,
        hallucination_risk="none",
    ),
    "S4": MetricDef(
        metric_id="S4",
        name="zero_citation_section_rate",
        description="Sections with no citations / total sections.",
        source="CitationAnalyzer.compute_structural_metrics",
        extract_path="analysis.S4_zero_citation_section_rate",
        llm_involved=False,
        hallucination_risk="none",
    ),
    "S5": MetricDef(
        metric_id="S5",
        name="section_cluster_alignment",
        description="NMI between section assignments and citation clusters. High alignment indicates well-organized structure.",
        source="CitationGraphAnalyzer.compute_section_cluster_alignment",
        extract_path="graph_analysis.S5_nmi",
        llm_involved=False,
        hallucination_risk="none",
    ),

    # === Citation Graph (G-series) ===
    "G1": MetricDef(
        metric_id="G1",
        name="graph_density",
        description="Actual edges / possible maximum edges. Measures literature interconnectedness.",
        source="CitationGraphAnalyzer.analyze",
        extract_path="graph_analysis.G1_density",
        llm_involved=False,
        hallucination_risk="none",
    ),
    "G2": MetricDef(
        metric_id="G2",
        name="connected_component_count",
        description="Number of disconnected components. Lower means more cohesive.",
        source="CitationGraphAnalyzer.analyze",
        extract_path="graph_analysis.G2_components",
        llm_involved=False,
        hallucination_risk="none",
    ),
    "G3": MetricDef(
        metric_id="G3",
        name="max_component_ratio",
        description="Largest component size / total nodes. Higher means literature is well-connected.",
        source="CitationGraphAnalyzer.analyze",
        extract_path="graph_analysis.G3_lcc_frac",
        llm_involved=False,
        hallucination_risk="none",
    ),
    "G4": MetricDef(
        metric_id="G4",
        name="foundational_coverage_rate",
        description="Coverage of field's foundational papers. Retrieved via academic API + LLM filtering.",
        source="FoundationalCoverageAnalyzer",
        extract_path="graph_analysis.G4_coverage_rate",
        llm_involved=True,
        hallucination_risk="low",
    ),
    "G5": MetricDef(
        metric_id="G5",
        name="cluster_count",
        description="Number of citation clusters. Indicates sub-topic diversity.",
        source="CitationGraphAnalyzer.analyze",
        extract_path="graph_analysis.G5_clusters",
        llm_involved=False,
        hallucination_risk="none",
    ),
    "G6": MetricDef(
        metric_id="G6",
        name="isolated_node_ratio",
        description="Isolated papers / total papers. High ratio may indicate off-topic references.",
        source="CitationGraphAnalyzer.analyze",
        extract_path="graph_analysis.G6_isolates",
        llm_involved=False,
        hallucination_risk="none",
    ),
}


# =============================================================================
# Agent Registry - Sub-dimensions, Rubrics, and Hallucination Risk
# =============================================================================

@dataclass
class SubDimensionDef:
    """Definition of an agent sub-dimension."""
    sub_id: str
    name: str
    description: str
    hallucination_risk: str  # Used to auto-derive corrector voting targets
    evidence_metric_ids: List[str]  # Metric IDs this sub-dimension depends on
    rubric: str  # 1-5 scoring rubric
    short_circuit: Optional[Dict[str, Any]] = None  # Short-circuit rule if any


@dataclass
class AgentDef:
    """Definition of an agent."""
    agent_name: str
    dimension: str
    input_metric_ids: List[str]  # All metric IDs this agent receives
    sub_dimensions: List[SubDimensionDef]
    supplementary_data: Optional[List[str]] = None  # Additional data slices to extract
    state_fields: List[str] = field(default_factory=list)  # Extra state fields to read


# VERIFIER Rubrics (V1, V2, V4 - V3 was merged into C6 per Plan v3)
VERIFIER_RUBRIC_V1 = """Rate the citation existence (V1) dimension:
- 5: metadata_verify_rate >= 95%
- 4: metadata_verify_rate >= 85%
- 3: metadata_verify_rate >= 70%
- 2: metadata_verify_rate >= 50%
- 1: metadata_verify_rate < 50%"""

VERIFIER_RUBRIC_V2_NORMAL = """Rate the citation-claim alignment (V2) dimension:
- 5: contradiction_rate < 1%
- 4: contradiction_rate 1-2%
- 3: contradiction_rate 2-3%
- 2: contradiction_rate 3-5%
- 1: contradiction_rate >= 5% or auto_failed"""

VERIFIER_RUBRIC_V4 = """Rate the internal consistency (V4) dimension:
- 5: No internal contradictions found; claims are consistent throughout
- 4: Minor inconsistencies in minor details; main claims are consistent
- 3: Some contradictions in examples or minor claims; main structure is sound
- 2: Multiple contradictions affecting key claims
- 1: Major contradictions that undermine the survey's credibility"""


# EXPERT Rubrics (E1-E4)
EXPERT_RUBRIC_E1 = """Rate the core literature coverage (E1) dimension:
- 5: G4 >= 0.8, no foundational works missing
- 4: G4 >= 0.6, minor omissions in non-critical areas
- 3: G4 >= 0.4, 1-2 important papers missing
- 2: G4 >= 0.2, several important papers missing
- 1: G4 < 0.2, major foundational works missing"""

EXPERT_RUBRIC_E2 = """Rate the method classification reasonableness (E2) dimension:
- 5: Classification is clear, comprehensive, and aligns with academic consensus; all major methods are categorized
- 4: Classification is mostly sound with minor gaps or overlaps
- 3: Some methods are misclassified or missing; overall structure is acceptable
- 2: Significant classification issues affecting understanding
- 1: Major methods are missing or badly misclassified"""

EXPERT_RUBRIC_E3 = """Rate the technical accuracy (E3) dimension:
- 5: All technical descriptions are accurate and reflect the referenced papers
- 4: Minor technical inaccuracies that don't affect overall understanding
- 3: Some technical errors in descriptions of methods or results
- 2: Multiple technical inaccuracies affecting credibility
- 1: Major technical errors that misrepresent the referenced work"""

EXPERT_RUBRIC_E4 = """Rate the critical analysis depth (E4) dimension:
- 5: Systematic comparisons, clear development trends, specific limitations, open questions discussed
- 4: Comparisons and trend analysis present but limitations not specific enough
- 3: Mostly listing with some comparisons and comments but lacking depth
- 2: Almost purely listing with minimal comparison or critique
- 1: Pure paper abstract堆砌 with no comprehensive analysis"""


# READER Rubrics (R1-R4)
READER_RUBRIC_R1 = """Rate the timeliness (R1) dimension:
- 5: T5 >= 0.7, T2 <= 2 years, T4 <= 1 year (no gaps)
- 4: T5 >= 0.5, T4 <= 2 years, overall temporal coverage is sound
- 3: T5 >= 0.3, minor temporal gaps or trend deviations
- 2: T5 < 0.3 or T4 >= 3 years, significant temporal issues
- 1: Almost all citations are from 1-2 years, or complete absence of foundational works"""

READER_RUBRIC_R2 = """Rate the information distribution balance (R2) dimension:
- 5: Information is well-distributed across sections; key sections have appropriate density
- 4: Overall balanced with minor unevenness in less critical sections
- 3: Some sections are too sparse or too dense; overall structure is acceptable
- 2: Significant imbalance affecting the survey's usability
- 1: Severe imbalance with some sections having almost no supporting citations"""

READER_RUBRIC_R3 = """Rate the structural clarity (R3) dimension:
- 5: Clear hierarchy, logical flow, S5 >= 0.7 indicating good section-cluster alignment
- 4: Mostly clear structure with S5 >= 0.5
- 3: Some organizational issues but overall navigable
- 2: Poor structure making it hard to follow
- 1: Confusing organization that significantly impairs readability"""

READER_RUBRIC_R4 = """Rate the writing quality (R4) dimension:
- 5: Clear, fluent writing with consistent terminology throughout
- 4: Mostly clear with minor terminology inconsistencies or awkward phrasing
- 3: Some passages are unclear or have terminology issues
- 2: Multiple clarity issues affecting comprehension
- 1: Poor writing quality that significantly impairs understanding"""


# AGENT_REGISTRY: All agents with their sub-dimensions
AGENT_REGISTRY: Dict[str, AgentDef] = {
    "verifier": AgentDef(
        agent_name="verifier",
        dimension="factuality",
        input_metric_ids=["C3", "C5", "C6"],
        supplementary_data=["unverified_references", "c6_contradictions"],
        sub_dimensions=[
            SubDimensionDef(
                sub_id="V1",
                name="citation_existence",
                description="Whether references are real and verifiable",
                hallucination_risk="low",  # Based on C5 threshold, deterministic
                evidence_metric_ids=["C5"],
                rubric=VERIFIER_RUBRIC_V1,
            ),
            SubDimensionDef(
                sub_id="V2",
                name="citation_claim_alignment",
                description="Whether the survey correctly understands cited papers",
                hallucination_risk="medium",  # Will be dynamically set to "low" if auto_fail=True
                evidence_metric_ids=["C6"],
                rubric=VERIFIER_RUBRIC_V2_NORMAL,
                short_circuit={
                    "condition": "C6.auto_fail == True",
                    "action": "pre_fill_score",
                    "result": 1,
                },
            ),
            SubDimensionDef(
                sub_id="V4",
                name="internal_consistency",
                description="Whether the survey has internal contradictions",
                hallucination_risk="high",  # Requires LLM judgment
                evidence_metric_ids=[],  # Based on parsed_content
                rubric=VERIFIER_RUBRIC_V4,
            ),
        ],
    ),
    "expert": AgentDef(
        agent_name="expert",
        dimension="academic_depth",
        input_metric_ids=["G1", "G2", "G3", "G4", "G5", "G6", "S5"],
        supplementary_data=["missing_key_papers", "suspicious_centrality"],
        state_fields=["parsed_content"],
        sub_dimensions=[
            SubDimensionDef(
                sub_id="E1",
                name="core_literature_coverage",
                description="Whether foundational and representative works are included",
                hallucination_risk="low",  # Based on G4 threshold, deterministic
                evidence_metric_ids=["G4"],
                rubric=EXPERT_RUBRIC_E1,
            ),
            SubDimensionDef(
                sub_id="E2",
                name="method_classification",
                description="Whether method classification is reasonable and complete",
                hallucination_risk="medium",
                evidence_metric_ids=["G5", "S5"],
                rubric=EXPERT_RUBRIC_E2,
            ),
            SubDimensionDef(
                sub_id="E3",
                name="technical_accuracy",
                description="Whether technical descriptions are accurate",
                hallucination_risk="high",
                evidence_metric_ids=[],  # Based on parsed_content
                rubric=EXPERT_RUBRIC_E3,
            ),
            SubDimensionDef(
                sub_id="E4",
                name="critical_analysis_depth",
                description="Whether there are comparisons, trend analysis, and limitations discussed",
                hallucination_risk="high",
                evidence_metric_ids=[],  # Based on parsed_content
                rubric=EXPERT_RUBRIC_E4,
            ),
        ],
    ),
    "reader": AgentDef(
        agent_name="reader",
        dimension="readability",
        input_metric_ids=["T1", "T2", "T3", "T4", "T5", "S1", "S2", "S3", "S4", "S5"],
        supplementary_data=["field_trend_baseline", "year_distribution"],
        state_fields=["parsed_content"],
        sub_dimensions=[
            SubDimensionDef(
                sub_id="R1",
                name="timeliness",
                description="Whether the survey balances foundational and frontier work",
                hallucination_risk="low",  # Based on T5 threshold, deterministic
                evidence_metric_ids=["T1", "T2", "T3", "T4", "T5"],
                rubric=READER_RUBRIC_R1,
            ),
            SubDimensionDef(
                sub_id="R2",
                name="information_distribution",
                description="Whether information density is balanced across sections",
                hallucination_risk="medium",
                evidence_metric_ids=["S2", "S3", "S5"],
                rubric=READER_RUBRIC_R2,
            ),
            SubDimensionDef(
                sub_id="R3",
                name="structural_clarity",
                description="Whether the hierarchy and reading path are clear",
                hallucination_risk="medium",
                evidence_metric_ids=["S1", "S5"],
                rubric=READER_RUBRIC_R3,
            ),
            SubDimensionDef(
                sub_id="R4",
                name="writing_quality",
                description="Whether writing is fluent and terminology is consistent",
                hallucination_risk="medium",
                evidence_metric_ids=[],  # Based on parsed_content
                rubric=READER_RUBRIC_R4,
            ),
        ],
    ),
}


# =============================================================================
# Helper Functions
# =============================================================================

def extract_metric_value(tool_evidence: Dict[str, Any], metric_id: str) -> Any:
    """Extract a metric value from tool_evidence using METRIC_REGISTRY extract_path.

    Args:
        tool_evidence: The tool_evidence dict from evidence_collection.
        metric_id: The metric ID to extract (e.g., "C6", "T5").

    Returns:
        The extracted value, or None if not found.
    """
    metric_def = METRIC_REGISTRY.get(metric_id)
    if not metric_def:
        logger.warning(f"Metric {metric_id} not found in METRIC_REGISTRY")
        return None

    # Parse extract_path (e.g., "c6_alignment.contradiction_rate")
    parts = metric_def.extract_path.split(".")
    value = tool_evidence
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
        if value is None:
            return None

    return value


def extract_metric_with_extra(tool_evidence: Dict[str, Any], metric_id: str) -> Dict[str, Any]:
    """Extract a metric value and its extra fields from tool_evidence.

    Args:
        tool_evidence: The tool_evidence dict.
        metric_id: The metric ID to extract.

    Returns:
        Dict with 'value' and any extra_fields requested.
    """
    metric_def = METRIC_REGISTRY.get(metric_id)
    if not metric_def:
        return {"value": None}

    result = {"value": extract_metric_value(tool_evidence, metric_id)}

    # Extract extra fields if any
    for extra_field in metric_def.extra_fields:
        # Construct path: e.g., "c6_alignment.auto_fail"
        path = metric_def.extract_path.rsplit(".", 1)[0] + "." + extra_field
        parts = path.split(".")
        value = tool_evidence
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
                break
        if value is not None:
            result[extra_field] = value

    return result


def build_warnings(agent_name: str, tool_evidence: Dict[str, Any], sub_dim: SubDimensionDef) -> List[str]:
    """Build warnings relevant to a specific sub-dimension.

    Args:
        agent_name: The agent name.
        tool_evidence: The tool_evidence dict.
        sub_dim: The sub-dimension definition.

    Returns:
        List of warning strings relevant to this sub-dimension.
    """
    warnings = []

    if agent_name == "verifier":
        verify_rate = extract_metric_value(tool_evidence, "C5")
        if verify_rate is not None and verify_rate < 0.7:
            warnings.append(f"⚠ C5 only {verify_rate:.0%}, some references could not be verified")

        c6_data = extract_metric_with_extra(tool_evidence, "C6")
        if c6_data.get("auto_fail"):
            warnings.append(f"🚨 C6 auto_fail triggered: V2 will be auto-scored as 1")

    elif agent_name == "expert":
        g4_coverage = extract_metric_value(tool_evidence, "G4")
        if g4_coverage is not None and g4_coverage < 0.6:
            warnings.append(f"⚠ G4={g4_coverage:.0%}, coverage rate is low")

        g6_isolates = extract_metric_value(tool_evidence, "G6")
        if g6_isolates is not None and g6_isolates > 5:
            warnings.append(f"⚠ G6={g6_isolates} isolated papers, some references may be off-topic")

    elif agent_name == "reader":
        t4_continuity = extract_metric_value(tool_evidence, "T4")
        if t4_continuity is not None and t4_continuity >= 3:
            warnings.append(f"⚠ T4={t4_continuity} years gap, may have missed developments in that period")

        t5_alignment = extract_metric_value(tool_evidence, "T5")
        if t5_alignment is not None and t5_alignment < 0.3:
            warnings.append(f"⚠ T5={t5_alignment:.2f}, citation trend significantly deviates from field trend")

    return warnings


def build_sub_dimension_context(
    agent_name: str,
    sub_dim: SubDimensionDef,
    tool_evidence: Dict[str, Any],
    state: SurveyState,
) -> Dict[str, Any]:
    """Build the prompt context for a single sub-dimension.

    This function creates the exact context needed for an agent to evaluate
    one sub-dimension, including:
    - The sub-dimension's rubric
    - Only the evidence metrics it depends on (filtered by evidence_metric_ids)
    - Relevant warnings
    - Output schema

    Args:
        agent_name: The agent name (verifier, expert, reader).
        sub_dim: The sub-dimension definition.
        tool_evidence: The tool_evidence dict from evidence_collection.
        state: The current SurveyState.

    Returns:
        A context dict for this sub-dimension.
    """
    # Build evidence_metrics dict with only the metrics this sub-dimension uses
    evidence_metrics = {}
    for metric_id in sub_dim.evidence_metric_ids:
        metric_def = METRIC_REGISTRY.get(metric_id)
        if not metric_def:
            continue

        extracted = extract_metric_with_extra(tool_evidence, metric_id)
        evidence_metrics[metric_id] = {
            "value": extracted.get("value"),
            "definition": metric_def.description,
        }
        # Include extra fields if present (e.g., auto_fail for C6)
        for key, val in extracted.items():
            if key != "value" and val is not None:
                evidence_metrics[metric_id][key] = val

    # Build supplementary_data if this agent has any
    supplementary_data = {}
    agent_def = AGENT_REGISTRY.get(agent_name)
    if agent_def and agent_def.supplementary_data:
        for data_key in agent_def.supplementary_data:
            if data_key == "field_trend_baseline":
                supplementary_data["field_trend_baseline"] = state.get("field_trend_baseline", {})
            elif data_key == "year_distribution":
                from src.graph.nodes.evidence_collection import _convert_numpy_types
                supplementary_data["year_distribution"] = _convert_numpy_types(
                    tool_evidence.get("analysis", {}).get("year_distribution", {})
                )
            elif data_key == "missing_key_papers":
                supplementary_data["missing_key_papers"] = tool_evidence.get("graph_analysis", {}).get("missing_key_papers", [])
            elif data_key == "suspicious_centrality":
                supplementary_data["suspicious_centrality"] = tool_evidence.get("graph_analysis", {}).get("suspicious_centrality", [])
            elif data_key == "c6_contradictions":
                supplementary_data["c6_contradictions"] = tool_evidence.get("c6_alignment", {}).get("contradictions", [])
            elif data_key == "unverified_references":
                supplementary_data["unverified_references"] = tool_evidence.get("validation", {}).get("references", [])[:10]

    # Build warnings
    warnings = build_warnings(agent_name, tool_evidence, sub_dim)

    # Output schema for this sub-dimension
    output_schema = {
        "sub_id": sub_dim.sub_id,
        "score": "integer 1-5",
        "llm_reasoning": "string - explanation for the score",
        "flagged_items": "list of strings - items that need attention",
        "tool_evidence_used": {k: v.get("value") for k, v in evidence_metrics.items() if v.get("value") is not None},
    }

    return {
        "sub_id": sub_dim.sub_id,
        "name": sub_dim.name,
        "description": sub_dim.description,
        "hallucination_risk": sub_dim.hallucination_risk,
        "rubric": sub_dim.rubric,
        "evidence_metrics": evidence_metrics,
        "supplementary_data": supplementary_data,
        "warnings": warnings,
        "output_schema": output_schema,
    }


def get_corrector_targets(agent_outputs: Dict[str, Any], tool_evidence: Dict[str, Any]) -> Dict[str, List[str]]: #FIXME: give corrector the same input as ohter agent to vote again
    """Determine which sub-dimensions should receive multi-model voting.

    This function dynamically determines voting targets based on hallucination_risk.
    Low-risk dimensions (V1, E1, R1) are skipped because they are based on
    deterministic thresholds.

    Args:
        agent_outputs: The agent_outputs dict from state.
        tool_evidence: The tool_evidence dict for checking C6.auto_fail.

    Returns:
        Dict mapping agent_name to list of sub_ids that need voting.
    """
    targets: Dict[str, List[str]] = {
        "verifier": [],
        "expert": [],
        "reader": [],
    }

    for agent_name, agent_def in AGENT_REGISTRY.items():
        for sub_dim in agent_def.sub_dimensions:
            # Determine hallucination_risk for this sub-dimension
            risk = sub_dim.hallucination_risk

            # Special case: V2's risk depends on C6.auto_fail
            if agent_name == "verifier" and sub_dim.sub_id == "V2":
                c6_data = extract_metric_with_extra(tool_evidence, "C6")
                if c6_data.get("auto_fail", False):
                    risk = "low"  # Auto-failed, no voting needed
                else:
                    risk = "medium"  # Normal LLM judgment

            # Only vote on medium/high risk dimensions
            if risk in ["medium", "high"]:
                targets[agent_name].append(sub_dim.sub_id)

    return targets


def generate_metrics_index() -> Dict[str, Any]:
    """Generate the metrics_index structure for run.json.

    Returns:
        The metrics_index dict as defined in Plan v3 §3.4.3.
    """
    metrics_index: Dict[str, Any] = {
        "metrics": {},
        "agent_dimensions": {},
    }

    # Populate metrics
    for metric_id, metric_def in METRIC_REGISTRY.items():
        metrics_index["metrics"][metric_id] = {
            "name": metric_def.name,
            "computed_by": metric_def.source,
            "llm_involved": metric_def.llm_involved,
            "hallucination_risk": metric_def.hallucination_risk,
            "consumed_by": [],  # Will be populated based on AGENT_REGISTRY
        }

    # Populate agent_dimensions and update consumed_by
    for agent_name, agent_def in AGENT_REGISTRY.items():
        agent_dimensions = {
            "input_evidence": agent_def.input_metric_ids,
            "output_dimensions": [sd.sub_id for sd in agent_def.sub_dimensions],
            "corrector_targets": [],  # Will be updated dynamically
        }

        for sub_dim in agent_def.sub_dimensions:
            for metric_id in sub_dim.evidence_metric_ids:
                if metric_id in metrics_index["metrics"]:
                    metrics_index["metrics"][metric_id]["consumed_by"].append(
                        f"{agent_name.capitalize()}Agent.{sub_dim.sub_id}"
                    )

        agent_dimensions["corrector_targets"] = [
            sd.sub_id for sd in agent_def.sub_dimensions
            if sd.hallucination_risk in ["medium", "high"]
        ]

        agent_dimensions["input_evidence"] = agent_def.input_metric_ids
        agent_dimensions["output_dimensions"] = [sd.sub_id for sd in agent_def.sub_dimensions]

        metrics_index["agent_dimensions"][f"{agent_name.capitalize()}Agent"] = agent_dimensions

    return metrics_index


# =============================================================================
# Main Dispatch Function
# =============================================================================

async def run_evidence_dispatch(state: SurveyState) -> Dict[str, Any]:
    """Node function for evidence dispatch (refactored).

    This node:
    1. Generates dispatch_specs for each agent with per-sub-dimension contexts
    2. Pre-fills scores for short-circuited sub-dimensions (e.g., V2 when C6.auto_fail=True)
    3. Generates metrics_index for run.json

    Args:
        state: Current workflow state with tool_evidence.

    Returns:
        Updated state with:
        - dispatch_specs: Per-agent per-sub-dimension contexts for evaluation
        - metrics_index: Index of all metrics for run.json
    """
    logger.info("Running evidence dispatch node (refactored)...")
    tool_evidence = state.get("tool_evidence", {})

    result: Dict[str, Any] = {}

    # =========================================================================
    # Generate dispatch_specs for each agent
    # =========================================================================
    dispatch_specs: Dict[str, Any] = {}

    for agent_name, agent_def in AGENT_REGISTRY.items():
        agent_dispatch: Dict[str, Any] = {
            "sub_dimension_contexts": {},
            "pre_filled_scores": {},
            "state_fields": agent_def.state_fields + ["parsed_content"],
            "agent_meta": {
                "agent_name": agent_name,
                "dimension": agent_def.dimension,
            },
        }

        for sub_dim in agent_def.sub_dimensions:
            # Check short-circuit condition
            should_short_circuit = False
            short_circuit_result = None

            if sub_dim.short_circuit:
                # Evaluate short-circuit condition
                condition = sub_dim.short_circuit.get("condition", "")
                if "C6.auto_fail == True" in condition:
                    c6_data = extract_metric_with_extra(tool_evidence, "C6")
                    if c6_data.get("auto_fail", False):
                        should_short_circuit = True
                        short_circuit_result = {
                            "score": sub_dim.short_circuit.get("result", 1),
                            "auto_failed": True,
                            "reason": "C6.auto_fail triggered",
                        }

            if should_short_circuit and short_circuit_result:
                # Pre-fill the score, don't add to sub_dimension_contexts
                agent_dispatch["pre_filled_scores"][sub_dim.sub_id] = short_circuit_result
                logger.info(f"  {agent_name}: {sub_dim.sub_id} short-circuited to score={short_circuit_result['score']}")
            else:
                # Build full context for this sub-dimension
                context = build_sub_dimension_context(agent_name, sub_dim, tool_evidence, state)
                agent_dispatch["sub_dimension_contexts"][sub_dim.sub_id] = context

        dispatch_specs[agent_name] = agent_dispatch

    result["dispatch_specs"] = dispatch_specs

    # =========================================================================
    # Generate metrics_index
    # =========================================================================
    result["metrics_index"] = generate_metrics_index()

    logger.info(f"Evidence dispatch complete: {len(dispatch_specs)} agents")
    for agent_name, spec in dispatch_specs.items():
        shorted = len(spec["pre_filled_scores"])
        contexted = len(spec["sub_dimension_contexts"])
        logger.info(f"  {agent_name}: {contexted} to evaluate, {shorted} pre-filled")

    return result
