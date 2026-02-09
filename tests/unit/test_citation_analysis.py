"""Unit tests for citation analysis tool."""

from pathlib import Path

import pytest

from src.tools.citation_analysis import CitationAnalyzer


def test_count_by_year_basic():
    """Count references by year and include unknown bucket."""
    references = [
        {"title": "A", "year": "2020"},
        {"title": "B", "year": "2021"},
        {"title": "C", "year": "2021"},
        {"title": "D", "year": ""},
    ]

    analyzer = CitationAnalyzer()
    year_counts = analyzer.count_by_year(references)

    assert year_counts[0].year == "2020"
    assert year_counts[0].count == 1
    assert year_counts[1].year == "2021"
    assert year_counts[1].count == 2
    assert year_counts[2].year == "unknown"
    assert year_counts[2].count == 1


def test_analyze_references_summary():
    """Analyze reference list summary metrics."""
    references = [
        {"title": "A", "year": "2019"},
        {"title": "B", "year": "2020"},
        {"title": "C", "year": "2020"},
    ]

    analyzer = CitationAnalyzer()
    summary = analyzer.analyze_references(references)

    assert summary["total_references"] == 3
    assert summary["earliest_year"] == 2019
    assert summary["latest_year"] == 2020
    assert summary["unknown_years"] == 0


def test_analyze_pdf_with_real_file():
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
    analyzer = CitationAnalyzer()
    summary = analyzer.analyze_pdf(str(pdf_path))

    assert "year_counts" in summary
    assert "total_references" in summary
