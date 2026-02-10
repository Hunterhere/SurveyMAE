"""Integration tests for Semantic Scholar fetcher (real API)."""

import pytest

from src.core.search_config import load_search_engine_config
from src.tools.fetchers.semantic_scholar_fetcher import SemanticScholarFetcher
from tests.integration import load_test_env


def test_semantic_scholar_fetcher_real_api():
    load_test_env()
    config = load_search_engine_config()
    if not config.semantic_scholar_api_key:
        pytest.skip("SEMANTIC_SCHOLAR_API_KEY not configured")

    fetcher = SemanticScholarFetcher(api_key=config.semantic_scholar_api_key)
    doi = "10.48550/arXiv.1706.03762"
    arxiv_id = "1706.03762"
    title = "Attention Is All You Need"

    result = fetcher.fetch_by_doi(doi)
    if result is None:
        result = fetcher.fetch_by_arxiv_id(arxiv_id)
    if result is None:
        result = fetcher.search_by_title(title)

    assert result is not None, "Semantic Scholar API returned no results"
    assert result.title
    assert result.year
