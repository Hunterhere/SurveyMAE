import json
import math
import os
from pathlib import Path

import pytest

from src.core.config import SurveyMAEConfig
from src.tools.citation_analysis import CitationAnalyzer
from src.tools.citation_checker import CitationChecker
from src.tools.citation_graph_analysis import CitationGraphAnalyzer
from src.tools.result_store import ResultStore


def _build_config(backend: str, grobid_url: str) -> SurveyMAEConfig:
    cfg = SurveyMAEConfig()
    cfg.citation.backend = backend
    cfg.citation.grobid_url = grobid_url
    cfg.citation.grobid_timeout_s = int(os.getenv("GROBID_TIMEOUT_S", "30"))
    cfg.citation.grobid_consolidate = False
    return cfg


def _render_mermaid(
    edges: list[dict[str, str]],
    nodes: list[str],
    max_edges: int = 80,
    max_nodes: int = 200,
) -> tuple[str, int, int]:
    """Render a compact Mermaid directed graph preview."""
    lines = ["graph LR"]
    shown_nodes = 0
    for node in nodes[:max_nodes]:
        node_id = str(node).strip()
        if not node_id:
            continue
        lines.append(f'  {node_id}["{node_id}"]')
        shown_nodes += 1

    seen: set[tuple[str, str]] = set()
    shown = 0

    for edge in edges:
        src = str(edge.get("source", "")).strip()
        dst = str(edge.get("target", "")).strip()
        if not src or not dst:
            continue
        key = (src, dst)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f'  {src}["{src}"] --> {dst}["{dst}"]')
        shown += 1
        if shown >= max_edges:
            break

    return "\n".join(lines), len(seen), shown_nodes


def _render_dot(
    edges: list[dict[str, str]],
    nodes: list[str],
    max_edges: int = 200,
    max_nodes: int = 500,
) -> tuple[str, int, int]:
    """Render a Graphviz DOT directed graph preview."""
    lines = [
        "digraph CitationGraph {",
        "  rankdir=LR;",
        "  node [shape=box, fontsize=10];",
    ]
    shown_nodes = 0
    for node in nodes[:max_nodes]:
        node_id = str(node).strip()
        if not node_id:
            continue
        lines.append(f'  "{node_id}";')
        shown_nodes += 1

    seen: set[tuple[str, str]] = set()
    shown = 0

    for edge in edges:
        src = str(edge.get("source", "")).strip()
        dst = str(edge.get("target", "")).strip()
        if not src or not dst:
            continue
        key = (src, dst)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f'  "{src}" -> "{dst}";')
        shown += 1
        if shown >= max_edges:
            break

    lines.append("}")
    return "\n".join(lines), len(seen), shown_nodes


def _elbow_center_count(degrees_desc: list[int], k_min: int, k_max: int) -> int:
    """Pick center count via elbow (max distance to first-last baseline)."""
    if not degrees_desc:
        return 0
    m = min(len(degrees_desc), max(1, k_max))
    if m <= 2:
        return m

    y = degrees_desc[:m]
    x1, y1 = 0.0, float(y[0])
    x2, y2 = float(m - 1), float(y[-1])
    den = math.hypot(y2 - y1, x2 - x1)
    if den == 0.0:
        return min(m, max(1, k_min))

    best_idx = 0
    best_dist = -1.0
    for i in range(1, m - 1):
        xi = float(i)
        yi = float(y[i])
        dist = abs((y2 - y1) * xi - (x2 - x1) * yi + x2 * y1 - y2 * x1) / den
        if dist > best_dist:
            best_dist = dist
            best_idx = i

    k = best_idx + 1
    return max(1, min(m, max(k_min, k)))


def _render_pyvis_html(
    edges: list[dict[str, str]],
    nodes: list[str],
    output_path: Path,
    max_edges: int = 500,
    max_nodes: int = 500,
) -> tuple[int, int]:
    """Render an interactive PyVis HTML preview."""
    try:
        from pyvis.network import Network
    except Exception as exc:
        raise RuntimeError("pyvis is not installed. Install with `uv add pyvis`.") from exc

    shown_nodes: list[str] = []
    for node in nodes[:max_nodes]:
        node_id = str(node).strip()
        if node_id:
            shown_nodes.append(node_id)
    shown_node_set = set(shown_nodes)

    dedup_edges: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for edge in edges:
        src = str(edge.get("source", "")).strip()
        dst = str(edge.get("target", "")).strip()
        if not src or not dst or src not in shown_node_set or dst not in shown_node_set:
            continue
        key = (src, dst)
        if key in seen:
            continue
        seen.add(key)
        dedup_edges.append(key)
        if len(dedup_edges) >= max_edges:
            break

    in_degree = {node: 0 for node in shown_nodes}
    out_degree = {node: 0 for node in shown_nodes}
    for src, dst in dedup_edges:
        out_degree[src] += 1
        in_degree[dst] += 1

    palette = [
        "#60a5fa",
        "#f59e0b",
        "#34d399",
        "#f472b6",
        "#a78bfa",
        "#22d3ee",
        "#fb7185",
        "#facc15",
    ]

    cluster_map: dict[str, int] = {}
    centers_summary: list[dict[str, object]] = []
    center_count = 0
    min_in_degree = 5
    k_min = 3
    k_max = 18
    max_hops = 3
    pagerank_alpha = 0.80
    try:
        import networkx as nx

        g = nx.DiGraph()
        g.add_nodes_from(shown_nodes)
        g.add_edges_from(dedup_edges)
        non_isolates = [n for n in shown_nodes if in_degree[n] > 0 or out_degree[n] > 0]
        non_isolates_set = set(non_isolates)
        if non_isolates:
            pagerank = nx.pagerank(g, alpha=pagerank_alpha)
            candidates = [n for n in non_isolates if in_degree[n] >= min_in_degree] or non_isolates
            candidates.sort(key=lambda n: (in_degree[n], pagerank.get(n, 0.0)), reverse=True)
            candidate_degrees = [in_degree[n] for n in candidates]
            center_count = _elbow_center_count(candidate_degrees, k_min=k_min, k_max=k_max)
            centers = candidates[: max(1, center_count)]
            center_rank = {c: i for i, c in enumerate(centers)}

            rev = g.reverse(copy=False)
            dist_to_center: dict[str, dict[str, int]] = {}
            for c in centers:
                lengths = nx.single_source_shortest_path_length(rev, c, cutoff=max_hops)
                for node, dist in lengths.items():
                    if node not in non_isolates_set:
                        continue
                    dist_to_center.setdefault(node, {})[c] = dist

            for c, cid in center_rank.items():
                cluster_map[c] = cid
            for node in non_isolates:
                if node in cluster_map:
                    continue
                options = dist_to_center.get(node, {})
                if not options:
                    continue
                best_center = min(
                    options.items(), key=lambda item: (item[1], center_rank[item[0]])
                )[0]
                cluster_map[node] = center_rank[best_center]

            for _ in range(3):
                changed = False
                for node in non_isolates:
                    if node in cluster_map:
                        continue
                    votes: dict[int, int] = {}
                    for neigh in g.predecessors(node):
                        cid = cluster_map.get(neigh)
                        if cid is not None:
                            votes[cid] = votes.get(cid, 0) + 1
                    for neigh in g.successors(node):
                        cid = cluster_map.get(neigh)
                        if cid is not None:
                            votes[cid] = votes.get(cid, 0) + 1
                    if not votes:
                        continue
                    cluster_map[node] = max(votes.items(), key=lambda item: (item[1], -item[0]))[0]
                    changed = True
                if not changed:
                    break

            centers_summary = [
                {
                    "node": c,
                    "cluster_id": cluster_map.get(c),
                    "in_degree": in_degree.get(c, 0),
                    "out_degree": out_degree.get(c, 0),
                    "pagerank": round(float(pagerank.get(c, 0.0)), 6),
                }
                for c in centers
            ]
    except Exception:
        cluster_map = {}
        centers_summary = []

    def node_color(node: str, in_deg: int, out_deg: int) -> str:
        if in_deg == 0 and out_deg == 0:
            return "#9ca3af"  # isolated
        cid = cluster_map.get(node)
        if cid is None:
            return "#60a5fa"
        return palette[cid % len(palette)]

    net = Network(
        height="900px",
        width="100%",
        bgcolor="#0b1020",
        font_color="#e5e7eb",
        directed=True,
        cdn_resources="remote",
    )
    net.barnes_hut(
        gravity=-32000,
        central_gravity=0.12,
        spring_length=240,
        spring_strength=0.008,
    )

    for node in shown_nodes:
        in_deg = in_degree[node]
        out_deg = out_degree[node]
        net.add_node(
            node,
            label=node,
            title=f"{node}<br>in={in_deg}, out={out_deg}",
            color=node_color(node, in_deg, out_deg),
            size=max(8, min(34, 10 + 4.2 * math.log1p(1.4 * in_deg + out_deg))),
        )

    for src, dst in dedup_edges:
        src_cluster = cluster_map.get(src)
        edge_color = (
            f"{palette[src_cluster % len(palette)]}66" if src_cluster is not None else "#94a3b866"
        )
        net.add_edge(src, dst, color=edge_color, width=1)

    net.set_options(
        """
        var options = {
          "layout": {"improvedLayout": true},
          "interaction": {
            "hover": true,
            "multiselect": true,
            "navigationButtons": true,
            "hideEdgesOnDrag": true
          },
          "edges": {"smooth": false},
          "physics": {
            "solver": "barnesHut",
            "barnesHut": {
              "gravitationalConstant": -32000,
              "centralGravity": 0.12,
              "springLength": 240,
              "springConstant": 0.008,
              "damping": 0.92,
              "avoidOverlap": 0.9
            },
            "stabilization": {"enabled": true, "iterations": 1200, "fit": true},
            "minVelocity": 0.15
          }
        }
        """
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    net.write_html(str(output_path), local=False, notebook=False, open_browser=False)
    print(
        "PyVis cluster mode: authority_center "
        f"(directed, selection=elbow, center_count={center_count}, "
        f"k_min={k_min}, k_max={k_max}, min_in_degree={min_in_degree}, max_hops={max_hops})"
    )
    if centers_summary:
        print("PyVis authority centers:")
        print(json.dumps(centers_summary, ensure_ascii=False, indent=2))
    return len(dedup_edges), len(shown_nodes)


def _graph_metrics_snapshot(report: dict) -> dict:
    """Compact snapshot for the four metric groups in the requirement doc."""
    summary = report.get("summary", {})
    density = summary.get("density_connectivity", {})
    centrality = summary.get("centrality", {}).get("metrics", {})
    cocitation = summary.get("cocitation_clustering", {})
    temporal = summary.get("temporal", {})

    return {
        "density_connectivity": {
            "density_global": density.get("density_global"),
            "n_weak_components": density.get("n_weak_components"),
            "lcc_frac": density.get("lcc_frac"),
            "n_isolates": density.get("n_isolates"),
            "component_sizes_top5": (density.get("component_sizes") or [])[:5],
        },
        "centrality": {
            "in_degree_top3": (centrality.get("in_degree", {}).get("topk") or [])[:3],
            "out_degree_top3": (centrality.get("out_degree", {}).get("topk") or [])[:3],
            "pagerank_top3": (centrality.get("pagerank", {}).get("topk") or [])[:3],
            "tail_index": {
                "in_degree": centrality.get("in_degree", {}).get("tail_index"),
                "out_degree": centrality.get("out_degree", {}).get("tail_index"),
                "pagerank": centrality.get("pagerank", {}).get("tail_index"),
            },
        },
        "cocitation_clustering": {
            "method": cocitation.get("clustering_method"),
            "n_clusters": cocitation.get("n_clusters"),
            "threshold": cocitation.get("cocitation_edge_weight_threshold"),
            "cluster_size_stats": cocitation.get("cluster_size_stats"),
        },
        "temporal": {
            "recency": temporal.get("recency"),
            "citation_lag": temporal.get("citation_lag"),
            "core_recency": temporal.get("core_recency"),
            "year_hist_head": {
                "bins": (temporal.get("year_hist", {}).get("bins") or [])[:8],
                "counts": (temporal.get("year_hist", {}).get("counts") or [])[:8],
            },
        },
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_citation_graph_full_pipeline_with_test_paper(tmp_path: Path):
    """End-to-end pipeline: parse -> verify -> graph build -> graph analysis."""
    grobid_url = os.getenv("GROBID_URL", "http://localhost:8070")
    pdf_path = Path(__file__).resolve().parents[2] / "test_paper.pdf"
    assert pdf_path.exists(), f"Missing test PDF: {pdf_path}"

    sources_raw = os.getenv("CITATION_VERIFY_SOURCES", "semantic_scholar,openalex")
    sources = [s.strip().lower() for s in sources_raw.split(",") if s.strip()]
    if "openalex" not in sources:
        sources.append("openalex")

    store = ResultStore(
        base_dir=str(tmp_path / "runs"),
        run_id="graph_pipeline_test",
        tool_params={"backend": "auto", "grobid_url": grobid_url, "sources": sources},
    )

    checker = CitationChecker(config=_build_config("auto", grobid_url), result_store=store)
    extracted = await checker.extract_citations_with_context_from_pdf_async(
        str(pdf_path),
        verify_references=True,
        sources=sources,
        # verify_limit=30, # Uncomment to verify more references if external sources are available and rate limits allow
    )

    citations = extracted.get("citations", [])
    references = extracted.get("references", [])
    sections = extracted.get("sections", [])

    assert citations, "Expected citations from PDF extraction"
    assert references, "Expected references from PDF extraction"

    verified = [ref for ref in references if ref.get("validation")]
    if not verified:
        pytest.skip("No reference metadata was verified; external source may be unavailable")

    citation_analyzer = CitationAnalyzer(result_store=store)
    reference_summary = citation_analyzer.analyze_references_with_validation(references)
    assert reference_summary["total_references"] == len(references)

    paragraph_report = citation_analyzer.analyze_paragraph_distribution(
        citations,
        references,
        sections=sections,
        max_examples_per_paragraph=1,
    )
    assert paragraph_report["summary"]["paragraphs_with_citations"] > 0

    for ref in references:
        ref["source_path"] = str(pdf_path)

    real_edges = extracted.get("real_citation_edges", [])
    real_edge_stats = extracted.get("real_citation_edge_stats", {})
    assert isinstance(real_edges, list)
    assert isinstance(real_edge_stats, dict)
    edges = real_edges
    graph_report = None
    if edges:
        graph_analyzer = CitationGraphAnalyzer(result_store=store)
        graph_report = graph_analyzer.analyze(
            references=references,
            edges=edges,
            reference_year=2026,
            config={
                "topk_papers": 10,
                "topk_clusters": 5,
                "compute_betweenness": False,
            },
        )

        assert graph_report["schema_version"] == "1.0.0"
        assert graph_report["tool"] == "citation_graph_analysis"

        meta = graph_report["meta"]
        assert meta["directed"] is True
        assert meta["n_nodes"] > 0
        assert meta["n_edges"] > 0
        assert 0.0 <= meta["missing_year_ratio"] <= 1.0
        assert 0.0 <= meta["unresolved_edge_ratio"] <= 1.0

        summary = graph_report["summary"]
        assert "density_connectivity" in summary
        assert "centrality" in summary
        assert "cocitation_clustering" in summary
        assert "temporal" in summary
        density = summary["density_connectivity"]
        assert "density_global" in density
        assert "n_weak_components" in density
        assert "lcc_frac" in density
        assert "n_isolates" in density
        assert "component_sizes" in density

        centrality_metrics = summary["centrality"]["metrics"]
        assert "in_degree" in centrality_metrics
        assert "out_degree" in centrality_metrics
        assert "pagerank" in centrality_metrics
        for metric_name in ("in_degree", "out_degree", "pagerank"):
            metric = centrality_metrics[metric_name]
            assert "quantiles" in metric
            assert "tail_index" in metric
            assert isinstance(metric.get("topk"), list)

        cocitation = summary["cocitation_clustering"]
        assert "cocitation_edge_weight_threshold" in cocitation
        assert "n_clusters" in cocitation
        assert "clustering_method" in cocitation
        assert "cluster_size_stats" in cocitation

        temporal = summary["temporal"]
        assert "recency" in temporal
        assert "citation_lag" in temporal
        assert "core_recency" in temporal

        evidence = graph_report["evidence"]
        assert evidence["top_papers"]["by_pagerank"]
        assert evidence["top_papers"]["by_in_degree"]

        warnings = graph_report["warnings"]
        assert isinstance(warnings, list)
    else:
        assert real_edge_stats.get("status") == "failed"
        assert real_edge_stats.get("failure_reason") == "NO_REAL_EDGES"

    run_dir = tmp_path / "runs" / "graph_pipeline_test"
    assert (run_dir / "run.json").exists()
    assert (run_dir / "index.json").exists()

    index_data = json.loads((run_dir / "index.json").read_text(encoding="utf-8"))
    assert index_data.get("papers"), "Expected papers in ResultStore index"
    assert (
        any(
            entry.get("status") == "graph_analyzed"
            for entry in index_data.get("papers", {}).values()
        )
        or edges == []
    )

    validation_files = list((run_dir / "papers").glob("*/validation.json"))
    assert validation_files, "Expected validation.json persisted in ResultStore"
    validation_payload = json.loads(validation_files[0].read_text(encoding="utf-8"))
    assert "reference_validations" in validation_payload
    assert "real_citation_edges" in validation_payload
    assert "real_citation_edge_stats" in validation_payload
    assert validation_payload["real_citation_edge_stats"].get("status") in {"ok", "failed"}
    # Ensure metadata with new fields remains JSON-persistable.
    metadata_items = [
        item.get("metadata")
        for item in validation_payload.get("reference_validations", [])
        if isinstance(item, dict) and isinstance(item.get("metadata"), dict)
    ]
    assert metadata_items, "Expected persisted metadata in validation results"
    assert any("reference_targets" in meta for meta in metadata_items)

    print("Verification sources:", sources)
    print("Verified references count:", len(verified))
    if graph_report:
        print(
            "Graph nodes/edges:", graph_report["meta"]["n_nodes"], graph_report["meta"]["n_edges"]
        )
    else:
        print("Graph metrics status: failed (NO_REAL_EDGES)")
    print("Real citation edges count:", len(real_edges))
    print("Real citation edge stats:")
    print(json.dumps(real_edge_stats, ensure_ascii=False, indent=2))
    print("Edge source: real_only")
    if graph_report:
        print("Four metric groups snapshot:")
        print(json.dumps(_graph_metrics_snapshot(graph_report), ensure_ascii=False, indent=2))
        print("Warnings:")
        print(json.dumps(graph_report.get("warnings", []), ensure_ascii=False, indent=2))
    else:
        print("Four metric groups snapshot: {}")
        print("Warnings: []")

    # Visualization preview for quick inspection in integration logs.
    node_keys = sorted(
        {str(ref.get("key", "")).strip() for ref in references if str(ref.get("key", "")).strip()}
    )
    mermaid_text, mermaid_edges, mermaid_nodes = _render_mermaid(
        edges,
        node_keys,
        max_edges=80,
    )
    dot_text, dot_edges, dot_nodes = _render_dot(
        edges,
        node_keys,
        max_edges=200,
    )

    vis_dir = run_dir / "visualization"
    vis_dir.mkdir(parents=True, exist_ok=True)
    mermaid_path = vis_dir / "citation_graph_preview.mmd"
    dot_path = vis_dir / "citation_graph_preview.dot"
    html_path = vis_dir / "citation_graph_preview.html"
    mermaid_path.write_text(mermaid_text, encoding="utf-8")
    dot_path.write_text(dot_text, encoding="utf-8")
    pyvis_edges = 0
    pyvis_nodes = 0
    pyvis_error = None
    try:
        pyvis_edges, pyvis_nodes = _render_pyvis_html(
            edges,
            node_keys,
            html_path,
            max_edges=500,
            max_nodes=500,
        )
    except Exception as exc:
        pyvis_error = str(exc)

    # Also persist a stable copy under the project directory for easy access.
    project_root = Path(__file__).resolve().parents[2]
    export_root_raw = os.getenv(
        "CITATION_GRAPH_EXPORT_DIR",
        "output/test_artifacts/citation_graph",
    )
    export_root = Path(export_root_raw)
    if not export_root.is_absolute():
        export_root = project_root / export_root
    export_root.mkdir(parents=True, exist_ok=True)

    stable_mermaid_path = export_root / f"{pdf_path.stem}_citation_graph_preview.mmd"
    stable_dot_path = export_root / f"{pdf_path.stem}_citation_graph_preview.dot"
    stable_html_path = export_root / f"{pdf_path.stem}_citation_graph_preview.html"
    stable_mermaid_path.write_text(mermaid_text, encoding="utf-8")
    stable_dot_path.write_text(dot_text, encoding="utf-8")
    if pyvis_error is None and html_path.exists():
        stable_html_path.write_text(html_path.read_text(encoding="utf-8"), encoding="utf-8")

    print(f"Mermaid preview edges shown: {mermaid_edges}")
    print(f"Mermaid nodes shown: {mermaid_nodes}")
    print("Mermaid graph preview:")
    print(mermaid_text)
    print(f"DOT preview edges shown: {dot_edges}")
    print(f"DOT nodes shown: {dot_nodes}")
    print(f"Saved Mermaid: {mermaid_path}")
    print(f"Saved DOT: {dot_path}")
    if pyvis_error is None:
        print(f"PyVis preview edges shown: {pyvis_edges}")
        print(f"PyVis nodes shown: {pyvis_nodes}")
        print(f"Saved PyVis HTML: {html_path}")
        print(f"Saved stable PyVis HTML: {stable_html_path}")
    else:
        print(f"PyVis rendering skipped: {pyvis_error}")
    print(f"Saved stable Mermaid: {stable_mermaid_path}")
    print(f"Saved stable DOT: {stable_dot_path}")
