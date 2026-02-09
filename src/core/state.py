"""SurveyMAE State Definitions.

Defines the TypedDict-based state schema for the LangGraph workflow.
All state fields must have explicit type annotations per Document 4.
"""

from typing import TypedDict, List, Annotated, Optional, Literal
import operator


class EvaluationRecord(TypedDict):
    """Represents a single evaluation result from an agent.

    Attributes:
        agent_name: The identifier of the agent that produced this evaluation.
        dimension: The evaluation dimension (e.g., "factuality", "coverage",
                   "depth", "bias").
        score: Numerical score in range [0.0, 10.0].
        reasoning: Detailed explanation for the score.
        evidence: Supporting evidence such as quotes or search results.
        confidence: Confidence level of the evaluation [0.0, 1.0].
    """

    agent_name: str
    dimension: str
    score: float
    reasoning: str
    evidence: Optional[str]
    confidence: float


class DebateMessage(TypedDict):
    """Represents a message in the debate/consensus process.

    Attributes:
        sender: The agent or role that sent this message.
        content: The message content.
        round_idx: The debate round this message belongs to.
    """

    sender: str
    content: str
    round_idx: int


class SectionResult(TypedDict):
    """Represents the evaluation result for a specific section of the survey.

    Attributes:
        section_name: Name of the section being evaluated.
        section_content: The actual content of the section.
        evaluations: List of evaluation records from different agents.
        debate_history: Discussion history if consensus was reached through debate.
        consensus_score: Final agreed score after debate (if applicable).
    """

    section_name: str
    section_content: str
    evaluations: List[EvaluationRecord]
    debate_history: List[DebateMessage]
    consensus_score: Optional[float]


class SurveyState(TypedDict):
    """Main state schema for the SurveyMAE evaluation workflow.

    This state is passed through all nodes in the LangGraph workflow.
    Uses Annotated with operator.add for fields that accumulate from multiple
    parallel agents.

    Attributes:
        source_pdf_path: Path to the input survey PDF file.
        parsed_content: PDF content parsed to markdown/text format.

        evaluations: Accumulated evaluation records from all agents.
                     Uses operator.add to append records from parallel nodes.

        debate_history: Accumulated debate messages during consensus process.
                        Uses operator.add to preserve all debate content.

        sections: Dictionary mapping section names to their evaluation results.

        current_round: Current debate round (starts at 0).

        consensus_reached: Boolean flag indicating if consensus is achieved.

        final_report_md: The final markdown report generated after evaluation.

        metadata: Additional metadata about the survey being evaluated.
    """

    # --- Input ---
    source_pdf_path: str
    parsed_content: str

    # --- Process Data (using reducer for incremental updates) ---
    evaluations: Annotated[List[EvaluationRecord], operator.add]
    debate_history: Annotated[List[DebateMessage], operator.add]
    sections: dict[str, SectionResult]

    # --- Control Flow ---
    current_round: int
    consensus_reached: bool

    # --- Output ---，
    final_report_md: str

    # --- Metadata ---
    metadata: dict[str, str]
