"""Unit tests for literature fetchers and search tool."""

from src.tools.fetchers.arxiv_fetcher import ArxivFetcher, ArxivMetadata
from src.tools.fetchers.crossref_fetcher import CrossRefFetcher, CrossRefResult
from src.tools.fetchers.dblp_fetcher import DBLPFetcher
from src.tools.fetchers.openalex_fetcher import OpenAlexFetcher
from src.tools.fetchers.scholar_fetcher import ScholarFetcher
from src.tools.fetchers.semantic_scholar_fetcher import SemanticScholarFetcher
from src.tools.literature_search import LiteratureSearch


def test_arxiv_fetcher_parses_entry():
    fetcher = ArxivFetcher()
    xml = """
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry>
        <id>http://arxiv.org/abs/2301.00001</id>
        <title>Test Paper</title>
        <summary>Test abstract.</summary>
        <author><name>Alice</name></author>
        <published>2023-01-01T00:00:00Z</published>
        <updated>2023-01-02T00:00:00Z</updated>
        <category term="cs.AI"/>
        <arxiv:primary_category term="cs.AI"/>
        <arxiv:doi>10.1234/abcd</arxiv:doi>
        <arxiv:journal_ref>Journal</arxiv:journal_ref>
        <arxiv:comment>Comment</arxiv:comment>
      </entry>
    </feed>
    """
    results = fetcher._parse_response_multiple(xml)
    assert len(results) == 1
    assert results[0].arxiv_id == "2301.00001"
    assert results[0].year == "2023"


def test_crossref_fetcher_parses_item():
    fetcher = CrossRefFetcher()
    item = {
        "title": ["Test Title"],
        "author": [{"given": "Alice", "family": "Smith"}],
        "published-print": {"date-parts": [[2021, 1, 1]]},
        "DOI": "10.1111/test",
        "publisher": "Test Pub",
        "container-title": ["Test Journal"],
        "abstract": "Abstract",
    }
    result = fetcher._parse_item(item)
    assert result is not None
    assert result.title == "Test Title"
    assert result.year == "2021"
    assert result.doi == "10.1111/test"


def test_openalex_fetcher_reconstructs_abstract():
    fetcher = OpenAlexFetcher()
    inverted = {"hello": [0], "world": [1]}
    assert fetcher._reconstruct_abstract(inverted) == "hello world"


def test_dblp_fetcher_parses_response():
    fetcher = DBLPFetcher()
    data = {
        "result": {
            "hits": {
                "hit": [
                    {
                        "info": {
                            "title": "DBLP Paper.",
                            "authors": {"author": [{"text": "Alice"}]},
                            "year": "2020",
                            "venue": "Conf",
                            "url": "https://dblp.org/rec",
                            "doi": "10.9999/test",
                        }
                    }
                ]
            }
        }
    }
    result = fetcher._parse_response(data)
    assert result is not None
    assert result.title == "DBLP Paper"
    assert result.doi == "10.9999/test"


def test_scholar_fetcher_parses_results():
    fetcher = ScholarFetcher()
    html = """
    <div class="gs_ri">
      <h3 class="gs_rt"><a href="http://example.com">Test Paper</a></h3>
      <div class="gs_a">Alice, Bob - Journal of Tests - 2020</div>
      <div class="gs_rs">Snippet text</div>
      <div class="gs_fl"><a>Cited by 42</a></div>
    </div>
    """
    results = fetcher._parse_results(html, max_results=1)
    assert len(results) == 1
    assert results[0].title == "Test Paper"
    assert results[0].year == "2020"
    assert results[0].cited_by == 42


def test_literature_search_aggregates_sources():
    arxiv_meta = ArxivMetadata(
        arxiv_id="2301.00001",
        title="Arxiv Paper",
        authors=["Alice"],
        abstract="Abstract",
        published="2023-01-01",
        updated="2023-01-01",
        categories=["cs.AI"],
        primary_category="cs.AI",
        doi="10.1234/abcd",
        journal_ref="",
        comment="",
        pdf_url="http://arxiv.org/pdf/2301.00001.pdf",
        abs_url="http://arxiv.org/abs/2301.00001",
    )
    crossref_meta = CrossRefResult(
        title="CrossRef Paper",
        authors=["Bob"],
        year="2022",
        doi="10.5555/xyz",
        publisher="Pub",
        container_title="Journal",
        abstract="",
        url="https://doi.org/10.5555/xyz",
    )

    class DummyArxiv:
        def search_by_title(self, title: str, max_results: int = 5):
            return [arxiv_meta]

    class DummyCrossRef:
        def search_by_title(self, title: str, max_results: int = 5):
            return crossref_meta

    searcher = LiteratureSearch(fetchers={"arxiv": DummyArxiv(), "crossref": DummyCrossRef()})
    results = searcher.search_by_title("Test", sources=["arxiv", "crossref"])
    sources = [r.source for r in results]
    assert sources == ["arxiv", "crossref"]
