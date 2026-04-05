"""DBLP API fetcher.

Based on BibGuard (https://github.com/thinkwee/BibGuard), Apache License 2.0.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import requests

from src.core.log import get_run_stats


@dataclass
class DBLPResult:
    """Metadata result from DBLP API."""

    title: str
    authors: list[str]
    year: str
    venue: str
    url: str
    doi: Optional[str] = None


class DBLPFetcher:
    """Fetcher for DBLP API."""

    BASE_URL = "https://dblp.org/search/publ/api"

    def __init__(self) -> None:
        self.last_request_time = 0.0
        self.rate_limit_delay = 1.5
        self.logger = logging.getLogger("surveymae.tools.fetchers.dblp")

    def _wait_for_rate_limit(self) -> None:
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self.last_request_time = time.time()

    def search_by_title(self, title: str) -> Optional[DBLPResult]:
        """Search DBLP by title."""
        self._wait_for_rate_limit()

        params = {"q": title, "format": "json", "h": 3}

        try:
            response = requests.get(self.BASE_URL, params=params, timeout=10)

            if response.status_code == 429:
                self.logger.warning("DBLP rate limit exceeded. Waiting longer...")
                time.sleep(5)
                return None

            if response.status_code != 200:
                self.logger.warning("DBLP API error: %s", response.status_code)
                return None

            get_run_stats().record_api()
            data = response.json()
            return self._parse_response(data)
        except Exception as exc:
            self.logger.error("Error fetching from DBLP: %s", exc)
            return None

    def _parse_response(self, data: dict) -> Optional[DBLPResult]:
        try:
            hits = data.get("result", {}).get("hits", {}).get("hit", [])
            if not hits:
                return None

            best_hit = hits[0]
            info = best_hit.get("info", {})

            authors_data = info.get("authors", {}).get("author", [])
            if isinstance(authors_data, list):
                authors = [a.get("text", "") for a in authors_data if isinstance(a, dict)]
            elif isinstance(authors_data, dict):
                authors = [authors_data.get("text", "")]
            else:
                authors = []

            title = info.get("title", "")
            if title.endswith("."):
                title = title[:-1]

            year = info.get("year", "")
            venue = info.get("venue", "")
            url = info.get("url", "")
            doi = info.get("doi", "") or None

            return DBLPResult(
                title=title,
                authors=authors,
                year=year,
                venue=venue,
                url=url,
                doi=doi,
            )
        except Exception as exc:
            self.logger.error("Error parsing DBLP response: %s", exc)
            return None
