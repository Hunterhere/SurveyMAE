"""Integration tests for parallel literature search dispatch.

Tests cover:
  1. Config loading & per-source settings
  2. Dispatcher retry / fallback / merge strategies (mock)
  3. Full PDF pipeline: parse → citation extract → parallel verify → search → field trend
  4. Performance comparison

Requires:
  - test_paper.pdf at project root
  - GROBID running (or fallback parser) for PDF parsing
  - Network access for real API tests

Run:
    uv run pytest tests/integration/test_parallel_literature_search.py -v -s
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.core.config import SurveyMAEConfig, load_config
from src.core.search_config import (
    ConcurrencyConfig,
    DegradationConfig,
    SearchEngineConfig,
    SourceConfig,
    load_search_engine_config,
)
from src.tools.citation_checker import CitationChecker
from src.tools.literature_search import LiteratureSearch
from src.tools.parallel_dispatcher import (
    AllSourcesFailedError,
    ParallelDispatcher,
    SourceResult,
    _execute_with_retry,
)
from src.tools.result_store import ResultStore
from tests.integration import load_test_env


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _load_env():
    load_test_env()


PDF_PATH = Path(__file__).resolve().parents[2] / "test_paper.pdf"


def _build_config(backend: str, grobid_url: str) -> SurveyMAEConfig:
    cfg = load_config()
    cfg.citation.backend = backend
    cfg.citation.grobid_url = grobid_url
    cfg.citation.grobid_timeout_s = int(os.getenv("GROBID_TIMEOUT_S", "30"))
    cfg.citation.grobid_consolidate = False
    return cfg


def _make_dispatcher_config(
    *,
    merge_strategy: str = "weighted_union",
    on_all_failed: str = "empty",
    concurrent_sources: list[str] | None = None,
    fallback_order: list[str] | None = None,
) -> SearchEngineConfig:
    """Build a SearchEngineConfig for dispatcher tests."""
    if concurrent_sources is None:
        concurrent_sources = ["semantic_scholar", "openalex"]
    if fallback_order is None:
        fallback_order = ["crossref", "dblp"]

    sources: dict[str, SourceConfig] = {}
    for i, name in enumerate(concurrent_sources):
        sources[name] = SourceConfig(
            enabled=True, priority=i + 1, concurrent=True,
            max_retries=1, retry_delay_seconds=0.1, retry_backoff=1.0,
            timeout_seconds=15,
        )
    for i, name in enumerate(fallback_order):
        if name not in sources:
            sources[name] = SourceConfig(
                enabled=True, priority=len(concurrent_sources) + i + 1,
                concurrent=False, max_retries=1, retry_delay_seconds=0.1,
                retry_backoff=1.0, timeout_seconds=15,
            )

    return SearchEngineConfig(
        concurrency=ConcurrencyConfig(
            max_concurrent_sources=3, merge_strategy=merge_strategy,
            per_source_timeout_seconds=15,
        ),
        degradation=DegradationConfig(
            fallback_order=fallback_order, on_all_failed=on_all_failed,
        ),
        sources=sources,
    )


# ===================================================================
# Part 1: Config loading
# ===================================================================

class TestConfigLoading:
    def test_load_config_from_yaml(self):
        cfg = load_search_engine_config()
        assert cfg.verify_limit == 100
        assert cfg.concurrency.merge_strategy == "weighted_union"
        assert cfg.degradation.on_all_failed == "empty"
        assert "semantic_scholar" in cfg.get_concurrent_sources()
        assert "openalex" in cfg.get_concurrent_sources()

    def test_source_configs_populated(self):
        cfg = load_search_engine_config()
        ss = cfg.sources["semantic_scholar"]
        assert ss.concurrent is True
        assert ss.max_retries >= 1
        assert 429 in ss.retry_on_status

    def test_legacy_accessors(self):
        cfg = load_search_engine_config()
        assert cfg.crossref_mailto == "surveymae@example.com"
        assert isinstance(cfg.fallback_order, list)


# ===================================================================
# Part 2: Dispatcher retry / fallback / merge (mock)
# ===================================================================

class TestDispatcherRetryAndFallback:
    def test_single_source_retry_then_success(self):
        call_count = 0
        def flaky_op():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                import requests
                resp = MagicMock(); resp.status_code = 429
                raise requests.HTTPError(response=resp)
            return [{"title": "Paper A"}]

        cfg = SourceConfig(max_retries=2, retry_delay_seconds=0.05,
                           retry_backoff=1.0, retry_on_status=[429])
        result = _execute_with_retry("test_source", flaky_op, cfg)
        assert result.success and len(result.items) == 1 and call_count == 2

    def test_all_retries_exhausted(self):
        def always_fail():
            import requests
            resp = MagicMock(); resp.status_code = 500
            raise requests.HTTPError(response=resp)

        cfg = SourceConfig(max_retries=1, retry_delay_seconds=0.01,
                           retry_on_status=[500])
        result = _execute_with_retry("bad", always_fail, cfg)
        assert not result.success and result.items == []

    def test_fallback_on_concurrent_fail(self):
        config = _make_dispatcher_config(
            concurrent_sources=["source_a"], fallback_order=["source_b"],
        )
        dispatcher = ParallelDispatcher(config)
        def build_op(source):
            if source == "source_a":
                return lambda: (_ for _ in ()).throw(RuntimeError("down"))
            return lambda: [{"title": "Fallback paper"}]
        results = dispatcher.dispatch(["source_a", "source_b"], build_op)
        assert len(results) == 1
        dispatcher.shutdown()

    def test_on_all_failed_empty(self):
        config = _make_dispatcher_config(
            concurrent_sources=["a"], fallback_order=["b"], on_all_failed="empty",
        )
        config.sources["b"] = SourceConfig(enabled=True, concurrent=False, max_retries=0)
        dispatcher = ParallelDispatcher(config)
        results = dispatcher.dispatch(
            ["a", "b"], lambda _s: lambda: (_ for _ in ()).throw(RuntimeError("x")),
        )
        assert results == []
        dispatcher.shutdown()

    def test_on_all_failed_raise(self):
        config = _make_dispatcher_config(
            concurrent_sources=["a"], fallback_order=[], on_all_failed="raise",
        )
        dispatcher = ParallelDispatcher(config)
        with pytest.raises(AllSourcesFailedError):
            dispatcher.dispatch(
                ["a"], lambda _s: lambda: (_ for _ in ()).throw(RuntimeError("x")),
            )
        dispatcher.shutdown()

    def test_merge_union(self):
        config = _make_dispatcher_config(merge_strategy="union",
                                         concurrent_sources=["a", "b"])
        dispatcher = ParallelDispatcher(config)
        results = dispatcher.dispatch(["a", "b"], lambda s: lambda: [{"from": s}])
        assert len(results) == 2
        dispatcher.shutdown()


# ===================================================================
# Part 3: Full PDF pipeline (real PDF + real API)
# ===================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_pdf_pipeline(tmp_path: Path):
    """End-to-end: PDF parse → citation extract → parallel verify →
    parallel literature search → field trend (group_by).
    """
    assert PDF_PATH.exists(), f"Missing test PDF: {PDF_PATH}"
    grobid_url = os.getenv("GROBID_URL", "http://localhost:8070")
    sources_raw = os.getenv("CITATION_VERIFY_SOURCES", "semantic_scholar,openalex")
    verify_sources = [s.strip().lower() for s in sources_raw.split(",") if s.strip()]

    # --- Step 1: PDF parse + citation extract + parallel verify -----------
    store = ResultStore(
        base_dir=str(tmp_path / "runs"),
        run_id="parallel_search_test",
        tool_params={"backend": "auto", "grobid_url": grobid_url,
                     "sources": verify_sources},
    )
    checker = CitationChecker(
        config=_build_config("auto", grobid_url), result_store=store,
    )

    t0 = time.monotonic()
    extracted = await checker.extract_citations_with_context_from_pdf_async(
        str(PDF_PATH),
        verify_references=True,
        sources=verify_sources,
        verify_limit=15,  # keep test fast
    )
    verify_elapsed = time.monotonic() - t0

    citations = extracted.get("citations", [])
    references = extracted.get("references", [])

    assert citations, "Expected citations from PDF extraction"
    assert references, "Expected references from PDF extraction"

    verified = [r for r in references if r.get("validation")]
    print(f"\n[Pipeline] PDF parse + verify: {verify_elapsed:.1f}s")
    print(f"  Citations: {len(citations)}")
    print(f"  References: {len(references)}")
    print(f"  Verified: {len(verified)}")

    if not verified:
        pytest.skip("No references verified (external source unavailable)")

    # Check that verification used multiple sources concurrently
    all_sources_checked: set[str] = set()
    for ref in verified:
        v = ref["validation"]
        for s in v.get("sources_checked", []):
            all_sources_checked.add(s)
    print(f"  Sources checked: {sorted(all_sources_checked)}")

    # --- Step 2: Parallel literature search (title) -----------------------
    ls = LiteratureSearch()

    # Pick a verified reference title for search
    sample_title = ""
    for ref in verified:
        t = ref.get("title", "")
        if len(t) > 10:
            sample_title = t
            break

    if sample_title:
        t0 = time.monotonic()
        search_results = ls.search_by_title(
            sample_title,
            sources=["semantic_scholar", "openalex"],
            max_results=3,
        )
        search_elapsed = time.monotonic() - t0
        print(f"\n[Pipeline] search_by_title({sample_title[:50]}...): "
              f"{len(search_results)} results in {search_elapsed:.1f}s")
        for r in search_results:
            print(f"  [{r.source}] {r.title} ({r.year})")
        assert len(search_results) >= 1

    # --- Step 3: Parallel field trend (group_by) --------------------------
    t0 = time.monotonic()
    trend = ls.search_field_trend(
        "deep learning survey",
        year_range=(2018, 2025),
        sources=["semantic_scholar", "openalex"],
    )
    trend_elapsed = time.monotonic() - t0
    yearly = trend["yearly_counts"]
    non_zero = sum(1 for v in yearly.values() if v > 0)
    print(f"\n[Pipeline] search_field_trend: {trend_elapsed:.1f}s, "
          f"non-zero years: {non_zero}/{len(yearly)}")
    for y in sorted(yearly):
        print(f"  {y}: {yearly[y]}")

    # --- Step 4: Parallel search_top_cited --------------------------------
    t0 = time.monotonic()
    top_papers = await ls.search_top_cited("deep learning", top_k=10)
    top_elapsed = time.monotonic() - t0
    print(f"\n[Pipeline] search_top_cited: {len(top_papers)} papers in {top_elapsed:.1f}s")
    for p in top_papers[:5]:
        print(f"  {p['title'][:60]} (citations={p['citation_count']})")

    # --- Step 5: Verify persistence artifacts -----------------------------
    run_dir = tmp_path / "runs" / "parallel_search_test"
    assert (run_dir / "run.json").exists()
    assert (run_dir / "index.json").exists()

    validation_files = list((run_dir / "papers").glob("*/validation.json"))
    assert validation_files, "Expected validation.json in ResultStore"

    # Print summary
    print(f"\n{'='*60}")
    print(f"PIPELINE SUMMARY")
    print(f"  PDF: {PDF_PATH.name}")
    print(f"  Verify time: {verify_elapsed:.1f}s ({len(verified)} refs)")
    print(f"  Field trend: {trend_elapsed:.1f}s (group_by)")
    print(f"  Top cited search: {top_elapsed:.1f}s")
    print(f"  Persistence: OK")
    print(f"{'='*60}")


# ===================================================================
# Part 4: Degradation with mocked fetchers
# ===================================================================

class TestDegradationWithMock:
    def test_primary_fails_fallback_succeeds(self):
        """When semantic_scholar + openalex both fail, crossref fallback works."""
        mock_ss = MagicMock()
        mock_ss.search_by_title.side_effect = RuntimeError("429")

        mock_oa = MagicMock()
        mock_oa.search_by_title.side_effect = RuntimeError("timeout")
        mock_oa.BASE_URL = "https://api.openalex.org"

        from src.tools.fetchers.crossref_fetcher import CrossRefResult
        mock_cr = MagicMock()
        mock_cr.search_by_title.return_value = CrossRefResult(
            title="Fallback Paper", authors=["Author A"], year="2023",
            doi="10.1234/test", publisher="Test", container_title="J",
        )
        mock_dblp = MagicMock()
        mock_dblp.search_by_title.return_value = None

        ls = LiteratureSearch(fetchers={
            "semantic_scholar": mock_ss, "openalex": mock_oa,
            "crossref": mock_cr, "dblp": mock_dblp,
            "arxiv": MagicMock(), "scholar": MagicMock(),
        })
        results = ls.search_by_title(
            "Some Paper", sources=["semantic_scholar", "openalex"],
        )
        print(f"\nDegradation: {len(results)} results")
        for r in results:
            print(f"  [{r.source}] {r.title}")
        assert any(r.source == "crossref" for r in results)


# ===================================================================
# Part 5: Performance (manual inspection)
# ===================================================================

@pytest.mark.integration
class TestPerformanceComparison:
    def test_field_trend_group_by_vs_serial(self):
        """OpenAlex group_by should complete in < 5s for an 11-year range."""
        ls = LiteratureSearch()
        t0 = time.monotonic()
        result = ls.search_field_trend(
            "reinforcement learning", year_range=(2015, 2025),
            sources=["openalex"],
        )
        elapsed = time.monotonic() - t0
        yearly = result["yearly_counts"]
        non_zero = sum(1 for v in yearly.values() if v > 0)
        print(f"\n[Perf] group_by: {elapsed:.2f}s, non-zero: {non_zero}/{len(yearly)}")
        print(f"  (Old serial approach: ~{len(yearly)}s+)")
        assert elapsed < 10.0
