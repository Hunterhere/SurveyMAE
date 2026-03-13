"""Unit tests for citation analysis tool."""

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


def test_bucket_by_year_window():
    """Bucket references into fixed year windows."""
    references = [
        {"title": "A", "year": "2018"},
        {"title": "B", "year": "2019"},
        {"title": "C", "year": "2020"},
        {"title": "D", "year": "2021"},
        {"title": "E", "year": "2022"},
    ]

    analyzer = CitationAnalyzer()
    buckets = analyzer.bucket_by_year_window(references, window=2)

    assert len(buckets) == 3
    assert (buckets[0].start_year, buckets[0].end_year, buckets[0].count) == (2018, 2019, 2)
    assert (buckets[1].start_year, buckets[1].end_year, buckets[1].count) == (2020, 2021, 2)
    assert (buckets[2].start_year, buckets[2].end_year, buckets[2].count) == (2022, 2023, 1)


def test_year_over_year_trend():
    """Compute year-over-year trends with moving averages."""
    references = [
        {"title": "A", "year": "2020"},
        {"title": "B", "year": "2021"},
        {"title": "C", "year": "2021"},
        {"title": "D", "year": "2022"},
    ]

    analyzer = CitationAnalyzer()
    trend = analyzer.year_over_year_trend(references)

    counts = trend["year_counts"]
    assert counts[0]["year"] == 2020
    assert counts[0]["count"] == 1
    assert counts[1]["year"] == 2021
    assert counts[1]["count"] == 2

    growth = trend["growth"]
    assert growth[0]["delta"] is None
    assert growth[1]["delta"] == 1
    assert growth[1]["pct"] == 100.0


def test_citation_age_distribution():
    """Compute citation age buckets."""
    references = [
        {"title": "A", "year": "2023"},
        {"title": "B", "year": "2022"},
        {"title": "C", "year": "2018"},
        {"title": "D", "year": "2010"},
        {"title": "E", "year": "2025"},
    ]

    analyzer = CitationAnalyzer()
    dist = analyzer.citation_age_distribution(references, paper_year=2023)

    assert dist["0-4"] == 2
    assert dist["5-9"] == 1
    assert dist["10-19"] == 1
    assert dist["future"] == 1


def test_concentration_top_years():
    """Compute top-k year concentration."""
    references = [
        {"title": "A", "year": "2020"},
        {"title": "B", "year": "2020"},
        {"title": "C", "year": "2021"},
        {"title": "D", "year": "2022"},
        {"title": "E", "year": "2022"},
        {"title": "F", "year": "2022"},
    ]

    analyzer = CitationAnalyzer()
    summary = analyzer.concentration_top_years(references, top_k=2)

    top_years = summary["top_years"]
    assert top_years[0]["year"] == 2022
    assert top_years[0]["count"] == 3
    assert top_years[1]["year"] == 2020
    assert top_years[1]["count"] == 2
    assert summary["top_k_share"] == 5 / 6
