"""SurveyMAE Logging System.

Architecture:
    - Console (stderr): Rich Console direct output for pipeline progress/steps,
      RichHandler for WARNING/ERROR
    - File: FileHandler with all levels (DEBUG+) in plain text

Usage:
    from src.core.log import setup_logging, get_console, create_progress
    from src.core.log import log_pipeline_step, log_substep, log_run_summary
    from src.core.log import track_step, get_run_stats

Public API:
    setup_logging(run_dir, verbose, log_level, quiet) -> logging.Logger
    get_console() -> rich.console.Console
    create_progress(quiet=False) -> rich.progress.Progress
    log_pipeline_step(step, total, name, detail, elapsed) -> None
    log_substep(name, detail, elapsed, is_last) -> None
    log_run_summary(stats, total_elapsed) -> None
    track_step(logger, label) -> context manager
    RunStats (class)
    get_run_stats() -> RunStats
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.rule import Rule

if TYPE_CHECKING:
    from src.core.log import RunStats as RunStatsType

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
_namespace = "surveymae"
_console = Console(stderr=True)
_run_stats: "RunStatsType | None" = None
_stats_lock = threading.Lock()
_file_logger: logging.Logger | None = None
_summary_logger: logging.Logger | None = None

# ---------------------------------------------------------------------------
# RunStats
# ---------------------------------------------------------------------------

class RunStats:
    """Thread-safe call counters for a single run."""

    __slots__ = (
        "_lock", "llm_calls", "llm_tokens_in", "llm_tokens_out",
        "api_calls", "warnings", "errors",
    )

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.llm_calls = 0
        self.llm_tokens_in = 0
        self.llm_tokens_out = 0
        self.api_calls = 0
        self.warnings = 0
        self.errors = 0

    def record_llm(self, tokens_in: int = 0, tokens_out: int = 0) -> None:
        with self._lock:
            self.llm_calls += 1
            self.llm_tokens_in += tokens_in
            self.llm_tokens_out += tokens_out

    def record_api(self) -> None:
        with self._lock:
            self.api_calls += 1

    def record_warning(self) -> None:
        with self._lock:
            self.warnings += 1

    def record_error(self) -> None:
        with self._lock:
            self.errors += 1

    def summary(self) -> dict:
        with self._lock:
            return {
                "llm_calls": self.llm_calls,
                "llm_tokens_in": self.llm_tokens_in,
                "llm_tokens_out": self.llm_tokens_out,
                "api_calls": self.api_calls,
                "warnings": self.warnings,
                "errors": self.errors,
            }


def get_run_stats() -> RunStats:
    """Return the global RunStats instance (creates on first call)."""
    global _run_stats
    with _stats_lock:
        if _run_stats is None:
            _run_stats = RunStats()
        return _run_stats


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------

def get_console() -> Console:
    """Return the global Console instance (stderr)."""
    return _console


def create_progress(quiet: bool = False) -> Progress:
    """Create a Rich Progress bar sharing the global Console.

    Args:
        quiet: If True, returns a no-op Progress that renders nothing
               but still has a compatible API (add_task / update).
               Always uses transient=False so completed bars remain visible.

    Returns:
        Rich Progress instance.
    """
    if quiet:
        return Progress(
            SpinnerColumn(),
            TextColumn(""),
            BarColumn(bar_width=None),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=Console(stderr=True, quiet=True),
            transient=False,
        )
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=30),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=_console,
        transient=False,
    )


# ---------------------------------------------------------------------------
# Pipeline / substep output
# ---------------------------------------------------------------------------

def log_pipeline_step(
    step: str,
    total: int,
    name: str,
    detail: str = "",
    elapsed: float | None = None,
) -> None:
    """Print a pipeline step to console (Rich) + write to file logger.

    Console format::
        [01/07] parse_pdf              │ 47 refs, 12 sections           2.3s

    Args:
        step:   Step number / code, e.g. "01"
        total:  Total number of steps, e.g. 7
        name:   Step name, e.g. "parse_pdf"
        detail: Key result snippet, e.g. "47 refs, 12 sections"
        elapsed: Optional elapsed time in seconds, shown as "2.3s"
    """
    # --- Console output ---
    step_str = f"[{step.zfill(2)}/{total:02d}] {name}"
    if detail:
        bar = " │ "
    else:
        bar = "  "

    if elapsed is not None:
        elapsed_str = f"  {elapsed:.1f}s"
    else:
        elapsed_str = ""

    _console.print(f"  {step_str}{bar}[dim]{detail}[/dim]{elapsed_str}")

    # --- File log ---
    msg = f"[{step.zfill(2)}/{total:02d}] {name}" + (f" | {detail}" if detail else "")
    if elapsed is not None:
        msg += f" | elapsed={elapsed:.1f}s"
    if _file_logger:
        _file_logger.info(msg)
    if _summary_logger:
        _summary_logger.info(msg)


def log_substep(
    name: str,
    detail: str,
    elapsed: float | None = None,
    is_last: bool = False,
) -> None:
    """Print a tree sub-step to console + write to file logger.

    Console format::
        ├── citation_validate    │ C3=8.51% C5=89.36%             18.7s
        └── key_papers           │ top-30, 匹配 19 篇 (63.3%)       5.4s

    Args:
        name:    Sub-step name, e.g. "citation_validate"
        detail:  Result string, e.g. "C3=8.51% C5=89.36%"
        elapsed: Optional elapsed time in seconds
        is_last: If True, uses "└──" instead of "├──"
    """
    branch = "└──" if is_last else "├──"
    if elapsed is not None:
        elapsed_str = f"  {elapsed:.1f}s"
    else:
        elapsed_str = ""

    _console.print(f"  {branch} {name}  │ [dim]{detail}[/dim]{elapsed_str}")

    msg = f"  {branch} {name} | {detail}"
    if elapsed is not None:
        msg += f" | elapsed={elapsed:.1f}s"
    if _file_logger:
        _file_logger.info(msg)
    if _summary_logger:
        _summary_logger.info(msg)


def log_run_summary(stats: RunStats, total_elapsed: float) -> None:
    """Print the final run summary with a Rule divider.

    Console format::
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        总耗时 51.2s │ LLM 调用 28 次 │ API 调用 94 次
    """
    snapshot = stats.summary()
    llm_calls = int(snapshot.get("llm_calls", 0))
    api_calls = int(snapshot.get("api_calls", 0))
    warnings = int(snapshot.get("warnings", 0))
    errors = int(snapshot.get("errors", 0))

    _console.print(Rule())
    _console.print(
        f"总耗时 {total_elapsed:.1f}s │ "
        f"LLM 调用 {llm_calls} 次 │ "
        f"API 调用 {api_calls} 次"
    )

    if _file_logger:
        _file_logger.info(
            "RUN_SUMMARY | elapsed=%.1fs llm_calls=%d api_calls=%d warnings=%d errors=%d",
            total_elapsed, llm_calls, api_calls, warnings, errors,
        )


@contextmanager
def track_step(logger: logging.Logger, label: str):
    """Context manager: logs label + elapsed time on exit.

    Usage::
        with track_step(logger, "citation_validate"):
            validate(refs)

    Logs DEBUG message: "STEP label | elapsed=X.XXs"
    """
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        logger.debug("STEP %s | elapsed=%.2fs", label, elapsed)


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(
    run_dir: str | Path | None = None,
    verbose: bool = False,
    log_level: str | None = None,
    quiet: bool = False,
    pdf_path: str | None = None,
) -> logging.Logger:
    """Initialize the SurveyMAE logging system.

    Behavior:
        1. Create "surveymae" root logger at DEBUG level
        2. Add RichHandler for console (WARNING+ by default, DEBUG in verbose)
        3. If run_dir provided, add FileHandler -> {run_dir}/logs/run.log
        4. If run_dir provided, add FileHandler -> {run_dir}/logs/summary.log
           (only pipeline steps and substeps)
        5. Suppress third-party loggers to WARNING
        6. Reset global RunStats

    Level resolution (console RichHandler):
        1. log_level explicitly set -> use that
        2. quiet=True -> WARNING
        3. verbose=True -> DEBUG
        4. default -> INFO (WARNING shown, INFO goes to Console directly)

    Args:
        run_dir:   Run output directory (e.g. output/runs/{run_id})
        verbose:   Enable DEBUG on console
        log_level: Explicit console level (DEBUG/INFO/WARNING/ERROR)
        quiet:     Suppress progress output (WARNING+ only)
        pdf_path:  PDF path to record in summary.log header

    Returns:
        The "surveymae" root logger
    """
    global _file_logger, _summary_logger

    # Resolve console handler level
    if log_level:
        console_level = getattr(logging, log_level.upper())
    elif quiet:
        console_level = logging.WARNING
    elif verbose:
        console_level = logging.DEBUG
    else:
        console_level = logging.INFO  # INFO goes via Console, not RichHandler

    # Root logger
    root_logger = logging.getLogger(_namespace)
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()

    # --- RichHandler for console (WARNING+ or DEBUG when verbose) ---
    rich_handler = RichHandler(
        console=_console,
        level=console_level,
        show_path=False,
        show_time=False,
        markup=True,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
    )
    rich_handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger.addHandler(rich_handler)

    # --- FileHandler (all levels, plain text) ---
    if run_dir is not None:
        run_dir = Path(run_dir)
        log_dir = run_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "run.log"

        # Use a dedicated file logger so its name is "surveymae.file"
        _file_logger = logging.getLogger(f"{_namespace}.file")
        _file_logger.setLevel(logging.DEBUG)
        _file_logger.handlers.clear()

        file_handler = logging.FileHandler(
            log_path,
            mode="a",
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        # Plain text format without rich markup
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)-8s] %(name)s | %(message)s"),
        )
        _file_logger.addHandler(file_handler)
        _file_logger.propagate = False

        # Also attach to root so all surveymae.* loggers write to file
        root_logger.addHandler(file_handler)

        # --- summary.log: pipeline steps and substeps only ---
        summary_path = log_dir / "summary.log"
        _summary_logger = logging.getLogger(f"{_namespace}.summary")
        _summary_logger.setLevel(logging.INFO)
        _summary_logger.handlers.clear()
        _summary_logger.propagate = False

        summary_handler = logging.FileHandler(
            summary_path,
            mode="a",
            encoding="utf-8",
        )
        summary_handler.setLevel(logging.INFO)
        summary_handler.setFormatter(logging.Formatter("%(message)s"))
        _summary_logger.addHandler(summary_handler)

        # Write header
        header = f"SurveyMAE 评测启动 | PDF: {pdf_path}" if pdf_path else "SurveyMAE 评测启动"
        _summary_logger.info(header)
        _summary_logger.info("")

    # --- Suppress third-party noise ---
    for lib in ("langchain", "langgraph", "httpx", "httpcore", "openai", "anthropic"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    # --- Reset / init RunStats ---
    global _run_stats
    with _stats_lock:
        _run_stats = RunStats()

    return root_logger


def _utc_now() -> str:
    """Return current UTC time in ISO-8601 format (Z suffix)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
