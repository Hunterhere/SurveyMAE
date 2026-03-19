"""Citation metadata retrieval and comparison utilities.

This module adapts BibGuard's metadata comparison logic for SurveyMAE.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional

import httpx

from src.core.search_config import load_search_engine_config

logger = logging.getLogger(__name__)


@dataclass
class BibEntry:
    """Structured bibliography entry.

    Attributes:
        key: Citation key.
        title: Paper title.
        author: Raw author string from BibTeX.
        year: Publication year.
        doi: DOI string.
        arxiv_id: arXiv identifier, if present.
        entry_type: BibTeX entry type.
        raw_entry: Optional raw entry data.
    """

    key: str
    title: str = ""
    author: str = ""
    year: str = ""
    doi: str = ""
    arxiv_id: str = ""
    entry_type: str = ""
    raw_entry: dict[str, Any] = field(default_factory=dict)

    @property
    def has_arxiv(self) -> bool:
        """Return True if the entry includes an arXiv id."""
        return bool(self.arxiv_id)

    @property
    def search_query(self) -> str:
        """Return a reasonable query string for searching."""
        return self.title or self.key


@dataclass
class ArxivMetadata:
    """Metadata fetched from arXiv."""

    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    published: str
    updated: str
    categories: list[str]
    primary_category: str
    doi: str
    journal_ref: str
    comment: str
    pdf_url: str
    abs_url: str

    @property
    def year(self) -> str:
        """Extract year from published date."""
        if self.published:
            match = re.match(r"(\d{4})", self.published)
            if match:
                return match.group(1)
        return ""


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


@dataclass
class SemanticScholarResult:
    """Metadata result from Semantic Scholar API."""

    title: str
    authors: list[str]
    year: str
    abstract: str
    paper_id: str
    citation_count: int
    url: str
    doi: str = ""
    arxiv_id: str = ""
    openalex_id: str = ""
    reference_targets: list[dict[str, str]] = field(default_factory=list)


@dataclass
class OpenAlexResult:
    """Metadata result from OpenAlex API."""

    title: str
    authors: list[str]
    year: str
    abstract: str
    doi: str
    citation_count: int
    url: str
    openalex_id: str = ""
    reference_targets: list[dict[str, str]] = field(default_factory=list)


@dataclass
class DBLPResult:
    """Metadata result from DBLP API."""

    title: str
    authors: list[str]
    year: str
    venue: str
    url: str
    doi: Optional[str] = None


@dataclass
class ScholarResult:
    """Metadata result from Google Scholar (if provided externally)."""

    title: str
    authors: str
    year: str
    snippet: str
    url: str
    cited_by: int


@dataclass
class ComparisonResult:
    """Result of comparing bib entry with fetched metadata."""

    entry_key: str
    title_match: bool
    title_similarity: float
    bib_title: str
    fetched_title: str
    author_match: bool
    author_similarity: float
    bib_authors: list[str]
    fetched_authors: list[str]
    year_match: bool
    bib_year: str
    fetched_year: str
    is_match: bool
    confidence: float
    issues: list[str]
    source: str

    @property
    def has_issues(self) -> bool:
        """Return True if any issues were found."""
        return len(self.issues) > 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON output."""
        return asdict(self)


class TextNormalizer:
    """Utility class for normalizing text for comparison."""

    LATEX_COMMANDS = [
        (r"\\textbf\{([^}]*)\}", r"\1"),
        (r"\\textit\{([^}]*)\}", r"\1"),
        (r"\\emph\{([^}]*)\}", r"\1"),
        (r"\\textrm\{([^}]*)\}", r"\1"),
        (r"\\texttt\{([^}]*)\}", r"\1"),
        (r"\\textsf\{([^}]*)\}", r"\1"),
        (r"\\textsc\{([^}]*)\}", r"\1"),
        (r"\\text\{([^}]*)\}", r"\1"),
        (r"\\mathrm\{([^}]*)\}", r"\1"),
        (r"\\mathbf\{([^}]*)\}", r"\1"),
        (r"\\mathit\{([^}]*)\}", r"\1"),
        (r"\\url\{([^}]*)\}", r"\1"),
        (r"\\href\{[^}]*\}\{([^}]*)\}", r"\1"),
    ]

    LATEX_CHARS = {
        r"\&": "&",
        r"\%": "%",
        r"\$": "$",
        r"\#": "#",
        r"\_": "_",
        r"\{": "{",
        r"\}": "}",
        r"\~": "~",
        r"\^": "^",
        r"``": '"',
        r"''": '"',
        r"`": "'",
        r"'": "'",
        r"--": "-",
        r"---": "-",
    }

    LATEX_ACCENTS = [
        (r"\\'([aeiouAEIOU])", r"\1"),
        (r"\\`([aeiouAEIOU])", r"\1"),
        (r"\\^([aeiouAEIOU])", r"\1"),
        (r'\\"([aeiouAEIOU])', r"\1"),
        (r"\\~([nNaAoO])", r"\1"),
        (r"\\c\{([cC])\}", r"\1"),
        (r"\\'{([aeiouAEIOU])}", r"\1"),
        (r"\\`{([aeiouAEIOU])}", r"\1"),
        (r"\\^{([aeiouAEIOU])}", r"\1"),
        (r'\\"{([aeiouAEIOU])}', r"\1"),
        (r"\\~{([nNaAoO])}", r"\1"),
    ]

    @classmethod
    def normalize_latex(cls, text: str) -> str:
        """Remove common LaTeX formatting commands."""
        if not text:
            return ""

        result = text

        for pattern, replacement in cls.LATEX_COMMANDS:
            result = re.sub(pattern, replacement, result)

        for pattern, replacement in cls.LATEX_ACCENTS:
            result = re.sub(pattern, replacement, result)

        for latex_char, normal_char in cls.LATEX_CHARS.items():
            result = result.replace(latex_char, normal_char)

        result = re.sub(r"[{}]", "", result)
        return result

    @classmethod
    def normalize_unicode(cls, text: str) -> str:
        """Normalize unicode characters to ASCII."""
        if not text:
            return ""

        text = unicodedata.normalize("NFKD", text)
        return text.encode("ascii", "ignore").decode("ascii")

    @classmethod
    def normalize_whitespace(cls, text: str) -> str:
        """Normalize whitespace."""
        if not text:
            return ""

        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @classmethod
    def remove_punctuation(cls, text: str) -> str:
        """Remove punctuation for comparison."""
        if not text:
            return ""

        return re.sub(r"[^\w\s]", "", text)

    @classmethod
    def normalize_for_comparison(cls, text: str) -> str:
        """Normalize text for similarity comparisons."""
        if not text:
            return ""

        text = cls.normalize_latex(text)
        text = cls.normalize_unicode(text)
        text = text.lower()
        text = cls.normalize_whitespace(text)
        text = cls.remove_punctuation(text)
        return text

    @classmethod
    def normalize_author_name(cls, name: str) -> str:
        """Normalize an author name to a comparable form."""
        if not name:
            return ""

        name = cls.normalize_latex(name)
        name = cls.normalize_unicode(name)
        name = cls.normalize_whitespace(name)

        if "," in name:
            parts = name.split(",", 1)
            if len(parts) == 2:
                name = f"{parts[1].strip()} {parts[0].strip()}"

        name = name.lower()
        name = cls.remove_punctuation(name)
        return name

    @classmethod
    def normalize_author_list(cls, authors: str) -> list[str]:
        """Normalize a BibTeX author list."""
        if not authors:
            return []

        author_list = re.split(r"\s+and\s+", authors, flags=re.IGNORECASE)
        normalized = []
        for author in author_list:
            normalized_name = cls.normalize_author_name(author.strip())
            if normalized_name:
                normalized.append(normalized_name)

        return normalized

    @classmethod
    def similarity_ratio(cls, text1: str, text2: str) -> float:
        """Calculate word-based Jaccard similarity."""
        if not text1 or not text2:
            return 0.0

        words1 = set(text1.split())
        words2 = set(text2.split())

        if not words1 and not words2:
            return 1.0
        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / len(union)

    @classmethod
    def levenshtein_similarity(cls, s1: str, s2: str) -> float:
        """Calculate normalized Levenshtein similarity."""
        if not s1 and not s2:
            return 1.0
        if not s1 or not s2:
            return 0.0

        m, n = len(s1), len(s2)
        dp = [[0] * (n + 1) for _ in range(m + 1)]

        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j

        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if s1[i - 1] == s2[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1]
                else:
                    dp[i][j] = min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]) + 1

        max_len = max(m, n)
        distance = dp[m][n]
        return 1.0 - (distance / max_len)


class MetadataComparator:
    """Compares bibliography entries with fetched metadata."""

    TITLE_THRESHOLD = 0.8
    AUTHOR_THRESHOLD = 0.6

    def __init__(
        self,
        title_threshold: Optional[float] = None,
        author_threshold: Optional[float] = None,
    ) -> None:
        self.normalizer = TextNormalizer
        self.title_threshold = title_threshold or self.TITLE_THRESHOLD
        self.author_threshold = author_threshold or self.AUTHOR_THRESHOLD

    def compare_with_arxiv(
        self,
        bib_entry: BibEntry,
        arxiv_meta: ArxivMetadata,
    ) -> ComparisonResult:
        """Compare bib entry with arXiv metadata."""
        return self._compare(
            bib_entry=bib_entry,
            fetched_title=arxiv_meta.title,
            fetched_authors=arxiv_meta.authors,
            fetched_year=arxiv_meta.year,
            source="arxiv",
        )

    def compare_with_scholar(
        self,
        bib_entry: BibEntry,
        scholar_result: ScholarResult,
    ) -> ComparisonResult:
        """Compare bib entry with Scholar metadata."""
        return self._compare(
            bib_entry=bib_entry,
            fetched_title=scholar_result.title,
            fetched_authors=scholar_result.authors,
            fetched_year=scholar_result.year,
            source="scholar",
        )

    def compare_with_crossref(
        self,
        bib_entry: BibEntry,
        crossref_result: CrossRefResult,
    ) -> ComparisonResult:
        """Compare bib entry with CrossRef metadata."""
        return self._compare(
            bib_entry=bib_entry,
            fetched_title=crossref_result.title,
            fetched_authors=crossref_result.authors,
            fetched_year=crossref_result.year,
            source="crossref",
        )

    def compare_with_semantic_scholar(
        self,
        bib_entry: BibEntry,
        ss_result: SemanticScholarResult,
    ) -> ComparisonResult:
        """Compare bib entry with Semantic Scholar metadata."""
        return self._compare(
            bib_entry=bib_entry,
            fetched_title=ss_result.title,
            fetched_authors=ss_result.authors,
            fetched_year=ss_result.year,
            source="semantic_scholar",
        )

    def compare_with_openalex(
        self,
        bib_entry: BibEntry,
        oa_result: OpenAlexResult,
    ) -> ComparisonResult:
        """Compare bib entry with OpenAlex metadata."""
        return self._compare(
            bib_entry=bib_entry,
            fetched_title=oa_result.title,
            fetched_authors=oa_result.authors,
            fetched_year=oa_result.year,
            source="openalex",
        )

    def compare_with_dblp(
        self,
        bib_entry: BibEntry,
        dblp_result: DBLPResult,
    ) -> ComparisonResult:
        """Compare bib entry with DBLP metadata."""
        return self._compare(
            bib_entry=bib_entry,
            fetched_title=dblp_result.title,
            fetched_authors=dblp_result.authors,
            fetched_year=dblp_result.year,
            source="dblp",
        )

    def compare_generic(
        self,
        bib_entry: BibEntry,
        title: str,
        authors: list[str] | str,
        year: str,
        source: str,
    ) -> ComparisonResult:
        """Compare bib entry with generic metadata."""
        return self._compare(
            bib_entry=bib_entry,
            fetched_title=title,
            fetched_authors=authors,
            fetched_year=year,
            source=source,
        )

    def create_unable_result(self, bib_entry: BibEntry, reason: str) -> ComparisonResult:
        """Create a result when metadata could not be fetched."""
        return ComparisonResult(
            entry_key=bib_entry.key,
            title_match=False,
            title_similarity=0.0,
            bib_title=bib_entry.title,
            fetched_title="",
            author_match=False,
            author_similarity=0.0,
            bib_authors=self.normalizer.normalize_author_list(bib_entry.author),
            fetched_authors=[],
            year_match=False,
            bib_year=bib_entry.year,
            fetched_year="",
            is_match=False,
            confidence=0.0,
            issues=[reason],
            source="unable",
        )

    def _compare( #FIXME: poor extraction leads to mismatch, see \output\runs\20260319T065912Z_53317b7e\papers\40b1a0d0d47b\validation.json
        self,
        bib_entry: BibEntry,
        fetched_title: str,
        fetched_authors: list[str] | str,
        fetched_year: str,
        source: str,
    ) -> ComparisonResult:
        issues: list[str] = []

        bib_title_norm = self.normalizer.normalize_for_comparison(bib_entry.title)
        fetched_title_norm = self.normalizer.normalize_for_comparison(fetched_title)

        title_similarity = self.normalizer.similarity_ratio(bib_title_norm, fetched_title_norm)
        if len(bib_title_norm) < 100:
            lev_sim = self.normalizer.levenshtein_similarity(bib_title_norm, fetched_title_norm)
            title_similarity = max(title_similarity, lev_sim)

        title_match = title_similarity >= self.title_threshold
        if not title_match:
            issues.append(f"Title mismatch (similarity: {title_similarity:.2%})")

        bib_authors = self.normalizer.normalize_author_list(bib_entry.author)
        fetched_author_list = self._normalize_fetched_authors(fetched_authors)

        author_similarity = self._compare_author_lists(bib_authors, fetched_author_list)
        author_match = author_similarity >= self.author_threshold
        if not author_match:
            issues.append(f"Author mismatch (similarity: {author_similarity:.2%})")

        bib_year = bib_entry.year.strip()
        fetched_year_str = str(fetched_year).strip() if fetched_year is not None else ""
        year_match = bool(bib_year and fetched_year_str and bib_year == fetched_year_str)
        if not year_match and bib_year and fetched_year_str:
            issues.append(f"Year mismatch: bib={bib_year}, {source}={fetched_year_str}")

        is_match = title_match and author_match
        confidence = (
            title_similarity * 0.5 + author_similarity * 0.3 + (1.0 if year_match else 0.5) * 0.2
        )

        return ComparisonResult(
            entry_key=bib_entry.key,
            title_match=title_match,
            title_similarity=title_similarity,
            bib_title=bib_entry.title,
            fetched_title=fetched_title,
            author_match=author_match,
            author_similarity=author_similarity,
            bib_authors=bib_authors,
            fetched_authors=fetched_author_list,
            year_match=year_match,
            bib_year=bib_year,
            fetched_year=fetched_year_str,
            is_match=is_match,
            confidence=confidence,
            issues=issues,
            source=source,
        )

    def _normalize_fetched_authors(self, authors: list[str] | str) -> list[str]:
        if not authors:
            return []

        if isinstance(authors, str):
            raw_parts = [p.strip() for p in authors.split(",") if p.strip()]
            return [self.normalizer.normalize_author_name(p) for p in raw_parts]

        return [self.normalizer.normalize_author_name(a) for a in authors if a]

    def _compare_author_lists(self, list1: list[str], list2: list[str]) -> float:
        if not list1 and not list2:
            return 1.0
        if not list1 or not list2:
            return 0.0

        total_similarity = 0.0
        for author1 in list1:
            best_match = 0.0
            for author2 in list2:
                if self._names_match(author1, author2):
                    best_match = 1.0
                    break
                sim = self.normalizer.similarity_ratio(author1, author2)
                best_match = max(best_match, sim)
            total_similarity += best_match

        return total_similarity / len(list1)

    def _names_match(self, name1: str, name2: str) -> bool:
        words1 = name1.split()
        words2 = name2.split()

        if not words1 or not words2:
            return False

        if words1[-1] != words2[-1]:
            if words1[0] != words2[-1] and words1[-1] != words2[0]:
                return False

        return True


class _AsyncRateLimiter:
    """Simple async rate limiter with per-fetcher intervals."""

    def __init__(self, min_interval_s: float) -> None:
        self._min_interval_s = min_interval_s
        self._last_request_time = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._min_interval_s:
                await asyncio.sleep(self._min_interval_s - elapsed)
            self._last_request_time = time.monotonic()


class ArxivFetcher:
    """Fetch metadata from arXiv API."""

    API_BASE = "http://export.arxiv.org/api/query"
    RATE_LIMIT_DELAY = 3.0

    def __init__(self) -> None:
        self._rate_limiter = _AsyncRateLimiter(self.RATE_LIMIT_DELAY)

    async def fetch_by_id(self, arxiv_id: str) -> Optional[ArxivMetadata]:
        arxiv_id = arxiv_id.strip()
        arxiv_id = re.sub(r"^arXiv:", "", arxiv_id, flags=re.IGNORECASE)

        await self._rate_limiter.wait()
        params = {"id_list": arxiv_id, "max_results": 1}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    self.API_BASE,
                    params=params,
                    headers={"User-Agent": "SurveyMAE/0.1 (mailto:surveymae@example.com)"},
                )
                response.raise_for_status()
        except httpx.HTTPError:
            return None

        return self._parse_response(response.text)

    async def search_by_title(self, title: str, max_results: int = 5) -> list[ArxivMetadata]:
        await self._rate_limiter.wait()

        clean_title = re.sub(r"[^\w\s]", " ", title)
        clean_title = re.sub(r"\s+", " ", clean_title).strip()
        search_query = f'ti:"{clean_title}"'

        params = {
            "search_query": search_query,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    self.API_BASE,
                    params=params,
                    headers={"User-Agent": "SurveyMAE/0.1 (mailto:surveymae@example.com)"},
                )
                response.raise_for_status()
        except httpx.HTTPError:
            return []

        return self._parse_response_multiple(response.text)

    def _parse_response(self, xml_content: str) -> Optional[ArxivMetadata]:
        results = self._parse_response_multiple(xml_content)
        return results[0] if results else None

    def _parse_response_multiple(self, xml_content: str) -> list[ArxivMetadata]:
        results: list[ArxivMetadata] = []

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError:
            return results

        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }

        entries = root.findall("atom:entry", ns)
        for entry in entries:
            try:
                metadata = self._parse_entry(entry, ns)
                if metadata:
                    results.append(metadata)
            except Exception:
                continue

        return results

    def _parse_entry(self, entry: ET.Element, ns: dict[str, str]) -> Optional[ArxivMetadata]:
        id_elem = entry.find("atom:id", ns)
        if id_elem is None or id_elem.text is None:
            return None

        abs_url = id_elem.text.strip()
        match = re.search(r"arxiv\.org/abs/(.+)$", abs_url)
        arxiv_id = match.group(1) if match else ""

        title_elem = entry.find("atom:title", ns)
        title = self._clean_text(title_elem.text) if title_elem is not None else ""

        summary_elem = entry.find("atom:summary", ns)
        abstract = self._clean_text(summary_elem.text) if summary_elem is not None else ""

        authors = []
        for author_elem in entry.findall("atom:author", ns):
            name_elem = author_elem.find("atom:name", ns)
            if name_elem is not None and name_elem.text:
                authors.append(name_elem.text.strip())

        published_elem = entry.find("atom:published", ns)
        published = ""
        if published_elem is not None and published_elem.text:
            published = published_elem.text.strip()

        updated_elem = entry.find("atom:updated", ns)
        updated = ""
        if updated_elem is not None and updated_elem.text:
            updated = updated_elem.text.strip()

        categories = []
        for cat_elem in entry.findall("atom:category", ns):
            term = cat_elem.get("term")
            if term:
                categories.append(term)

        primary_cat_elem = entry.find("arxiv:primary_category", ns)
        primary_category = primary_cat_elem.get("term", "") if primary_cat_elem is not None else ""

        doi_elem = entry.find("arxiv:doi", ns)
        doi = doi_elem.text.strip() if doi_elem is not None and doi_elem.text else ""

        journal_elem = entry.find("arxiv:journal_ref", ns)
        journal_ref = ""
        if journal_elem is not None and journal_elem.text:
            journal_ref = journal_elem.text.strip()

        comment_elem = entry.find("arxiv:comment", ns)
        comment = ""
        if comment_elem is not None and comment_elem.text:
            comment = comment_elem.text.strip()

        pdf_url = abs_url.replace("/abs/", "/pdf/") + ".pdf"

        return ArxivMetadata(
            arxiv_id=arxiv_id,
            title=title,
            authors=authors,
            abstract=abstract,
            published=published,
            updated=updated,
            categories=categories,
            primary_category=primary_category,
            doi=doi,
            journal_ref=journal_ref,
            comment=comment,
            pdf_url=pdf_url,
            abs_url=abs_url,
        )

    def _clean_text(self, text: Optional[str]) -> str:
        if not text:
            return ""
        return re.sub(r"\s+", " ", text).strip()


class CrossRefFetcher:
    """Fetch metadata from CrossRef API."""

    BASE_URL = "https://api.crossref.org/works"
    RATE_LIMIT_DELAY = 1.0

    def __init__(self, mailto: str = "surveymae@example.com") -> None:
        self._mailto = mailto
        self._rate_limiter = _AsyncRateLimiter(self.RATE_LIMIT_DELAY)

    async def search_by_title(self, title: str, max_results: int = 5) -> Optional[CrossRefResult]:
        await self._rate_limiter.wait()

        params = {
            "query.title": title,
            "rows": max_results,
            "select": (
                "title,author,published-print,published-online,DOI,"
                "publisher,container-title,abstract"
            ),
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    self.BASE_URL,
                    params=params,
                    headers=self._get_headers(),
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError:
            return None

        if data.get("status") != "ok":
            return None

        items = data.get("message", {}).get("items", [])
        if not items:
            return None

        return self._parse_item(items[0])

    async def search_by_doi(self, doi: str) -> Optional[CrossRefResult]:
        await self._rate_limiter.wait()

        doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    f"{self.BASE_URL}/{doi}",
                    headers=self._get_headers(),
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError:
            return None

        if data.get("status") != "ok":
            return None

        return self._parse_item(data.get("message", {}))

    def _get_headers(self) -> dict[str, str]:
        return {
            "User-Agent": f"SurveyMAE/0.1 (mailto:{self._mailto})",
            "Accept": "application/json",
        }

    def _parse_item(self, item: dict[str, Any]) -> Optional[CrossRefResult]:
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
                    authors.append(f"{given} {family}".strip())

            year = ""
            for date_field in ["published-print", "published-online", "created"]:
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


class SemanticScholarFetcher:
    """Fetch metadata from Semantic Scholar API."""

    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    RATE_LIMIT_DELAY = 0.5
    _FIELDS = (
        "title,authors,year,abstract,paperId,citationCount,url,"
        "externalIds,references.paperId,references.externalIds"
    )

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key
        self._rate_limiter = _AsyncRateLimiter(self.RATE_LIMIT_DELAY)

    async def search_by_title(
        self,
        title: str,
        max_results: int = 5,
    ) -> Optional[SemanticScholarResult]:
        await self._rate_limiter.wait()

        url = f"{self.BASE_URL}/paper/search"
        params = {
            "query": title,
            "limit": max_results,
            "fields": self._FIELDS,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url, params=params, headers=self._headers())
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError:
            return None

        papers = data.get("data", [])
        if not papers:
            return None

        return self._parse_paper(papers[0])

    async def fetch_by_doi(self, doi: str) -> Optional[SemanticScholarResult]:
        await self._rate_limiter.wait()

        url = f"{self.BASE_URL}/paper/DOI:{doi}"
        params = {"fields": self._FIELDS}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url, params=params, headers=self._headers())
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError:
            return None

        return self._parse_paper(data)

    async def fetch_by_arxiv_id(self, arxiv_id: str) -> Optional[SemanticScholarResult]:
        await self._rate_limiter.wait()

        clean_id = arxiv_id.replace("arXiv:", "")
        url = f"{self.BASE_URL}/paper/ARXIV:{clean_id}"
        params = {"fields": self._FIELDS}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url, params=params, headers=self._headers())
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError:
            return None

        return self._parse_paper(data)

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._api_key:
            headers["x-api-key"] = self._api_key
        return headers

    def _parse_paper(self, paper_data: dict[str, Any]) -> Optional[SemanticScholarResult]:
        try:
            authors = []
            for author in paper_data.get("authors", []):
                name = author.get("name", "")
                if name:
                    authors.append(name)

            year = paper_data.get("year")
            year_str = str(year) if year else ""
            external_ids = paper_data.get("externalIds") or {}
            doi = str(external_ids.get("DOI") or external_ids.get("doi") or "").strip()
            arxiv_id = str(
                external_ids.get("ArXiv")
                or external_ids.get("arXiv")
                or external_ids.get("arxiv")
                or ""
            ).strip()
            openalex_id = str(
                external_ids.get("OpenAlex") or external_ids.get("openalex") or ""
            ).strip()
            reference_targets: list[dict[str, str]] = []
            for ref in paper_data.get("references", []) or []:
                if not isinstance(ref, dict):
                    continue
                target: dict[str, str] = {}
                ref_pid = str(ref.get("paperId") or "").strip()
                if ref_pid:
                    target["semantic_scholar_id"] = ref_pid
                ref_external_ids = ref.get("externalIds") or {}
                ref_doi = str(
                    ref_external_ids.get("DOI") or ref_external_ids.get("doi") or ""
                ).strip()
                if ref_doi:
                    target["doi"] = ref_doi
                ref_arxiv = str(
                    ref_external_ids.get("ArXiv")
                    or ref_external_ids.get("arXiv")
                    or ref_external_ids.get("arxiv")
                    or ""
                ).strip()
                if ref_arxiv:
                    target["arxiv_id"] = ref_arxiv
                ref_openalex = str(
                    ref_external_ids.get("OpenAlex") or ref_external_ids.get("openalex") or ""
                ).strip()
                if ref_openalex:
                    target["openalex_id"] = ref_openalex
                if target:
                    reference_targets.append(target)

            return SemanticScholarResult(
                title=paper_data.get("title", ""),
                authors=authors,
                year=year_str,
                abstract=paper_data.get("abstract", ""),
                paper_id=paper_data.get("paperId", ""),
                citation_count=paper_data.get("citationCount", 0),
                url=paper_data.get("url", ""),
                doi=doi,
                arxiv_id=arxiv_id,
                openalex_id=openalex_id,
                reference_targets=reference_targets,
            )
        except (KeyError, TypeError):
            return None


class OpenAlexFetcher:
    """Fetch metadata from OpenAlex API."""

    BASE_URL = "https://api.openalex.org"
    RATE_LIMIT_DELAY = 0.1

    def __init__(self, email: Optional[str] = None) -> None:
        self._email = email
        self._rate_limiter = _AsyncRateLimiter(self.RATE_LIMIT_DELAY)

    async def search_by_title(self, title: str, max_results: int = 5) -> Optional[OpenAlexResult]:
        await self._rate_limiter.wait()

        url = f"{self.BASE_URL}/works"
        params = {"search": title, "per-page": max_results}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url, params=params, headers=self._headers())
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError:
            return None

        results = data.get("results", [])
        if not results:
            return None

        return self._parse_work(results[0])

    async def fetch_by_doi(self, doi: str) -> Optional[OpenAlexResult]:
        await self._rate_limiter.wait()

        doi_url = f"https://doi.org/{doi}"
        url = f"{self.BASE_URL}/works/{doi_url}"

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url, headers=self._headers())
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError:
            return None

        return self._parse_work(data)

    def _headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": "SurveyMAE/0.1 (mailto:surveymae@example.com)",
        }
        if self._email:
            headers["From"] = self._email
        return headers

    def _parse_work(self, work_data: dict[str, Any]) -> Optional[OpenAlexResult]:
        try:
            title = work_data.get("title", "")

            authors = []
            for authorship in work_data.get("authorships", []):
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
            openalex_id = str(work_data.get("id", "")).strip()
            reference_targets: list[dict[str, str]] = []
            for target in work_data.get("referenced_works", []) or []:
                target_id = str(target).strip()
                if target_id:
                    reference_targets.append({"openalex_id": target_id})

            return OpenAlexResult(
                title=title,
                authors=authors,
                year=year_str,
                abstract=abstract,
                doi=doi,
                citation_count=citation_count,
                url=url,
                openalex_id=openalex_id,
                reference_targets=reference_targets,
            )
        except (KeyError, TypeError):
            return None

    def _reconstruct_abstract(self, inverted_index: dict[str, list[int]]) -> str:
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


class DBLPFetcher:
    """Fetch metadata from DBLP API."""

    BASE_URL = "https://dblp.org/search/publ/api"
    RATE_LIMIT_DELAY = 1.5

    def __init__(self) -> None:
        self._rate_limiter = _AsyncRateLimiter(self.RATE_LIMIT_DELAY)

    async def search_by_title(self, title: str) -> Optional[DBLPResult]:
        await self._rate_limiter.wait()

        params = {"q": title, "format": "json", "h": 3}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(self.BASE_URL, params=params)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError:
            return None

        return self._parse_response(data)

    def _parse_response(self, data: dict[str, Any]) -> Optional[DBLPResult]:
        try:
            hits = data.get("result", {}).get("hits", {}).get("hit", [])
            if not hits:
                return None

            best_hit = hits[0]
            info = best_hit.get("info", {})

            authors_data = info.get("authors", {}).get("author", [])
            authors = []
            if isinstance(authors_data, list):
                authors = [a.get("text", "") for a in authors_data if isinstance(a, dict)]
            elif isinstance(authors_data, dict):
                authors = [authors_data.get("text", "")]

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
        except Exception:
            return None


@dataclass
class VerificationReport:
    """Verification report for a single bibliography entry."""

    key: str
    is_valid: bool
    confidence: float
    issues: list[str]
    source: str
    sources_checked: list[str]
    comparison: Optional[ComparisonResult] = None
    metadata: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "key": self.key,
            "is_valid": self.is_valid,
            "confidence": self.confidence,
            "issues": self.issues,
            "source": self.source,
            "sources_checked": self.sources_checked,
        }
        if self.comparison:
            result["comparison"] = self.comparison.to_dict()
        if self.metadata:
            result["metadata"] = self.metadata
        return result


class CitationMetadataChecker:
    """Fetch and compare metadata for bibliography entries."""

    DEFAULT_SOURCES = ("arxiv", "crossref", "semantic_scholar", "openalex", "dblp")

    def __init__(
        self,
        crossref_mailto: Optional[str] = None,
        semantic_scholar_api_key: Optional[str] = None,
        openalex_email: Optional[str] = None,
        title_threshold: Optional[float] = None,
        author_threshold: Optional[float] = None,
        config_path: Optional[str] = None,
    ) -> None:
        config = load_search_engine_config(config_path)
        if semantic_scholar_api_key is None:
            semantic_scholar_api_key = config.semantic_scholar_api_key
        if crossref_mailto is None:
            crossref_mailto = config.crossref_mailto
        if openalex_email is None:
            openalex_email = config.openalex_email

        self.comparator = MetadataComparator(
            title_threshold=title_threshold,
            author_threshold=author_threshold,
        )
        self.arxiv_fetcher = ArxivFetcher()
        self.crossref_fetcher = CrossRefFetcher(mailto=crossref_mailto or "surveymae@example.com")
        self.semantic_scholar_fetcher = SemanticScholarFetcher(api_key=semantic_scholar_api_key)
        self.openalex_fetcher = OpenAlexFetcher(email=openalex_email)
        self.dblp_fetcher = DBLPFetcher()

    async def verify_bib_entry(
        self,
        bib_entry: BibEntry,
        sources: Optional[Iterable[str]] = None,
    ) -> VerificationReport:
        """Verify a single bib entry using external metadata sources."""
        sources_checked: list[str] = []
        sources_to_check = list(sources or self.DEFAULT_SOURCES)

        for source in sources_to_check:
            source = source.lower().strip()
            sources_checked.append(source)

            if source == "arxiv":
                result = await self._verify_with_arxiv(bib_entry)
            elif source == "crossref":
                result = await self._verify_with_crossref(bib_entry)
            elif source == "semantic_scholar":
                result = await self._verify_with_semantic_scholar(bib_entry)
            elif source == "openalex":
                result = await self._verify_with_openalex(bib_entry)
            elif source == "dblp":
                result = await self._verify_with_dblp(bib_entry)
            else:
                continue

            if result is not None:
                result.sources_checked = sources_checked
                return result

        unable = self.comparator.create_unable_result(
            bib_entry=bib_entry,
            reason="Unable to fetch metadata from configured sources",
        )
        return VerificationReport(
            key=bib_entry.key,
            is_valid=False,
            confidence=0.0,
            issues=unable.issues,
            source="unable",
            sources_checked=sources_checked,
            comparison=unable,
        )

    def compare_metadata(
        self,
        bib_entry: BibEntry,
        metadata: dict[str, Any],
        source: str,
    ) -> ComparisonResult:
        """Compare a bib entry with provided metadata fields."""
        title = str(metadata.get("title", ""))
        authors = metadata.get("authors") or metadata.get("author", "")
        year = str(metadata.get("year", ""))
        return self.comparator.compare_generic(
            bib_entry=bib_entry,
            title=title,
            authors=authors,
            year=year,
            source=source,
        )

    async def _verify_with_arxiv(self, bib_entry: BibEntry) -> Optional[VerificationReport]:
        meta = None
        if bib_entry.arxiv_id:
            meta = await self.arxiv_fetcher.fetch_by_id(bib_entry.arxiv_id)
        if not meta and bib_entry.title:
            results = await self.arxiv_fetcher.search_by_title(bib_entry.title)
            meta = results[0] if results else None

        if not meta:
            return None

        comparison = self.comparator.compare_with_arxiv(bib_entry, meta)
        return self._build_report(bib_entry, comparison, meta)

    async def _verify_with_crossref(self, bib_entry: BibEntry) -> Optional[VerificationReport]:
        meta = None
        if bib_entry.doi:
            meta = await self.crossref_fetcher.search_by_doi(bib_entry.doi)
        if not meta and bib_entry.title:
            meta = await self.crossref_fetcher.search_by_title(bib_entry.title)

        if not meta:
            return None

        comparison = self.comparator.compare_with_crossref(bib_entry, meta)
        return self._build_report(bib_entry, comparison, meta)

    async def _verify_with_semantic_scholar(
        self,
        bib_entry: BibEntry,
    ) -> Optional[VerificationReport]:
        meta = None
        if bib_entry.doi:
            meta = await self.semantic_scholar_fetcher.fetch_by_doi(bib_entry.doi)
        if not meta and bib_entry.arxiv_id:
            meta = await self.semantic_scholar_fetcher.fetch_by_arxiv_id(bib_entry.arxiv_id)
        if not meta and bib_entry.title:
            meta = await self.semantic_scholar_fetcher.search_by_title(bib_entry.title)

        if not meta:
            return None

        comparison = self.comparator.compare_with_semantic_scholar(bib_entry, meta)
        return self._build_report(bib_entry, comparison, meta)

    async def _verify_with_openalex(self, bib_entry: BibEntry) -> Optional[VerificationReport]:
        meta = None
        if bib_entry.doi:
            meta = await self.openalex_fetcher.fetch_by_doi(bib_entry.doi)
        if not meta and bib_entry.title:
            meta = await self.openalex_fetcher.search_by_title(bib_entry.title)

        if not meta:
            return None

        comparison = self.comparator.compare_with_openalex(bib_entry, meta)
        return self._build_report(bib_entry, comparison, meta)

    async def _verify_with_dblp(self, bib_entry: BibEntry) -> Optional[VerificationReport]:
        if not bib_entry.title:
            return None

        meta = await self.dblp_fetcher.search_by_title(bib_entry.title)
        if not meta:
            return None

        comparison = self.comparator.compare_with_dblp(bib_entry, meta)
        return self._build_report(bib_entry, comparison, meta)

    def _build_report(
        self,
        bib_entry: BibEntry,
        comparison: ComparisonResult,
        metadata: Any,
    ) -> VerificationReport:
        return VerificationReport(
            key=bib_entry.key or bib_entry.title,
            is_valid=comparison.is_match,
            confidence=comparison.confidence,
            issues=comparison.issues,
            source=comparison.source,
            sources_checked=[comparison.source],
            comparison=comparison,
            metadata=self._serialize_metadata(metadata),
        )

    def _serialize_metadata(self, metadata: Any) -> dict[str, Any]:
        if hasattr(metadata, "__dataclass_fields__"):
            return asdict(metadata)
        if isinstance(metadata, dict):
            return metadata
        return {"value": str(metadata)}


def bib_entry_from_dict(data: dict[str, Any]) -> BibEntry:
    """Build a BibEntry from a plain dictionary."""
    key = str(data.get("key", "")).strip()
    title = str(data.get("title", "")).strip()
    author = str(data.get("author", "")).strip()
    year = str(data.get("year", "")).strip()
    doi = str(data.get("doi", "")).strip()
    arxiv_id = str(data.get("arxiv_id", "")).strip()
    entry_type = str(data.get("entry_type", "")).strip()

    return BibEntry(
        key=key or title,
        title=title,
        author=author,
        year=year,
        doi=doi,
        arxiv_id=arxiv_id,
        entry_type=entry_type,
        raw_entry=dict(data),
    )
