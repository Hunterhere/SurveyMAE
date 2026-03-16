"""Literature search tool backed by BibGuard fetchers.

Provides a unified interface to query multiple scholarly sources.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from functools import wraps
from typing import Any, Callable, Iterable, Optional, TypeVar

from src.core.search_config import load_search_engine_config
from src.tools.fetchers.arxiv_fetcher import ArxivFetcher, ArxivMetadata
from src.tools.fetchers.crossref_fetcher import CrossRefFetcher, CrossRefResult
from src.tools.fetchers.dblp_fetcher import DBLPFetcher, DBLPResult
from src.tools.fetchers.openalex_fetcher import OpenAlexFetcher, OpenAlexResult
from src.tools.fetchers.scholar_fetcher import ScholarFetcher, ScholarResult
from src.tools.fetchers.semantic_scholar_fetcher import (
    SemanticScholarFetcher,
    SemanticScholarResult,
)

logger = logging.getLogger(__name__)

# Retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0  # seconds
DEFAULT_RETRY_BACKOFF = 2.0  # exponential backoff multiplier

T = TypeVar("T")


def with_retry(
    max_retries: int = DEFAULT_MAX_RETRIES,
    delay: float = DEFAULT_RETRY_DELAY,
    backoff: float = DEFAULT_RETRY_BACKOFF,
    exceptions: tuple = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to retry a function on failure with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts.
        delay: Initial delay between retries in seconds.
        backoff: Multiplier for exponential backoff.
        exceptions: Tuple of exceptions to catch and retry on.

    Returns:
        Decorated function with retry logic.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Optional[Exception] = None
            current_delay = delay

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            "Attempt %d/%d failed for %s: %s. Retrying in %.1fs...",
                            attempt + 1,
                            max_retries + 1,
                            func.__name__,
                            e,
                            current_delay,
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            "All %d attempts failed for %s: %s",
                            max_retries + 1,
                            func.__name__,
                            e,
                        )
            # This should never happen but satisfies type checker
            raise last_exception if last_exception else Exception("Retry failed")

        return wrapper

    return decorator


@dataclass
class LiteratureResult:
    """Normalized metadata result across sources."""

    source: str
    title: str
    authors: list[str]
    year: str
    doi: str = ""
    arxiv_id: str = ""
    url: str = ""
    abstract: str = ""
    citation_count: Optional[int] = None
    venue: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON output."""
        return asdict(self)


class LiteratureSearch:
    """Search literature across multiple sources."""

    DEFAULT_SOURCES = ("arxiv", "crossref", "semantic_scholar", "openalex", "dblp")
    ALL_SOURCES = DEFAULT_SOURCES + ("scholar",)
    DOI_SOURCES = ("crossref", "semantic_scholar", "openalex")
    ARXIV_SOURCES = ("arxiv", "semantic_scholar")

    def __init__(
        self,
        crossref_mailto: Optional[str] = None,
        semantic_scholar_api_key: Optional[str] = None,
        openalex_email: Optional[str] = None,
        fetchers: Optional[dict[str, Any]] = None,
        config_path: Optional[str] = None,
    ) -> None:
        if fetchers is not None:
            self.fetchers = {k.lower(): v for k, v in fetchers.items()}
            return

        config = load_search_engine_config(config_path)
        if semantic_scholar_api_key is None:
            semantic_scholar_api_key = config.semantic_scholar_api_key
        if crossref_mailto is None:
            crossref_mailto = config.crossref_mailto
        if openalex_email is None:
            openalex_email = config.openalex_email

        self.fetchers = {
            "arxiv": ArxivFetcher(),
            "crossref": CrossRefFetcher(mailto=crossref_mailto or "surveymae@example.com"),
            "semantic_scholar": SemanticScholarFetcher(api_key=semantic_scholar_api_key),
            "openalex": OpenAlexFetcher(email=openalex_email),
            "dblp": DBLPFetcher(),
            "scholar": ScholarFetcher(),
        }

    def list_sources(self) -> list[str]:
        """Return available source identifiers."""
        return sorted(self.fetchers.keys())

    def search_literature(
        self,
        *,
        title: Optional[str] = None,
        doi: Optional[str] = None,
        arxiv_id: Optional[str] = None,
        sources: Optional[Iterable[str]] = None,
        max_results: int = 5,
        include_scholar: bool = False,
    ) -> list[LiteratureResult]:
        """Search by DOI, arXiv ID, or title (in that priority order)."""
        if doi:
            return self.fetch_by_doi(doi, sources=sources)
        if arxiv_id:
            return self.fetch_by_arxiv_id(arxiv_id, sources=sources)
        if title:
            return self.search_by_title(
                title,
                sources=sources,
                max_results=max_results,
                include_scholar=include_scholar,
            )
        raise ValueError("One of title, doi, or arxiv_id must be provided.")

    def search_by_title(
        self,
        title: str,
        *,
        sources: Optional[Iterable[str]] = None,
        max_results: int = 5,
        include_scholar: bool = False,
    ) -> list[LiteratureResult]:
        """Search for a paper by title across sources."""
        if not title:
            raise ValueError("title is required")

        resolved = self._resolve_sources(sources, include_scholar=include_scholar)
        results: list[LiteratureResult] = []

        for source in resolved:
            fetcher = self.fetchers[source]
            raw = None
            try:
                if source == "arxiv":
                    raw = fetcher.search_by_title(title, max_results=max_results)
                elif source == "crossref":
                    raw = fetcher.search_by_title(title, max_results=max_results)
                elif source == "semantic_scholar":
                    raw = fetcher.search_by_title(title, max_results=max_results)
                elif source == "openalex":
                    raw = fetcher.search_by_title(title, max_results=max_results)
                elif source == "dblp":
                    raw = fetcher.search_by_title(title)
                elif source == "scholar":
                    raw = fetcher.search_by_title(title)
            except Exception as exc:
                logger.warning("Search failed for %s: %s", source, exc)
                continue

            for item in self._ensure_list(raw):
                normalized = self._normalize_result(source, item)
                if normalized:
                    results.append(normalized)

        return results

    def fetch_by_doi(
        self,
        doi: str,
        *,
        sources: Optional[Iterable[str]] = None,
    ) -> list[LiteratureResult]:
        """Fetch metadata by DOI across supported sources."""
        if not doi:
            raise ValueError("doi is required")

        resolved = self._resolve_sources(sources, only=self.DOI_SOURCES)
        results: list[LiteratureResult] = []

        for source in resolved:
            fetcher = self.fetchers[source]
            raw = None
            try:
                if source == "crossref":
                    raw = fetcher.search_by_doi(doi)
                elif source == "semantic_scholar":
                    raw = fetcher.fetch_by_doi(doi)
                elif source == "openalex":
                    raw = fetcher.fetch_by_doi(doi)
            except Exception as exc:
                logger.warning("DOI fetch failed for %s: %s", source, exc)
                continue

            for item in self._ensure_list(raw):
                normalized = self._normalize_result(source, item)
                if normalized:
                    results.append(normalized)

        return results

    def fetch_by_arxiv_id(
        self,
        arxiv_id: str,
        *,
        sources: Optional[Iterable[str]] = None,
    ) -> list[LiteratureResult]:
        """Fetch metadata by arXiv ID across supported sources."""
        if not arxiv_id:
            raise ValueError("arxiv_id is required")

        resolved = self._resolve_sources(sources, only=self.ARXIV_SOURCES)
        results: list[LiteratureResult] = []

        for source in resolved:
            fetcher = self.fetchers[source]
            raw = None
            try:
                if source == "arxiv":
                    raw = fetcher.fetch_by_id(arxiv_id)
                elif source == "semantic_scholar":
                    raw = fetcher.fetch_by_arxiv_id(arxiv_id)
            except Exception as exc:
                logger.warning("arXiv fetch failed for %s: %s", source, exc)
                continue

            for item in self._ensure_list(raw):
                normalized = self._normalize_result(source, item)
                if normalized:
                    results.append(normalized)

        return results

    def search_by_keywords(
        self,
        keywords: str,
        *,
        sources: Optional[Iterable[str]] = None,
        max_results: int = 20,
        sort_by: str = "citation_count",
        include_scholar: bool = False,
    ) -> list[LiteratureResult]:
        """Search for papers by keywords across sources.

        Args:
            keywords: Keyword query string.
            sources: List of sources to query (default: semantic_scholar, openalex).
            max_results: Maximum results per source.
            sort_by: Sort order - "citation_count" or "relevance".
            include_scholar: Whether to include Google Scholar (slow).

        Returns:
            List of literature results sorted by citation count.
        """
        if not keywords:
            raise ValueError("keywords is required")

        # Default to sources that support citation sorting
        if sources is None:
            sources = ["semantic_scholar", "openalex"]

        resolved = self._resolve_sources(sources, include_scholar=include_scholar)
        results: list[LiteratureResult] = []

        for source in resolved:
            fetcher = self.fetchers[source]
            raw = None
            try:
                # Use search endpoint with keywords
                if source == "semantic_scholar":
                    # Semantic Scholar search uses query param
                    raw = fetcher.search_by_title(keywords, max_results=max_results)
                elif source == "openalex":
                    # OpenAlex search uses 'search' param
                    url = f"{fetcher.BASE_URL}/works"
                    params = {"search": keywords, "per-page": max_results}
                    import requests as _requests

                    response = _requests.get(url, params=params, timeout=10)
                    response.raise_for_status()
                    data = response.json()
                    raw = data.get("results", []) if isinstance(data, dict) else []
                elif source == "crossref":
                    raw = fetcher.search_by_title(keywords, max_results=max_results)
                elif source == "dblp":
                    raw = fetcher.search_by_title(keywords)
                elif source == "arxiv":
                    raw = fetcher.search_by_title(keywords, max_results=max_results)
                elif source == "scholar":
                    raw = fetcher.search_by_title(keywords)
            except Exception as exc:
                logger.warning("Keyword search failed for %s: %s", source, exc)
                continue

            for item in self._ensure_list(raw):
                normalized = self._normalize_result(source, item)
                if normalized:
                    results.append(normalized)

        # Sort by citation count if requested
        if sort_by == "citation_count":
            results.sort(key=lambda x: x.citation_count or 0, reverse=True)

        # Deduplicate by title (case-insensitive)
        seen_titles: set[str] = set()
        deduplicated: list[LiteratureResult] = []
        for r in results:
            title_lower = r.title.lower().strip()
            if title_lower not in seen_titles:
                seen_titles.add(title_lower)
                deduplicated.append(r)

        return deduplicated[:max_results]

    def search_field_trend(
        self,
        keywords: str,
        year_range: Optional[tuple[int, int]] = None,
        *,
        sources: Optional[Iterable[str]] = None,
    ) -> dict[str, Any]:
        """Search for paper counts by year to build field trend baseline.

        This is used for T5 (trend_alignment) metric calculation.

        Args:
            keywords: Keyword query for the field.
            year_range: (start_year, end_year) tuple.
            sources: Sources to query.

        Returns:
            Dict with year -> count mapping.
        """
        if year_range is None:
            import datetime as _dt

            current_year = _dt.datetime.now().year
            year_range = (max(2000, current_year - 25), current_year)

        start_year, end_year = year_range

        # Use Semantic Scholar or OpenAlex for year-based search
        if sources is None:
            sources = ["semantic_scholar", "openalex"]

        resolved = self._resolve_sources(sources)
        yearly_counts: dict[str, int] = {str(y): 0 for y in range(start_year, end_year + 1)}
        failed_sources: list[str] = []

        for source in resolved:
            try:
                if source == "semantic_scholar":
                    # Apply retry to semantic scholar search
                    count = self._search_field_trend_semantic_scholar(
                        fetcher=self.fetchers[source],
                        keywords=keywords,
                        start_year=start_year,
                        end_year=end_year,
                    )
                    for year_str, c in count.items():
                        yearly_counts[year_str] += c
                elif source == "openalex":
                    # Apply retry to openalex search
                    count = self._search_field_trend_openalex(
                        fetcher=self.fetchers[source],
                        keywords=keywords,
                        start_year=start_year,
                        end_year=end_year,
                    )
                    for year_str, c in count.items():
                        yearly_counts[year_str] += c
            except Exception as exc:
                logger.warning("Field trend search failed for %s: %s", source, exc)
                failed_sources.append(source)
                continue

        # Log summary of failures
        if failed_sources:
            logger.warning(
                "Field trend search failed for all retries on sources: %s. "
                "Results may be incomplete.",
                failed_sources,
            )

        # Check if all sources failed
        if len(failed_sources) == len(resolved) and not any(
            yearly_counts.values()
        ):
            logger.error(
                "All sources failed for field trend search. Returning empty results."
            )

        return {
            "yearly_counts": yearly_counts,
            "year_range": {"start": start_year, "end": end_year},
            "keywords": keywords,
            "failed_sources": failed_sources,
        }

    @with_retry(max_retries=2, delay=0.5)
    def _search_field_trend_semantic_scholar(
        self,
        fetcher: SemanticScholarFetcher,
        keywords: str,
        start_year: int,
        end_year: int,
    ) -> dict[str, int]:
        """Search Semantic Scholar for field trend with retry."""
        yearly_counts: dict[str, int] = {}
        results = fetcher.search_by_title(keywords, max_results=50)
        for r in self._ensure_list(results):
            if r.year:
                year_str = r.year if isinstance(r.year, str) else str(r.year)
                if year_str.isdigit():
                    y = int(year_str)
                    if start_year <= y <= end_year:
                        yearly_counts[year_str] = yearly_counts.get(year_str, 0) + 1
        return yearly_counts

    @with_retry(max_retries=2, delay=0.5)
    def _search_field_trend_openalex(
        self,
        fetcher: OpenAlexFetcher,
        keywords: str,
        start_year: int,
        end_year: int,
    ) -> dict[str, int]:
        """Search OpenAlex for field trend with retry."""
        import requests as _requests

        yearly_counts: dict[str, int] = {}
        for year in range(start_year, end_year + 1):
            url = f"{fetcher.BASE_URL}/works"
            params = {
                "search": keywords,
                "filter": f"publication_year:{year}",
                "per-page": 1,
            }
            response = _requests.get(url, params=params, timeout=10)
            if response.ok:
                data = response.json()
                count = (
                    data.get("meta", {}).get("count", 0)
                    if isinstance(data, dict)
                    else 0
                )
                yearly_counts[str(year)] = count
        return yearly_counts

    async def search_top_cited(
        self,
        keywords: str | list[str],
        top_k: int = 30,
    ) -> list[dict[str, Any]]:
        """Search for top-cited papers by keywords.

        This is used for G4 (foundational_coverage_rate) metric calculation.

        Args:
            keywords: Keyword query string or list of keywords.
            top_k: Number of top-cited papers to retrieve.

        Returns:
            List of paper dicts with title, citation_count, year, venue, etc.
        """
        # Handle both string and list input
        if isinstance(keywords, list):
            keywords = " ".join(keywords[:3])  # Use first 3 keywords

        # Use search_by_keywords which already sorts by citation_count
        results = self.search_by_keywords(
            keywords=keywords,
            max_results=top_k,
            sort_by="citation_count",
        )

        # Convert to dict format for foundational coverage analysis
        papers = []
        for r in results:
            papers.append(
                {
                    "title": r.title,
                    "authors": r.authors,
                    "year": r.year,
                    "citation_count": r.citation_count or 0,
                    "venue": r.venue or "",
                    "doi": r.doi or "",
                    "url": r.url or "",
                    "abstract": r.abstract or "",
                }
            )

        return papers

    def _resolve_sources(
        self,
        sources: Optional[Iterable[str]],
        *,
        include_scholar: bool = False,
        only: Optional[Iterable[str]] = None,
    ) -> list[str]:
        if sources is None:
            if only is not None:
                resolved = [s.lower() for s in only]
            else:
                resolved = list(self.DEFAULT_SOURCES)
                if include_scholar:
                    resolved.append("scholar")
        else:
            resolved = [str(s).lower().strip() for s in sources if str(s).strip()]

        if only is not None:
            allowed = {s.lower() for s in only}
            invalid = [s for s in resolved if s not in allowed]
            if invalid:
                raise ValueError(f"Unsupported sources for this query: {invalid}")
            resolved = [s for s in resolved if s in allowed]

        missing = [s for s in resolved if s not in self.fetchers]
        if missing:
            raise ValueError(f"Unknown sources: {missing}")

        return resolved

    def _ensure_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def _normalize_result(self, source: str, item: Any) -> Optional[LiteratureResult]:
        try:
            if source == "arxiv" and isinstance(item, ArxivMetadata):
                return LiteratureResult(
                    source=source,
                    title=item.title,
                    authors=item.authors,
                    year=item.year,
                    doi=item.doi,
                    arxiv_id=item.arxiv_id,
                    url=item.abs_url,
                    abstract=item.abstract,
                    raw=_as_dict(item),
                )
            if source == "crossref" and isinstance(item, CrossRefResult):
                return LiteratureResult(
                    source=source,
                    title=item.title,
                    authors=item.authors,
                    year=item.year,
                    doi=item.doi,
                    url=item.url,
                    abstract=item.abstract,
                    raw=_as_dict(item),
                )
            if source == "semantic_scholar" and isinstance(item, SemanticScholarResult):
                return LiteratureResult(
                    source=source,
                    title=item.title,
                    authors=item.authors,
                    year=item.year,
                    url=item.url,
                    abstract=item.abstract,
                    citation_count=item.citation_count,
                    raw=_as_dict(item),
                )
            if source == "openalex" and isinstance(item, OpenAlexResult):
                return LiteratureResult(
                    source=source,
                    title=item.title,
                    authors=item.authors,
                    year=item.year,
                    doi=item.doi,
                    url=item.url,
                    abstract=item.abstract,
                    citation_count=item.citation_count,
                    raw=_as_dict(item),
                )
            if source == "dblp" and isinstance(item, DBLPResult):
                return LiteratureResult(
                    source=source,
                    title=item.title,
                    authors=item.authors,
                    year=item.year,
                    doi=item.doi or "",
                    url=item.url,
                    raw=_as_dict(item),
                )
            if source == "scholar" and isinstance(item, ScholarResult):
                authors = _split_authors(item.authors)
                return LiteratureResult(
                    source=source,
                    title=item.title,
                    authors=authors,
                    year=item.year,
                    url=item.url,
                    abstract=item.snippet,
                    citation_count=item.cited_by,
                    raw=_as_dict(item),
                )
        except Exception as exc:
            logger.warning("Failed to normalize %s result: %s", source, exc)

        return None


def _split_authors(authors: str) -> list[str]:
    if not authors:
        return []
    return [a.strip() for a in authors.split(",") if a.strip()]


def _as_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    return {"value": str(value)}


def create_literature_search_mcp_server():
    """Create an MCP server for literature search."""
    from mcp.server import Server
    from mcp.types import TextContent, Tool

    app = Server("literature-search")
    searcher = LiteratureSearch()

    def _select_searcher(arguments: dict) -> LiteratureSearch:
        config_path = arguments.get("config_path")
        if any(
            key in arguments
            for key in ("crossref_mailto", "semantic_scholar_api_key", "openalex_email")
        ):
            return LiteratureSearch(
                crossref_mailto=arguments.get("crossref_mailto", "surveymae@example.com"),
                semantic_scholar_api_key=arguments.get("semantic_scholar_api_key"),
                openalex_email=arguments.get("openalex_email"),
                config_path=config_path,
            )
        if config_path:
            return LiteratureSearch(config_path=config_path)
        return searcher

    @app.list_tools()
    async def list_tools():
        base_props = {
            "sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ordered list of sources to query",
            },
            "config_path": {
                "type": "string",
                "description": "Optional path to search_engines.yaml",
            },
            "crossref_mailto": {
                "type": "string",
                "description": "Email for CrossRef polite pool",
            },
            "semantic_scholar_api_key": {
                "type": "string",
                "description": "Semantic Scholar API key (optional)",
            },
            "openalex_email": {
                "type": "string",
                "description": "Email for OpenAlex polite pool",
            },
        }

        return [
            Tool(
                name="search_literature",
                description="Search by DOI, arXiv ID, or title (priority order)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "doi": {"type": "string"},
                        "arxiv_id": {"type": "string"},
                        "max_results": {
                            "type": "integer",
                            "description": "Max results for title search",
                            "default": 5,
                        },
                        "include_scholar": {
                            "type": "boolean",
                            "description": "Include Google Scholar (slow/scraping)",
                            "default": False,
                        },
                        **base_props,
                    },
                },
            ),
            Tool(
                name="search_by_title",
                description="Search by paper title across sources",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "max_results": {
                            "type": "integer",
                            "description": "Max results for title search",
                            "default": 5,
                        },
                        "include_scholar": {
                            "type": "boolean",
                            "description": "Include Google Scholar (slow/scraping)",
                            "default": False,
                        },
                        **base_props,
                    },
                    "required": ["title"],
                },
            ),
            Tool(
                name="fetch_by_doi",
                description="Fetch metadata by DOI",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "doi": {"type": "string"},
                        **base_props,
                    },
                    "required": ["doi"],
                },
            ),
            Tool(
                name="fetch_by_arxiv_id",
                description="Fetch metadata by arXiv ID",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "arxiv_id": {"type": "string"},
                        **base_props,
                    },
                    "required": ["arxiv_id"],
                },
            ),
            Tool(
                name="list_sources",
                description="List available literature sources",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
            tool_searcher = _select_searcher(arguments)

            if name == "list_sources":
                payload = tool_searcher.list_sources()
                return [TextContent(type="text", text=json.dumps(payload))]

            if name == "search_literature":
                results = tool_searcher.search_literature(
                    title=arguments.get("title"),
                    doi=arguments.get("doi"),
                    arxiv_id=arguments.get("arxiv_id"),
                    sources=arguments.get("sources"),
                    max_results=arguments.get("max_results", 5),
                    include_scholar=arguments.get("include_scholar", False),
                )
                return [TextContent(type="text", text=json.dumps(_serialize(results)))]

            if name == "search_by_title":
                results = tool_searcher.search_by_title(
                    arguments["title"],
                    sources=arguments.get("sources"),
                    max_results=arguments.get("max_results", 5),
                    include_scholar=arguments.get("include_scholar", False),
                )
                return [TextContent(type="text", text=json.dumps(_serialize(results)))]

            if name == "fetch_by_doi":
                results = tool_searcher.fetch_by_doi(
                    arguments["doi"],
                    sources=arguments.get("sources"),
                )
                return [TextContent(type="text", text=json.dumps(_serialize(results)))]

            if name == "fetch_by_arxiv_id":
                results = tool_searcher.fetch_by_arxiv_id(
                    arguments["arxiv_id"],
                    sources=arguments.get("sources"),
                )
                return [TextContent(type="text", text=json.dumps(_serialize(results)))]

            return [TextContent(type="text", text=f"Unknown tool: {name}", isError=True)]
        except Exception as exc:
            return [TextContent(type="text", text=str(exc), isError=True)]

    return app


def _serialize(results: list[LiteratureResult]) -> list[dict[str, Any]]:
    return [r.to_dict() for r in results]
