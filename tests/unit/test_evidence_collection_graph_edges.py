from types import SimpleNamespace

import pytest

from src.graph.nodes import evidence_collection as ec


class _FakeResultStore:
    def register_paper(self, _source_pdf: str) -> str:
        return "paper_test"

    def save_c6_alignment(self, _paper_id: str, _data: dict) -> None:
        return None

    def save_trend_baseline(self, _paper_id: str, _data: dict) -> None:
        return None

    def save_key_papers(self, _paper_id: str, _data: dict) -> None:
        return None

    def save_citation_analysis(self, _paper_id: str, _data: dict) -> None:
        return None


class _FakeCitationChecker:
    def __init__(self, result_store=None):
        self.result_store = result_store

    async def extract_citations_with_context_from_pdf_async(
        self,
        pdf_path: str,
        verify_references: bool = False,
        sources=None,
        verify_limit=None,
    ) -> dict:
        assert pdf_path
        assert verify_references is True
        assert sources is not None
        assert verify_limit is not None
        return {
            "citations": [{"ref_key": "ref_1", "section_title": "Intro"}],
            "references": [
                {"key": "ref_1", "title": "Paper A", "year": "2021", "validation": {"is_valid": True}},
                {"key": "ref_2", "title": "Paper B", "year": "2022", "validation": {"is_valid": True}},
            ],
            "real_citation_edges": [{"source": "ref_1", "target": "ref_2"}],
        }


class _FakeKeywordExtractor:
    async def extract_keywords(self, **_kwargs):
        return SimpleNamespace(keywords=["rag"])


class _FakeLiteratureSearch:
    def search_field_trend(self, _kw: str, year_range=None):
        assert year_range is not None
        return {"yearly_counts": {"2024": 3}}

    async def search_top_cited(self, _kw: str, top_k=30):
        assert top_k > 0
        return []


class _FakeCitationAnalyzer:
    def compute_temporal_metrics(self, _refs, field_trend_baseline=None):
        assert field_trend_baseline is not None
        return {
            "T1_year_span": 3,
            "T2_foundational_retrieval_gap": 1,
            "T3_peak_year_ratio": 0.4,
            "T4_temporal_continuity": 1,
            "T5_trend_alignment": 0.8,
            "year_distribution": {"2021": 1, "2022": 1},
            "S1_section_count": 1,
        }

    def compute_structural_metrics(self, _section_ref_counts, total_paragraphs=1):
        assert total_paragraphs >= 0
        return {
            "S2_citation_density": 1.0,
            "S3_citation_gini": 0.2,
            "S4_zero_citation_section_rate": 0.0,
        }


class _FakeGraphAnalyzer:
    last_edges = None

    def __init__(self, result_store=None):
        self.result_store = result_store

    def analyze(self, references, edges, config=None):
        _FakeGraphAnalyzer.last_edges = edges
        assert references
        assert config is not None
        return {
            "meta": {"n_nodes": 2, "n_edges": 1, "unresolved_edge_ratio": 0.0},
            "summary": {
                "density_connectivity": {
                    "density_global": 0.5,
                    "n_weak_components": 1,
                    "lcc_frac": 1.0,
                    "n_isolates": 0,
                },
                "cocitation_clustering": {"n_clusters": 1},
            },
            "evidence": {"clusters": []},
        }

    def compute_section_cluster_alignment(self, section_ref_counts, references, cluster_evidence):
        assert isinstance(section_ref_counts, dict)
        assert isinstance(references, list)
        assert isinstance(cluster_evidence, list)
        return {"nmi": 0.9, "ari": 0.8}


class _FakeFoundationalCoverageAnalyzer:
    async def analyze(self, **_kwargs):
        return SimpleNamespace(
            coverage_rate=0.6,
            missing_key_papers=[],
            suspicious_centrality=[],
        )


@pytest.mark.asyncio
async def test_run_evidence_collection_prefers_extraction_real_edges(monkeypatch):
    monkeypatch.setattr(ec, "CitationChecker", _FakeCitationChecker)
    monkeypatch.setattr(ec, "KeywordExtractor", _FakeKeywordExtractor)
    monkeypatch.setattr(ec, "LiteratureSearch", _FakeLiteratureSearch)
    monkeypatch.setattr(ec, "CitationAnalyzer", _FakeCitationAnalyzer)
    monkeypatch.setattr(ec, "CitationGraphAnalyzer", _FakeGraphAnalyzer)
    monkeypatch.setattr(ec, "FoundationalCoverageAnalyzer", _FakeFoundationalCoverageAnalyzer)

    async def _fake_c6(_extraction, _references):
        return {
            "total_pairs": 1,
            "support": 1,
            "contradict": 0,
            "insufficient": 0,
            "contradiction_rate": 0.0,
            "auto_fail": False,
            "contradictions": [],
        }

    monkeypatch.setattr(ec, "_collect_c6_citation_alignment", _fake_c6)

    state = {
        "parsed_content": "dummy parsed content",
        "source_pdf_path": "dummy.pdf",
        "section_headings": ["Intro"],
    }

    updates = await ec.run_evidence_collection(state, result_store=_FakeResultStore())

    assert updates["tool_evidence"]["graph_analysis"]["G1_density"] == 0.5
    assert _FakeGraphAnalyzer.last_edges == [{"source": "ref_1", "target": "ref_2"}]
