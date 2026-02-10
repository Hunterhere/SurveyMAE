"""CrossRef API fetcher for bibliography metadata.

Based on BibGuard (https://github.com/thinkwee/BibGuard), Apache License 2.0.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import requests


@dataclass
class CrossRefResult:
    """Metadata result from CrossRef API."""

    title: str
    authors: list[str]
    year: str
    doi: str
    publisher: str
    container_title: str
    abstract: str = ""
    url: str = ""


class CrossRefFetcher:
    """Fetcher for CrossRef API."""

    BASE_URL = "https://api.crossref.org/works"
    RATE_LIMIT_DELAY = 1.0

    def __init__(self, mailto: str = "surveymae@example.com") -> None:
        self.mailto = mailto
        self._last_request_time = 0.0
        self._session = requests.Session()

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_time
        if elapsed < self.RATE_LIMIT_DELAY:
            time.sleep(self.RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = time.time()

    def _get_headers(self) -> dict[str, str]:
        return {
            "User-Agent": f"SurveyMAE/0.1 (mailto:{self.mailto})",
            "Accept": "application/json",
        }

    def search_by_title(self, title: str, max_results: int = 5) -> Optional[CrossRefResult]:
        """Search for a paper by title."""
        self._rate_limit()

        params = {
            "query.title": title,
            "rows": max_results,
            "select": "title,author,published-print,published-online,DOI,publisher,container-title,abstract",
        }

        try:
            response = self._session.get(
                self.BASE_URL,
                params=params,
                headers=self._get_headers(),
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException:
            return None

        if data.get("status") != "ok":
            return None

        items = data.get("message", {}).get("items", [])
        if not items:
            return None

        return self._parse_item(items[0])

    def search_by_doi(self, doi: str) -> Optional[CrossRefResult]:
        """Fetch metadata by DOI."""
        self._rate_limit()

        doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")

        try:
            response = self._session.get(
                f"{self.BASE_URL}/{doi}",
                headers=self._get_headers(),
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException:
            return None

        if data.get("status") != "ok":
            return None

        item = data.get("message", {})
        return self._parse_item(item)

    def _parse_item(self, item: dict) -> Optional[CrossRefResult]:
        try:
            titles = item.get("title", [])
            title = titles[0] if titles else ""
            if not title:
                return None

            authors = []
            for author in item.get("author", []):
                given = author.get("given", "")
                family = author.get("family", "")
                if family:
                    authors.append(f"{given} {family}".strip() if given else family)

            year = ""
            for date_field in ("published-print", "published-online", "created"):
                date_parts = item.get(date_field, {}).get("date-parts", [[]])
                if date_parts and date_parts[0]:
                    year = str(date_parts[0][0])
                    break

            doi = item.get("DOI", "")
            publisher = item.get("publisher", "")
            container_titles = item.get("container-title", [])
            container_title = container_titles[0] if container_titles else ""
            abstract = item.get("abstract", "")
            url = f"https://doi.org/{doi}" if doi else ""

            return CrossRefResult(
                title=title,
                authors=authors,
                year=year,
                doi=doi,
                publisher=publisher,
                container_title=container_title,
                abstract=abstract,
                url=url,
            )
        except (KeyError, IndexError, TypeError):
            return None
