"""Fetcher implementations reused from BibGuard.

These classes provide metadata retrieval from multiple scholarly sources.
Based on BibGuard (https://github.com/thinkwee/BibGuard), Apache License 2.0.
"""

from .arxiv_fetcher import ArxivFetcher, ArxivMetadata
from .crossref_fetcher import CrossRefFetcher, CrossRefResult
from .semantic_scholar_fetcher import SemanticScholarFetcher, SemanticScholarResult
from .openalex_fetcher import OpenAlexFetcher, OpenAlexResult
from .dblp_fetcher import DBLPFetcher, DBLPResult
from .scholar_fetcher import ScholarFetcher, ScholarResult

__all__ = [
    "ArxivFetcher",
    "ArxivMetadata",
    "CrossRefFetcher",
    "CrossRefResult",
    "SemanticScholarFetcher",
    "SemanticScholarResult",
    "OpenAlexFetcher",
    "OpenAlexResult",
    "DBLPFetcher",
    "DBLPResult",
    "ScholarFetcher",
    "ScholarResult",
]
