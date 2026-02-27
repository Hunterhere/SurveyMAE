"""Integration tests for PDF citation analysis (real file parsing)."""

import json
import os
from pathlib import Path

import pytest

from src.tools.citation_analysis import CitationAnalyzer
from src.tools.result_store import ResultStore


def test_analyze_pdf_with_real_file(tmp_path: Path):
    """Analyze real PDF file if parser deps are installed."""
    try:
        import pymupdf4llm  # noqa: F401

        pdf_ready = True
    except Exception:
        try:
            import pypdf  # noqa: F401

            pdf_ready = True
        except Exception:
            pdf_ready = False

    if not pdf_ready:
        pytest.skip("PDF parsing dependencies not installed")

    pdf_path = Path(__file__).resolve().parents[2] / "test_paper.pdf"
    store = ResultStore(base_dir=str(tmp_path / "runs"), run_id="test_run")
    analyzer = CitationAnalyzer(result_store=store)
    summary = analyzer.analyze_pdf(str(pdf_path))

    if os.getenv("SHOW_PDF_CITATION_STATS") == "1":
        print(json.dumps(summary, indent=2, ensure_ascii=False))

    assert "year_counts" in summary
    assert "total_references" in summary

    run_dir = tmp_path / "runs" / "test_run"
    assert (run_dir / "run.json").exists()
    assert (run_dir / "index.json").exists()
