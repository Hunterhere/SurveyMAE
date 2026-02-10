"""OpenAlex API fetcher.

Based on BibGuard (https://github.com/thinkwee/BibGuard), Apache License 2.0.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import requests


@dataclass
class OpenAlexResult:
    """Search result from OpenAlex API."""

    title: str
    authors: list[str]
    year: str
    abstract: str
    doi: str
    citation_count: int
    url: str


class OpenAlexFetcher:
    """Fetcher using OpenAlex's free API."""

    BASE_URL = "https://api.openalex.org"
    RATE_LIMIT_DELAY = 0.1

    def __init__(self, email: Optional[str] = None) -> None:
        self.email = email
        self._last_request_time = 0.0
        self._session = requests.Session()

        self._session.headers.update(
            {
                "User-Agent": (
                    "SurveyMAE/0.1 (https://github.com/your-org/SurveyMAE; "
                    "mailto:surveymae@example.com)"
                )
            }
        )

        if email:
            self._session.headers.update({"From": email})

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_time
        if elapsed < self.RATE_LIMIT_DELAY:
            time.sleep(self.RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = time.time()

    def search_by_title(self, title: str, max_results: int = 5) -> Optional[OpenAlexResult]:
        """Search for a paper by title."""
        self._rate_limit()

        url = f"{self.BASE_URL}/works"
        params = {"search": title, "per-page": max_results}

        try:
            response = self._session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException:
            return None

        results = data.get("results", [])
        if not results:
            return None

        return self._parse_work(results[0])

    def fetch_by_doi(self, doi: str) -> Optional[OpenAlexResult]:
        """Fetch paper metadata by DOI."""
        self._rate_limit()

        doi_url = f"https://doi.org/{doi}"
        url = f"{self.BASE_URL}/works/{doi_url}"

        try:
            response = self._session.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException:
            return None

        return self._parse_work(data)

    def _parse_work(self, work_data: dict) -> Optional[OpenAlexResult]:
        try:
            title = work_data.get("title", "")

            authors = []
            authorships = work_data.get("authorships", [])
            for authorship in authorships:
                author = authorship.get("author", {})
                name = author.get("display_name", "")
                if name:
                    authors.append(name)

            year = work_data.get("publication_year")
            year_str = str(year) if year else ""

            abstract = ""
            abstract_inverted = work_data.get("abstract_inverted_index")
            if abstract_inverted:
                abstract = self._reconstruct_abstract(abstract_inverted)

            doi = work_data.get("doi", "")
            if doi and doi.startswith("https://doi.org/"):
                doi = doi.replace("https://doi.org/", "")

            citation_count = work_data.get("cited_by_count", 0)
            url = work_data.get("id", "")

            return OpenAlexResult(
                title=title,
                authors=authors,
                year=year_str,
                abstract=abstract,
                doi=doi,
                citation_count=citation_count,
                url=url,
            )
        except (KeyError, TypeError):
            return None

    def _reconstruct_abstract(self, inverted_index: dict) -> str:
        if not inverted_index:
            return ""

        try:
            max_pos = max(max(positions) for positions in inverted_index.values())
            words = [""] * (max_pos + 1)

            for word, positions in inverted_index.items():
                for pos in positions:
                    words[pos] = word

            return " ".join(word for word in words if word)
        except (ValueError, TypeError):
            return ""
