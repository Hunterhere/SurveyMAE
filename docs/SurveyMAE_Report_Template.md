# SurveyMAE Report Template Design

This document defines the final evaluation report template for SurveyMAE.
Claude Code should implement `generate_report()` in `src/graph/nodes/aggregator.py`
according to this specification.

**Key principle:** The report is 100% template-based (no LLM calls during report generation).
All content comes from structured data already computed and stored in:
- `tool_evidence` (first-layer deterministic metrics)
- `agent_outputs` (each agent's sub_scores with reasoning and flagged items)
- `corrector_output` (variance data for corrected dimensions)
- `aggregation_result` (weighted scores and grade)

---

## 1. Data Sources

### 1.1 Required fields from agent_outputs

Each agent's output (`agent_outputs[agent_name]`) must contain:

```python
{
  "sub_scores": {
    "V1_citation_existence": {
      "score": 4,
      "hallucination_risk": "low",
      "tool_evidence": {                    # <-- REQUIRED for Evidence column
        "metric": "metadata_verify_rate",
        "value": 0.83,
        "detail": "30/36 references verified via Semantic Scholar"
      },
      "llm_reasoning": "...",               # <-- REQUIRED for Agent Analysis section
      "flagged_items": [                    # <-- REQUIRED for Examples section
        "[23] - title not found in any source",
        "[37] - year mismatch (2023 vs 2021)"
      ]
    }
  },
  "evidence_summary": "..."                 # <-- OPTIONAL, used in fallback
}
```

**Critical:** If `llm_reasoning` or `flagged_items` are empty/null in agent output,
the report will show "No detailed analysis available" for that dimension.
Ensure agent prompts require structured output with these fields populated.

### 1.2 Required fields from tool_evidence

```python
tool_evidence = {
  "extraction": { ... },
  "validation": {
    "C3_orphan_ref_rate": 0.03,
    "C5_metadata_verify_rate": 0.83,
    "unverified_references": ["ref_23", "ref_37", ...],
    ...
  },
  "c6_alignment": {
    "total_pairs": 124,
    "support": 115,
    "contradict": 4,
    "insufficient": 5,
    "contradiction_rate": 0.032,
    "auto_fail": false,
    "contradictions": [
      {"citation": "[15]", "sentence": "...", "ref_abstract": "...", "note": "..."},
      ...
    ],
    "missing_abstract_count": 3
  },
  "analysis": {
    "T1_year_span": 34,
    "T2_foundational_retrieval_gap": 5,
    "T3_peak_year_ratio": 0.65,
    "T4_temporal_continuity": 2,
    "T5_trend_alignment": 0.77,
    "S1_section_count": 7,
    "S2_citation_density": 0.897,
    "S3_citation_gini": 0.25,
    "S4_zero_citation_section_rate": 0.0,
    "S5_section_cluster_alignment": 0.68,
    "year_distribution": { "2018": 3, "2019": 5, ... }
  },
  "graph_analysis": {
    "G1_graph_density": 0.12,
    "G2_connected_component_count": 2,
    "G3_max_component_ratio": 0.85,
    "G4_foundational_coverage_rate": 0.47,
    "G5_cluster_count": 3,
    "G6_isolated_node_ratio": 0.08,
    "missing_key_papers": [
      {"title": "Attention Is All You Need", "year": 2017, "citation_count": 95000},
      ...
    ],
    "suspicious_centrality": [...]
  }
}
```

### 1.3 Required fields from corrector_output

```python
corrector_output = {
  "corrections": {
    "V4_internal_consistency": {
      "original_score": 5,
      "corrected_score": 4,
      "variance": {
        "models_used": ["gpt-4o", "claude-sonnet", "deepseek-chat"],
        "scores": [4, 5, 4],
        "median": 4,
        "std": 0.47,
        "high_disagreement": false
      }
    }
  },
  "skipped_dimensions": ["V1", "V2", "E1", "R1"]
}
```

---

## 2. Report Structure

The report has three sections:
1. **Evidence Dashboard** - Deterministic metrics from tool_evidence
2. **Agent Assessment** - Per-agent scoring with reasoning and examples
3. **Key Findings & Recommendations** - Actionable items derived from low scores

---

## 3. Template Specification

### 3.1 Header

```markdown
# SurveyMAE Evaluation Report

**Source**: {source_pdf_path} | **Generated**: {timestamp}
**Overall Score**: {overall_score}/10 (Grade: {grade})

---
```

### 3.2 Section 1: Evidence Dashboard

This section displays ONLY first-layer deterministic metrics.
All values come from `tool_evidence`. No LLM output is used here.

```markdown
## 1. Evidence Dashboard

### Citation Integrity
| Metric | Value | Note |
|--------|-------|------|
| C3 Orphan Ref Rate | {C3} | {C3_note} |
| C5 Metadata Verify Rate | {C5} | {C5_note} |
| C6 Contradiction Rate | {C6_rate} | {C6_note} |

### Temporal Coverage
| Metric | Value | Note |
|--------|-------|------|
| T1 Year Span | {T1} years ({min_year}-{max_year}) | |
| T2 Foundational Gap | {T2} years | {T2_note} |
| T4 Max Citation Gap | {T4} years | {T4_note} |
| T5 Trend Alignment | {T5} | {T5_note} |

### Structure & Graph
| Metric | Value | Note |
|--------|-------|------|
| G4 Foundational Coverage | {G4} | {G4_note} |
| S5 Section-Cluster Alignment | {S5} | {S5_note} |
| G6 Isolated Node Ratio | {G6} | {G6_note} |
```

**Note generation rules** (deterministic, no LLM):

| Metric | Good | Warning | Bad |
|--------|------|---------|-----|
| C3 | < 0.10: "Low orphan rate" | 0.10-0.20 | >= 0.20: "High orphan rate" |
| C5 | >= 0.90: "Strong verification" | 0.70-0.90 | < 0.70: "Many unverified refs" |
| C6 | < 0.02: "Very few contradictions" | 0.02-0.05 | >= 0.05: "Auto-fail triggered" |
| T2 | <= 2: "Covers foundational period" | 3-5 | > 5: "May miss early work" |
| T4 | <= 1: "No significant gap" | 2-3 | > 3: "Significant temporal gap" |
| T5 | >= 0.7: "Well-aligned with field" | 0.4-0.7 | < 0.4: "Misaligned with field trend" |
| G4 | >= 0.7: "Strong coverage" | 0.4-0.7 | < 0.4: "Many key papers missing" |
| S5 | >= 0.7: "Well-organized structure" | 0.4-0.7 | < 0.4: "Weak structure-content alignment" |
| G6 | < 0.10: "Low isolation" | 0.10-0.25 | >= 0.25: "Many isolated references" |

**Implementation:**
```python
def _evidence_dashboard(tool_evidence: dict) -> str:
    validation = tool_evidence.get("validation", {})
    c6 = tool_evidence.get("c6_alignment", {})
    analysis = tool_evidence.get("analysis", {})
    graph = tool_evidence.get("graph_analysis", {})

    # Extract values with safe defaults
    c3 = validation.get("C3_orphan_ref_rate", "N/A")
    c5 = validation.get("C5_metadata_verify_rate", "N/A")
    c6_rate = c6.get("contradiction_rate", "N/A")
    # ... etc

    # Generate notes using threshold rules above
    c5_note = _threshold_note(c5, [(0.9, "Strong verification"), (0.7, ""), (0, "Many unverified refs")])
    # ... etc

    # Format markdown tables
    # ...
```

### 3.3 Section 2: Agent Assessment

This section shows each agent's per-dimension scoring.
Data comes from `agent_outputs` and `corrector_output`.

**IMPORTANT:** The reasoning text and flagged items shown below are EXAMPLES ONLY.
In production, these come directly from each agent's `llm_reasoning` and `flagged_items`
fields in their structured output. The report template simply formats and displays them.

```markdown
## 2. Agent Assessment

### Factuality (VerifierAgent)

| Sub-dimension | Score | Evidence |
|---------------|-------|----------|
| V1 Citation Existence | {V1_score}/5 | {V1_tool_evidence_summary} |
| V2 Citation-Claim Alignment | {V2_score}/5 | {V2_tool_evidence_summary} |
| V4 Internal Consistency | {V4_score}/5 {V4_variance_badge} | {V4_tool_evidence_summary} |

**Agent Analysis:**
{verifier_reasoning_for_lowest_scoring_dimension}

**Flagged Items:**
{verifier_flagged_items_formatted}

---

### Depth (ExpertAgent)

| Sub-dimension | Score | Evidence |
|---------------|-------|----------|
| E1 Foundational Coverage | {E1_score}/5 | {E1_tool_evidence_summary} |
| E2 Classification | {E2_score}/5 {E2_variance_badge} | {E2_tool_evidence_summary} |
| E3 Technical Accuracy | {E3_score}/5 {E3_variance_badge} | {E3_tool_evidence_summary} |
| E4 Critical Analysis | {E4_score}/5 {E4_variance_badge} | {E4_tool_evidence_summary} |

**Agent Analysis:**
{expert_reasoning_for_lowest_scoring_dimension}

**Flagged Items:**
{expert_flagged_items_formatted}

**Missing Key Papers (from G4 search):**
{missing_key_papers_list}

---

### Coverage (ReaderAgent)

| Sub-dimension | Score | Evidence |
|---------------|-------|----------|
| R1 Timeliness | {R1_score}/5 | {R1_tool_evidence_summary} |
| R2 Information Balance | {R2_score}/5 {R2_variance_badge} | {R2_tool_evidence_summary} |
| R3 Structural Clarity | {R3_score}/5 {R3_variance_badge} | {R3_tool_evidence_summary} |
| R4 Writing Quality | {R4_score}/5 {R4_variance_badge} | {R4_tool_evidence_summary} |

**Agent Analysis:**
{reader_reasoning_for_lowest_scoring_dimension}

**Flagged Items:**
{reader_flagged_items_formatted}
```

**Field extraction rules:**

| Template variable | Source | Extraction |
|---|---|---|
| `{V1_score}` | `agent_outputs["verifier"]["sub_scores"]["V1_..."]["score"]` | Direct |
| `{V1_tool_evidence_summary}` | `agent_outputs["verifier"]["sub_scores"]["V1_..."]["tool_evidence"]` | Format as "metric=value, detail" |
| `{V4_variance_badge}` | `corrector_output["corrections"]["V4_..."]["variance"]` | If corrected: "(corrected, std={std})" else empty |
| `{verifier_reasoning_for_lowest_scoring_dimension}` | Find sub_score with lowest score, use its `llm_reasoning` | Truncate to 300 chars if needed |
| `{verifier_flagged_items_formatted}` | Collect `flagged_items` from ALL sub_scores of this agent | Format as bullet list |
| `{missing_key_papers_list}` | `tool_evidence["graph_analysis"]["missing_key_papers"]` | Format as numbered list with title, year, citation_count |

**Variance badge rules:**
- If dimension is in `corrector_output["corrections"]`: show `(corrected, std={std:.2f})`
- If `high_disagreement=true`: show `(corrected, HIGH VARIANCE std={std:.2f})`
- If dimension is NOT corrected: show nothing

**When data is missing:**
- `llm_reasoning` is null/empty: show "No detailed analysis available for this dimension."
- `flagged_items` is null/empty: show "No specific items flagged."
- `tool_evidence` is null/empty: show "N/A"
- `missing_key_papers` is empty: show "No missing key papers detected."

### 3.4 Section 3: Key Findings & Recommendations

This section synthesizes findings from both tool evidence and agent analysis.
Items are sorted by severity (lowest score first).

```markdown
## 3. Key Findings & Recommendations

### Areas Requiring Attention

**{dim_id_1}** (Score: {score_1}/5, Agent: {agent_1})
Evidence: {tool_evidence_summary_1}
Agent assessment: {llm_reasoning_1_truncated}
Recommendation: {recommendation_1}

**{dim_id_2}** (Score: {score_2}/5, Agent: {agent_2})
Evidence: {tool_evidence_summary_2}
Agent assessment: {llm_reasoning_2_truncated}
Recommendation: {recommendation_2}

### Strengths

- {strength_1}: {evidence_1}
- {strength_2}: {evidence_2}
```

**Generation rules (all deterministic, no LLM):**

1. **Areas Requiring Attention:** All dimensions with `final_score < 3.5` (on 1-5 scale), sorted ascending.
   - Evidence line: from `tool_evidence` field of that sub_score
   - Agent assessment line: first 200 characters of `llm_reasoning`
   - Recommendation line: generated by template rules below

2. **Strengths:** All dimensions with `final_score >= 4.0`, sorted descending.
   - Show the tool evidence metric value as supporting evidence

3. **Recommendation rules** (based on dimension ID):

| Dimension | Low-score recommendation template |
|-----------|----------------------------------|
| V1 | "Verify unverified references, particularly: {top_3_unverified_refs}" |
| V2 | "Review flagged citation-claim contradictions, particularly: {top_3_contradictions}" |
| V4 | "Check for internal consistency issues identified by the verifier." |
| E1 | "Consider adding the following key papers: {top_3_missing_papers}" |
| E2 | "Review the classification structure for completeness." |
| E3 | "Double-check technical descriptions flagged by the expert." |
| E4 | "Add comparative analysis, method limitations, and open questions." |
| R1 | "Improve temporal coverage; current trend alignment is T5={T5}." |
| R2 | "Balance citation distribution across sections (current Gini={S3})." |
| R3 | "Improve structural organization (current S5={S5})." |
| R4 | "Review writing quality issues flagged by the reader." |

Each recommendation template pulls specific data from `tool_evidence` or `flagged_items`
to make it concrete and actionable.

### 3.5 Footer

```markdown
---

*Report generated by SurveyMAE v3 - Multi-Agent Survey Evaluation Framework*
*Deterministic metrics are exact values. LLM-based scores may vary across models.*
*Dimensions marked (corrected) were re-scored via multi-model voting.*
```

---

## 4. Implementation Skeleton

```python
def generate_report(aggregation_result: Dict, state: SurveyState) -> str:
    """Generate v3 report with evidence chain display."""

    tool_evidence = state.get("tool_evidence", {})
    agent_outputs = state.get("agent_outputs", {})
    corrector_output = state.get("corrector_output", {})
    dimension_scores = aggregation_result.get("dimension_scores", {})

    sections = []

    # Header
    sections.append(_render_header(state, aggregation_result))

    # Section 1: Evidence Dashboard (pure tool_evidence)
    sections.append(_render_evidence_dashboard(tool_evidence))

    # Section 2: Agent Assessment (agent_outputs + corrector_output)
    sections.append(_render_agent_assessment(
        agent_outputs, dimension_scores, corrector_output, tool_evidence
    ))

    # Section 3: Key Findings (synthesized from dimension_scores + tool_evidence + agent_outputs)
    sections.append(_render_key_findings(
        dimension_scores, tool_evidence, agent_outputs
    ))

    # Footer
    sections.append(_render_footer())

    return "\n\n".join(sections)


def _render_evidence_dashboard(tool_evidence: dict) -> str:
    """Render Section 1 from tool_evidence only. No LLM data used."""
    # Extract metrics with safe defaults
    # Apply threshold rules for notes
    # Format as markdown tables
    ...

def _render_agent_assessment(
    agent_outputs: dict,
    dimension_scores: dict,
    corrector_output: dict,
    tool_evidence: dict,
) -> str:
    """Render Section 2 from agent outputs.

    For each agent:
    1. Score table with tool_evidence summary and variance badge
    2. Reasoning from the lowest-scoring dimension
    3. All flagged items across dimensions
    4. Special: missing_key_papers for ExpertAgent from tool_evidence
    """
    ...

def _render_key_findings(
    dimension_scores: dict,
    tool_evidence: dict,
    agent_outputs: dict,
) -> str:
    """Render Section 3: synthesized findings.

    1. Sort dimensions by score ascending
    2. Low scores (<3.5): show evidence + reasoning + recommendation
    3. High scores (>=4.0): show as strengths with evidence
    """
    ...

def _threshold_note(value, thresholds: list) -> str:
    """Generate deterministic note based on threshold rules.

    Args:
        value: metric value (float)
        thresholds: list of (threshold, note) pairs, sorted descending

    Returns:
        The note for the first threshold that value exceeds.
    """
    if not isinstance(value, (int, float)):
        return "N/A"
    for threshold, note in thresholds:
        if value >= threshold:
            return note
    return thresholds[-1][1] if thresholds else ""
```

---

## 5. Agent Output Requirements Checklist

For the report to display rich content, each agent's prompt must require
the following fields in its structured output. Check current prompts against
this list:

| Field | Required by | Example |
|-------|------------|---------|
| `sub_scores.{dim}.score` | Score table | `4` |
| `sub_scores.{dim}.tool_evidence` | Evidence column in score table | `{"metric": "C5", "value": 0.83, "detail": "30/36 verified"}` |
| `sub_scores.{dim}.llm_reasoning` | Agent Analysis section | "The survey correctly references most works but..." |
| `sub_scores.{dim}.flagged_items` | Flagged Items section, Recommendations | `["[15] - overgeneralization", "[23] - wrong category"]` |
| `sub_scores.{dim}.hallucination_risk` | Variance badge logic | `"low"` |

**If any agent prompt does not currently require `flagged_items` or
`tool_evidence` in its output format, the prompt must be updated.**

Specifically check:
- Does the agent prompt include the JSON output schema showing these fields?
- Does the prompt instruct the agent to reference specific tool evidence values?
- Does the prompt instruct the agent to list concrete examples in flagged_items?

---

## 6. run_summary.json

In addition to the markdown report, `generate_report` should also produce
`run_summary.json` (saved via result_store). This is a machine-readable
summary for batch experiments:

```json
{
  "run_id": "{run_id}",
  "source": "{source_pdf}",
  "timestamp": "{iso_timestamp}",
  "schema_version": "v3",
  "deterministic_metrics": {
    "C3": 0.03, "C5": 0.83, "C6_contradiction_rate": 0.032,
    "T1": 34, "T2": 5, "T3": 0.65, "T4": 2, "T5": 0.77,
    "S1": 7, "S2": 0.897, "S3": 0.25, "S4": 0.0, "S5": 0.68,
    "G1": 0.12, "G2": 2, "G3": 0.85, "G4": 0.47, "G5": 3, "G6": 0.08
  },
  "dimension_scores": {
    "V1": {"score": 4, "source": "original"},
    "V2": {"score": 3, "source": "original"},
    "V4": {"score": 4, "source": "corrected", "std": 0.47},
    "E1": {"score": 2, "source": "original"},
    "...": "..."
  },
  "overall_score": 7.20,
  "grade": "C"
}
```
