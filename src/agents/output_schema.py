"""Helper utilities for building Agent outputs.

This module provides functions to create structured Agent output JSON
according to the schema defined in Plan v2.
"""

import json
from typing import Any, Dict, List, Optional


def create_sub_score(
    score: float,
    llm_involved: bool,
    tool_evidence: Dict[str, Any],
    llm_reasoning: str,
    flagged_items: Optional[List[Any]] = None,
    variance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create an AgentSubScore dictionary.

    Args:
        score: Numerical score (1-5).
        llm_involved: Whether LLM was involved.
        tool_evidence: Tool evidence used.
        llm_reasoning: LLM's reasoning.
        flagged_items: Items flagged for attention.
        variance: Variance information from multi-model voting.

    Returns:
        AgentSubScore dictionary.
    """
    return {
        "score": score,
        "llm_involved": llm_involved,
        "tool_evidence": tool_evidence,
        "llm_reasoning": llm_reasoning,
        "flagged_items": flagged_items or [],
        "variance": variance,
    }


def create_agent_output(
    agent_name: str,
    dimension: str,
    sub_scores: Dict[str, Dict[str, Any]],
    overall_score: float,
    confidence: float,
    evidence_summary: str,
) -> Dict[str, Any]:
    """Create an AgentOutput dictionary.

    Args:
        agent_name: Name of the agent.
        dimension: Evaluation dimension.
        sub_scores: Dict of sub-dimension scores.
        overall_score: Overall score (1-5).
        confidence: Confidence level (0-1).
        evidence_summary: Summary of evidence used.

    Returns:
        AgentOutput dictionary.
    """
    return {
        "agent_name": agent_name,
        "dimension": dimension,
        "sub_scores": sub_scores,
        "overall_score": overall_score,
        "confidence": confidence,
        "evidence_summary": evidence_summary,
    }


def parse_agent_json_output(raw_output: str) -> Optional[Dict[str, Any]]:
    """Parse Agent output from JSON string.

    Args:
        raw_output: Raw JSON string from agent.

    Returns:
        Parsed JSON or None if parsing fails.
    """
    try:
        # Try direct JSON parse
        return json.loads(raw_output)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from markdown code blocks
    import re

    json_match = re.search(r"```json\s*(.*?)\s*```", raw_output, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find any JSON object
    json_match = re.search(r"\{.*\}", raw_output, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def calculate_overall_from_subscores(sub_scores: Dict[str, Dict[str, Any]]) -> float:
    """Calculate overall score from sub-scores.

    Args:
        sub_scores: Dict of sub-dimension scores.

    Returns:
        Average of all sub-scores.
    """
    if not sub_scores:
        return 0.0

    total = sum(s.get("score", 0) for s in sub_scores.values())
    return total / len(sub_scores)


def create_variance_info(
    models_used: List[str],
    scores: List[float],
    aggregation: str = "median",
) -> Dict[str, Any]:
    """Create variance information for multi-model voting.

    Args:
        models_used: List of model names.
        scores: List of scores from each model.
        aggregation: Aggregation method (median, mean).

    Returns:
        Variance info dictionary.
    """
    import statistics

    if not scores:
        return {
            "models_used": models_used,
            "scores": [],
            "aggregated": None,
            "std": None,
        }

    if aggregation == "median":
        aggregated = statistics.median(scores)
    else:
        aggregated = statistics.mean(scores)

    std = statistics.stdev(scores) if len(scores) > 1 else 0.0

    return {
        "models_used": models_used,
        "scores": scores,
        "aggregated": aggregated,
        "std": std,
    }


# Rubric templates for each sub-dimension
VERIFIER_RUBRICS = {
    "V1": {
        "name": "citation_existence",
        "description": "Whether references actually exist in external databases",
        "rubric": {
            5: "C5 ≥ 0.95",
            4: "C5 ≥ 0.85",
            3: "C5 ≥ 0.70",
            2: "C5 ≥ 0.50",
            1: "C5 < 0.50",
        },
    },
    "V2": {
        "name": "citation_supportiveness",
        "description": "Whether cited sources support the claims made",
        "rubric": {
            5: "≥90% of sampled citation-claim pairs are fully supported",
            4: "70-89% supported, some partial support",
            3: "50-69% supported, some irrelevant citations",
            2: "30-49% supported, many mismatches",
            1: "<30% supported, many false/irrelevant citations",
        },
    },
    "V3": {
        "name": "citation_accuracy",
        "description": "Whether the survey correctly understands the cited work",
        "rubric": {
            5: "No misinterpretation, overgeneralization, or misattribution",
            4: "Minor errors, overall accurate understanding",
            5: "Some misinterpretation or overgeneralization",
            2: "Frequent misinterpretation or misattribution",
            1: "Severe misunderstanding of cited works",
        },
    },
    "V4": {
        "name": "internal_consistency",
        "description": "Whether the survey has internal contradictions",
        "rubric": {
            5: "No contradictions detected",
            4: "Minor inconsistencies, easily explained",
            3: "Some contradictions that need clarification",
            2: "Multiple contradictions affecting credibility",
            1: "Severe contradictions making the survey unreliable",
        },
    },
}

EXPERT_RUBRICS = {
    "E1": {
        "name": "foundational_coverage",
        "description": "Coverage of foundational works in the field",
        "rubric": {
            5: "G4 ≥ 0.8, no seminal works missing",
            4: "G4 ≥ 0.6, missing non-critical papers",
            3: "G4 ≥ 0.4, missing 1-2 core papers",
            2: "G4 ≥ 0.2, missing multiple core papers",
            1: "G4 < 0.2, severely missing foundational works",
        },
    },
    "E2": {
        "name": "classification_reasonableness",
        "description": "Reasonableness of method classification",
        "rubric": {
            5: "S5 (NMI) high, classification aligns with citation clusters",
            4: "Good alignment, minor deviations",
            3: "Some misalignment, but acceptable",
            2: "Significant misalignment",
            1: "Classification contradicts citation structure",
        },
    },
    "E3": {
        "name": "technical_accuracy",
        "description": "Technical correctness of method descriptions",
        "rubric": {
            5: "No technical errors",
            4: "Minor technical inaccuracies",
            3: "Some technical errors,不影响理解",
            2: "Frequent technical errors",
            1: "Severe technical misunderstandings",
        },
    },
    "E4": {
        "name": "critical_analysis_depth",
        "description": "Depth of critical analysis and comparison",
        "rubric": {
            5: "Systematic comparison, clear trends, detailed limitations",
            4: "Good comparison, some analysis",
            3: "Some comparison, mostly listing",
            2: "Mostly listing, minimal analysis",
            1: "Pure paper summary, no analysis",
        },
    },
}

READER_RUBRICS = {
    "R1": {
        "name": "timeliness",
        "description": "Coverage of historical and recent developments",
        "rubric": {
            5: "T5 ≥ 0.7, T2 ≤ 2 years, T4 ≤ 1 year",
            4: "T5 ≥ 0.5, T4 ≤ 2 years, reasonable coverage",
            3: "T5 ≥ 0.3, minor gaps",
            2: "T5 < 0.3, or T4 ≥ 3 years gap",
            1: "Almost all citations from 1-2 years, or missing foundational work",
        },
    },
    "R2": {
        "name": "information_balance",
        "description": "Balance of information across sections",
        "rubric": {
            5: "Good balance, reasonable focus on key areas",
            4: "Generally balanced, minor unevenness",
            3: "Some imbalance, but justified focus",
            2: "Significant imbalance",
            1: "Severe imbalance affecting completeness",
        },
    },
    "R3": {
        "name": "structural_clarity",
        "description": "Clarity of hierarchical structure",
        "rubric": {
            5: "S5 (NMI) high, clear hierarchical structure",
            4: "Good structure, minor issues",
            3: "Acceptable structure",
            2: "Unclear structure, hard to follow",
            1: "Poor structure, confusing organization",
        },
    },
    "R4": {
        "name": "writing_quality",
        "description": "Language quality and consistency",
        "rubric": {
            5: "Excellent language, consistent terminology",
            4: "Good language, minor issues",
            3: "Acceptable, some inconsistencies",
            2: "Frequent language issues",
            1: "Poor language, hard to understand",
        },
    },
}


def get_rubric(agent: str, sub_dimension: str) -> Optional[Dict[str, Any]]:
    """Get rubric for a specific sub-dimension.

    Args:
        agent: Agent name (verifier, expert, reader).
        sub_dimension: Sub-dimension ID (V1, V2, etc.).

    Returns:
        Rubric dictionary or None.
    """
    rubrics = {
        "verifier": VERIFIER_RUBRICS,
        "expert": EXPERT_RUBRICS,
        "reader": READER_RUBRICS,
    }

    agent_rubrics = rubrics.get(agent.lower())
    if agent_rubrics:
        return agent_rubrics.get(sub_dimension)
    return None


def format_rubric_for_prompt(agent: str) -> str:
    """Format rubrics for inclusion in agent prompt.

    Args:
        agent: Agent name.

    Returns:
        Formatted rubric string.
    """
    rubrics = {
        "verifier": VERIFIER_RUBRICS,
        "expert": EXPERT_RUBRICS,
        "reader": READER_RUBRICS,
    }

    agent_rubrics = rubrics.get(agent.lower(), {})
    if not agent_rubrics:
        return "No rubrics defined."

    lines = ["## Scoring Rubric\n"]
    for dim_id, rubric in agent_rubrics.items():
        lines.append(f"### {dim_id}: {rubric['name']}")
        lines.append(f"{rubric['description']}\n")
        for score, description in sorted(rubric["rubric"].items(), reverse=True):
            lines.append(f"- **{score}**: {description}")
        lines.append("")

    return "\n".join(lines)
