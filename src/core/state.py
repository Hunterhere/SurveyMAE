"""SurveyMAE State Definitions.

Defines the TypedDict-based state schema for the LangGraph workflow.
All state fields must have explicit type annotations per Document 4.
"""

from typing import TypedDict, List, Annotated, Optional, Literal, Dict, Any
import operator
from typing import Callable


def dict_merge(left: dict, right: dict) -> dict:
    """Merge two dictionaries for LangGraph state updates.

    Args:
        left: Existing dictionary.
        right: New dictionary to merge.

    Returns:
        Merged dictionary.
    """
    result = dict(left)
    result.update(right)
    return result


class MetricMetadata(TypedDict):
    """Metadata for evaluation metrics.

    Attributes:
        metric_id: Unique identifier for the metric (e.g., "V1", "T5", "G4").
        metric_name: Human-readable name of the metric.
        llm_involved: Whether LLM is involved in this metric's calculation.
        llm_role: Description of LLM's role if involved.
        hallucination_risk: Risk level of hallucination ("none", "low", "medium", "high").
        variance_strategy: Strategy for variance control (for LLM-involved metrics).
        reported_variance: Reported variance statistics.
        confidence: Confidence level for deterministic metrics (1.0).
    """

    metric_id: str
    metric_name: str
    llm_involved: bool
    llm_role: Optional[str]
    hallucination_risk: Optional[str]
    variance_strategy: Optional[Dict[str, Any]]
    reported_variance: Optional[Dict[str, Any]]
    confidence: float


class ToolEvidence(TypedDict):
    """Evidence collected from tools for agent evaluation.

    Attributes:
        extraction: Citation extraction results from CitationChecker.
        validation: Metadata validation results (C3, C5).
        analysis: Temporal and structural analysis (T1-T5, S1-S5).
        graph_analysis: Citation graph analysis (G1-G6).
    """

    extraction: Dict[str, Any]
    validation: Dict[str, Any]
    analysis: Dict[str, Any]
    graph_analysis: Dict[str, Any]


class AgentSubScore(TypedDict):
    """Sub-dimension score from an agent.

    Attributes:
        score: Numerical score (1-5).
        llm_involved: Whether LLM was involved in this scoring.
        tool_evidence: Tool evidence used for scoring.
        llm_reasoning: LLM's reasoning for the score.
        flagged_items: Items flagged for attention.
        variance: Variance information (for multi-model voting).
    """

    score: float
    llm_involved: bool
    tool_evidence: Dict[str, Any]
    llm_reasoning: str
    flagged_items: Optional[List[Any]]
    variance: Optional[Dict[str, Any]]


class AgentOutput(TypedDict):
    """Output from an agent evaluation.

    Attributes:
        agent_name: Name of the agent.
        dimension: Evaluation dimension.
        sub_scores: Sub-dimension scores.
        overall_score: Overall score for this dimension.
        confidence: Confidence level of the evaluation.
        evidence_summary: Summary of evidence used.
    """

    agent_name: str
    dimension: str
    sub_scores: Dict[str, AgentSubScore]
    overall_score: float
    confidence: float
    evidence_summary: str


class AggregatedScores(TypedDict):
    """Aggregated scores from all agents.

    Attributes:
        weighted_score: Weighted aggregate score.
        deterministic_score: Score from deterministic metrics only.
        llm_score: Score from LLM-involved metrics (with variance).
        variance: Variance information.
        agent_scores: Individual agent scores.
    """

    weighted_score: float
    deterministic_score: Optional[float]
    llm_score: Optional[float]
    variance: Optional[Dict[str, Any]]
    agent_scores: Dict[str, float]


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

        section_headings: Extracted section headings from the PDF.

        tool_evidence: Evidence collected from tools for agent evaluation.

        ref_metadata_cache: Core shared data - complete metadata for each reference.

        topic_keywords: LLM-extracted keywords (shared by T2/T5/G4).

        field_trend_baseline: Field publication trend retrieved from academic APIs.

        candidate_key_papers: Retrieved candidate key papers for G4 analysis.

        evaluations: Accumulated evaluation records from all agents.
                     Uses operator.add to append records from parallel nodes.

        debate_history: Accumulated debate messages during consensus process.
                        Uses operator.add to preserve all debate content.

        sections: Dictionary mapping section names to their evaluation results.

        agent_outputs: Structured outputs from each agent.

        aggregated_scores: Aggregated scores from all agents.

        current_round: Current debate round (starts at 0).

        consensus_reached: Boolean flag indicating if consensus is achieved.

        final_report_md: The final markdown report generated after evaluation.

        metadata: Additional metadata about the survey being evaluated.
    """

    # --- Input ---
    source_pdf_path: str
    parsed_content: str

    # --- Preprocessed Data ---
    section_headings: List[str]

    # --- Tool Evidence (Phase 1) ---
    tool_evidence: ToolEvidence
    ref_metadata_cache: Dict[str, dict]  # Key: ref_id, Value: complete metadata
    topic_keywords: List[str]
    field_trend_baseline: Dict[str, Any]
    candidate_key_papers: List[dict]

    # --- Process Data (using reducer for incremental updates) ---
    evaluations: Annotated[List[EvaluationRecord], operator.add]
    debate_history: Annotated[List[DebateMessage], operator.add]
    sections: dict[str, SectionResult]

    # --- Agent Outputs ---
    agent_outputs: Annotated[Dict[str, AgentOutput], dict_merge]
    aggregated_scores: AggregatedScores

    # --- Control Flow ---
    current_round: int
    consensus_reached: bool

    # --- Output ---
    final_report_md: str

    # --- Metadata ---
    metadata: dict[str, str]

    # --- Evidence Reports (Phase 2) ---
    evidence_reports: Optional[Dict[str, str]] = None
    verifier_evidence: Optional[Dict[str, Any]] = None
    expert_evidence: Optional[Dict[str, Any]] = None
    reader_evidence: Optional[Dict[str, Any]] = None
