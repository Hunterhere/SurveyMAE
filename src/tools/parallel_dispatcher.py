"""Parallel multi-source dispatcher for literature search.

Fan-out requests to multiple sources concurrently, with per-source retry,
timeout, result merging, and fallback degradation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TypeVar

import requests

from src.core.search_config import (
    ConcurrencyConfig,
    DegradationConfig,
    SearchEngineConfig,
    SourceConfig,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Single-source result wrapper
# ---------------------------------------------------------------------------

@dataclass
class SourceResult:
    """Outcome of a single source fetch attempt."""

    source: str
    items: list[Any] = field(default_factory=list)
    success: bool = False
    error: Optional[str] = None
    latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# Retry-aware single-source executor
# ---------------------------------------------------------------------------

def _execute_with_retry(
    source: str,
    op: Callable[[], Any],
    cfg: SourceConfig,
) -> SourceResult:
    """Execute *op* with retry / back-off per *cfg*.

    Returns a ``SourceResult`` that is **always populated** (never raises).
    """
    last_error: Optional[str] = None
    delay = cfg.retry_delay_seconds
    max_attempts = cfg.max_retries + 1
    t0 = time.monotonic()

    for attempt in range(max_attempts):
        try:
            raw = op()
            items = _ensure_list(raw)
            elapsed = (time.monotonic() - t0) * 1000
            return SourceResult(
                source=source, items=items, success=True, latency_ms=elapsed
            )
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            last_error = f"HTTP {status}: {exc}"
            if status in cfg.retry_on_status and attempt < max_attempts - 1:
                logger.warning(
                    "[%s] attempt %d/%d failed (%s), retrying in %.1fs",
                    source, attempt + 1, max_attempts, last_error, delay,
                )
                time.sleep(delay)
                delay *= cfg.retry_backoff
                continue
            break
        except (requests.ConnectionError, requests.Timeout, OSError) as exc:
            last_error = str(exc)
            if attempt < max_attempts - 1:
                logger.warning(
                    "[%s] attempt %d/%d network error (%s), retrying in %.1fs",
                    source, attempt + 1, max_attempts, last_error, delay,
                )
                time.sleep(delay)
                delay *= cfg.retry_backoff
                continue
            break
        except Exception as exc:
            last_error = str(exc)
            break

    elapsed = (time.monotonic() - t0) * 1000
    logger.error("[%s] all %d attempts failed: %s", source, max_attempts, last_error)
    return SourceResult(
        source=source, items=[], success=False,
        error=last_error, latency_ms=elapsed,
    )


# ---------------------------------------------------------------------------
# Async wrappers
# ---------------------------------------------------------------------------

async def _run_source_async(
    source: str,
    op: Callable[[], Any],
    cfg: SourceConfig,
    executor: ThreadPoolExecutor,
    timeout: float,
) -> SourceResult:
    """Run a blocking source fetch in a thread with an async timeout."""
    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(
                executor, _execute_with_retry, source, op, cfg
            ),
            timeout=timeout,
        )
        return result
    except asyncio.TimeoutError:
        logger.error("[%s] timed out after %.1fs", source, timeout)
        return SourceResult(
            source=source, items=[], success=False,
            error=f"timeout after {timeout}s",
        )


# ---------------------------------------------------------------------------
# Merge strategies
# ---------------------------------------------------------------------------

def _merge_first_wins(
    results: list[SourceResult],
    _config: SearchEngineConfig,
) -> list[Any]:
    """Return items from the first successful source (by priority)."""
    for r in results:
        if r.success and r.items:
            return r.items
    return []


def _merge_union(
    results: list[SourceResult],
    _config: SearchEngineConfig,
) -> list[Any]:
    """Concatenate all successful items (dedup happens in caller)."""
    merged: list[Any] = []
    for r in results:
        if r.success:
            merged.extend(r.items)
    return merged


def _merge_weighted_union(
    results: list[SourceResult],
    config: SearchEngineConfig,
) -> list[Any]:
    """Higher-priority source items first; lower-priority fills gaps."""
    # Sort by priority (lower number = higher priority)
    ordered = sorted(
        results,
        key=lambda r: config.sources.get(r.source, SourceConfig()).priority,
    )
    merged: list[Any] = []
    for r in ordered:
        if r.success:
            merged.extend(r.items)
    return merged


_MERGE_STRATEGIES: dict[str, Callable[[list[SourceResult], SearchEngineConfig], list[Any]]] = {
    "first_wins": _merge_first_wins,
    "union": _merge_union,
    "weighted_union": _merge_weighted_union,
}


# ---------------------------------------------------------------------------
# Core dispatcher
# ---------------------------------------------------------------------------

class ParallelDispatcher:
    """Fan-out search requests to multiple sources concurrently.

    Usage::

        dispatcher = ParallelDispatcher(config)
        results = dispatcher.dispatch(
            sources=["semantic_scholar", "openalex"],
            build_op=lambda source: lambda: fetcher_map[source].search_by_title(title),
        )

    Or async::

        results = await dispatcher.dispatch_async(...)
    """

    def __init__(self, config: SearchEngineConfig) -> None:
        self.config = config
        self._executor = ThreadPoolExecutor(
            max_workers=config.concurrency.max_concurrent_sources,
            thread_name_prefix="lit_search",
        )

    # -- async dispatch (preferred) -----------------------------------------

    async def dispatch_async(
        self,
        sources: list[str],
        build_op: Callable[[str], Callable[[], Any]],
    ) -> list[Any]:
        """Dispatch to *sources* concurrently, merge, fallback if needed."""
        conc = self.config.concurrency
        deg = self.config.degradation

        # Phase 1: concurrent batch
        concurrent_sources = [
            s for s in sources
            if self.config.sources.get(s, SourceConfig()).concurrent
        ]
        # If no sources are marked concurrent, treat all requested as concurrent
        if not concurrent_sources:
            concurrent_sources = sources

        timeout = conc.per_source_timeout_seconds
        tasks = [
            _run_source_async(
                source=s,
                op=build_op(s),
                cfg=self.config.sources.get(s, SourceConfig()),
                executor=self._executor,
                timeout=timeout,
            )
            for s in concurrent_sources
        ]

        results: list[SourceResult] = await asyncio.gather(*tasks)

        # Log summary
        for r in results:
            status = "OK" if r.success else f"FAIL({r.error})"
            logger.info(
                "[dispatch] %s: %s (%d items, %.0fms)",
                r.source, status, len(r.items), r.latency_ms,
            )

        # Merge
        merge_fn = _MERGE_STRATEGIES.get(conc.merge_strategy, _merge_weighted_union)
        merged = merge_fn(results, self.config)

        if merged:
            return merged

        # Phase 2: fallback (serial)
        logger.warning(
            "All concurrent sources returned empty; trying fallback: %s",
            deg.fallback_order,
        )
        for fb_source in deg.fallback_order:
            if fb_source in concurrent_sources:
                continue  # already tried
            src_cfg = self.config.sources.get(fb_source, SourceConfig())
            if not src_cfg.enabled:
                continue
            try:
                fb_result = _execute_with_retry(
                    fb_source, build_op(fb_source), src_cfg
                )
                if fb_result.success and fb_result.items:
                    logger.info(
                        "[fallback] %s succeeded with %d items",
                        fb_source, len(fb_result.items),
                    )
                    return fb_result.items
            except Exception as exc:
                logger.warning("[fallback] %s failed: %s", fb_source, exc)

        # Phase 3: all failed
        if deg.on_all_failed == "raise":
            raise AllSourcesFailedError(
                "All literature search sources failed "
                f"(concurrent={concurrent_sources}, fallback={deg.fallback_order})"
            )

        logger.error("All sources (concurrent + fallback) failed; returning []")
        return []

    # -- sync dispatch (bridges to async) -----------------------------------

    def dispatch(
        self,
        sources: list[str],
        build_op: Callable[[str], Callable[[], Any]],
    ) -> list[Any]:
        """Synchronous wrapper around :meth:`dispatch_async`."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            # Already inside an async context – run in thread pool
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(1) as pool:
                future = pool.submit(
                    asyncio.run, self.dispatch_async(sources, build_op)
                )
                return future.result()
        else:
            return asyncio.run(self.dispatch_async(sources, build_op))

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class AllSourcesFailedError(Exception):
    """Raised when every source (including fallbacks) has failed
    and ``on_all_failed`` is set to ``"raise"``."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
