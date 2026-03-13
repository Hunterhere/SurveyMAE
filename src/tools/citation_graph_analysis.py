"""Citation graph analysis tool.

Builds structural metrics over a citation graph constructed from a survey's
reference set. Outputs a stable schema suitable for MCP and ResultStore usage.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from src.tools.result_store import ResultStore

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
TOOL_NAME = "citation_graph_analysis"


def _utc_year() -> int:
    return datetime.now(timezone.utc).year



@dataclass
class GraphAnalysisConfig:
    """Configuration for citation graph analysis."""

    topk_papers: int = 20
    topk_clusters: int = 10
    compute_betweenness: bool = False
    cocitation_edge_weight_threshold: int = 2
    recency_windows_years: list[int] = field(default_factory=lambda: [2, 5])
    core_topk_for_recency: int = 50
    compute_on_lcc_only_for_heavy_metrics: bool = True
    # Clustering algorithm: cocitation (default), louvain, spectral
    clustering_algorithm: str = "cocitation"
    # Random seed for deterministic clustering
    clustering_seed: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> "GraphAnalysisConfig":
        if not data:
            return cls()
        return cls(
            topk_papers=int(data.get("topk_papers", 20)),
            topk_clusters=int(data.get("topk_clusters", 10)),
            compute_betweenness=bool(data.get("compute_betweenness", False)),
            cocitation_edge_weight_threshold=int(data.get("cocitation_edge_weight_threshold", 2)),
            recency_windows_years=list(data.get("recency_windows_years", [2, 5])),
            core_topk_for_recency=int(data.get("core_topk_for_recency", 50)),
            compute_on_lcc_only_for_heavy_metrics=bool(
                data.get("compute_on_lcc_only_for_heavy_metrics", True)
            ),
            clustering_algorithm=str(data.get("clustering_algorithm", "cocitation")),
            clustering_seed=data.get("clustering_seed"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "topk_papers": self.topk_papers,
            "topk_clusters": self.topk_clusters,
            "compute_betweenness": self.compute_betweenness,
            "cocitation_edge_weight_threshold": self.cocitation_edge_weight_threshold,
            "recency_windows_years": self.recency_windows_years,
            "core_topk_for_recency": self.core_topk_for_recency,
            "compute_on_lcc_only_for_heavy_metrics": self.compute_on_lcc_only_for_heavy_metrics,
            "clustering_algorithm": self.clustering_algorithm,
            "clustering_seed": self.clustering_seed,
        }


class CitationGraphAnalyzer:
    """Analyze citation graphs over a reference set."""

    def __init__(self, result_store: Optional[ResultStore] = None) -> None:
        self.result_store = result_store

    def analyze(
        self,
        *,
        references: list[dict[str, Any]],
        edges: list[Any],
        canonical_map: Optional[dict[str, str]] = None,
        reference_year: Optional[int] = None,
        config: Optional[dict[str, Any]] = None,
        run_id: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> dict[str, Any]:
        cfg = GraphAnalysisConfig.from_dict(config)
        run_id = run_id or self._generate_run_id(references, edges, cfg)
        reference_year = reference_year or _utc_year()

        nodes, node_years, _ = self._build_nodes(references, canonical_map)
        node_set = set(nodes)
        parsed_edges, unresolved_ratio = self._normalize_edges(edges, node_set, canonical_map)

        out_adj, in_adj = self._build_adjacency(nodes, parsed_edges)
        in_degree, out_degree = self._degree_stats(nodes, out_adj, in_adj)

        components = self._weak_components(nodes, out_adj)
        component_sizes = sorted((len(c) for c in components), reverse=True)
        n_nodes = len(nodes)
        n_edges = sum(len(v) for v in out_adj.values())
        n_isolates = sum(1 for node in nodes if in_degree[node] == 0 and out_degree[node] == 0)
        lcc_size = component_sizes[0] if component_sizes else 0
        lcc_frac = (lcc_size / n_nodes) if n_nodes else 0.0
        density_global = (n_edges / (n_nodes * (n_nodes - 1))) if n_nodes > 1 else 0.0

        pagerank = self._pagerank(nodes, out_adj)
        betweenness = {}
        if cfg.compute_betweenness:
            betweenness = self._betweenness(
                nodes,
                out_adj,
                components,
                only_lcc=cfg.compute_on_lcc_only_for_heavy_metrics,
            )

        centrality = self._centrality_summary(
            nodes=nodes,
            in_degree=in_degree,
            out_degree=out_degree,
            pagerank=pagerank,
            betweenness=betweenness if cfg.compute_betweenness else None,
            topk=cfg.topk_papers,
        )

        # Select clustering algorithm based on config
        clustering_alg = cfg.clustering_algorithm.lower() if cfg.clustering_algorithm else "cocitation"
        if clustering_alg == "louvain":
            cocitation = self._louvain_clustering(
                nodes=nodes,
                out_adj=out_adj,
                pagerank=pagerank,
                topk_clusters=cfg.topk_clusters,
                topk_papers=cfg.topk_papers,
                seed=cfg.clustering_seed,
            )
        elif clustering_alg == "spectral":
            cocitation = self._spectral_clustering(
                nodes=nodes,
                out_adj=out_adj,
                pagerank=pagerank,
                topk_clusters=cfg.topk_clusters,
                topk_papers=cfg.topk_papers,
                seed=cfg.clustering_seed,
            )
        else:
            # Default: cocitation clustering
            cocitation = self._cocitation_clustering(
                nodes=nodes,
                out_adj=out_adj,
                pagerank=pagerank,
                threshold=cfg.cocitation_edge_weight_threshold,
                topk_clusters=cfg.topk_clusters,
                topk_papers=cfg.topk_papers,
            )

        temporal = self._temporal_metrics(
            nodes=nodes,
            node_years=node_years,
            out_adj=out_adj,
            reference_year=reference_year,
            recency_windows=cfg.recency_windows_years,
            core_topk=cfg.core_topk_for_recency,
            pagerank=pagerank,
        )

        missing_year_ratio = self._missing_year_ratio(nodes, node_years)

        summary = {
            "density_connectivity": {
                "density_global": density_global,
                "n_weak_components": len(components),
                "lcc_frac": lcc_frac,
                "n_isolates": n_isolates,
                "component_sizes": component_sizes,
            },
            "centrality": centrality,
            "cocitation_clustering": cocitation["summary"],
            "temporal": temporal["summary"],
        }

        evidence = {
            "components": self._component_evidence(components, topk=10),
            "top_papers": self._top_paper_evidence(
                in_degree=in_degree,
                pagerank=pagerank,
                betweenness=betweenness if cfg.compute_betweenness else None,
                topk=cfg.topk_papers,
            ),
            "clusters": cocitation["evidence"],
        }

        warnings = self._build_warnings(
            n_nodes=n_nodes,
            n_components=len(components),
            n_isolates=n_isolates,
            missing_year_ratio=missing_year_ratio,
            unresolved_edge_ratio=unresolved_ratio,
            temporal_summary=temporal["summary"],
            compute_betweenness=cfg.compute_betweenness,
        )

        meta = {
            "n_nodes": n_nodes,
            "n_edges": n_edges,
            "directed": True,
            "reference_year": reference_year,
            "missing_year_ratio": missing_year_ratio,
            "unresolved_edge_ratio": unresolved_ratio,
        }
        if seed is not None:
            meta["seed"] = seed

        output = {
            "schema_version": SCHEMA_VERSION,
            "tool": TOOL_NAME,
            "run_id": run_id,
            "meta": meta,
            "summary": summary,
            "evidence": evidence,
            "warnings": warnings,
            "config": cfg.to_dict(),
        }

        if self.result_store:
            self._persist_result(run_id, output, references)
        return output

    def _generate_run_id(
        self,
        references: list[dict[str, Any]],
        edges: list[Any],
        config: GraphAnalysisConfig,
    ) -> str:
        try:
            payload = {
                "refs": [ref.get("key") or ref.get("id") for ref in references],
                "edges": edges,
                "config": config.to_dict(),
            }
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
            return digest[:16]
        except Exception:
            return str(uuid.uuid4())

    def _build_nodes(
        self,
        references: list[dict[str, Any]],
        canonical_map: Optional[dict[str, str]],
    ) -> tuple[list[str], dict[str, Optional[int]], dict[str, list[str]]]:
        canonical_map = canonical_map or {}
        node_years: dict[str, Optional[int]] = {}
        node_members: dict[str, list[str]] = {}

        for ref in references:
            ref_key = str(ref.get("key") or ref.get("id") or "").strip()
            if not ref_key:
                continue
            node_id = canonical_map.get(ref_key, ref_key)
            node_members.setdefault(node_id, []).append(ref_key)
            year_raw = str(ref.get("year", "")).strip()
            year_val = int(year_raw) if year_raw.isdigit() else None
            if year_val is not None:
                current = node_years.get(node_id)
                if current is None or year_val < current:
                    node_years[node_id] = year_val
            else:
                node_years.setdefault(node_id, None)

        nodes = sorted(node_members.keys())
        for node in nodes:
            node_years.setdefault(node, None)

        return nodes, node_years, node_members

    def _normalize_edges(
        self,
        edges: list[Any],
        node_set: set[str],
        canonical_map: Optional[dict[str, str]],
    ) -> tuple[list[tuple[str, str]], float]:
        canonical_map = canonical_map or {}
        parsed_edges: list[tuple[str, str]] = []
        total = 0
        unresolved = 0

        for edge in edges:
            total += 1
            src, dst = self._edge_endpoints(edge)
            if not src or not dst:
                unresolved += 1
                continue
            src = canonical_map.get(src, src)
            dst = canonical_map.get(dst, dst)
            if src not in node_set or dst not in node_set:
                unresolved += 1
                continue
            if src == dst:
                continue
            parsed_edges.append((src, dst))

        unresolved_ratio = (unresolved / total) if total else 0.0
        return parsed_edges, unresolved_ratio

    def _edge_endpoints(self, edge: Any) -> tuple[Optional[str], Optional[str]]:
        if isinstance(edge, (tuple, list)) and len(edge) >= 2:
            return str(edge[0]).strip(), str(edge[1]).strip()
        if isinstance(edge, dict):
            for left, right in (("source", "target"), ("src", "dst"), ("from", "to")):
                if left in edge and right in edge:
                    return str(edge[left]).strip(), str(edge[right]).strip()
        return None, None

    def _build_adjacency(
        self,
        nodes: list[str],
        edges: list[tuple[str, str]],
    ) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
        out_adj = {node: set() for node in nodes}
        in_adj = {node: set() for node in nodes}
        for src, dst in edges:
            if dst in out_adj[src]:
                continue
            out_adj[src].add(dst)
            in_adj[dst].add(src)
        return out_adj, in_adj

    def _degree_stats(
        self,
        nodes: list[str],
        out_adj: dict[str, set[str]],
        in_adj: dict[str, set[str]],
    ) -> tuple[dict[str, int], dict[str, int]]:
        in_degree = {node: len(in_adj[node]) for node in nodes}
        out_degree = {node: len(out_adj[node]) for node in nodes}
        return in_degree, out_degree

    def _weak_components(
        self,
        nodes: list[str],
        out_adj: dict[str, set[str]],
    ) -> list[list[str]]:
        undirected = {node: set(neigh) for node, neigh in out_adj.items()}
        for src, targets in out_adj.items():
            for dst in targets:
                undirected[dst].add(src)

        seen = set()
        components: list[list[str]] = []
        for node in nodes:
            if node in seen:
                continue
            stack = [node]
            comp = []
            seen.add(node)
            while stack:
                current = stack.pop()
                comp.append(current)
                for neigh in undirected[current]:
                    if neigh not in seen:
                        seen.add(neigh)
                        stack.append(neigh)
            components.append(comp)
        components.sort(key=len, reverse=True)
        return components

    def _pagerank(
        self,
        nodes: list[str],
        out_adj: dict[str, set[str]],
        damping: float = 0.85,
        iterations: int = 30,
    ) -> dict[str, float]:
        n = len(nodes)
        if n == 0:
            return {}
        pr = {node: 1.0 / n for node in nodes}
        out_degree = {node: len(out_adj[node]) for node in nodes}
        in_adj = {node: set() for node in nodes}
        for src, targets in out_adj.items():
            for dst in targets:
                in_adj[dst].add(src)

        for _ in range(iterations):
            new_pr = {}
            dangling_sum = sum(pr[node] for node in nodes if out_degree[node] == 0)
            for node in nodes:
                rank = (1.0 - damping) / n
                rank += damping * (dangling_sum / n)
                for src in in_adj[node]:
                    rank += damping * (pr[src] / out_degree[src])
                new_pr[node] = rank
            pr = new_pr
        return pr

    def _betweenness(
        self,
        nodes: list[str],
        out_adj: dict[str, set[str]],
        components: list[list[str]],
        *,
        only_lcc: bool,
    ) -> dict[str, float]:
        if not nodes:
            return {}

        if only_lcc and components:
            focus = set(components[0])
        else:
            focus = set(nodes)

        betweenness = {node: 0.0 for node in nodes}
        for s in focus:
            stack = []
            pred = {v: [] for v in focus}
            sigma = {v: 0.0 for v in focus}
            dist = {v: -1 for v in focus}
            sigma[s] = 1.0
            dist[s] = 0

            queue = [s]
            while queue:
                v = queue.pop(0)
                stack.append(v)
                for w in out_adj[v]:
                    if w not in focus:
                        continue
                    if dist[w] < 0:
                        queue.append(w)
                        dist[w] = dist[v] + 1
                    if dist[w] == dist[v] + 1:
                        sigma[w] += sigma[v]
                        pred[w].append(v)

            delta = {v: 0.0 for v in focus}
            while stack:
                w = stack.pop()
                for v in pred[w]:
                    if sigma[w] > 0:
                        delta_v = (sigma[v] / sigma[w]) * (1.0 + delta[w])
                        delta[v] += delta_v
                if w != s:
                    betweenness[w] += delta[w]

        return betweenness

    def _centrality_summary(
        self,
        *,
        nodes: list[str],
        in_degree: dict[str, int],
        out_degree: dict[str, int],
        pagerank: dict[str, float],
        betweenness: Optional[dict[str, float]],
        topk: int,
    ) -> dict[str, Any]:
        metrics = {
            "in_degree": self._metric_summary(in_degree, topk),
            "out_degree": self._metric_summary(out_degree, topk),
            "pagerank": self._metric_summary(pagerank, topk),
        }
        if betweenness is not None:
            metrics["betweenness"] = self._metric_summary(betweenness, topk)

        return {"metrics": metrics}

    def _metric_summary(
        self,
        values: dict[str, float] | dict[str, int],
        topk: int,
    ) -> dict[str, Any]:
        items = list(values.items())
        scores = [float(v) for _, v in items]
        quantiles = self._quantiles(scores)
        tail_index = 0.0
        if quantiles["p50"] is not None and quantiles["p99"] is not None:
            tail_index = quantiles["p99"] / max(quantiles["p50"], 1e-9)

        top_items = sorted(items, key=lambda item: (-float(item[1]), item[0]))[:topk]
        topk_list = [{"paper_id": key, "score": float(score)} for key, score in top_items]

        return {
            "quantiles": quantiles,
            "tail_index": tail_index,
            "topk": topk_list,
        }

    def _quantiles(self, values: list[float]) -> dict[str, Optional[float]]:
        if not values:
            return {"p50": None, "p75": None, "p90": None, "p99": None, "max": None}
        values = sorted(values)
        return {
            "p50": self._percentile(values, 50),
            "p75": self._percentile(values, 75),
            "p90": self._percentile(values, 90),
            "p99": self._percentile(values, 99),
            "max": values[-1],
        }

    def _percentile(self, values: list[float], percentile: int) -> float:
        if not values:
            return 0.0
        if percentile <= 0:
            return values[0]
        if percentile >= 100:
            return values[-1]
        index = math.ceil((percentile / 100) * len(values)) - 1
        index = max(0, min(index, len(values) - 1))
        return values[index]

    def _cocitation_clustering(
        self,
        *,
        nodes: list[str],
        out_adj: dict[str, set[str]],
        pagerank: dict[str, float],
        threshold: int,
        topk_clusters: int,
        topk_papers: int,
    ) -> dict[str, Any]:
        weights: dict[tuple[str, str], int] = {}
        for src in nodes:
            cited = sorted(out_adj[src])
            for i in range(len(cited)):
                for j in range(i + 1, len(cited)):
                    left, right = cited[i], cited[j]
                    key = (left, right) if left < right else (right, left)
                    weights[key] = weights.get(key, 0) + 1

        undirected = {node: set() for node in nodes}
        for (u, v), w in weights.items():
            if w < threshold:
                continue
            undirected[u].add(v)
            undirected[v].add(u)

        clusters = self._connected_components(nodes, undirected)
        cluster_sizes = sorted((len(c) for c in clusters), reverse=True)

        cluster_evidence = []
        for cluster_id, cluster_nodes in enumerate(sorted(clusters, key=len, reverse=True)):
            if cluster_id >= topk_clusters:
                break
            top_nodes = sorted(
                [(node, pagerank.get(node, 0.0)) for node in cluster_nodes],
                key=lambda item: (-item[1], item[0]),
            )[:topk_papers]
            cluster_evidence.append(
                {
                    "cluster_id": cluster_id,
                    "size": len(cluster_nodes),
                    "top_papers": [
                        {"paper_id": node, "score": float(score)} for node, score in top_nodes
                    ],
                }
            )

        cluster_stats = {
            "max": cluster_sizes[0] if cluster_sizes else 0,
            "p90": self._percentile(cluster_sizes, 90) if cluster_sizes else 0,
            "p50": self._percentile(cluster_sizes, 50) if cluster_sizes else 0,
            "min": cluster_sizes[-1] if cluster_sizes else 0,
        }

        return {
            "summary": {
                "cocitation_edge_weight_threshold": threshold,
                "n_clusters": len(clusters),
                "clustering_method": "components",
                "cluster_size_stats": cluster_stats,
            },
            "evidence": cluster_evidence,
        }

    def _louvain_clustering(
        self,
        *,
        nodes: list[str],
        out_adj: dict[str, set[str]],
        pagerank: dict[str, float],
        topk_clusters: int,
        topk_papers: int,
        seed: Optional[int] = None,
    ) -> dict[str, Any]:
        """Louvain community detection algorithm.

        Args:
            nodes: List of node IDs.
            out_adj: Outgoing adjacency dict.
            pagerank: Pagerank scores for ranking.
            topk_clusters: Maximum number of clusters to return.
            topk_papers: Number of top papers per cluster.
            seed: Random seed for deterministic results.

        Returns:
            Dict with summary and evidence.
        """
        try:
            import networkx as nx
            from community import community_louvain
        except ImportError:
            logger.warning("networkx or python-louvain not available, falling back to cocitation")
            return self._cocitation_clustering(
                nodes=nodes,
                out_adj=out_adj,
                pagerank=pagerank,
                threshold=2,
                topk_clusters=topk_clusters,
                topk_papers=topk_papers,
            )

        # Build undirected graph for community detection
        G = nx.Graph()
        for node in nodes:
            G.add_node(node)
        for src, targets in out_adj.items():
            for dst in targets:
                if src in nodes and dst in nodes:
                    G.add_edge(src, dst)

        if G.number_of_edges() == 0:
            # No edges, each node is its own cluster
            clusters = [[n] for n in nodes]
        else:
            # Run Louvain algorithm
            partition = community_louvain.best_partition(G, random_state=seed)

            # Group nodes by community
            communities: dict[int, list[str]] = {}
            for node, comm_id in partition.items():
                communities.setdefault(comm_id, []).append(node)
            clusters = list(communities.values())

        cluster_sizes = sorted((len(c) for c in clusters), reverse=True)

        # Build cluster evidence
        cluster_evidence = []
        for cluster_id, cluster_nodes in enumerate(sorted(clusters, key=len, reverse=True)):
            if cluster_id >= topk_clusters:
                break
            top_nodes = sorted(
                [(node, pagerank.get(node, 0.0)) for node in cluster_nodes],
                key=lambda item: (-item[1], item[0]),
            )[:topk_papers]
            cluster_evidence.append(
                {
                    "cluster_id": cluster_id,
                    "size": len(cluster_nodes),
                    "top_papers": [
                        {"paper_id": node, "score": float(score)} for node, score in top_nodes
                    ],
                }
            )

        cluster_stats = {
            "max": cluster_sizes[0] if cluster_sizes else 0,
            "p90": self._percentile(cluster_sizes, 90) if cluster_sizes else 0,
            "p50": self._percentile(cluster_sizes, 50) if cluster_sizes else 0,
            "min": cluster_sizes[-1] if cluster_sizes else 0,
        }

        return {
            "summary": {
                "n_clusters": len(clusters),
                "clustering_method": "louvain",
                "cluster_size_stats": cluster_stats,
            },
            "evidence": cluster_evidence,
        }

    def _spectral_clustering(
        self,
        *,
        nodes: list[str],
        out_adj: dict[str, set[str]],
        pagerank: dict[str, float],
        topk_clusters: int,
        topk_papers: int,
        seed: Optional[int] = None,
    ) -> dict[str, Any]:
        """Spectral clustering algorithm.

        Args:
            nodes: List of node IDs.
            out_adj: Outgoing adjacency dict.
            pagerank: Pagerank scores for ranking.
            topk_clusters: Maximum number of clusters to return.
            topk_papers: Number of top papers per cluster.
            seed: Random seed for deterministic results.

        Returns:
            Dict with summary and evidence.
        """
        try:
            from sklearn.cluster import SpectralClustering
        except ImportError:
            logger.warning("sklearn not available, falling back to cocitation")
            return self._cocitation_clustering(
                nodes=nodes,
                out_adj=out_adj,
                pagerank=pagerank,
                threshold=2,
                topk_clusters=topk_clusters,
                topk_papers=topk_papers,
            )

        n_nodes = len(nodes)
        if n_nodes < 2:
            clusters = [[n] for n in nodes]
        else:
            # Build adjacency matrix
            node_idx = {node: i for i, node in enumerate(nodes)}
            import numpy as np

            # Determine number of clusters (use min of topk_clusters or n_nodes//2)
            n_clusters = min(topk_clusters, max(1, n_nodes // 2))

            # Build affinity matrix (symmetric)
            affinity = np.zeros((n_nodes, n_nodes))
            for src, targets in out_adj.items():
                if src not in node_idx:
                    continue
                i = node_idx[src]
                for dst in targets:
                    if dst not in node_idx:
                        continue
                    j = node_idx[dst]
                    affinity[i, j] = 1.0
                    affinity[j, i] = 1.0

            # If no edges, fall back to cocitation
            if affinity.sum() == 0:
                return self._cocitation_clustering(
                    nodes=nodes,
                    out_adj=out_adj,
                    pagerank=pagerank,
                    threshold=2,
                    topk_clusters=topk_clusters,
                    topk_papers=topk_papers,
                )

            try:
                clustering = SpectralClustering(
                    n_clusters=n_clusters,
                    affinity="precomputed",
                    random_state=seed,
                    assign_labels="kmeans",
                )
                labels = clustering.fit_predict(affinity)
            except Exception as e:
                logger.warning(f"Spectral clustering failed: {e}, falling back to cocitation")
                return self._cocitation_clustering(
                    nodes=nodes,
                    out_adj=out_adj,
                    pagerank=pagerank,
                    threshold=2,
                    topk_clusters=topk_clusters,
                    topk_papers=topk_papers,
                )

            # Group nodes by cluster
            communities: dict[int, list[str]] = {}
            for i, label in enumerate(labels):
                communities.setdefault(int(label), []).append(nodes[i])
            clusters = list(communities.values())

        cluster_sizes = sorted((len(c) for c in clusters), reverse=True)

        # Build cluster evidence
        cluster_evidence = []
        for cluster_id, cluster_nodes in enumerate(sorted(clusters, key=len, reverse=True)):
            if cluster_id >= topk_clusters:
                break
            top_nodes = sorted(
                [(node, pagerank.get(node, 0.0)) for node in cluster_nodes],
                key=lambda item: (-item[1], item[0]),
            )[:topk_papers]
            cluster_evidence.append(
                {
                    "cluster_id": cluster_id,
                    "size": len(cluster_nodes),
                    "top_papers": [
                        {"paper_id": node, "score": float(score)} for node, score in top_nodes
                    ],
                }
            )

        cluster_stats = {
            "max": cluster_sizes[0] if cluster_sizes else 0,
            "p90": self._percentile(cluster_sizes, 90) if cluster_sizes else 0,
            "p50": self._percentile(cluster_sizes, 50) if cluster_sizes else 0,
            "min": cluster_sizes[-1] if cluster_sizes else 0,
        }

        return {
            "summary": {
                "n_clusters": len(clusters),
                "clustering_method": "spectral",
                "cluster_size_stats": cluster_stats,
            },
            "evidence": cluster_evidence,
        }

    def _connected_components(
        self,
        nodes: list[str],
        undirected: dict[str, set[str]],
    ) -> list[list[str]]:
        seen = set()
        components: list[list[str]] = []
        for node in nodes:
            if node in seen:
                continue
            stack = [node]
            comp = []
            seen.add(node)
            while stack:
                current = stack.pop()
                comp.append(current)
                for neigh in undirected.get(current, set()):
                    if neigh not in seen:
                        seen.add(neigh)
                        stack.append(neigh)
            components.append(comp)
        components.sort(key=len, reverse=True)
        return components

    def compute_section_cluster_alignment(
        self,
        *,
        section_ref_counts: dict[str, dict[str, int]],
        references: list[dict[str, Any]],
        cluster_evidence: list[dict[str, Any]],
        canonical_map: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Compute S5: section-cluster alignment (NMI/ARI).

        This metric measures how well the section organization matches the
        citation graph clustering structure.

        Args:
            section_ref_counts: Dict mapping section titles to {ref_key: count}.
            references: List of reference dictionaries.
            cluster_evidence: Cluster information from _cocitation_clustering.
            canonical_map: Optional mapping of reference keys to canonical ids.

        Returns:
            Dict with nmi, ari, and details.
        """
        try:
            from sklearn.metrics import normalized_mutual_info_score, adjusted_rand_score
        except ImportError:
            logger.warning("sklearn not available, S5 alignment will be skipped")
            return {
                "nmi": None,
                "ari": None,
                "status": "sklearn_unavailable",
                "message": "sklearn required for NMI/ARI calculation",
            }

        # Build canonical map for references
        canonical_map = canonical_map or {}
        ref_to_canonical = {}
        for ref in references:
            ref_key = str(ref.get("key") or ref.get("id") or "").strip()
            if ref_key:
                canonical = canonical_map.get(ref_key, ref_key)
                ref_to_canonical[ref_key] = canonical

        # Determine primary section for each reference
        ref_to_section: dict[str, str] = {}
        for section_title, ref_counts in section_ref_counts.items():
            if not ref_counts:
                continue
            # Find the reference with highest count in this section
            primary_ref = max(ref_counts.items(), key=lambda x: x[1])[0]
            # Map to canonical form
            canonical_ref = ref_to_canonical.get(primary_ref, primary_ref)
            ref_to_section[canonical_ref] = section_title

        # Build cluster assignment for each reference
        ref_to_cluster: dict[str, int] = {}
        for cluster_info in cluster_evidence:
            cluster_id = cluster_info.get("cluster_id")
            for paper in cluster_info.get("top_papers", []):
                paper_id = paper.get("paper_id")
                if paper_id:
                    ref_to_cluster[paper_id] = cluster_id

        # Find common references (have both section and cluster assignments)
        common_refs = set(ref_to_section.keys()) & set(ref_to_cluster.keys())

        if len(common_refs) < 2:
            return {
                "nmi": None,
                "ari": None,
                "status": "insufficient_data",
                "message": f"Only {len(common_refs)} common references, need at least 2",
                "common_ref_count": len(common_refs),
            }

        # Build aligned label arrays
        section_labels = []
        cluster_labels = []
        for ref in sorted(common_refs):
            section_labels.append(ref_to_section.get(ref, "unknown"))
            cluster_labels.append(ref_to_cluster.get(ref, -1))

        try:
            nmi = normalized_mutual_info_score(section_labels, cluster_labels)
            ari = adjusted_rand_score(section_labels, cluster_labels)
        except Exception as e:
            logger.warning(f"Failed to compute NMI/ARI: {e}")
            return {
                "nmi": None,
                "ari": None,
                "status": "computation_error",
                "message": str(e),
            }

        # Build detailed breakdown
        section_clusters: dict[str, set[int]] = {}
        for ref in sorted(common_refs):
            section = ref_to_section.get(ref, "unknown")
            cluster = ref_to_cluster.get(ref, -1)
            if section not in section_clusters:
                section_clusters[section] = set()
            section_clusters[section].add(cluster)

        return {
            "nmi": float(nmi),
            "ari": float(ari),
            "status": "success",
            "common_ref_count": len(common_refs),
            "section_clusters": {
                section: list(clusters) for section, clusters in section_clusters.items()
            },
        }

    def _temporal_metrics(
        self,
        *,
        nodes: list[str],
        node_years: dict[str, Optional[int]],
        out_adj: dict[str, set[str]],
        reference_year: int,
        recency_windows: Iterable[int],
        core_topk: int,
        pagerank: dict[str, float],
    ) -> dict[str, Any]:
        known_years = [year for year in node_years.values() if year is not None]
        missing_ratio = self._missing_year_ratio(nodes, node_years)

        if missing_ratio > 0.30:
            summary = {
                "recency": {"median_age": None, "ratio_last_2y": None, "ratio_last_5y": None},
                "citation_lag": {"p50": None, "p90": None, "neg_ratio": None},
                "core_recency": {
                    "top50_ratio_last_2y": None,
                    "top50_ratio_last_5y": None,
                },
                "year_hist": {"bins": [], "counts": []},
            }
            return {"summary": summary, "degraded": True}

        ages = [reference_year - year for year in known_years if year is not None]
        ages_sorted = sorted(ages)
        median_age = self._percentile(ages_sorted, 50) if ages_sorted else None

        recency_windows = sorted(set(recency_windows) | {2, 5})
        ratios = {}
        for window in recency_windows:
            if known_years:
                threshold_year = reference_year - window + 1
                count = sum(1 for year in known_years if year >= threshold_year)
                ratios[window] = count / len(known_years)
            else:
                ratios[window] = None

        citation_lags = []
        neg_count = 0
        for src, targets in out_adj.items():
            src_year = node_years.get(src)
            if src_year is None:
                continue
            for dst in targets:
                dst_year = node_years.get(dst)
                if dst_year is None:
                    continue
                lag = src_year - dst_year
                citation_lags.append(lag)
                if lag < 0:
                    neg_count += 1

        citation_lags_sorted = sorted(citation_lags)
        lag_p50 = self._percentile(citation_lags_sorted, 50) if citation_lags_sorted else None
        lag_p90 = self._percentile(citation_lags_sorted, 90) if citation_lags_sorted else None
        neg_ratio = (neg_count / len(citation_lags_sorted)) if citation_lags_sorted else None

        core_nodes = sorted(pagerank.items(), key=lambda item: (-item[1], item[0]))[
            : min(core_topk, len(pagerank))
        ]
        core_years = [node_years.get(node) for node, _ in core_nodes]
        core_years = [year for year in core_years if year is not None]

        def _core_ratio(window: int) -> Optional[float]:
            if not core_years:
                return None
            threshold = reference_year - window + 1
            count = sum(1 for year in core_years if year >= threshold)
            return count / len(core_years)

        if known_years:
            bins = sorted(set(known_years))
            counts = [known_years.count(year) for year in bins]
            year_hist = {"bins": bins, "counts": counts}
        else:
            year_hist = {"bins": [], "counts": []}

        summary = {
            "recency": {
                "median_age": median_age,
                "ratio_last_2y": ratios.get(2),
                "ratio_last_5y": ratios.get(5),
            },
            "citation_lag": {"p50": lag_p50, "p90": lag_p90, "neg_ratio": neg_ratio},
            "core_recency": {
                "top50_ratio_last_2y": _core_ratio(2),
                "top50_ratio_last_5y": _core_ratio(5),
            },
            "year_hist": year_hist,
        }
        return {"summary": summary, "degraded": False}

    def _missing_year_ratio(self, nodes: list[str], node_years: dict[str, Optional[int]]) -> float:
        if not nodes:
            return 0.0
        missing = sum(1 for node in nodes if node_years.get(node) is None)
        return missing / len(nodes)

    def _component_evidence(self, components: list[list[str]], topk: int) -> list[dict[str, Any]]:
        evidence = []
        for idx, comp in enumerate(components[:topk]):
            sample = sorted(comp)[:10]
            entry = {"component_id": idx, "size": len(comp)}
            if sample:
                entry["paper_ids_sample"] = sample
            evidence.append(entry)
        return evidence

    def _top_paper_evidence(
        self,
        *,
        in_degree: dict[str, int],
        pagerank: dict[str, float],
        betweenness: Optional[dict[str, float]],
        topk: int,
    ) -> dict[str, Any]:
        evidence = {
            "by_pagerank": self._topk_list(pagerank, topk),
            "by_in_degree": self._topk_list(in_degree, topk),
        }
        if betweenness is not None:
            evidence["by_betweenness"] = self._topk_list(betweenness, topk)
        return evidence

    def _topk_list(self, values: dict[str, float] | dict[str, int], topk: int) -> list[dict]:
        items = sorted(values.items(), key=lambda item: (-float(item[1]), item[0]))[:topk]
        return [{"paper_id": key, "score": float(score)} for key, score in items]

    def _build_warnings(
        self,
        *,
        n_nodes: int,
        n_components: int,
        n_isolates: int,
        missing_year_ratio: float,
        unresolved_edge_ratio: float,
        temporal_summary: dict[str, Any],
        compute_betweenness: bool,
    ) -> list[dict[str, Any]]:
        warnings = []

        def _add(code: str, severity: str, message: str, stats: Optional[dict[str, Any]] = None):
            entry = {"code": code, "severity": severity, "message": message}
            if stats:
                entry["stats"] = stats
            warnings.append(entry)

        if missing_year_ratio > 0.30:
            _add(
                "YEAR_MISSING_HIGH",
                "warning",
                "Missing year ratio exceeds 0.30; temporal metrics degraded.",
                {"missing_year_ratio": missing_year_ratio},
            )

        if unresolved_edge_ratio > 0.30:
            _add(
                "EDGE_UNRESOLVED_HIGH",
                "warning",
                "Unresolved edge ratio exceeds 0.30.",
                {"unresolved_edge_ratio": unresolved_edge_ratio},
            )

        neg_ratio = temporal_summary.get("citation_lag", {}).get("neg_ratio")
        if neg_ratio is not None and neg_ratio > 0.05:
            _add(
                "NEGATIVE_CITATION_LAG_HIGH",
                "warning",
                "Negative citation lag ratio exceeds 0.05.",
                {"neg_ratio": neg_ratio},
            )

        if n_nodes:
            if n_components > max(10, int(0.05 * n_nodes)):
                _add(
                    "MANY_COMPONENTS",
                    "info",
                    "Weak components exceed heuristic threshold.",
                    {"n_weak_components": n_components},
                )

            if (n_isolates / n_nodes) > 0.05:
                _add(
                    "ISOLATES_HIGH",
                    "info",
                    "Isolates exceed 5% of nodes.",
                    {"n_isolates": n_isolates},
                )

        if (
            temporal_summary.get("recency", {}).get("median_age") is None
            and missing_year_ratio > 0.30
        ):
            _add(
                "TEMPORAL_METRICS_DEGRADED",
                "info",
                "Temporal metrics degraded due to missing year metadata.",
            )

        if not compute_betweenness:
            _add(
                "BETWEENNESS_SKIPPED",
                "info",
                "Betweenness centrality was not computed (compute_betweenness=false).",
            )

        return warnings

    def _persist_result(
        self,
        run_id: str,
        output: dict[str, Any],
        references: list[dict[str, Any]],
    ) -> None:
        try:
            if not self.result_store:
                return
            source_path = self._guess_source_path(references)
            if not source_path:
                logger.warning("ResultStore persistence skipped: missing source path.")
                return
            paper_id = self.result_store.register_paper(source_path)
            analysis_payload = self._merge_existing_analysis(paper_id, output)
            self.result_store.save_analysis(paper_id, analysis_payload)
            self.result_store.update_index(
                paper_id, status="graph_analyzed", source_path=source_path
            )
        except Exception as exc:
            logger.warning("Failed to persist citation graph analysis: %s", exc)

    def _guess_source_path(self, references: list[dict[str, Any]]) -> Optional[str]:
        for ref in references:
            path = ref.get("source_path")
            if path:
                return str(path)
        return None

    def _merge_existing_analysis(self, paper_id: str, output: dict[str, Any]) -> dict[str, Any]:
        if not self.result_store:
            return {"citation_graph_analysis": output}
        analysis_path = self.result_store._paper_dir(paper_id) / "analysis.json"
        if analysis_path.exists():
            try:
                data = json.loads(analysis_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        else:
            data = {}
        data["citation_graph_analysis"] = output
        return data


def create_citation_graph_analysis_mcp_server():
    """Create an MCP server for citation graph analysis."""
    from mcp.server import Server
    from mcp.types import Tool, TextContent

    app = Server("citation-graph-analysis")
    analyzer = CitationGraphAnalyzer()

    @app.list_tools()
    async def list_tools():
        return [
            Tool(
                name="citation_graph_analysis",
                description="Analyze citation graph structure from references and edges",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "references": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Reference list entries",
                        },
                        "edges": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Citation edges (source->target) within the set",
                        },
                        "canonical_map": {
                            "type": "object",
                            "description": "Optional mapping of reference keys to canonical ids",
                        },
                        "reference_year": {
                            "type": "integer",
                            "description": "Reference year for recency metrics",
                        },
                        "config": {
                            "type": "object",
                            "description": "Tool configuration overrides",
                        },
                        "run_id": {
                            "type": "string",
                            "description": "Optional run id",
                        },
                        "seed": {
                            "type": "integer",
                            "description": "Optional random seed identifier",
                        },
                    },
                    "required": ["references", "edges"],
                },
            )
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict):
        if name != "citation_graph_analysis":
            return [TextContent(type="text", text=f"Unknown tool: {name}", isError=True)]
        try:
            result = analyzer.analyze(
                references=arguments["references"],
                edges=arguments["edges"],
                canonical_map=arguments.get("canonical_map"),
                reference_year=arguments.get("reference_year"),
                config=arguments.get("config"),
                run_id=arguments.get("run_id"),
                seed=arguments.get("seed"),
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
        except Exception as exc:
            return [TextContent(type="text", text=str(exc), isError=True)]

    return app
