"""Evidence Collection Node (Full Implementation).

This node executes the complete tool chain to collect evidence for agent evaluation:
1. Citation extraction and validation (C3, C5, ref_metadata_cache)
2. Keyword extraction (topic_keywords)
3. Field trend baseline retrieval (T2, T5)
4. Candidate key papers retrieval (G4)
5. Temporal analysis (T1-T5, S1-S4)
6. Citation graph analysis (G1-G6, S5)
7. Foundational coverage analysis (G4)
"""

import logging
import time as time_module
from pathlib import Path
from typing import Any, Dict, List, Optional
import re

from src.core.log import log_pipeline_step, log_substep
from src.core.state import SurveyState
from src.core.config import load_config, SearchEnginesConfig
from src.tools.citation_checker import CitationChecker, GrobidReferenceExtractor
from src.tools.citation_analysis import CitationAnalyzer


def _convert_numpy_types(obj: Any) -> Any:
    """Recursively convert numpy types to Python native types for serialization.

    Args:
        obj: Any object that might contain numpy types

    Returns:
        Object with numpy types converted to Python native types
    """
    try:
        import numpy as np
    except ImportError:
        return obj

    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {key: _convert_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_convert_numpy_types(item) for item in obj]
    return obj
from src.tools.citation_graph_analysis import CitationGraphAnalyzer
from src.tools.keyword_extractor import KeywordExtractor
from src.tools.literature_search import LiteratureSearch
from src.tools.foundational_coverage import FoundationalCoverageAnalyzer

logger = logging.getLogger("surveymae.graph.nodes.evidence_collection")


def _load_evidence_config() -> Dict[str, Any]:
    """Load evidence configuration from config files."""
    try:
        cfg = load_config()
        search_cfg = SearchEnginesConfig.from_yaml()
        return {
            "foundational_top_k": cfg.evidence.foundational_top_k,
            "foundational_match_threshold": cfg.evidence.foundational_match_threshold,
            "trend_query_count": cfg.evidence.trend_query_count,
            "trend_year_range": cfg.evidence.trend_year_range,
            "clustering_algorithm": cfg.evidence.clustering_algorithm,
            "clustering_seed": cfg.evidence.clustering_seed,
            "citation_sample_size": cfg.evidence.citation_sample_size,
            "api_timeout_seconds": search_cfg.api_timeout_seconds,
            "fallback_order": search_cfg.fallback_order,
            "verify_limit": search_cfg.verify_limit,
            "c6_batch_size": cfg.evidence.c6_batch_size,
            "c6_model": cfg.evidence.c6_model,
            "c6_max_concurrency": cfg.evidence.c6_max_concurrency,
            "contradiction_threshold": cfg.evidence.contradiction_threshold,
        }
    except Exception as e:
        logger.warning(f"Failed to load config, using defaults: {e}")
        return {}


# Load config at module level for reuse
_EVIDENCE_CONFIG = _load_evidence_config()

# Default configuration values (fallback if config not available)
DEFAULT_VERIFY_SOURCES = _EVIDENCE_CONFIG.get("fallback_order", ["semantic_scholar", "openalex"])
DEFAULT_VERIFY_LIMIT = _EVIDENCE_CONFIG.get("verify_limit", 50)
DEFAULT_TOP_K = _EVIDENCE_CONFIG.get("foundational_top_k", 30)
DEFAULT_TREND_YEAR_RANGE = _EVIDENCE_CONFIG.get("trend_year_range", (2015, 2025))
DEFAULT_C6_BATCH_SIZE = _EVIDENCE_CONFIG.get("c6_batch_size", 10)
DEFAULT_C6_MODEL = _EVIDENCE_CONFIG.get("c6_model", "qwen3.5-flash")
DEFAULT_C6_MAX_CONCURRENCY = _EVIDENCE_CONFIG.get("c6_max_concurrency", 5)
DEFAULT_CONTRADICTION_THRESHOLD = _EVIDENCE_CONFIG.get("contradiction_threshold", 0.05)


def _extract_title_and_abstract_with_grobid(
    pdf_path: str, grobid_url: str, timeout_s: int
) -> tuple[str, str]:
    """Try to extract title and abstract via GROBID header endpoint.

    Returns:
        Tuple of (title, abstract). Both empty strings on failure.
    """
    try:
        extractor = GrobidReferenceExtractor(url=grobid_url, timeout_s=timeout_s)
        meta = extractor.extract_header_metadata(pdf_path)
        return meta.get("title", "") or "", meta.get("abstract", "") or ""
    except Exception as exc:
        logger.warning(
            "[DEGRADED] GROBID header extraction failed: %s. "
            "Falling back to regex title/abstract extraction. "
            "[Impact] Keyword quality may be lower if regex misses title or abstract. "
            "[Fix] Ensure GROBID is reachable at %s and increase citation.grobid_timeout_s "
            "(current=%ss, suggested=180s for large PDFs).",
            exc,
            grobid_url,
            timeout_s,
        )
        return "", ""


def _extract_title_and_abstract(parsed_content: str) -> tuple[str, str]:
    """Extract title and abstract from parsed PDF content.

    Args:
        parsed_content: Parsed PDF content in markdown format.

    Returns:
        Tuple of (title, abstract).
    """
    lines = parsed_content.split("\n")

    # Extract title (first heading or bold text)
    title = ""
    for line in lines[:10]:
        line = line.strip()
        if line.startswith("# "):
            title = line[2:].strip()
            break
        if line.startswith("**") and "**" in line[2:]:
            # Try to find the title in bold format
            match = re.search(r"\*\*(.+?)\*\*", line)
            if match:
                title = match.group(1).strip()
                break

    # Extract abstract
    abstract = ""
    in_abstract = False
    abstract_lines = []
    for line in lines:
        line_upper = line.strip().upper()
        if "ABSTRACT" in line_upper and len(line_upper) < 20:
            in_abstract = True
            continue
        if in_abstract:
            if line.strip() and not line.startswith("#") and not line.startswith("**"):
                if line.strip().endswith(".") or line.strip().endswith(","):
                    abstract_lines.append(line.strip())
                elif len(abstract_lines) > 0 and abstract_lines[-1]:
                    abstract_lines.append(line.strip())
                    if len(abstract_lines) > 3:
                        break
            elif line.strip().startswith("#") or line.startswith("1.") or line.startswith("Keywords"):
                break

    abstract = " ".join(abstract_lines[:10])  # Limit abstract length

    return title, abstract


def _build_ref_metadata_cache(references: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Build metadata cache from validated references.

    Args:
        references: List of reference dictionaries from CitationChecker.

    Returns:
        Dictionary mapping ref_id to metadata.
    """
    cache = {}
    for ref in references:
        ref_id = ref.get("key", ref.get("ref_id", ""))
        if not ref_id:
            continue

        # Extract available metadata
        metadata = {
            "key": ref_id,
            "title": ref.get("title", ""),
            "year": ref.get("year"),
            "authors": ref.get("authors", []),
            "doi": ref.get("doi", ""),
            "venue": ref.get("venue", ""),
        }

        # Add validation data if available
        validation = ref.get("validation", {})
        if validation:
            metadata["citation_count"] = validation.get("citation_count", 0)
            metadata["external_ids"] = validation.get("external_ids", {})
            metadata["verified"] = validation.get("verified", False)

            # Extract reference_targets for citation edge building
            # This is used by _build_citation_edges as fallback
            validation_meta = validation.get("metadata", {})
            if isinstance(validation_meta, dict):
                targets = validation_meta.get("reference_targets", [])
                if targets:
                    # Extract target keys from reference_targets
                    target_keys = []
                    for target in targets:
                        if isinstance(target, dict):
                            key = target.get("key", "")
                            if key:
                                target_keys.append(key)
                    if target_keys:
                        metadata["references"] = target_keys

        cache[ref_id] = metadata

    return cache


def _build_citation_edges(ref_metadata_cache: Dict[str, Dict[str, Any]]) -> List[tuple]:
    """Build citation edges from reference metadata cache.

    Args:
        ref_metadata_cache: Cache of reference metadata.

    Returns:
        List of (source_ref_id, target_ref_id) tuples.
    """
    edges = []

    for ref_id, metadata in ref_metadata_cache.items():
        # Look for references field in metadata (from external APIs)
        refs = metadata.get("references", [])
        if isinstance(refs, list):
            for target_id in refs:
                if target_id in ref_metadata_cache:
                    edges.append((ref_id, target_id))

    return edges


# =============================================================================
# Evidence Collection Sub-functions
# =============================================================================


async def _collect_citation_extraction(
    source_pdf: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], float, float]:
    """Step 1: Extract and validate citations from PDF.

    This collects evidence for VerifierAgent:
    - C3 (orphan_ref_rate): references not cited in text
    - C5 (metadata_verify_rate): verified references ratio

    Args:
        source_pdf: Path to the PDF file.

    Returns:
        Tuple of (extraction, references, orphan_ref_rate, metadata_verify_rate)
    """
    logger.info("Step 1: Extracting and validating citations...")
    checker = CitationChecker()

    extraction: dict[str, Any] = {"citations": [], "references": []}
    references: list[dict[str, Any]] = []

    if source_pdf:
        extraction = await checker.extract_citations_with_context_from_pdf(
            source_pdf,
            verify_references=True,
            sources=DEFAULT_VERIFY_SOURCES,
            verify_limit=DEFAULT_VERIFY_LIMIT,
        )
        references = extraction.get("references", [])

    # Calculate C3 (orphan_ref_rate)
    cited_ref_keys = set()
    for citation in extraction.get("citations", []):
        ref_key = citation.get("ref_key", "")
        if ref_key:
            cited_ref_keys.add(ref_key)

    total_refs = len(references)
    uncited_refs = sum(1 for r in references if r.get("key", "") not in cited_ref_keys)
    orphan_ref_rate = uncited_refs / total_refs if total_refs > 0 else 0.0

    # Calculate C5 (metadata_verify_rate)
    verified_count = sum(
        1 for r in references
        if r.get("validation") and r["validation"].get("verified", False)
    )
    metadata_verify_rate = verified_count / total_refs if total_refs > 0 else 0.0

    logger.info(f"  C3 (orphan_ref_rate): {orphan_ref_rate:.2%}")
    logger.info(f"  C5 (metadata_verify_rate): {metadata_verify_rate:.2%}")

    return extraction, references, orphan_ref_rate, metadata_verify_rate


async def _collect_c6_citation_alignment(
    extraction: dict[str, Any],
    references: list[dict[str, Any]],
) -> dict[str, Any]:
    """Step 1.5: Analyze citation-sentence alignment (C6 metric).

    This collects evidence for VerifierAgent's V2 dimension:
    - C6 (citation_sentence_alignment): LLM-based alignment analysis

    Args:
        extraction: Citation extraction result with citations and sentences.
        references: List of reference entries with validation metadata.

    Returns:
        C6 analysis result with contradiction_rate and auto_fail flag.
    """
    from src.tools.citation_checker import CitationChecker
    from src.tools.citation_checker import ReferenceEntry

    logger.info("Step 1.5: Analyzing citation-sentence alignment (C6)...")

    # Convert dict references to ReferenceEntry objects
    ref_entries = []
    for ref in references:
        ref_entry = ReferenceEntry(
            key=ref.get("key", ""),
            title=ref.get("title", ""),
            year=ref.get("year", ""),
        )
        # Preserve validation data
        if "validation" in ref:
            ref_entry.validation = ref["validation"]
        ref_entries.append(ref_entry)

    if not ref_entries:
        logger.warning("  No references available for C6 analysis")
        return {
            "metric_id": "C6",
            "status": "no_references",
            "total_pairs": 0,
            "contradiction_rate": 0.0,
            "auto_fail": False,
        }

    # Run C6 analysis
    checker = CitationChecker()
    try:
        c6_result = await checker.analyze_citation_sentence_alignment(
            citations=extraction.get("citations", []),
            references=ref_entries,
            batch_size=DEFAULT_C6_BATCH_SIZE,
            model_name=DEFAULT_C6_MODEL,
            max_concurrency=DEFAULT_C6_MAX_CONCURRENCY,
            contradiction_threshold=DEFAULT_CONTRADICTION_THRESHOLD,
        )
        logger.info(
            f"  C6 complete: contradiction_rate={c6_result.get('contradiction_rate', 0):.2%}, "
            f"auto_fail={c6_result.get('auto_fail', False)}"
        )
        return c6_result
    except Exception as e:
        logger.error(f"  C6 analysis failed: {e}")
        return {
            "metric_id": "C6",
            "status": "error",
            "error": str(e),
            "total_pairs": 0,
            "contradiction_rate": 0.0,
            "auto_fail": False,
        }


async def _collect_temporal_and_structural(
    references: list[dict[str, Any]],
    extraction: dict[str, Any],
    parsed_content: str,
    field_trend_baseline: dict[str, int],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Step 5: Compute temporal and structural metrics.

    This collects evidence for ReaderAgent:
    - T1-T5 (temporal metrics)
    - S1-S4 (structural metrics)

    Args:
        references: List of reference dictionaries.
        extraction: Citation extraction result.
        parsed_content: Parsed PDF content.
        field_trend_baseline: Field trend baseline counts.

    Returns:
        Tuple of (temporal_metrics, structural_metrics)
    """
    logger.info("Step 5: Computing temporal metrics...")
    analyzer = CitationAnalyzer()

    # Convert references to dict format
    ref_dicts = [
        {"key": ref.get("key", ""), "title": ref.get("title", ""), "year": ref.get("year")}
        for ref in references
    ]

    # Compute T1-T5
    temporal_metrics = analyzer.compute_temporal_metrics(
        ref_dicts,
        field_trend_baseline={"yearly_counts": field_trend_baseline},
    )

    # Compute S1-S4 (structural metrics)
    section_ref_counts: Dict[str, Dict[str, int]] = {}
    for citation in extraction.get("citations", []):
        section = citation.get("section_title", "Unknown")
        ref_key = citation.get("ref_key", "")
        if section not in section_ref_counts:
            section_ref_counts[section] = {}
        section_ref_counts[section][ref_key] = section_ref_counts[section].get(ref_key, 0) + 1

    structural_metrics = analyzer.compute_structural_metrics(
        section_ref_counts,
        total_paragraphs=len(parsed_content) // 500,
    )

    logger.info(f"  T1 (year_span): {temporal_metrics.get('T1_year_span')}")
    logger.info(f"  T5 (trend_alignment): {temporal_metrics.get('T5_trend_alignment')}")

    return temporal_metrics, structural_metrics


async def _collect_citation_graph(
    references: list[dict[str, Any]],
    ref_metadata_cache: Dict[str, Dict[str, Any]],
    extraction: dict[str, Any],
    section_ref_counts: Dict[str, Dict[str, int]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Step 6: Compute citation graph metrics.

    This collects evidence for ExpertAgent:
    - G1-G6 (graph metrics)
    - S5 (section-cluster alignment)

    Args:
        references: List of reference dictionaries.
        ref_metadata_cache: Metadata cache for references.
        extraction: Citation extraction result.
        section_ref_counts: Section-citation counts.

    Returns:
        Tuple of (graph_result, s5_result)
    """
    logger.info("Step 6: Computing citation graph metrics...")
    graph_analyzer = CitationGraphAnalyzer()

    # Build edges from real citation data
    real_edges = extraction.get("real_citation_edges", [])
    if real_edges:
        edges = real_edges
        logger.info(f"  Using {len(edges)} real citation edges from verification")
    else:
        edges = _build_citation_edges(ref_metadata_cache)
        if not edges:
            logger.warning("  No citation edges found, graph metrics may be limited")

    # Build graph config
    graph_config = {
        "clustering_algorithm": _EVIDENCE_CONFIG.get("clustering_algorithm", "cocitation"),
        "clustering_seed": _EVIDENCE_CONFIG.get("clustering_seed"),
    }

    # Analyze graph
    ref_dicts = [
        {"key": ref.get("key", ""), "title": ref.get("title", ""), "year": ref.get("year")}
        for ref in references
    ]

    try:
        graph_result = graph_analyzer.analyze(
            references=ref_dicts,
            edges=edges,
            config=graph_config,
        )
    except Exception as e:
        logger.warning(f"  Graph analysis failed: {e}")
        graph_result = {}

    # Compute S5 (section-cluster alignment)
    summary = graph_result.get("summary", {})
    cluster_summary = summary.get("cocitation_clustering", {})
    cluster_evidence = cluster_summary.get("cluster_evidence", [])

    try:
        s5_result = graph_analyzer.compute_section_cluster_alignment(
            section_ref_counts=section_ref_counts,
            references=ref_dicts,
            cluster_evidence=cluster_evidence,
        )
    except Exception as e:
        logger.warning(f"  S5 computation failed: {e}")
        s5_result = {}

    return graph_result, s5_result


async def _collect_foundational_coverage(
    topic_keywords: list[str],
    references: list[dict[str, Any]],
    ref_metadata_cache: Dict[str, Dict[str, Any]],
) -> tuple[Optional[float], list[dict[str, Any]], list[dict[str, Any]]]:
    """Step 7: Compute foundational coverage analysis (G4).

    This collects evidence for ExpertAgent:
    - G4 (foundational_coverage_rate)
    - missing_key_papers
    - suspicious_centrality

    Args:
        topic_keywords: List of topic keywords.
        references: List of reference dictionaries.
        ref_metadata_cache: Metadata cache for references.

    Returns:
        Tuple of (coverage_rate, missing_papers, suspicious_papers)
    """
    logger.info("Step 7: Computing foundational coverage...")
    g4_analyzer = FoundationalCoverageAnalyzer()

    ref_dicts = [
        {"key": ref.get("key", ""), "title": ref.get("title", ""), "year": ref.get("year")}
        for ref in references
    ]

    try:
        g4_result = await g4_analyzer.analyze(
            topic_keywords=topic_keywords,
            survey_references=ref_dicts,
            ref_metadata_cache=ref_metadata_cache,
        )
        coverage_rate = g4_result.coverage_rate
        missing_papers = g4_result.missing_key_papers
        suspicious_papers = g4_result.suspicious_centrality
    except Exception as e:
        logger.warning(f"  G4 analysis failed: {e}")
        coverage_rate = None
        missing_papers = []
        suspicious_papers = []

    logger.info(f"  G4 (foundational_coverage_rate): {coverage_rate}")

    return coverage_rate, missing_papers, suspicious_papers


async def run_evidence_collection(
    state: SurveyState,
    result_store: Any = None,
) -> Dict[str, Any]:
    """Execute complete evidence collection pipeline.

    This function orchestrates all tool calls to collect comprehensive evidence
    for agent evaluation, including:
    - Citation validation (C3, C5)
    - Keyword extraction for retrieval
    - Field trend baseline
    - Temporal analysis (T1-T5)
    - Citation graph analysis (G1-G6)
    - Foundational coverage (G4)

    Args:
        state: The current workflow state.
        result_store: Optional ResultStore instance for tool artifact persistence.

    Returns:
        State updates with tool_evidence and related data.
    """
    from src.tools.result_store import ResultStore

    parsed_content = state.get("parsed_content", "")
    source_pdf = state.get("source_pdf_path", "")
    section_headings = state.get("section_headings", [])

    # Track overall elapsed time
    step_start = time_module.monotonic()

    # Get paper_id for persistence
    paper_id = None
    if result_store and source_pdf:
        try:
            paper_id = result_store.register_paper(source_pdf)
        except Exception as e:
            logger.warning(f"Failed to register paper: {e}")

    if not parsed_content:
        logger.warning("No parsed content available")
        return {
            "tool_evidence": {},
            "ref_metadata_cache": {},
            "topic_keywords": [],
            "field_trend_baseline": {},
            "candidate_key_papers": [],
        }

    try:
        # Log pipeline step entry
        log_pipeline_step("02", 7, "evidence_collection", detail="证据收集中...")

        # =========================================================================
        # Step 1: Citation Extraction and Validation
        # =========================================================================
        logger.info("Step 1: Extracting and validating citations...")
        checker = CitationChecker(result_store=result_store)

        # Extract citations with context
        if source_pdf:
            # Use async version to enable verification
            extraction = await checker.extract_citations_with_context_from_pdf_async(
                source_pdf,
                verify_references=True,
                sources=DEFAULT_VERIFY_SOURCES,
                verify_limit=DEFAULT_VERIFY_LIMIT,
            )
            references = extraction.get("references", [])
        else:
            extraction = {"citations": [], "references": []}
            references = []

        # Build ref_metadata_cache from validated references
        ref_metadata_cache = _build_ref_metadata_cache(references)

        # Calculate C3 (orphan_ref_rate) - references not cited in text
        cited_ref_keys = set()
        for citation in extraction.get("citations", []):
            ref_key = citation.get("ref_key", "")
            if ref_key:
                cited_ref_keys.add(ref_key)

        total_refs = len(references)
        uncited_refs = sum(1 for r in references if r.get("key", "") not in cited_ref_keys)
        orphan_ref_rate = uncited_refs / total_refs if total_refs > 0 else 0.0

        # Calculate C5 (metadata_verify_rate) - verified references ratio
        verified_count = 0
        for r in references:
            validation = r.get("validation")
            if validation and isinstance(validation, dict):
                # Check is_valid field (not "verified")
                if validation.get("is_valid", False):
                    verified_count += 1
        metadata_verify_rate = verified_count / total_refs if total_refs > 0 else 0.0

        # Primary source for graph edges is extraction-level real_citation_edges,
        # which is produced by CitationChecker.build_real_citation_edges().
        real_citation_edges_raw = extraction.get("real_citation_edges", [])
        real_citation_edges = []
        seen_edge_pairs = set()
        for edge in real_citation_edges_raw:
            if not isinstance(edge, dict):
                continue
            src = str(edge.get("source", "")).strip()
            dst = str(edge.get("target", "")).strip()
            if not src or not dst:
                continue
            key = (src, dst)
            if key in seen_edge_pairs:
                continue
            seen_edge_pairs.add(key)
            real_citation_edges.append({"source": src, "target": dst})

        # Legacy fallback for backward compatibility with old payload shapes.
        if not real_citation_edges:
            fallback_edges = []
            for r in references:
                validation = r.get("validation")
                if not isinstance(validation, dict):
                    continue
                val_meta = validation.get("metadata", {})
                if isinstance(val_meta, dict):
                    edges = val_meta.get("real_citation_edges", [])
                    if isinstance(edges, list) and edges:
                        fallback_edges.extend(edges)
            if fallback_edges:
                logger.warning(
                    "Using legacy validation.metadata.real_citation_edges fallback (count=%d).",
                    len(fallback_edges),
                )
                real_citation_edges = fallback_edges

        logger.info(f"  C3 (orphan_ref_rate): {orphan_ref_rate:.2%}")
        logger.info(f"  C5 (metadata_verify_rate): {metadata_verify_rate:.2%}")
        logger.info(
            "  Real citation edges from extraction: %d (raw=%d, dedup=%d)",
            len(real_citation_edges),
            len(real_citation_edges_raw) if isinstance(real_citation_edges_raw, list) else 0,
            max(
                0,
                (len(real_citation_edges_raw) if isinstance(real_citation_edges_raw, list) else 0)
                - len(real_citation_edges),
            ),
        )
        step1_elapsed = time_module.monotonic() - step_start
        log_substep(
            "citation_validate",
            f"C3={orphan_ref_rate:.2%} C5={metadata_verify_rate:.2%} ({verified_count}/{total_refs}) "
            f"edges={len(real_citation_edges)}",
            elapsed=step1_elapsed,
        )

        # =========================================================================
        # Step 1.5: C6 Citation-Sentence Alignment Analysis
        # =========================================================================
        c6_result = await _collect_c6_citation_alignment(extraction, references)

        # Save C6 alignment results (v3)
        c6_elapsed = time_module.monotonic() - step_start
        if result_store and paper_id:
            try:
                result_store.save_c6_alignment(paper_id, c6_result)
                logger.info(f"  Saved C6 alignment to c6_alignment.json")
            except Exception as e:
                logger.warning(f"  Failed to save C6 alignment: {e}")
        log_substep(
            "C6_alignment",
            f"pairs={c6_result.get('total_pairs', 0)} "
            f"contradiction={c6_result.get('contradiction_rate', 0):.2%} "
            f"auto_fail={c6_result.get('auto_fail', False)}",
            elapsed=c6_elapsed,
        )

        # =========================================================================
        # Step 2: Keyword Extraction
        # =========================================================================
        logger.info("Step 2: Extracting keywords...")
        cfg = load_config()
        grobid_url = getattr(cfg.citation, "grobid_url", "http://localhost:8070")
        grobid_timeout = int(getattr(cfg.citation, "grobid_timeout_s", 30))
        title, abstract = "", ""
        if source_pdf and Path(source_pdf).suffix.lower() == ".pdf":
            title, abstract = _extract_title_and_abstract_with_grobid(
                source_pdf, grobid_url, grobid_timeout
            )
        if not title:
            title, abstract = _extract_title_and_abstract(parsed_content)

        extractor = KeywordExtractor()
        kw_result = await extractor.extract_keywords(
            title=title,
            abstract=abstract,
            section_headings=section_headings if section_headings else None,
        )
        topic_keywords = kw_result.keywords

        if not topic_keywords:
            # Fallback: generate keywords from title
            topic_keywords = [title] if title else []

        step2_elapsed = time_module.monotonic() - step_start
        log_substep(
            "keyword_extract",
            f"{len(topic_keywords)} keywords: {topic_keywords[:3]}" if topic_keywords else "no keywords",
            elapsed=step2_elapsed,
        )

        # =========================================================================
        # Step 3: Field Trend Baseline Retrieval
        # =========================================================================
        logger.info("Step 3: Retrieving field trend baseline...")
        lit_search = LiteratureSearch()

        field_trend_baseline: Dict[str, int] = {}

        for kw in topic_keywords[:3]:  # Use top 3 keywords
            try:
                result = lit_search.search_field_trend(
                    kw,
                    year_range=DEFAULT_TREND_YEAR_RANGE,
                )
                yearly_counts = result.get("yearly_counts", {})
                for year, count in yearly_counts.items():
                    field_trend_baseline[year] = field_trend_baseline.get(year, 0) + count
            except Exception as e:
                logger.warning(f"  Failed to search field trend for '{kw}': {e}")
                continue

        step3_elapsed = time_module.monotonic() - step_start
        log_substep(
            "trend_baseline",
            f"{len(field_trend_baseline)} years",
            elapsed=step3_elapsed,
        )

        # Save field_trend_baseline (v3)
        if result_store and paper_id:
            try:
                result_store.save_trend_baseline(paper_id, {"yearly_counts": field_trend_baseline})
                logger.info(f"  Saved trend_baseline to trend_baseline.json")
            except Exception as e:
                logger.warning(f"  Failed to save trend_baseline: {e}")

        # =========================================================================
        # Step 4: Candidate Key Papers Retrieval
        # =========================================================================
        logger.info("Step 4: Retrieving candidate key papers...")
        candidate_key_papers = []

        for kw in topic_keywords[:3]:
            try:
                papers = await lit_search.search_top_cited(kw, top_k=DEFAULT_TOP_K)
                candidate_key_papers.extend(papers)
            except Exception as e:
                logger.warning(f"  Failed to search top cited for '{kw}': {e}")
                continue

        # Deduplicate
        seen_titles = set()
        unique_papers = []
        for paper in candidate_key_papers:
            title_lower = paper.get("title", "").lower()
            if title_lower and title_lower not in seen_titles:
                seen_titles.add(title_lower)
                unique_papers.append(paper)

        candidate_key_papers = unique_papers
        step4_elapsed = time_module.monotonic() - step_start
        log_substep(
            "key_papers",
            f"{len(candidate_key_papers)} candidates",
            elapsed=step4_elapsed,
        )

        # Prepare key_papers_data for persistence (v3)
        key_papers_data = {
            "candidate_papers": candidate_key_papers,
        }
        # Note: G4 coverage data will be added after G4 analysis

        # =========================================================================
        # Step 5: Temporal Analysis (T1-T5)
        # =========================================================================
        logger.info("Step 5: Computing temporal metrics...")
        analyzer = CitationAnalyzer()

        # Convert references to dict format for analyzer (include source_path for persistence)
        ref_dicts = []
        for ref in references:
            ref_dict = {
                "key": ref.get("key", ""),
                "title": ref.get("title", ""),
                "year": ref.get("year"),
                "source_path": source_pdf,  # Include for CitationGraphAnalyzer persistence
            }
            ref_dicts.append(ref_dict)

        # Compute T1-T5
        temporal_metrics = analyzer.compute_temporal_metrics(
            ref_dicts,
            field_trend_baseline={"yearly_counts": field_trend_baseline}
        )

        # Compute S1-S4 (structural metrics)
        # Build section-citation counts from extraction
        section_ref_counts: Dict[str, Dict[str, int]] = {}
        for citation in extraction.get("citations", []):
            section = citation.get("section_title", "Unknown")
            ref_key = citation.get("ref_key", "")
            if section not in section_ref_counts:
                section_ref_counts[section] = {}
            section_ref_counts[section][ref_key] = section_ref_counts[section].get(ref_key, 0) + 1

        structural_metrics = analyzer.compute_structural_metrics(
            section_ref_counts,
            total_paragraphs=len(parsed_content) // 500,  # Rough estimate
        )

        step5_elapsed = time_module.monotonic() - step_start
        t1_val = temporal_metrics.get('T1_year_span', 'N/A')
        t5_val = temporal_metrics.get('T5_trend_alignment', 'N/A')
        log_substep(
            "temporal_metrics",
            f"T1={t1_val} T5={t5_val:.2f}" if isinstance(t5_val, float) else f"T1={t1_val} T5={t5_val}",
            elapsed=step5_elapsed,
        )

        # =========================================================================
        # Step 6: Citation Graph Analysis (G1-G6, S5)
        # =========================================================================
        logger.info("Step 6: Computing citation graph metrics...")
        graph_analyzer = CitationGraphAnalyzer(result_store=result_store)

        # Build edges from real citation data (verified by citation checker)
        # Use real_citation_edges from validation (already extracted above)
        if real_citation_edges:
            edges = real_citation_edges
            logger.info(f"  Using {len(edges)} real citation edges from validation")
        else:
            # Fallback: try to build edges from reference metadata
            edges = _build_citation_edges(ref_metadata_cache)
            if not edges:
                logger.warning("  No citation edges found, graph metrics may be limited")

        # Build graph config from evidence config
        graph_config = {
            "clustering_algorithm": _EVIDENCE_CONFIG.get("clustering_algorithm", "cocitation"),
            "clustering_seed": _EVIDENCE_CONFIG.get("clustering_seed"),
        }

        # Analyze graph
        try:
            graph_result = graph_analyzer.analyze(
                references=ref_dicts,
                edges=edges,
                config=graph_config,
            )
            graph_meta = graph_result.get("meta", {}) if isinstance(graph_result, dict) else {}
            logger.info(
                "  Graph analysis output: n_nodes=%s n_edges=%s unresolved_edge_ratio=%s",
                graph_meta.get("n_nodes"),
                graph_meta.get("n_edges"),
                graph_meta.get("unresolved_edge_ratio"),
            )
            if len(edges) > 0 and (graph_meta.get("n_edges") or 0) == 0:
                logger.warning(
                    "  Graph analysis received %d edges but produced 0 resolved edges. "
                    "Check edge key space and reference keys alignment.",
                    len(edges),
                )
        except Exception as e:
            logger.warning(f"  Graph analysis failed: {e}")
            graph_result = {}

        # Get cluster evidence for S5 calculation
        summary = graph_result.get("summary", {})
        evidence = graph_result.get("evidence", {})
        cluster_evidence = evidence.get("clusters", [])

        # Compute S5 (section-cluster alignment)
        try:
            s5_result = graph_analyzer.compute_section_cluster_alignment(
                section_ref_counts=section_ref_counts,
                references=ref_dicts,
                cluster_evidence=cluster_evidence,
            )
        except Exception as e:
            logger.warning(f"  S5 computation failed: {e}")
            s5_result = {}

        step6_elapsed = time_module.monotonic() - step_start
        n_clusters = summary.get("cocitation_clustering", {}).get("n_clusters", "N/A")
        density = summary.get("density_connectivity", {}).get("density_global", "N/A")
        log_substep(
            "citation_graph",
            f"G1={density} G5={n_clusters}" if isinstance(density, float) else "graph_metrics_computed",
            elapsed=step6_elapsed,
        )

        # =========================================================================
        # Step 7: Foundational Coverage Analysis (G4)
        # =========================================================================
        logger.info("Step 7: Computing foundational coverage...")
        g4_analyzer = FoundationalCoverageAnalyzer()

        try:
            g4_result = await g4_analyzer.analyze(
                topic_keywords=topic_keywords,
                survey_references=ref_dicts,
                ref_metadata_cache=ref_metadata_cache,
            )
            g4_coverage = g4_result.coverage_rate
            missing_papers = g4_result.missing_key_papers
            suspicious_papers = g4_result.suspicious_centrality
        except Exception as e:
            logger.warning(f"  G4 analysis failed: {e}")
            g4_coverage = None
            missing_papers = []
            suspicious_papers = []

        step7_elapsed = time_module.monotonic() - step_start
        log_substep(
            "foundational_coverage",
            f"G4={g4_coverage:.2%}" if g4_coverage is not None else "G4=N/A",
            elapsed=step7_elapsed,
        )

        # Save key_papers with G4 data (v3)
        key_papers_data.update({
            "coverage_rate": g4_coverage,
            "missing_key_papers": missing_papers,
            "suspicious_centrality": suspicious_papers,
        })
        if result_store and paper_id:
            try:
                result_store.save_key_papers(paper_id, key_papers_data)
                logger.info(f"  Saved key_papers to key_papers.json")
            except Exception as e:
                logger.warning(f"  Failed to save key_papers: {e}")

        # Save citation analysis (T1-T5, S1-S4) (v3)
        analysis_data = {
            "temporal": temporal_metrics,
            "structural": structural_metrics,
        }
        if result_store and paper_id:
            try:
                result_store.save_citation_analysis(paper_id, analysis_data)
                logger.info(f"  Saved citation analysis to analysis.json")
            except Exception as e:
                logger.warning(f"  Failed to save citation analysis: {e}")

        # =========================================================================
        # Assemble Tool Evidence
        # =========================================================================
        def _require_float(value, name: str, default: float = -1.0) -> float:
            """Return value if not None, else log an error and return default."""
            if value is None:
                logger.error(
                    "Metric %s is None (likely due to failed external API calls); "
                    "falling back to default value %s",
                    name, default,
                )
                return default
            return value

        tool_evidence = {
            "extraction": extraction,
            "validation": {
                "C3_orphan_ref_rate": _require_float(orphan_ref_rate, "C3_orphan_ref_rate"),
                "C5_metadata_verify_rate": _require_float(metadata_verify_rate, "C5_metadata_verify_rate"),
                "references": references,
                "verified_count": verified_count,
                "total_refs": total_refs,
            },
            "analysis": {
                # Temporal (T1-T5)
                "T1_year_span": temporal_metrics.get("T1_year_span"),
                "T2_foundational_retrieval_gap": temporal_metrics.get("T2_foundational_retrieval_gap"),
                "T3_peak_year_ratio": temporal_metrics.get("T3_peak_year_ratio"),
                "T4_temporal_continuity": temporal_metrics.get("T4_temporal_continuity"),
                "T5_trend_alignment": _require_float(temporal_metrics.get("T5_trend_alignment"), "T5_trend_alignment"),
                "year_distribution": temporal_metrics.get("year_distribution"),
                # Structural (S1-S4)
                "S1_section_count": temporal_metrics.get("S1_section_count"),
                "S2_citation_density": structural_metrics.get("S2_citation_density"),
                "S3_citation_gini": structural_metrics.get("S3_citation_gini"),
                "S4_zero_citation_section_rate": structural_metrics.get("S4_zero_citation_section_rate"),
            },
            "graph_analysis": {
                # Graph metrics (G1-G6)
                "G1_density": summary.get("density_connectivity", {}).get("density_global"),
                "G2_components": summary.get("density_connectivity", {}).get("n_weak_components"),
                "G3_lcc_frac": summary.get("density_connectivity", {}).get("lcc_frac"),
                "G4_coverage_rate": _require_float(g4_coverage, "G4_coverage_rate"),
                "G5_clusters": summary.get("cocitation_clustering", {}).get("n_clusters"),
                "G6_isolates": summary.get("density_connectivity", {}).get("n_isolates"),
                # Section-cluster alignment (S5)
                "S5_nmi": _require_float(s5_result.get("nmi"), "S5_nmi"),
                "S5_ari": s5_result.get("ari"),
                # Additional data for agents
                "missing_key_papers": missing_papers,
                "suspicious_centrality": suspicious_papers,
            },
            # C6 citation-sentence alignment
            "c6_alignment": c6_result,
        }

        total_elapsed = time_module.monotonic() - step_start
        log_pipeline_step(
            "02",
            7,
            "evidence_collection",
            detail=f"{total_refs} refs, {len(topic_keywords)} keywords",
            elapsed=total_elapsed,
        )

        # Convert numpy types to Python native types for msgpack serialization
        tool_evidence = _convert_numpy_types(tool_evidence)
        candidate_key_papers = _convert_numpy_types(candidate_key_papers)

        # Dump tool_evidence schema for Step 0 refactoring
        # dump_tool_evidence_schema(tool_evidence, "docs/tool_evidence_schema.json") #[x]: used to debug

        return {
            "tool_evidence": tool_evidence,
            "ref_metadata_cache": ref_metadata_cache,
            "topic_keywords": topic_keywords,
            "field_trend_baseline": {"yearly_counts": field_trend_baseline},
            "candidate_key_papers": candidate_key_papers,
        }

    except Exception as e:
        logger.error(f"Evidence collection failed: {e}", exc_info=True)
        # Re-raise so the workflow wrapper can handle it with full context
        raise


def dump_tool_evidence_schema(tool_evidence: Dict[str, Any], output_path: str) -> None:
    """Dump tool_evidence to JSON file for schema documentation.

    This is used in Step 0 of the refactoring plan to establish the contract
    between evidence_collection output and evidence_dispatch extraction paths.

    Args:
        tool_evidence: The tool_evidence dict to dump.
        output_path: Path to output JSON file.
    """
    import json
    import os

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(tool_evidence, f, indent=2, ensure_ascii=False, default=str)
    logger.info(f"Dumped tool_evidence schema to {output_path}")
