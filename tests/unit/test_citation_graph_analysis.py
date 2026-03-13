"""Unit tests for citation graph analysis tool."""

from src.tools.citation_graph_analysis import CitationGraphAnalyzer


def test_citation_graph_basic_metrics():
    references = [
        {"key": "A", "year": "2020"},
        {"key": "B", "year": "2021"},
        {"key": "C", "year": ""},
    ]
    edges = [
        {"source": "A", "target": "B"},
        {"source": "A", "target": "C"},
        {"source": "B", "target": "C"},
        {"source": "X", "target": "A"},
    ]

    analyzer = CitationGraphAnalyzer()
    report = analyzer.analyze(references=references, edges=edges, run_id="test_run")

    meta = report["meta"]
    assert meta["n_nodes"] == 3
    assert meta["n_edges"] == 3
    assert meta["unresolved_edge_ratio"] == 0.25

    density = report["summary"]["density_connectivity"]
    assert density["n_weak_components"] == 1
    assert density["n_isolates"] == 0

    warnings = {w["code"] for w in report["warnings"]}
    assert "YEAR_MISSING_HIGH" in warnings
    assert "TEMPORAL_METRICS_DEGRADED" in warnings


def test_negative_citation_lag_warning():
    references = [
        {"key": "A", "year": "2020"},
        {"key": "B", "year": "2022"},
    ]
    edges = [
        ("A", "B"),
        ("B", "A"),
    ]

    analyzer = CitationGraphAnalyzer()
    report = analyzer.analyze(references=references, edges=edges, run_id="lag_test")

    warnings = {w["code"] for w in report["warnings"]}
    assert "NEGATIVE_CITATION_LAG_HIGH" in warnings

    cocitation = report["summary"]["cocitation_clustering"]
    assert cocitation["clustering_method"] == "components"
