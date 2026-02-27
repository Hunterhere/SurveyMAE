import json
import os
from pathlib import Path

import httpx
import pytest

from src.core.config import SurveyMAEConfig
from src.tools.citation_checker import CitationChecker
from src.tools.citation_analysis import CitationAnalyzer
from src.tools.result_store import ResultStore


def _grobid_is_available(url: str) -> bool:
    try:
        response = httpx.get(f"{url.rstrip('/')}/api/isalive", timeout=2)
        return response.status_code == 200
    except Exception:
        return False


def _build_config(backend: str, grobid_url: str) -> SurveyMAEConfig:
    cfg = SurveyMAEConfig()
    cfg.citation.backend = backend
    cfg.citation.grobid_url = grobid_url
    cfg.citation.grobid_timeout_s = int(os.getenv("GROBID_TIMEOUT_S", "30"))
    cfg.citation.grobid_consolidate = False
    return cfg


def _sample_citations(citations: list[dict], limit: int = 3) -> list[dict]:
    samples = []
    for item in citations[:limit]:
        sentence = item.get("sentence") or ""
        preview = sentence if len(sentence) <= 240 else f"{sentence[:240]}..."
        samples.append(
            {
                "marker": item.get("marker"),
                "marker_raw": item.get("marker_raw"),
                "page": item.get("page"),
                "paragraph_index": item.get("paragraph_index"),
                "line_in_paragraph": item.get("line_in_paragraph"),
                "ref_key": item.get("ref_key"),
                "sentence_len": len(sentence),
                "sentence_preview": preview,
            }
        )
    return samples


def _sample_references(references: list[dict], limit: int = 3) -> list[dict]:
    samples = []
    for item in references[:limit]:
        samples.append(
            {
                "key": item.get("key"),
                "title": (item.get("title") or "")[:200],
                "author": (item.get("author") or "")[:120],
                "year": item.get("year"),
                "doi": item.get("doi"),
                "reference_number": item.get("reference_number"),
            }
        )
    return samples


@pytest.mark.integration
def test_grobid_reference_extraction_and_context(tmp_path: Path):
    grobid_url = os.getenv("GROBID_URL", "http://localhost:8070")
    grobid_available = _grobid_is_available(grobid_url)

    pdf_path = Path(__file__).resolve().parents[2] / "test_paper.pdf"
    assert pdf_path.exists(), f"Missing test PDF: {pdf_path}"

    backend = "grobid" if grobid_available else "auto"
    store = ResultStore(
        base_dir=str(tmp_path / "runs"),
        run_id="test_run",
        tool_params={"backend": backend, "grobid_url": grobid_url},
    )
    checker = CitationChecker(config=_build_config(backend, grobid_url), result_store=store)
    result = checker.extract_citations_with_context_from_pdf(str(pdf_path))

    backend_result = result.get("backend", "")
    if grobid_available:
        assert "references:grobid" in backend_result
    else:
        assert "references:mupdf" in backend_result

    citations = result.get("citations", [])
    references = result.get("references", [])

    assert citations, "Expected citations extracted from PDF"
    assert references, "Expected references extracted via GROBID"
    assert any(ref.get("title") for ref in references), "Expected reference titles"
    assert any(c.get("line_in_paragraph", 0) > 0 for c in citations)

    print("Extraction backend:", backend_result)
    print("Sample citations:")
    print(json.dumps(_sample_citations(citations), ensure_ascii=False, indent=2))
    print("Sample references:")
    print(json.dumps(_sample_references(references), ensure_ascii=False, indent=2))

    run_dir = tmp_path / "runs" / "test_run"
    assert (run_dir / "run.json").exists()
    assert (run_dir / "index.json").exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_citation_metadata_verification_pipeline():
    grobid_url = os.getenv("GROBID_URL", "http://localhost:8070")
    pdf_path = Path(__file__).resolve().parents[2] / "test_paper.pdf"
    assert pdf_path.exists(), f"Missing test PDF: {pdf_path}"

    sources_raw = os.getenv("CITATION_VERIFY_SOURCES", "semantic_scholar")
    sources = [s.strip() for s in sources_raw.split(",") if s.strip()]

    checker = CitationChecker(config=_build_config("auto", grobid_url))
    result = await checker.extract_citations_with_context_from_pdf_async(
        str(pdf_path),
        verify_references=True,
        sources=sources,
        verify_limit=2,
    )

    references = result.get("references", [])
    verified = [ref for ref in references if ref.get("validation")]
    assert verified, "Expected at least one reference with validation results"

    analyzer = CitationAnalyzer()
    summary = analyzer.analyze_references_with_validation(references)
    assert summary["total_references"] == len(references)
    paragraph_report = analyzer.analyze_paragraph_distribution(
        result.get("citations", []),
        references,
        max_examples_per_paragraph=1,
    )
    assert paragraph_report["summary"]["paragraphs_with_citations"] > 0

    print("Verification sources:", sources)
    print("Verified references (sample):")
    print(json.dumps(verified[:2], ensure_ascii=False, indent=2))
    print("Analysis summary:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Paragraph distribution (markdown):")
    print(paragraph_report["render"]["markdown"])
