"""Semantic Scholar API fetcher.

Based on BibGuard (https://github.com/thinkwee/BibGuard), Apache License 2.0.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import requests


@dataclass
class SemanticScholarResult:
    """Search result from Semantic Scholar API."""

    title: str
    authors: list[str]
    year: str
    abstract: str
    paper_id: str
    citation_count: int
    url: str


class SemanticScholarFetcher:
    """Fetcher using Semantic Scholar's official API."""

    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    RATE_LIMIT_DELAY = 0.5

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key
        self._last_request_time = 0.0
        self._session = requests.Session()

        if api_key:
            self._session.headers.update({"x-api-key": api_key})

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_time
        if elapsed < self.RATE_LIMIT_DELAY:
            time.sleep(self.RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = time.time()

    def search_by_title(self, title: str, max_results: int = 5) -> Optional[SemanticScholarResult]:
        """Search for a paper by title."""
        self._rate_limit()

        url = f"{self.BASE_URL}/paper/search"
        params = {
            "query": title,
            "limit": max_results,
            "fields": "title,authors,year,abstract,paperId,citationCount,url",
        }

        try:
            response = self._session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException:
            return None

        papers = data.get("data", [])
        if not papers:
            return None

        return self._parse_paper(papers[0])

    def fetch_by_doi(self, doi: str) -> Optional[SemanticScholarResult]:
        """Fetch paper metadata by DOI."""
        self._rate_limit()

        url = f"{self.BASE_URL}/paper/DOI:{doi}"
        params = {"fields": "title,authors,year,abstract,paperId,citationCount,url"}

        try:
            response = self._session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException:
            return None

        return self._parse_paper(data)

    def fetch_by_arxiv_id(self, arxiv_id: str) -> Optional[SemanticScholarResult]:
        """Fetch paper metadata by arXiv ID."""
        self._rate_limit()

        clean_id = arxiv_id.replace("arXiv:", "")
        url = f"{self.BASE_URL}/paper/ARXIV:{clean_id}"
        params = {"fields": "title,authors,year,abstract,paperId,citationCount,url"}

        try:
            response = self._session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException:
            return None

        return self._parse_paper(data)

    def _parse_paper(self, paper_data: dict) -> Optional[SemanticScholarResult]:
        try:
            authors = []
            for author in paper_data.get("authors", []):
                name = author.get("name", "")
                if name:
                    authors.append(name)

            year = paper_data.get("year")
            year_str = str(year) if year else ""

            return SemanticScholarResult(
                title=paper_data.get("title", ""),
                authors=authors,
                year=year_str,
                abstract=paper_data.get("abstract", ""),
                paper_id=paper_data.get("paperId", ""),
                citation_count=paper_data.get("citationCount", 0),
                url=paper_data.get("url", ""),
            )
        except (KeyError, TypeError):
            return None
