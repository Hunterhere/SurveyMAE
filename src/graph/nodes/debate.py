"""Debate Node.

Handles the debate/consensus mechanism between conflicting evaluations.
"""

import logging
from typing import Dict, Any

from src.core.state import SurveyState, DebateMessage, EvaluationRecord

logger = logging.getLogger(__name__)


async def run_debate(state: SurveyState) -> Dict[str, Any]:
    """Run a debate round to resolve conflicting evaluations.

    This node is triggered when agents have significantly different scores.
    It facilitates discussion and attempts to reach consensus.

    Args:
        state: The current workflow state containing evaluations.

    Returns:
        Updated state with debate messages and potentially revised scores.
    """
    current_round = state.get("current_round", 0)
    evaluations = state.get("evaluations", [])
    debate_history = state.get("debate_history", [])

    logger.info(f"Running debate round {current_round + 1}")

    # Group evaluations by dimension
    dim_evals: dict[str, list] = {}
    for eval_record in evaluations:
        dim = eval_record.get("dimension", "unknown")
        if dim not in dim_evals:
            dim_evals[dim] = []
        dim_evals[dim].append(eval_record)

    # Generate debate messages for conflicting dimensions
    new_messages: list[DebateMessage] = []

    for dim, evals in dim_evals.items():
        if len(evals) >= 2:
            # Find conflicting scores
            scores = [e.get("score", 5.0) for e in evals]
            score_range = max(scores) - min(scores)

            if score_range > 2.0:  # Threshold for debate
                # Create a debate message about the conflict
                debate_content = (
                    f"Debate on dimension '{dim}': "
                    f"Scores range from {min(scores):.1f} to {max(scores):.1f}. "
                    f"Agents should discuss their reasoning and provide additional evidence."
                )

                new_messages.append(
                    DebateMessage(
                        sender="debate_moderator",
                        content=debate_content,
                        round_idx=current_round,
                    )
                )

                # In a full implementation, this would invoke LLM agents
                # to debate and potentially revise their scores

    return {
        "debate_history": new_messages,
        "current_round": current_round + 1,
        # In a full implementation, revised evaluations would be returned here
        "consensus_reached": len(new_messages) == 0,  # No conflicts = consensus
    }
