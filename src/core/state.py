"""SurveyMAE State Definitions.

Defines the TypedDict-based state schema for the LangGraph workflow.
All state fields must have explicit type annotations per Document 4.
"""

from typing import TypedDict, List, Annotated, Optional, Literal, Dict, Any
import operator
from typing import Callable

from pydantic import BaseModel, Field


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


class C6AlignmentResult(TypedDict):
    """Result from C6 citation-sentence alignment analysis.

    Attributes:
        total_pairs: Total number of citation-sentence pairs analyzed.
        support: Number of pairs where sentence is supported by abstract.
        contradict: Number of pairs where sentence contradicts abstract.
        insufficient: Number of pairs with insufficient information.
        contradiction_rate: Rate of contradictions (contradict / total_pairs).
        auto_fail: Whether contradiction_rate exceeds threshold.
        contradictions: List of contradiction details.
        missing_abstract_count: Number of pairs missing abstract.
    """

    total_pairs: int
    support: int
    contradict: int
    insufficient: int
    contradiction_rate: float
    auto_fail: bool
    contradictions: List[Dict[str, Any]]
    missing_abstract_count: int


class KeyPapersResult(TypedDict):
    """Result from G4 foundational coverage analysis.

    Attributes:
        candidate_count: Number of candidate key papers retrieved.
        matched_count: Number of candidate papers matched in survey references.
        coverage_rate: G4 coverage rate (matched / candidate).
        missing_key_papers: List of papers that should be cited but are not.
        suspicious_centrality: List of papers with high internal citations but low external citations.
    """

    candidate_count: int
    matched_count: int
    coverage_rate: float
    missing_key_papers: List[Dict[str, Any]]
    suspicious_centrality: List[Dict[str, Any]]


class ToolEvidence(TypedDict):
    """Evidence collected from tools for agent evaluation.

    Attributes:
        extraction: Citation extraction results from CitationChecker.
        validation: Metadata validation results (C3, C5) + ref_metadata_cache.
        c6_alignment: C6 citation-sentence alignment results (v3 new).
        analysis: Temporal and structural analysis (T1-T5, S1-S4).
        graph_analysis: Citation graph analysis (G1-G6, S5).
        trend_baseline: Field publication trend from academic APIs (v3 new).
        key_papers: Candidate key papers + G4 results (v3 new).
    """

    extraction: Dict[str, Any]
    validation: Dict[str, Any]
    c6_alignment: Optional[C6AlignmentResult]
    analysis: Dict[str, Any]
    graph_analysis: Dict[str, Any]
    trend_baseline: Optional[Dict[str, Any]]
    key_papers: Optional[KeyPapersResult]


class VarianceRecord(TypedDict):
    """Variance information from multi-model voting.

    Attributes:
        models_used: List of model identifiers used.
        scores: List of scores from each model.
        median: Median score.
        std: Standard deviation of scores.
        high_disagreement: Whether the variance indicates high disagreement (std > 1.0 or max-min > 2).
    """

    models_used: List[str]
    scores: List[float]
    median: float
    std: float
    high_disagreement: bool


class CorrectionRecord(TypedDict):
    """Correction record from Corrector multi-model voting.

    Attributes:
        original_agent: Original agent that provided the score.
        original_score: Original score before correction.
        corrected_score: Corrected score (median from multi-model voting).
        variance: Variance information from the voting.
    """

    original_agent: str
    original_score: float
    corrected_score: float
    variance: VarianceRecord


class CorrectorOutput(TypedDict):
    """Output from Corrector multi-model voting correction.

    Attributes:
        corrections: Dict mapping dimension ID to correction record.
        skipped_dimensions: List of dimensions that were skipped (low hallucination risk).
        skip_reason: Reason for skipping dimensions.
        total_model_calls: Total number of LLM calls made.
        failed_calls: Number of failed LLM calls.
    """

    corrections: Dict[str, CorrectionRecord]
    skipped_dimensions: List[str]
    skip_reason: str
    total_model_calls: int
    failed_calls: int


class DimensionScore(TypedDict):
    """Final score for a dimension in aggregation.

    Attributes:
        dim_id: Dimension identifier (e.g., "V1", "E2").
        final_score: Final score after correction (if any) or original score.
        source: Source of the score ("original" or "corrected").
        agent: Agent that produced the original score.
        hallucination_risk: Hallucination risk level.
        variance: Variance information (if corrected).
        weight: Weight used in aggregation.
    """

    dim_id: str
    final_score: float
    source: Literal["original", "corrected"]
    agent: str
    hallucination_risk: str
    variance: Optional[VarianceRecord]
    weight: float


class AgentSubScore(TypedDict):
    """Sub-dimension score from an agent.

    Attributes:
        score: Numerical score (1-5).
        llm_involved: Whether LLM was involved in this scoring.
        hallucination_risk: Risk level of hallucination ("low", "medium", "high").
        tool_evidence: Tool evidence used for scoring.
        llm_reasoning: LLM's reasoning for the score.
        flagged_items: Items flagged for attention.
        variance: Variance information (for multi-model voting, initially null, filled by Corrector).
    """

    score: float
    llm_involved: bool
    hallucination_risk: str
    tool_evidence: Dict[str, Any]
    llm_reasoning: str
    flagged_items: Optional[List[Any]]
    variance: Optional[VarianceRecord]


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
    """Aggregated scores from all agents (v3 weighted aggregation).

    Attributes:
        dimension_scores: Dict mapping dimension ID to final score info.
        deterministic_metrics: Raw values of first-layer metrics (C3, C5, T1-T5, S1-S5, G1-G6).
        overall_score: Weighted overall score (0-10 scale).
        grade: Letter grade (A/B/C/D/F).
        total_weight: Total weight used in aggregation.
    """

    dimension_scores: Dict[str, DimensionScore]
    deterministic_metrics: Dict[str, float]
    overall_score: float
    grade: str
    total_weight: float


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


class EvaluationRecordModel(BaseModel):
    """Pydantic model for EvaluationRecord with validation.

    This provides stricter validation than the TypedDict version,
    including score range validation and required field enforcement.

    Attributes:
        agent_name: The identifier of the agent (required).
        dimension: The evaluation dimension (required).
        score: Numerical score in range [0.0, 10.0] (required).
        reasoning: Detailed explanation for the score (required).
        evidence: Supporting evidence such as quotes or search results (optional).
        confidence: Confidence level of the evaluation [0.0, 1.0] (required).
    """

    agent_name: str = Field(..., description="The identifier of the agent")
    dimension: str = Field(..., description="The evaluation dimension")
    score: float = Field(..., ge=0.0, le=10.0, description="Score in range [0.0, 10.0]")
    reasoning: str = Field(..., description="Detailed explanation for the score")
    evidence: str | None = Field(default=None, description="Supporting evidence")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence level [0.0, 1.0]")

    def to_typed_dict(self) -> EvaluationRecord:
        """Convert to TypedDict for LangGraph compatibility."""
        return EvaluationRecord(
            agent_name=self.agent_name,
            dimension=self.dimension,
            score=self.score,
            reasoning=self.reasoning,
            evidence=self.evidence,
            confidence=self.confidence,
        )

    @classmethod
    def from_typed_dict(cls, record: EvaluationRecord) -> "EvaluationRecordModel":
        """Create from TypedDict."""
        return cls(**record)


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

        sections: Dictionary mapping section names to their evaluation results.

        agent_outputs: Structured outputs from each agent (V/E/R).

        corrector_output: Output from Corrector multi-model voting (v3 new).

        aggregated_scores: Aggregated scores from all agents.

        current_round: Current round (starts at 0, kept for compatibility).

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
    sections: dict[str, SectionResult]

    # --- Agent Outputs ---
    agent_outputs: Annotated[Dict[str, AgentOutput], dict_merge]
    corrector_output: Optional[CorrectorOutput] = None  # v3: Corrector voting results
    aggregated_scores: AggregatedScores

    # --- Control Flow ---
    current_round: int
    consensus_reached: bool

    # --- Output ---
    final_report_md: str

    # --- Metadata ---
    metadata: dict[str, str]

    # --- Dispatch Specs (Phase 2) ---
    # Per-agent evaluation contexts generated by evidence_dispatch node
    dispatch_specs: Optional[Dict[str, Any]] = None

    # --- Metrics Index (Phase 2) ---
    # Index of all metrics for run.json, generated by evidence_dispatch node
    metrics_index: Optional[Dict[str, Any]] = None
