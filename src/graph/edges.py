"""Edge Logic for Conditional Routing.

Defines the routing logic for the LangGraph workflow.
"""

from typing import Literal

from src.core.state import SurveyState


def should_continue_debate(state: SurveyState) -> Literal["continue", "reporter"]:
    """Determine if the debate should continue or proceed to report generation.

    Args:
        state: The current workflow state.

    Returns:
        "continue" to run another debate round, "reporter" to finalize scores.
    """
    # This would typically use DebateConfig, passed via config or state
    max_rounds = state.get("metadata", {}).get("max_debate_rounds", 3)
    current_round = state.get("current_round", 0)
    consensus_reached = state.get("consensus_reached", False)

    # Continue if we haven't reached max rounds and consensus isn't reached
    if current_round < max_rounds and not consensus_reached:
        return "continue"

    return "reporter"


def should_end(state: SurveyState) -> Literal["END", "debate"]:
    """Determine if the evaluation process is complete.

    Args:
        state: The current workflow state.

    Returns:
        "END" to terminate the workflow, "debate" to enter debate phase.
    """
    evaluations = state.get("evaluations", [])

    if not evaluations:
        # No evaluations yet, continue to evaluation phase
        return "debate"

    # Check if we need a debate phase
    # This could be based on score variance or explicit requirements
    needs_debate = _check_if_debate_needed(evaluations)

    if needs_debate:
        return "debate"

    return "END"


def _check_if_debate_needed(evaluations: list) -> bool:
    """Check if the evaluations suggest a need for debate.

    Args:
        evaluations: List of evaluation records.

    Returns:
        True if debate is recommended based on score variance.
    """
    if not evaluations:
        return False

    # Group evaluations by dimension
    dim_scores: dict[str, list] = {}
    for eval_record in evaluations:
        dim = eval_record.get("dimension", "unknown")
        if dim not in dim_scores:
            dim_scores[dim] = []
        dim_scores[dim].append(eval_record.get("score", 5.0))

    # Check variance for each dimension
    threshold = 2.0  # Score difference threshold
    for dim, scores in dim_scores.items():
        if len(scores) >= 2:
            score_range = max(scores) - min(scores)
            if score_range > threshold:
                return True

    return False
