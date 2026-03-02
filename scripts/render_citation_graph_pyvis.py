"""Render citation graph artifacts to interactive HTML via PyVis.

Example:
    uv run python scripts/render_citation_graph_pyvis.py \
      --validation output/runs/<run_id>/papers/<paper_id>/validation.json \
      --extraction output/runs/<run_id>/papers/<paper_id>/extraction.json \
      --output output/test_artifacts/citation_graph/citation_graph_pyvis.html
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

_CLUSTER_PALETTE = [
    "#60a5fa",  # blue
    "#f59e0b",  # amber
    "#34d399",  # emerald
    "#f472b6",  # pink
    "#a78bfa",  # violet
    "#22d3ee",  # cyan
    "#fb7185",  # rose
    "#facc15",  # yellow
    "#2dd4bf",  # teal
    "#c084fc",  # purple
]
_AUTHORITY_CENTER_MIN_IN_DEG = 5
_AUTHORITY_CENTER_K_MIN = 3
_AUTHORITY_CENTER_K_MAX = 18
_AUTHORITY_CENTER_MAX_HOPS = 3
_AUTHORITY_CENTER_ALPHA = 0.80
# TODO(authority-center-v2): Evaluate hybrid center selection (Scheme 4).
# - Goal:
#   Combine count-based authority (in-degree) and quality-based authority (PageRank)
#   before applying elbow, to improve robustness across different citation graphs.
# - Why (expected advantages):
#   1) More robust than single-metric elbow when degree curve has weak/no clear knee.
#   2) Can retain nodes with moderate in-degree but high "influence quality" via PageRank.
#   3) Better cross-dataset stability by using percentile thresholds.
# - Tradeoffs (known disadvantages):
#   1) More hyperparameters (percentile thresholds + k range).
#   2) Slightly higher compute cost than pure in-degree elbow.
#   3) Harder to explain than a single knee rule.
# - Proposed computation:
#   1) Compute in-degree and PageRank for all non-isolated nodes.
#   2) Build candidate set by OR rule:
#      in_degree >= Q_in_degree (e.g., P95) OR pagerank >= Q_pagerank (e.g., P90).
#   3) Rank candidates by (in_degree, pagerank) descending.
#   4) Apply elbow on ranked in-degree sequence of candidates to derive center_count.
#   5) Clamp center_count to [k_min, k_max], then continue current assignment flow.
_CLUSTER_SEPARATION_RADIUS = 1600.0
_CLUSTER_MEMBER_SPREAD = 180.0
_INTRA_EDGE_LENGTH = 80
_INTER_EDGE_LENGTH = 700
_ANCHOR_EDGE_LENGTH = 60
_GLOBAL_ANCHOR_ID = "__global_anchor"
_GLOBAL_ANCHOR_EDGE_LENGTH = 980
_ISOLATE_INITIAL_RADIUS = 860.0
_ISOLATE_INITIAL_SPREAD = 180.0


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _discover_extraction(validation_path: Path) -> Path | None:
    candidate = validation_path.with_name("extraction.json")
    return candidate if candidate.exists() else None


def _normalize_edges(payload: dict[str, Any], edge_limit: int | None) -> list[tuple[str, str]]:
    raw_edges = payload.get("real_citation_edges")
    if not isinstance(raw_edges, list):
        raw_edges = payload.get("edges", [])

    edges: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_edges:
        if not isinstance(item, dict):
            continue
        src = str(item.get("source", "")).strip()
        dst = str(item.get("target", "")).strip()
        if not src or not dst:
            continue
        key = (src, dst)
        if key in seen:
            continue
        seen.add(key)
        edges.append(key)
        if edge_limit is not None and len(edges) >= edge_limit:
            break
    return edges


def _collect_nodes(
    validation_payload: dict[str, Any],
    extraction_payload: dict[str, Any] | None,
    edges: list[tuple[str, str]],
    node_limit: int | None,
) -> list[str]:
    nodes: set[str] = set()

    reference_validations = validation_payload.get("reference_validations", [])
    if isinstance(reference_validations, list):
        for item in reference_validations:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", "")).strip()
            if key:
                nodes.add(key)

    if extraction_payload:
        references = extraction_payload.get("references", [])
        if isinstance(references, list):
            for ref in references:
                if not isinstance(ref, dict):
                    continue
                key = str(ref.get("key", "")).strip()
                if key:
                    nodes.add(key)

    for src, dst in edges:
        nodes.add(src)
        nodes.add(dst)

    ordered = sorted(nodes)
    if node_limit is not None:
        ordered = ordered[:node_limit]
    return ordered


def _build_degree_maps(nodes: list[str], edges: list[tuple[str, str]]) -> tuple[dict[str, int], dict[str, int]]:
    in_degree = {node: 0 for node in nodes}
    out_degree = {node: 0 for node in nodes}
    node_set = set(nodes)
    for src, dst in edges:
        if src in node_set:
            out_degree[src] += 1
        if dst in node_set:
            in_degree[dst] += 1
    return in_degree, out_degree


def _renumber_clusters(cluster_map: dict[str, int]) -> dict[str, int]:
    remap: dict[int, int] = {}
    next_id = 0
    normalized: dict[str, int] = {}
    for node, cid in cluster_map.items():
        mapped = remap.get(cid)
        if mapped is None:
            mapped = next_id
            remap[cid] = mapped
            next_id += 1
        normalized[node] = mapped
    return normalized


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
        # Distance from point to line through (x1,y1)->(x2,y2)
        dist = abs((y2 - y1) * xi - (x2 - x1) * yi + x2 * y1 - y2 * x1) / den
        if dist > best_dist:
            best_dist = dist
            best_idx = i

    k = best_idx + 1
    return max(1, min(m, max(k_min, k)))


def _compute_communities(nodes: list[str], edges: list[tuple[str, str]]) -> tuple[dict[str, int], dict[str, Any]]:
    """Cluster by authority centers on directed citation graph."""
    try:
        import networkx as nx
    except Exception:
        return {}, {"algorithm": "none"}

    g = nx.DiGraph()
    g.add_nodes_from(nodes)
    g.add_edges_from(edges)
    if g.number_of_nodes() == 0:
        return {}, {"algorithm": "none"}

    in_degree = {node: int(g.in_degree(node)) for node in g.nodes}
    out_degree = {node: int(g.out_degree(node)) for node in g.nodes}
    non_isolates = {node for node in g.nodes if in_degree[node] > 0 or out_degree[node] > 0}
    if not non_isolates:
        return {}, {"algorithm": "authority_center", "centers": []}

    try:
        pagerank = nx.pagerank(g, alpha=_AUTHORITY_CENTER_ALPHA)
    except Exception:
        pagerank = {node: 0.0 for node in g.nodes}

    candidates = [
        node
        for node in non_isolates
        if in_degree[node] >= _AUTHORITY_CENTER_MIN_IN_DEG
    ]
    if not candidates:
        candidates = list(non_isolates)
    candidates.sort(key=lambda n: (in_degree[n], pagerank.get(n, 0.0)), reverse=True)

    # TODO(authority-center-v2):
    # Replace this pure in-degree prefilter with hybrid candidate construction:
    # candidate = (in-degree above percentile threshold) OR (PageRank above percentile threshold).
    # Keep elbow here for adaptive center count, then compare:
    # - cluster purity / conductance
    # - center stability across reruns and datasets
    # - interpretability of chosen centers
    candidate_degrees = [in_degree[n] for n in candidates]
    center_count = _elbow_center_count(
        candidate_degrees,
        k_min=_AUTHORITY_CENTER_K_MIN,
        k_max=_AUTHORITY_CENTER_K_MAX,
    )
    centers = candidates[: max(1, center_count)]
    center_rank = {center: idx for idx, center in enumerate(centers)}

    # Distances to centers in original direction: node -> ... -> center.
    reverse_g = g.reverse(copy=False)
    dist_to_center: dict[str, dict[str, int]] = {}
    for center in centers:
        lengths = nx.single_source_shortest_path_length(
            reverse_g,
            center,
            cutoff=_AUTHORITY_CENTER_MAX_HOPS,
        )
        for node, dist in lengths.items():
            if node not in non_isolates:
                continue
            prev = dist_to_center.setdefault(node, {})
            prev[center] = min(prev.get(center, dist), dist)

    cluster_map: dict[str, int] = {}
    for center, cid in center_rank.items():
        cluster_map[center] = cid

    for node in non_isolates:
        if node in cluster_map:
            continue
        options = dist_to_center.get(node, {})
        if not options:
            continue
        best_center = min(
            options.items(),
            key=lambda item: (item[1], center_rank[item[0]]),
        )[0]
        cluster_map[node] = center_rank[best_center]

    # Expand assignment from already clustered neighbors to avoid large unclustered tail.
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
            best_cid = max(votes.items(), key=lambda item: (item[1], -item[0]))[0]
            cluster_map[node] = best_cid
            changed = True
        if not changed:
            break

    normalized = _renumber_clusters(cluster_map)
    center_stats = [
        {
            "node": center,
            "cluster_id": normalized.get(center),
            "in_degree": in_degree.get(center, 0),
            "out_degree": out_degree.get(center, 0),
            "pagerank": round(float(pagerank.get(center, 0.0)), 6),
        }
        for center in centers
    ]
    return normalized, {
        "algorithm": "authority_center",
        "directed": True,
        "center_selection": "elbow",
        "k_min": _AUTHORITY_CENTER_K_MIN,
        "k_max": _AUTHORITY_CENTER_K_MAX,
        "center_count": len(centers),
        "min_in_degree": _AUTHORITY_CENTER_MIN_IN_DEG,
        "max_hops": _AUTHORITY_CENTER_MAX_HOPS,
        "pagerank_alpha": _AUTHORITY_CENTER_ALPHA,
        "centers": center_stats,
    }


def _node_color(in_deg: int, out_deg: int, cluster_id: int | None) -> str:
    if in_deg == 0 and out_deg == 0:
        return "#9ca3af"  # isolated
    if cluster_id is not None:
        return _CLUSTER_PALETTE[cluster_id % len(_CLUSTER_PALETTE)]
    return "#60a5fa"


def _node_size(in_deg: int, out_deg: int) -> float:
    """Slow-growth node size scaling, avoids giant hubs and tiny tails."""
    score = 2.2 * in_deg + 1.0 * out_deg
    size = 10.0 + 5.2 * math.log1p(score) #TODO: Tune these constants for better visual spread on typical citation graphs. Goal is to keep most nodes in 8-40 size range, with good differentiation for hubs vs non-hubs.
    return max(8.0, min(40.0, size))


def _stable_pair(name: str) -> tuple[float, float]:
    digest = hashlib.blake2b(name.encode("utf-8"), digest_size=8).digest()
    a = int.from_bytes(digest[:4], "big") / 2**32
    b = int.from_bytes(digest[4:], "big") / 2**32
    return a, b


def _node_xy(node: str, cluster_id: int | None, rank: dict[int, int], n_clusters: int) -> tuple[float, float]:
    a, b = _stable_pair(node)
    if cluster_id is None or n_clusters <= 0:
        theta = 2.0 * math.pi * b
        r = _ISOLATE_INITIAL_RADIUS + _ISOLATE_INITIAL_SPREAD * math.sqrt(a)
        return r * math.cos(theta), r * math.sin(theta)

    idx = rank.get(cluster_id, 0)
    base_theta = 2.0 * math.pi * idx / max(1, n_clusters)
    cx = _CLUSTER_SEPARATION_RADIUS * math.cos(base_theta)
    cy = _CLUSTER_SEPARATION_RADIUS * math.sin(base_theta)
    local_theta = 2.0 * math.pi * b
    local_r = _CLUSTER_MEMBER_SPREAD * math.sqrt(a)
    return cx + local_r * math.cos(local_theta), cy + local_r * math.sin(local_theta)


def render_pyvis(
    *,
    validation_path: Path,
    extraction_path: Path | None,
    output_path: Path,
    edge_limit: int | None,
    node_limit: int | None,
    notebook: bool,
) -> None:
    try:
        from pyvis.network import Network
    except Exception as exc:  # pragma: no cover - runtime dependency guard
        raise RuntimeError(
            "pyvis is not installed. Install with: `uv add pyvis`"
        ) from exc

    validation_payload = _load_json(validation_path)
    extraction_payload = _load_json(extraction_path) if extraction_path and extraction_path.exists() else None

    edges = _normalize_edges(validation_payload, edge_limit=edge_limit)
    nodes = _collect_nodes(
        validation_payload,
        extraction_payload,
        edges,
        node_limit=node_limit,
    )
    in_degree, out_degree = _build_degree_maps(nodes, edges)
    cluster_map, cluster_meta = _compute_communities(nodes, edges)
    node_set = set(nodes)
    cluster_ids = sorted(set(cluster_map.values()))
    cluster_rank = {cid: i for i, cid in enumerate(cluster_ids)}

    net = Network(
        height="900px",
        width="100%",
        bgcolor="#0b1020",
        font_color="#e5e7eb",
        directed=True,
        notebook=notebook,
        cdn_resources="remote",
    )
    net.barnes_hut(
        gravity=-32000,
        central_gravity=0.12,
        spring_length=240,
        spring_strength=0.008,
    )
    net.add_node(
        _GLOBAL_ANCHOR_ID,
        label="",
        title="",
        color="#00000000",
        size=1,
        x=0.0,
        y=0.0,
        physics=False,
        fixed=True,
    )

    isolate_nodes: list[str] = []

    for node in nodes:
        indeg = in_degree.get(node, 0)
        outdeg = out_degree.get(node, 0)
        if indeg == 0 and outdeg == 0:
            isolate_nodes.append(node)
        cluster_id = cluster_map.get(node)
        x, y = _node_xy(node, cluster_id, cluster_rank, len(cluster_ids))
        title = f"{node}<br>in={indeg}, out={outdeg}"
        if cluster_id is not None:
            title += f"<br>cluster={cluster_id}"
        size = _node_size(indeg, outdeg)
        net.add_node(
            node,
            label=node,
            title=title,
            color=_node_color(indeg, outdeg, cluster_id),
            size=size,
            x=x,
            y=y,
        )

    # Add fixed anchors to keep clusters separated in large dense graphs.
    for cid, idx in cluster_rank.items():
        theta = 2.0 * math.pi * idx / max(1, len(cluster_ids))
        ax = _CLUSTER_SEPARATION_RADIUS * math.cos(theta)
        ay = _CLUSTER_SEPARATION_RADIUS * math.sin(theta)
        anchor_id = f"__cluster_anchor_{cid}"
        net.add_node(
            anchor_id,
            label="",
            title="",
            color="#00000000",
            size=1,
            x=ax,
            y=ay,
            physics=False,
            fixed=True,
        )

    for node, cid in cluster_map.items():
        if node not in node_set:
            continue
        net.add_edge(
            node,
            f"__cluster_anchor_{cid}",
            color="#00000000",
            width=0.1,
            arrows="",
            length=_ANCHOR_EDGE_LENGTH,
            physics=True,
        )

    # Weak global anchor for isolated nodes: keeps them from drifting away while still movable.
    for node in isolate_nodes:
        net.add_edge(
            node,
            _GLOBAL_ANCHOR_ID,
            color="#00000000",
            width=0.1,
            arrows="",
            length=_GLOBAL_ANCHOR_EDGE_LENGTH,
            physics=True,
        )

    for src, dst in edges:
        if src not in node_set or dst not in node_set:
            continue
        src_cluster = cluster_map.get(src)
        dst_cluster = cluster_map.get(dst)
        is_intra = src_cluster is not None and src_cluster == dst_cluster
        edge_color = (
            f"{_CLUSTER_PALETTE[src_cluster % len(_CLUSTER_PALETTE)]}66"
            if src_cluster is not None
            else "#94a3b866"
        )
        net.add_edge(
            src,
            dst,
            color=edge_color if is_intra else "#94a3b844",
            width=1.15 if is_intra else 0.6,
            length=_INTRA_EDGE_LENGTH if is_intra else _INTER_EDGE_LENGTH,
        )

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
              "gravitationalConstant": -52000,
              "centralGravity": 0.02,
              "springLength": 320,
              "springConstant": 0.0035,
              "damping": 0.95,
              "avoidOverlap": 1.0
            },
            "stabilization": {"enabled": true, "iterations": 2200, "fit": true},
            "minVelocity": 0.15
          }
        }
        """
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    net.write_html(str(output_path), local=False, notebook=notebook, open_browser=False)

    print(f"Saved HTML: {output_path}")
    print(f"Nodes: {len(nodes)}")
    print(f"Edges: {len(edges)}")
    algo = cluster_meta.get("algorithm", "unknown")
    if algo == "authority_center":
        print(
            "Community algo: authority_center "
            f"(directed=True, selection={cluster_meta.get('center_selection')}, "
            f"center_count={cluster_meta.get('center_count')}, "
            f"min_in_degree={cluster_meta.get('min_in_degree')}, max_hops={cluster_meta.get('max_hops')})"
        )
        print("Authority centers:")
        print(
            json.dumps(
                cluster_meta.get("centers", []),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"Community algo: {algo}")
    print(f"Clusters detected: {len(set(cluster_map.values())) if cluster_map else 0}")
    print("Legend: gray=isolated, others=community colors; node size=log-scaled degree")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render citation graph to interactive PyVis HTML.")
    parser.add_argument(
        "--validation",
        type=Path,
        required=True,
        help="Path to validation.json (expects real_citation_edges).",
    )
    parser.add_argument(
        "--extraction",
        type=Path,
        default=None,
        help="Optional extraction.json (for complete node list).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/test_artifacts/citation_graph/citation_graph_pyvis.html"),
        help="Output HTML path.",
    )
    parser.add_argument(
        "--edge-limit",
        type=int,
        default=None,
        help="Optional max number of edges to render.",
    )
    parser.add_argument(
        "--node-limit",
        type=int,
        default=None,
        help="Optional max number of nodes to render.",
    )
    parser.add_argument(
        "--notebook",
        action="store_true",
        help="Enable notebook mode for PyVis.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    validation_path: Path = args.validation
    if not validation_path.exists():
        raise FileNotFoundError(f"validation file not found: {validation_path}")

    extraction_path: Path | None = args.extraction
    if extraction_path is None:
        extraction_path = _discover_extraction(validation_path)

    render_pyvis(
        validation_path=validation_path,
        extraction_path=extraction_path,
        output_path=args.output,
        edge_limit=args.edge_limit,
        node_limit=args.node_limit,
        notebook=args.notebook,
    )


if __name__ == "__main__":
    main()
