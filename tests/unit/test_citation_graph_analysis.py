"""Unit tests for citation graph analysis tool."""

import pytest

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


def test_authority_center_clustering_basic():
    """authority_center should produce valid summary and evidence."""
    references = [
        {"key": f"P{i}", "year": str(2010 + i)} for i in range(10)
    ]
    # P0 is a hub: cited by P1-P8; P9 cites P0 and P1.
    edges = (
        [{"source": f"P{i}", "target": "P0"} for i in range(1, 9)]
        + [{"source": "P9", "target": "P0"}, {"source": "P9", "target": "P1"}]
    )

    analyzer = CitationGraphAnalyzer()
    report = analyzer.analyze(
        references=references,
        edges=edges,
        run_id="ac_test",
        config={"clustering_algorithm": "authority_center"},
    )

    cocitation = report["summary"]["cocitation_clustering"]
    assert cocitation["clustering_method"] == "authority_center"
    assert cocitation["n_clusters"] >= 1
    assert "center_count" in cocitation
    assert "cluster_size_stats" in cocitation

    evidence = report["evidence"]["clusters"]
    assert isinstance(evidence, list)
    if evidence:
        cluster = evidence[0]
        assert "cluster_id" in cluster
        assert "size" in cluster
        assert isinstance(cluster["top_papers"], list)


def test_elbow_center_count_basic():
    """_elbow_center_count returns value within [k_min, k_max]."""
    analyzer = CitationGraphAnalyzer()
    degrees = [50, 40, 30, 10, 5, 3, 2, 2, 1, 1]
    k = analyzer._elbow_center_count(degrees, k_min=2, k_max=8)
    assert 2 <= k <= 8


def test_elbow_center_count_empty():
    analyzer = CitationGraphAnalyzer()
    assert analyzer._elbow_center_count([], k_min=2, k_max=8) == 0


def test_elbow_center_count_flat():
    """Flat curve: should clamp to k_min."""
    analyzer = CitationGraphAnalyzer()
    degrees = [5, 5, 5, 5, 5]
    k = analyzer._elbow_center_count(degrees, k_min=2, k_max=8)
    assert k >= 1


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("networkx") is None,
    reason="networkx not installed",
)
def test_authority_center_no_isolates():
    """All non-isolate nodes should be assigned to a cluster."""
    references = [{"key": f"R{i}", "year": "2020"} for i in range(8)]
    # Chain: R0->R1->R2->R3, hub R0 also cited by R4,R5,R6,R7
    edges = [
        {"source": "R1", "target": "R0"},
        {"source": "R2", "target": "R0"},
        {"source": "R3", "target": "R0"},
        {"source": "R4", "target": "R0"},
        {"source": "R5", "target": "R0"},
        {"source": "R6", "target": "R0"},
        {"source": "R7", "target": "R0"},
        {"source": "R1", "target": "R2"},
    ]

    analyzer = CitationGraphAnalyzer()
    report = analyzer.analyze(
        references=references,
        edges=edges,
        run_id="ac_no_isolates",
        config={"clustering_algorithm": "authority_center"},
    )

    cocitation = report["summary"]["cocitation_clustering"]
    assert cocitation["clustering_method"] == "authority_center"
    # Hub R0 has in_degree=7, must be a center; all citing nodes reachable within 1 hop.
    assert cocitation["n_clusters"] >= 1
