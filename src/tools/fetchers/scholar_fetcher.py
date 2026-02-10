"""Google Scholar search (scraping-based fallback).

Based on BibGuard (https://github.com/thinkwee/BibGuard), Apache License 2.0.
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup

try:
    import lxml  # noqa: F401

    _BS_PARSER = "lxml"
except Exception:
    _BS_PARSER = "html.parser"


@dataclass
class ScholarResult:
    """Search result from Google Scholar."""

    title: str
    authors: str
    year: str
    snippet: str
    url: str
    cited_by: int


class ScholarFetcher:
    """Fallback fetcher using Google Scholar search."""

    SEARCH_URL = "https://scholar.google.com/scholar"
    RATE_LIMIT_DELAY = 10.0
    MAX_RETRIES = 2

    USER_AGENTS = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    ]

    def __init__(self) -> None:
        self._last_request_time = 0.0
        self._session = requests.Session()
        self._request_count = 0
        self._blocked = False

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_time
        delay = self.RATE_LIMIT_DELAY + random.uniform(3, 5)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_request_time = time.time()

    def _get_headers(self) -> dict[str, str]:
        return {
            "User-Agent": random.choice(self.USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    def search(self, query: str, max_results: int = 5) -> list[ScholarResult]:
        """Search Google Scholar."""
        if self._blocked:
            return []

        self._rate_limit()
        self._request_count += 1

        params = {"q": query, "hl": "en", "num": min(max_results, 10)}

        try:
            response = self._session.get(
                self.SEARCH_URL,
                params=params,
                headers=self._get_headers(),
                timeout=30,
            )
            response.raise_for_status()
        except requests.RequestException:
            return []

        if "unusual traffic" in response.text.lower() or response.status_code == 429:
            self._blocked = True
            print(
                "WARNING: Google Scholar blocked after "
                f"{self._request_count} requests. Skipping further Scholar queries."
            )
            return []

        return self._parse_results(response.text, max_results)

    def search_by_title(self, title: str) -> Optional[ScholarResult]:
        """Search for a specific paper by title."""
        query = f'"{title}"'
        results = self.search(query, max_results=3)

        if not results:
            results = self.search(title, max_results=5)

        return results[0] if results else None

    def _parse_results(self, html: str, max_results: int) -> list[ScholarResult]:
        results: list[ScholarResult] = []
        soup = BeautifulSoup(html, _BS_PARSER)

        entries = soup.find_all("div", class_="gs_ri")

        for entry in entries[:max_results]:
            try:
                result = self._parse_entry(entry)
                if result:
                    results.append(result)
            except Exception:
                continue

        return results

    def _parse_entry(self, entry) -> Optional[ScholarResult]:
        title_elem = entry.find("h3", class_="gs_rt")
        if not title_elem:
            return None

        title_link = title_elem.find("a")
        if title_link:
            title = title_link.get_text(strip=True)
            url = title_link.get("href", "")
        else:
            title = title_elem.get_text(strip=True)
            url = ""

        title = re.sub(r"^\[(PDF|HTML|BOOK|CITATION)\]\s*", "", title)

        meta_elem = entry.find("div", class_="gs_a")
        authors = ""
        year = ""

        if meta_elem:
            meta_text = meta_elem.get_text(strip=True)

            year_match = re.search(r"\b(19|20)\d{2}\b", meta_text)
            if year_match:
                year = year_match.group(0)

            parts = meta_text.split(" - ")
            if parts:
                author_part = parts[0].strip()

                if year:
                    author_part = re.sub(
                        r",?\s*" + re.escape(year) + r".*$", "", author_part
                    )

                author_part = re.sub(
                    r"\s+the\s+(journal|proceedings|conference|symposium|workshop|transactions|magazine|review|annals)\s+.*$",
                    "",
                    author_part,
                    flags=re.IGNORECASE,
                )

                author_part = re.sub(
                    r"\s+(journal|proceedings|conference|symposium|workshop|transactions|magazine|review|annals)\s+.*$",
                    "",
                    author_part,
                    flags=re.IGNORECASE,
                )

                author_part = re.sub(r"\s+the\s*$", "", author_part, flags=re.IGNORECASE)
                author_part = author_part.rstrip(", ").strip()

                authors = author_part

        snippet_elem = entry.find("div", class_="gs_rs")
        snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

        cited_by = 0
        cited_elem = entry.find("a", string=re.compile(r"Cited by \d+"))
        if cited_elem:
            match = re.search(r"Cited by (\d+)", cited_elem.get_text())
            if match:
                cited_by = int(match.group(1))

        return ScholarResult(
            title=title,
            authors=authors,
            year=year,
            snippet=snippet,
            url=url,
            cited_by=cited_by,
        )
