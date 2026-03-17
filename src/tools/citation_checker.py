"""Citation Checker Tool.

Provides citation extraction and verification functionality.
Can be used to check if cited papers exist and match claims.
"""

import re
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Any, Iterable, Tuple

import httpx

from src.tools.citation_metadata import (
    CitationMetadataChecker,
    bib_entry_from_dict,
)
from src.tools.pdf_parser import PDFParser
from src.tools.result_store import ResultStore
from src.core.config import load_config, SurveyMAEConfig

logger = logging.getLogger(__name__)


@dataclass
class CitationSpan:
    """In-text citation with location context."""

    marker: str
    kind: str
    sentence: str
    page: int
    paragraph_index: int
    line_in_paragraph: int
    bbox: Optional[Tuple[float, float, float, float]] = None
    reference_number: Optional[int] = None
    author: str = ""
    year: str = ""
    ref_key: Optional[str] = None
    ref_candidates: list[str] = field(default_factory=list)
    marker_raw: Optional[str] = None
    section_title: Optional[str] = None
    section_index: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "marker": self.marker,
            "marker_raw": self.marker_raw,
            "kind": self.kind,
            "sentence": self.sentence,
            "page": self.page,
            "paragraph_index": self.paragraph_index,
            "line_in_paragraph": self.line_in_paragraph,
            "bbox": self.bbox,
            "reference_number": self.reference_number,
            "author": self.author,
            "year": self.year,
            "ref_key": self.ref_key,
            "ref_candidates": self.ref_candidates,
            "section_title": self.section_title,
            "section_index": self.section_index,
        }


@dataclass
class ReferenceEntry:
    """Parsed reference entry."""

    key: str
    title: str = ""
    author: str = ""
    year: str = ""
    doi: str = ""
    arxiv_id: str = ""
    entry_type: str = "reference"
    reference_number: Optional[int] = None
    raw: str = ""
    source: str = ""
    validation: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "author": self.author,
            "year": self.year,
            "doi": self.doi,
            "arxiv_id": self.arxiv_id,
            "entry_type": self.entry_type,
            "reference_number": self.reference_number,
            "raw": self.raw,
            "source": self.source,
            "validation": self.validation,
        }


@dataclass
class CitationExtractionResult:
    """Structured citation extraction result."""

    citations: list[CitationSpan] = field(default_factory=list)
    references: list[ReferenceEntry] = field(default_factory=list)
    sections: list[dict[str, Any]] = field(default_factory=list)
    backend: str = ""
    errors: list[str] = field(default_factory=list)
    real_citation_edges: list[dict[str, Any]] = field(default_factory=list)
    real_citation_edge_stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "citations": [c.to_dict() for c in self.citations],
            "references": [r.to_dict() for r in self.references],
            "sections": self.sections,
            "backend": self.backend,
            "errors": self.errors,
            "real_citation_edges": self.real_citation_edges,
            "real_citation_edge_stats": self.real_citation_edge_stats,
        }


class GrobidReferenceExtractor:
    """Extract references using a running GROBID service."""

    TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}

    def __init__(
        self,
        url: str = "http://localhost:8070",
        timeout_s: int = 30,
        consolidate: bool = False,
    ) -> None:
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s
        self.consolidate = consolidate

    def extract_references(self, pdf_path: str) -> list[ReferenceEntry]:
        tei = self._process_fulltext(pdf_path)
        return self._parse_references(tei)

    def _process_fulltext(self, pdf_path: str) -> str:
        pdf_file = Path(pdf_path)
        if not pdf_file.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        params = {
            "consolidateCitations": "1" if self.consolidate else "0",
            "includeRawCitations": "1",
        }

        with pdf_file.open("rb") as handle:
            files = {"input": (pdf_file.name, handle, "application/pdf")}
            response = httpx.post(
                f"{self.url}/api/processFulltextDocument",
                data=params,
                files=files,
                timeout=self.timeout_s,
            )
            response.raise_for_status()

        return response.text

    def _parse_references(self, tei_xml: str) -> list[ReferenceEntry]:
        root = ET.fromstring(tei_xml)
        entries: list[ReferenceEntry] = []

        for bibl in root.findall(".//tei:listBibl/tei:biblStruct", self.TEI_NS):
            ref_id = bibl.get("{http://www.w3.org/XML/1998/namespace}id", "")
            reference_number = self._parse_reference_number(ref_id)

            title = (
                self._get_text(bibl.find(".//tei:analytic/tei:title", self.TEI_NS))
                or self._get_text(bibl.find(".//tei:monogr/tei:title", self.TEI_NS))
                or self._get_text(bibl.find(".//tei:title", self.TEI_NS))
            )

            authors = self._parse_authors(bibl)
            author_str = " and ".join(authors)

            year = self._extract_year(bibl)
            doi = self._get_text(bibl.find(".//tei:idno[@type='DOI']", self.TEI_NS))
            arxiv_id = self._get_text(bibl.find(".//tei:idno[@type='arXiv']", self.TEI_NS))

            raw = ET.tostring(bibl, encoding="unicode")
            key = ref_id or f"ref_{reference_number or len(entries) + 1}"

            entries.append(
                ReferenceEntry(
                    key=key,
                    title=title,
                    author=author_str,
                    year=year,
                    doi=doi,
                    arxiv_id=arxiv_id,
                    reference_number=reference_number,
                    raw=raw,
                    source="grobid",
                )
            )

        return entries

    def _parse_authors(self, bibl: ET.Element) -> list[str]:
        authors: list[str] = []
        for author in bibl.findall(".//tei:author", self.TEI_NS):
            surname = self._get_text(author.find(".//tei:surname", self.TEI_NS))
            forename = self._get_text(author.find(".//tei:forename", self.TEI_NS))
            if surname or forename:
                name = f"{surname}, {forename}".strip(", ").strip()
                authors.append(name)
            else:
                raw = self._get_text(author)
                if raw:
                    authors.append(raw)
        return authors

    def _extract_year(self, bibl: ET.Element) -> str:
        date = bibl.find(".//tei:date", self.TEI_NS)
        if date is None:
            return ""
        when = date.get("when", "")
        if when:
            return when[:4]
        text = self._get_text(date)
        match = re.search(r"\b(19|20)\d{2}\b", text)
        return match.group(0) if match else ""

    def _get_text(self, elem: Optional[ET.Element]) -> str:
        if elem is None:
            return ""
        return "".join(elem.itertext()).strip()

    def _parse_reference_number(self, ref_id: str) -> Optional[int]:
        if not ref_id:
            return None
        match = re.search(r"(\d+)", ref_id)
        if match:
            return int(match.group(1))
        return None


class CitationChecker:
    """Citation extraction and verification utility.

    This class provides:
    - Extraction of citations from text ([1], [1-3], [1, 2, 3])
    - Parsing of reference lists
    - Basic validation of citation format

    Attributes:
        citation_pattern: Regex pattern for matching citations.
        ref_pattern: Regex pattern for matching reference entries.
    """

    # Pattern to match citations like [1], [1-3], [1, 2, 3]
    CITATION_PATTERN = r"\[(?:[0-9]+(?:[-,]\s*[0-9]+)*)\]"

    # Pattern to match reference entries
    REF_PATTERN = r"^\[(\d+)\]\s+(.+)$"

    # Reference section headings in PDF text
    REFERENCE_HEADINGS = (
        "references",
        "bibliography",
        "literature cited",
    )

    # Patterns for detecting the start of a reference entry
    REF_ENTRY_PATTERNS = [
        r"^\[\d+\]\s+",
        r"^\d+\.\s+",
        r"^\d+\)\s+",
    ]
    REF_AUTHOR_YEAR_PATTERN = r"^[A-Z].{0,160}\b(19|20)\d{2}\b"

    # Author-year citation patterns
    AUTHOR_YEAR_INLINE_PATTERN = (
        r"([A-Z][A-Za-z'`\-]+(?:\s+(?:et al\.|and|&)\s+[A-Z][A-Za-z'`\-]+)*)"
        r"\s*\((\d{4}[a-z]?)\)"
    )
    AUTHOR_YEAR_PAREN_PATTERN = r"\(([^)]*\b(?:19|20)\d{2}[a-z]?\b[^)]*)\)"

    # Sentence splitting
    SENTENCE_SPLIT_PATTERN = r"(?<=[.!?])\s+(?=[A-Z0-9])"
    SENTENCE_ABBREVIATIONS = {
        "et al.",
        "fig.",
        "figs.",
        "eq.",
        "eqs.",
        "cf.",
        "e.g.",
        "i.e.",
        "vs.",
        "dr.",
        "mr.",
        "ms.",
        "prof.",
    }

    def __init__(
        self,
        config: Optional[SurveyMAEConfig] = None,
        result_store: Optional[ResultStore] = None,
    ):
        """Initialize the citation checker."""
        self.citation_regex = re.compile(self.CITATION_PATTERN)
        self.ref_regex = re.compile(self.REF_PATTERN, re.MULTILINE)
        self.author_year_inline_regex = re.compile(self.AUTHOR_YEAR_INLINE_PATTERN)
        self.author_year_paren_regex = re.compile(self.AUTHOR_YEAR_PAREN_PATTERN)
        self.sentence_split_regex = re.compile(self.SENTENCE_SPLIT_PATTERN)

        self.config = config or load_config()
        self.result_store = result_store
        self._heading_threshold: Optional[float] = None
        self._heading_candidates: set[str] = set()

    def extract_citations(self, text: str) -> List[str]:
        """Extract all citations from the text.

        Args:
            text: The text to search for citations.

        Returns:
            List of unique citation strings (e.g., ["[1]", "[2-4]"]).
        """
        matches = self.citation_regex.findall(text)
        # Remove duplicates while preserving order
        seen = set()
        unique = []
        for m in matches:
            if m not in seen:
                seen.add(m)
                unique.append(m)
        return unique

    def extract_citation_numbers(self, text: str) -> List[int]:
        """Extract all citation numbers from the text.

        Args:
            text: The text to search for citations.

        Returns:
            List of unique citation numbers.
        """
        citations = self.extract_citations(text)
        numbers = set()

        for cit in citations:
            # Remove brackets and split by comma or hyphen
            inner = cit.strip("[]")
            parts = inner.split(",")
            for part in parts:
                part = part.strip()
                if "-" in part:
                    # Handle range like "1-5"
                    try:
                        start, end = map(int, part.split("-"))
                        numbers.update(range(start, end + 1))
                    except ValueError:
                        pass
                else:
                    try:
                        numbers.add(int(part))
                    except ValueError:
                        pass

        return sorted(numbers)

    def parse_reference_list(self, text: str) -> Dict[int, str]:
        """Parse a reference list into a dictionary.

        Args:
            text: The text containing reference entries.

        Returns:
            Dictionary mapping citation number to reference text.
        """
        refs = {}
        lines = text.split("\n")

        for line in lines:
            match = self.ref_regex.match(line)
            if match:
                num = int(match.group(1))
                ref_text = match.group(2).strip()
                refs[num] = ref_text

        return refs

    def validate_citations(
        self,
        text: str,
        reference_list: Optional[Dict[int, str]] = None,
    ) -> Dict[str, Any]:
        """Validate citations in the text.

        Args:
            text: The text containing citations.
            reference_list: Optional dictionary of references.

        Returns:
            Dictionary with validation results.
        """
        extracted_nums = self.extract_citation_numbers(text)
        total_citations = len(extracted_nums)
        unique_citations = len(set(extracted_nums))

        result = {
            "total_citations": total_citations,
            "unique_citations": unique_citations,
            "cited_numbers": extracted_nums,
            "invalid_citations": [],
            "has_reference_list": reference_list is not None,
        }

        if reference_list:
            # Check for citations without references
            invalid = [n for n in extracted_nums if n not in reference_list]
            result["invalid_citations"] = invalid

        return result

    def get_citation_context(
        self,
        text: str,
        citation: str,
        context_chars: int = 100,
    ) -> List[str]:
        """Get the surrounding context for a citation.

        Args:
            text: The full text.
            citation: The citation to find (e.g., "[1]").
            context_chars: Number of characters before/after to include.

        Returns:
            List of context strings for each occurrence.
        """
        contexts = []
        pattern = re.escape(citation)

        for match in re.finditer(pattern, text):
            start = max(0, match.start() - context_chars)
            end = min(len(text), match.end() + context_chars)
            context = text[start:end]
            contexts.append(f"...{context}...")

        return contexts

    def parse_pdf(self, pdf_path: str) -> str:
        """Parse a PDF file into text suitable for citation extraction.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            Extracted PDF content as a string.
        """
        parser = PDFParser()
        return parser.parse_cached(pdf_path)

    def extract_citations_from_pdf(self, pdf_path: str) -> List[str]:
        """Extract citation markers from a PDF file.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            List of unique citation strings (e.g., ["[1]", "[2-4]"]).
        """
        content = self.parse_pdf(pdf_path)
        return self.extract_citations(content)

    async def extract_citations_with_context_from_pdf(
        self,
        pdf_path: str,
        verify_references: bool = False,
        sources: Optional[Iterable[str]] = None,
        verify_limit: Optional[int] = None,
    ) -> dict[str, Any]:
        """Extract citations with sentence and location context from PDF.

        This is the unified async version. Use verify_references=True to enable
        reference verification and real citation edge building.

        Args:
            pdf_path: Path to the PDF file.
            verify_references: Whether to verify references via external APIs.
            sources: Sources to use for verification.
            verify_limit: Maximum number of references to verify.

        Returns:
            Structured dict with citations, references, backend, and errors.
        """
        base = self._extract_citations_with_context_mupdf(pdf_path)
        references, backend, errors = self._extract_references_with_backend(pdf_path)
        citation_backend = base.backend or "mupdf"
        base.references = references
        base.backend = f"citations:{citation_backend};references:{backend}"
        base.errors.extend(errors)
        self._link_citations_to_references(base.citations, base.references)
        self._persist_extraction(pdf_path, base)

        if verify_references:
            await self._verify_references(base.references, sources, verify_limit)
            real_graph = self.build_real_citation_edges(base.references)
            base.real_citation_edges = real_graph["edges"]
            base.real_citation_edge_stats = real_graph["stats"]
            # Re-persist extraction so downstream can read real edges from extraction.json.
            self._persist_extraction(pdf_path, base)
            self._persist_validation(
                pdf_path,
                base.references,
                sources,
                verify_limit,
                real_graph,
            )

        return base.to_dict()

    # Backwards compatibility alias (deprecated, use extract_citations_with_context_from_pdf)
    extract_citations_with_context_from_pdf_async = extract_citations_with_context_from_pdf

    def extract_references_from_text(self, text: str) -> List[Dict[str, Any]]:
        """Extract reference entries from PDF text.

        Args:
            text: Full text of the paper.

        Returns:
            List of reference dicts compatible with compare_metadata.
        """
        reference_block = self._find_reference_block(text)
        if not reference_block:
            return []

        entries = self._split_reference_entries(reference_block)
        return self._parse_reference_entries(entries)

    def extract_references_from_pdf(self, pdf_path: str) -> List[Dict[str, Any]]:
        """Extract reference entries from a PDF file.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            List of reference dicts compatible with compare_metadata.
        """
        content = self.parse_pdf(pdf_path)
        return self.extract_references_from_text(content)

    def _extract_references_with_backend(
        self,
        pdf_path: str,
    ) -> tuple[list[ReferenceEntry], str, list[str]]:
        citation_cfg = getattr(self.config, "citation", None)
        backend = str(getattr(citation_cfg, "backend", "auto")).lower()
        errors: list[str] = []

        if backend in {"grobid", "auto"}:
            if backend == "auto" and not self._grobid_is_available(
                getattr(citation_cfg, "grobid_url", "http://localhost:8070")
            ):
                fallback_refs = self.extract_references_from_pdf(pdf_path)
                return (
                    self._reference_entries_from_dicts(fallback_refs, source="mupdf"),
                    "mupdf",
                    errors,
                )
            try:
                extractor = GrobidReferenceExtractor(
                    url=getattr(citation_cfg, "grobid_url", "http://localhost:8070"),
                    timeout_s=int(getattr(citation_cfg, "grobid_timeout_s", 30)),
                    consolidate=bool(getattr(citation_cfg, "grobid_consolidate", False)),
                )
                refs = extractor.extract_references(pdf_path)
                if refs:
                    return refs, "grobid", errors
            except Exception as exc:
                msg = f"grobid_failed: {exc}"
                logger.warning(msg)
                errors.append(msg)

        fallback_refs = self.extract_references_from_pdf(pdf_path)
        return self._reference_entries_from_dicts(fallback_refs, source="mupdf"), "mupdf", errors

    def _grobid_is_available(self, url: str) -> bool:
        try:
            response = httpx.get(f"{url.rstrip('/')}/api/isalive", timeout=2)
            return response.status_code == 200
        except Exception:
            return False

    def _reference_entries_from_dicts(
        self,
        references: list[dict[str, Any]],
        source: str,
    ) -> list[ReferenceEntry]:
        entries: list[ReferenceEntry] = []
        for ref in references:
            author = str(ref.get("author", "")).strip()
            if ";" in author and " and " not in author:
                parts = [p.strip() for p in author.split(";") if p.strip()]
                author = " and ".join(parts)
            entries.append(
                ReferenceEntry(
                    key=str(ref.get("key", "")).strip() or f"ref_{len(entries) + 1}",
                    title=str(ref.get("title", "")).strip(),
                    author=author,
                    year=str(ref.get("year", "")).strip(),
                    doi=str(ref.get("doi", "")).strip(),
                    arxiv_id=str(ref.get("arxiv_id", "")).strip(),
                    entry_type=str(ref.get("entry_type", "reference")),
                    reference_number=ref.get("reference_number"),
                    raw=str(ref.get("raw", "")),
                    source=source,
                )
            )
        return entries

    async def _verify_references(
        self,
        references: list[ReferenceEntry],
        sources: Optional[Iterable[str]] = None,
        verify_limit: Optional[int] = None,
    ) -> None:
        checker = CitationMetadataChecker()
        verified = 0
        for ref in references:
            if not (ref.title or ref.doi or ref.arxiv_id):
                continue
            bib_entry = bib_entry_from_dict(ref.to_dict())
            report = await checker.verify_bib_entry(bib_entry, sources=sources)
            ref.validation = report.to_dict()
            verified += 1
            if verify_limit is not None and verified >= verify_limit:
                break

    def _persist_extraction(self, pdf_path: str, result: CitationExtractionResult) -> None:
        if not self.result_store:
            return
        try:
            paper_id = self.result_store.register_paper(pdf_path)
            self.result_store.save_extraction(paper_id, result.to_dict())
            self.result_store.update_index(paper_id, status="extracted", source_path=pdf_path)
        except Exception as exc:
            logger.warning("Failed to persist extraction result: %s", exc)

    def _persist_validation(
        self,
        pdf_path: str,
        references: list[ReferenceEntry],
        sources: Optional[Iterable[str]],
        verify_limit: Optional[int],
        real_graph: Optional[dict[str, Any]] = None,
    ) -> None:
        if not self.result_store:
            return
        try:
            paper_id = self.result_store.register_paper(pdf_path)
            validation = {
                "paper_id": paper_id,
                "validated_at": datetime.now(timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
                "sources": list(sources) if sources else [],
                "verify_limit": verify_limit,
                "reference_validations": [
                    ref.validation for ref in references if ref.validation is not None
                ],
            }
            if real_graph is not None:
                validation["real_citation_edges"] = real_graph.get("edges", [])
                validation["real_citation_edge_stats"] = real_graph.get("stats", {})
            self.result_store.save_validation(paper_id, validation)
            self.result_store.update_index(paper_id, status="validated", source_path=pdf_path)
        except Exception as exc:
            logger.warning("Failed to persist validation result: %s", exc)

    def build_real_citation_edges(
        self,
        references: list[ReferenceEntry],
    ) -> dict[str, Any]:
        """Build real in-set citation edges from verified metadata."""
        id_to_keys: dict[str, set[str]] = {}
        source_tokens: dict[str, set[str]] = {}

        for ref in references:
            tokens = self._reference_identity_tokens(ref)
            source_tokens[ref.key] = tokens
            for token in tokens:
                id_to_keys.setdefault(token, set()).add(ref.key)

        edge_set: set[tuple[str, str]] = set()
        total_target_candidates = 0
        resolved_target_candidates = 0
        unresolved_target_candidates = 0

        for ref in references:
            target_token_sets = self._extract_target_token_sets(ref.validation)
            for token_set in target_token_sets:
                total_target_candidates += 1
                matched: set[str] = set()
                for token in token_set:
                    matched.update(id_to_keys.get(token, set()))
                if ref.key in matched:
                    matched.remove(ref.key)
                if matched:
                    resolved_target_candidates += 1
                else:
                    unresolved_target_candidates += 1
                for dst in matched:
                    edge_set.add((ref.key, dst))

        edges = [
            {"source": src, "target": dst}
            for src, dst in sorted(edge_set, key=lambda item: (item[0], item[1]))
        ]
        stats = {
            "n_edges": len(edges),
            "n_sources": len([ref for ref in references if ref.validation]),
            "total_target_candidates": total_target_candidates,
            "resolved_target_candidates": resolved_target_candidates,
            "unresolved_target_candidates": unresolved_target_candidates,
            "resolved_target_ratio": (
                (resolved_target_candidates / total_target_candidates)
                if total_target_candidates
                else 0.0
            ),
        }
        if edges:
            stats["status"] = "ok"
            stats["failure_reason"] = ""
        else:
            stats["status"] = "failed"
            stats["failure_reason"] = "NO_REAL_EDGES"
        return {"edges": edges, "stats": stats}

    async def analyze_citation_sentence_alignment(
        self,
        citations: list[dict[str, Any]],
        references: list[ReferenceEntry],
        batch_size: int = 10,
        model_name: str = "qwen3.5-flash",
        max_concurrency: int = 5,
        contradiction_threshold: float = 0.05,
    ) -> dict[str, Any]:
        """Analyze citation-sentence alignment (C6 metric).

        For each citation-sentence pair, determines whether the sentence's claim
        is supported, contradicted, or insufficiently evidenced by the cited paper's abstract.

        Args:
            citations: List of citation dicts from extraction (with sentence context).
            references: List of ReferenceEntry objects with validation metadata.
            batch_size: Number of pairs to process per LLM call.
            model_name: Model to use for batch processing.
            max_concurrency: Maximum concurrent batch calls.
            contradiction_threshold: Threshold for auto-fail.

        Returns:
            Dict with C6 metrics including contradiction_rate and auto_fail flag.
        """
        from langchain_core.messages import HumanMessage
        from langchain_openai import ChatOpenAI
        import asyncio

        logger.info(f"Starting C6 citation-sentence alignment analysis...")

        # Build reference lookup with abstract
        ref_lookup: dict[str, dict[str, Any]] = {}
        for ref in references:
            ref_lookup[ref.key] = {
                "title": ref.title or "",
                "abstract": ref.validation.get("metadata", {}).get("abstract", "") if ref.validation else "",
                "key": ref.key,
            }

        # Build citation-sentence pairs
        pairs: list[dict[str, Any]] = []
        for citation in citations:
            ref_keys = citation.get("ref_keys", [])
            sentence = citation.get("sentence", "")
            if not sentence or not ref_keys:
                continue

            # One pair per cited reference
            for ref_key in ref_keys:
                ref_data = ref_lookup.get(ref_key, {})
                abstract = ref_data.get("abstract", "")

                pairs.append({
                    "citation_marker": citation.get("marker", ""),
                    "sentence": sentence,
                    "ref_key": ref_key,
                    "ref_title": ref_data.get("title", ""),
                    "abstract": abstract,
                    "has_abstract": bool(abstract),
                })

        logger.info(f"Built {len(pairs)} citation-sentence pairs")

        if not pairs:
            return {
                "metric_id": "C6",
                "llm_involved": True,
                "hallucination_risk": "low",
                "total_pairs": 0,
                "support": 0,
                "contradict": 0,
                "insufficient": 0,
                "contradiction_rate": 0.0,
                "auto_fail": False,
                "contradictions": [],
                "status": "no_pairs",
            }

        # Mark pairs without abstract as insufficient
        insufficient_pairs = [p for p in pairs if not p["has_abstract"]]
        pairs_with_abstract = [p for p in pairs if p["has_abstract"]]

        logger.info(f"Pairs with abstract: {len(pairs_with_abstract)}, without: {len(insufficient_pairs)}")

        # Initialize LLM
        try:
            llm = ChatOpenAI(model=model_name, temperature=0.1)
        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}")
            return {
                "metric_id": "C6",
                "llm_involved": True,
                "hallucination_risk": "low",
                "total_pairs": len(pairs),
                "support": 0,
                "contradict": 0,
                "insufficient": len(pairs),
                "contradiction_rate": 0.0,
                "auto_fail": False,
                "contradictions": [],
                "status": "llm_error",
                "error": str(e),
            }

        # Create batches
        batches = [
            pairs_with_abstract[i:i + batch_size]
            for i in range(0, len(pairs_with_abstract), batch_size)
        ]

        logger.info(f"Processing {len(batches)} batches with max concurrency {max_concurrency}")

        async def process_batch(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
            """Process a single batch of pairs."""
            prompt = self._build_c6_prompt(batch)
            try:
                response = await llm.ainvoke([HumanMessage(content=prompt)])
                content = response.content if hasattr(response, "content") else str(response)
                return self._parse_c6_response(content, batch)
            except Exception as e:
                logger.warning(f"Batch processing failed: {e}")
                # Mark all as insufficient on error
                return [
                    {
                        "citation_marker": p["citation_marker"],
                        "sentence": p["sentence"][:200],
                        "ref_abstract": p["abstract"][:500],
                        "llm_judgment": "insufficient",
                        "note": f"LLM error: {e}",
                    }
                    for p in batch
                ]

        # Process batches with concurrency limit
        semaphore = asyncio.Semaphore(max_concurrency)

        async def bounded_process(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
            async with semaphore:
                return await process_batch(batch)

        results = await asyncio.gather(*[bounded_process(b) for b in batches])
        batch_results = [item for sublist in results for item in sublist]

        # Add insufficient pairs (no abstract)
        for p in insufficient_pairs:
            batch_results.append({
                "citation_marker": p["citation_marker"],
                "sentence": p["sentence"][:200],
                "ref_abstract": "[ABSTRACT NOT AVAILABLE]",
                "llm_judgment": "insufficient",
                "note": "Abstract not available in metadata",
            })

        # Count results
        support = sum(1 for r in batch_results if r.get("llm_judgment") == "support")
        contradict = sum(1 for r in batch_results if r.get("llm_judgment") == "contradict")
        insufficient = sum(1 for r in batch_results if r.get("llm_judgment") == "insufficient")

        # Calculate contradiction rate (excluding insufficient)
        valid_count = support + contradict
        contradiction_rate = contradict / valid_count if valid_count > 0 else 0.0
        auto_fail = contradiction_rate >= contradiction_threshold

        # Collect contradictions
        contradictions = [
            {
                "citation": r.get("citation_marker", ""),
                "sentence": r.get("sentence", ""),
                "ref_abstract": r.get("ref_abstract", ""),
                "llm_judgment": r.get("llm_judgment", ""),
                "note": r.get("note", ""),
            }
            for r in batch_results
            if r.get("llm_judgment") == "contradict"
        ]

        logger.info(
            f"C6 complete: {support} support, {contradict} contradict, {insufficient} insufficient, "
            f"contradiction_rate={contradiction_rate:.3f}, auto_fail={auto_fail}"
        )

        return {
            "metric_id": "C6",
            "llm_involved": True,
            "hallucination_risk": "low",
            "total_pairs": len(pairs),
            "support": support,
            "contradict": contradict,
            "insufficient": insufficient,
            "contradiction_rate": round(contradiction_rate, 4),
            "auto_fail": auto_fail,
            "contradictions": contradictions[:50],  # Limit to 50 for report size
            "missing_abstract_count": len(insufficient_pairs),
            "status": "ok" if not auto_fail else "auto_fail",
        }

    def _build_c6_prompt(self, pairs: list[dict[str, Any]]) -> str:
        """Build prompt for C6 batch processing."""
        items = []
        for i, p in enumerate(pairs, 1):
            items.append(f"""### Pair {i}
Citation: [{p['citation_marker']}]
Sentence: {p['sentence'][:300]}
Abstract: {p['abstract'][:500]}""")

        prompt = f"""You are evaluating whether a sentence's claim about a cited paper is supported by the paper's abstract.

For each pair, classify as:
- "support": The sentence's claim is consistent with the abstract
- "contradict": The sentence's claim contradicts or misrepresents the abstract
- "insufficient": The abstract doesn't provide enough information to judge

Output in this format (one per line):
Pair N: support/contradict/insufficient
[If contradict, add a brief note in parentheses]

{"=".join(items)}

Output:"""
        return prompt

    def _parse_c6_response(self, response: str, pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Parse LLM response for C6 results."""
        results = []
        lines = response.strip().split("\n")

        for i, p in enumerate(pairs):
            judgment = "insufficient"
            note = ""

            # Find matching line
            for line in lines:
                line_lower = line.lower().strip()
                if f"pair {i+1}" in line_lower or f"pair{i+1}" in line_lower:
                    if "support" in line_lower and "contradict" not in line_lower:
                        judgment = "support"
                    elif "contradict" in line_lower:
                        judgment = "contradict"
                        # Extract note if present
                        if "(" in line and ")" in line:
                            note = line[line.index("(") + 1:line.index(")")].strip()
                    break
                elif "support" in line_lower and "contradict" not in line_lower and any(
                    f"pair {j}" in line_lower for j in range(1, len(pairs) + 1)
                ):
                    judgment = "support"
                    break
                elif "contradict" in line_lower and any(
                    f"pair {j}" in line_lower for j in range(1, len(pairs) + 1)
                ):
                    judgment = "contradict"
                    break

            results.append({
                "citation_marker": p["citation_marker"],
                "sentence": p["sentence"][:200],
                "ref_abstract": p["abstract"][:500],
                "llm_judgment": judgment,
                "note": note,
            })

        return results

    def _reference_identity_tokens(self, ref: ReferenceEntry) -> set[str]:
        tokens: set[str] = set()
        if ref.key:
            tokens.add(f"key:{ref.key.strip()}")
        if ref.doi:
            doi = self._normalize_doi(ref.doi)
            if doi:
                tokens.add(f"doi:{doi}")
        if ref.arxiv_id:
            arxiv = self._normalize_arxiv_id(ref.arxiv_id)
            if arxiv:
                tokens.add(f"arxiv:{arxiv}")

        validation = ref.validation if isinstance(ref.validation, dict) else {}
        metadata = validation.get("metadata") if isinstance(validation, dict) else {}
        if isinstance(metadata, dict):
            meta_doi = self._normalize_doi(str(metadata.get("doi", "")).strip())
            if meta_doi:
                tokens.add(f"doi:{meta_doi}")
            meta_arxiv = self._normalize_arxiv_id(str(metadata.get("arxiv_id", "")).strip())
            if meta_arxiv:
                tokens.add(f"arxiv:{meta_arxiv}")
            meta_openalex = self._normalize_openalex_id(
                str(metadata.get("openalex_id") or metadata.get("id") or "")
            )
            if meta_openalex:
                tokens.add(f"openalex:{meta_openalex}")
            meta_ss = str(metadata.get("paper_id") or "").strip()
            if meta_ss:
                tokens.add(f"s2:{meta_ss}")
        return tokens

    def _extract_target_token_sets(
        self,
        validation: Optional[dict[str, Any]],
    ) -> list[set[str]]:
        if not isinstance(validation, dict):
            return []
        metadata = validation.get("metadata")
        if not isinstance(metadata, dict):
            return []

        targets = metadata.get("reference_targets", [])
        token_sets: list[set[str]] = []
        for target in targets:
            if not isinstance(target, dict):
                continue
            tokens: set[str] = set()
            target_key = str(target.get("key") or "").strip()
            if target_key:
                tokens.add(f"key:{target_key}")
            target_doi = self._normalize_doi(str(target.get("doi") or "").strip())
            if target_doi:
                tokens.add(f"doi:{target_doi}")
            target_arxiv = self._normalize_arxiv_id(str(target.get("arxiv_id") or "").strip())
            if target_arxiv:
                tokens.add(f"arxiv:{target_arxiv}")
            target_openalex = self._normalize_openalex_id(
                str(target.get("openalex_id") or target.get("id") or "")
            )
            if target_openalex:
                tokens.add(f"openalex:{target_openalex}")
            target_ss = str(target.get("semantic_scholar_id") or "").strip()
            if target_ss:
                tokens.add(f"s2:{target_ss}")
            if tokens:
                token_sets.append(tokens)

        return token_sets

    def _normalize_doi(self, doi: str) -> str:
        value = doi.strip().lower()
        if not value:
            return ""
        value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value)
        value = re.sub(r"^doi:\s*", "", value)
        return value.strip()

    def _normalize_arxiv_id(self, arxiv_id: str) -> str:
        value = arxiv_id.strip()
        if not value:
            return ""
        value = re.sub(r"^arxiv:\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"v\d+$", "", value, flags=re.IGNORECASE)
        return value.strip().lower()

    def _normalize_openalex_id(self, openalex_id: str) -> str:
        value = openalex_id.strip()
        if not value:
            return ""
        value = value.replace("https://openalex.org/", "").replace("http://openalex.org/", "")
        value = value.replace("openalex:", "")
        return value.strip().upper()

    def _extract_citations_with_context_mupdf(self, pdf_path: str) -> CitationExtractionResult:
        try:
            import fitz  # PyMuPDF
        except Exception as exc:
            logger.warning(
                "PyMuPDF unavailable, falling back to text-only citation extraction: %s", exc
            )
            return self._extract_citations_with_context_text(pdf_path)

        doc = fitz.open(pdf_path)
        citations: list[CitationSpan] = []
        paragraph_index = 0
        sections: list[dict[str, Any]] = []
        current_section_title: Optional[str] = None
        section_index = 0
        body_font_size = self._estimate_body_font_size(doc)
        self._heading_threshold = body_font_size + 1.5 if body_font_size else None
        self._heading_candidates = self._extract_markdown_headings(pdf_path)

        for page_index, page in enumerate(doc, start=1):
            page_dict = page.get_text("dict")
            paragraphs = self._merge_text_blocks(page_dict.get("blocks", []))
            for blocks in paragraphs:
                paragraph_index += 1
                paragraph_text, line_meta, max_font_size = self._build_paragraph_from_blocks(blocks)
                if not paragraph_text.strip():
                    continue
                heading = self._extract_heading_text(paragraph_text, max_font_size)
                if heading:
                    if heading:
                        current_section_title = heading
                        section_index += 1
                        kind = self._infer_section_kind(current_section_title)
                        if (
                            section_index == 1
                            and page_index == 1
                            and kind == "main"
                            and not re.match(r"^\d+(\.\d+)*\b", current_section_title)
                        ):
                            kind = "title"
                        sections.append(
                            {
                                "section_index": section_index,
                                "section_title": current_section_title,
                                "page": page_index,
                                "paragraph_index": paragraph_index,
                                "level": self._infer_section_level(current_section_title),
                                "kind": kind,
                            }
                        )
                    continue

                for sentence, start, end in self._split_sentences_with_spans(paragraph_text):
                    extracted = self._extract_sentence_citations(sentence)
                    if not extracted:
                        continue

                    line_info = self._find_line_for_span(line_meta, start, end)
                    line_in_paragraph = line_info.get("line_in_paragraph", 0)
                    bbox = line_info.get("bbox")

                    for item in extracted:
                        if item["kind"] == "numeric":
                            for number in item.get("numbers", []):
                                citations.append(
                                    CitationSpan(
                                        marker=f"[{number}]",
                                        marker_raw=item["marker"],
                                        kind="numeric",
                                        sentence=sentence,
                                        page=page_index,
                                        paragraph_index=paragraph_index,
                                        line_in_paragraph=line_in_paragraph,
                                        bbox=bbox,
                                        reference_number=number,
                                        section_title=current_section_title,
                                        section_index=section_index or None,
                                    )
                                )
                        else:
                            citations.append(
                                CitationSpan(
                                    marker=item["marker"],
                                    kind="author_year",
                                    sentence=sentence,
                                    page=page_index,
                                    paragraph_index=paragraph_index,
                                    line_in_paragraph=line_in_paragraph,
                                    bbox=bbox,
                                    author=item.get("author", ""),
                                    year=item.get("year", ""),
                                    section_title=current_section_title,
                                    section_index=section_index or None,
                                )
                            )

        return CitationExtractionResult(citations=citations, sections=sections, backend="mupdf")

    def _extract_citations_with_context_text(self, pdf_path: str) -> CitationExtractionResult:
        content = self.parse_pdf(pdf_path)
        citations: list[CitationSpan] = []
        paragraph_index = 0
        sections: list[dict[str, Any]] = []
        current_section_title: Optional[str] = None
        section_index = 0

        for paragraph in content.split("\n\n"):
            paragraph = paragraph.strip()
            if not paragraph or paragraph.lower().startswith("## page"):
                continue
            if paragraph.startswith("#"):
                heading = self._normalize_heading_text(paragraph)
                if heading:
                    current_section_title = heading
                    section_index += 1
                    kind = self._infer_section_kind(current_section_title)
                    if section_index == 1 and kind == "main":
                        kind = "title"
                    sections.append(
                        {
                            "section_index": section_index,
                            "section_title": current_section_title,
                            "page": None,
                            "paragraph_index": paragraph_index,
                            "level": self._infer_section_level(current_section_title),
                            "kind": kind,
                        }
                    )
                continue
            paragraph_index += 1
            for sentence, start, end in self._split_sentences_with_spans(paragraph):
                extracted = self._extract_sentence_citations(sentence)
                if not extracted:
                    continue
                for item in extracted:
                    if item["kind"] == "numeric":
                        for number in item.get("numbers", []):
                            citations.append(
                                CitationSpan(
                                    marker=item["marker"],
                                    kind="numeric",
                                    sentence=sentence,
                                    page=0,
                                    paragraph_index=paragraph_index,
                                    line_in_paragraph=0,
                                    reference_number=number,
                                    section_title=current_section_title,
                                    section_index=section_index or None,
                                )
                            )
                    else:
                        citations.append(
                            CitationSpan(
                                marker=item["marker"],
                                kind="author_year",
                                sentence=sentence,
                                page=0,
                                paragraph_index=paragraph_index,
                                line_in_paragraph=0,
                                author=item.get("author", ""),
                                year=item.get("year", ""),
                                section_title=current_section_title,
                                section_index=section_index or None,
                            )
                        )

        return CitationExtractionResult(citations=citations, sections=sections, backend="text")

    def _merge_text_blocks(
        self,
        blocks: list[dict[str, Any]],
    ) -> list[list[dict[str, Any]]]:
        paragraphs: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []

        for block in blocks:
            if block.get("type") != 0:
                continue

            if not current:
                current = [block]
                continue

            if self._should_merge_blocks(current[-1], block):
                current.append(block)
            else:
                paragraphs.append(current)
                current = [block]

        if current:
            paragraphs.append(current)

        return paragraphs

    def _should_merge_blocks(
        self,
        prev: dict[str, Any],
        curr: dict[str, Any],
    ) -> bool:
        if self._is_heading_block(prev) or self._is_heading_block(curr):
            return False
        prev_bbox = prev.get("bbox") or [0, 0, 0, 0]
        curr_bbox = curr.get("bbox") or [0, 0, 0, 0]
        prev_x0, prev_y0, prev_x1, prev_y1 = prev_bbox
        curr_x0, curr_y0, _curr_x1, _curr_y1 = curr_bbox

        gap = curr_y0 - prev_y1
        if gap < -2:
            return False

        prev_line_height = self._estimate_line_height(prev)
        if prev_line_height <= 0:
            prev_line_height = 10.0

        close_vertically = gap <= (prev_line_height * 1.6)
        aligned = abs(curr_x0 - prev_x0) <= 10
        indent = curr_x0 - prev_x0

        prev_last_line = self._last_line_text(prev)
        prev_end_sentence = bool(re.search(r"[.!?]['\"”’)]*$", prev_last_line.strip()))
        curr_first_line = self._first_line_text(curr)
        curr_starts_lower = curr_first_line[:1].islower()

        if indent > 18:
            return False

        if close_vertically and aligned and (not prev_end_sentence or curr_starts_lower):
            return True

        return False

    def _is_heading_block(self, block: dict[str, Any]) -> bool:
        text = self._first_line_text(block).strip()
        font_size = self._block_font_size(block)
        return bool(self._extract_heading_text(text, font_size))

    def _extract_heading_text(self, text: str, font_size: float) -> Optional[str]:
        if self._heading_threshold is not None and font_size < self._heading_threshold:
            return None
        heading = self._normalize_heading_text(text)
        if not heading:
            return None
        if not self._is_heading_text(heading):
            return None
        if self._heading_candidates and len(self._heading_candidates) >= 3:
            if heading not in self._heading_candidates:
                return None
        return heading

    def _is_heading_text(self, text: str) -> bool:
        if not text:
            return False
        stripped = text.strip()
        if len(stripped) > 80:
            return False
        if stripped.endswith("."):
            return False
        lowered = stripped.lower()
        if lowered.startswith("references") or lowered.startswith("bibliography"):
            return True
        if re.match(r"^\d+(\.\d+)*\s+\S", stripped):
            return True
        if stripped.isupper():
            return True
        words = re.findall(r"[A-Za-z][A-Za-z'\-]*", stripped)
        if not words:
            return False
        title_case = sum(1 for w in words if w[0].isupper())
        return title_case / max(len(words), 1) >= 0.6

    def _normalize_heading_text(self, text: str) -> str:
        raw = text.strip()
        if not raw:
            return ""
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if len(lines) >= 2 and re.fullmatch(r"\d+(\.\d+)*|[A-Z]", lines[0]):
            heading = f"{lines[0]} {lines[1]}"
        else:
            heading = lines[0]
        heading = heading.lstrip("#").strip()
        heading = re.sub(r"\*\*(.+?)\*\*", r"\1", heading)
        heading = re.sub(r"\s+", " ", heading)
        return heading.strip()

    def _extract_markdown_headings(self, pdf_path: str) -> set[str]:
        """Extract heading candidates from markdown output (when available)."""
        try:
            parser = PDFParser()
            content = parser.parse_cached(pdf_path)
        except Exception:
            return set()

        candidates: set[str] = set()
        for line in content.splitlines():
            if not line.lstrip().startswith("#"):
                continue
            heading = self._normalize_heading_text(line)
            if not heading:
                continue
            if len(heading) < 4:
                continue
            if not self._is_heading_text(heading):
                continue
            candidates.add(heading)
        return candidates

    def _estimate_body_font_size(self, doc: Any) -> float:
        from collections import Counter

        counts: Counter[float] = Counter()
        for page in doc:
            page_dict = page.get_text("dict")
            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        size = span.get("size")
                        text = span.get("text", "")
                        if size and text:
                            counts[round(float(size), 1)] += len(text)
        if not counts:
            return 0.0
        return counts.most_common(1)[0][0]

    def _block_font_size(self, block: dict[str, Any]) -> float:
        sizes = []
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                size = span.get("size")
                if size:
                    sizes.append(float(size))
        if not sizes:
            return 0.0
        return sum(sizes) / len(sizes)

    def _infer_section_level(self, title: str) -> int:
        match = re.match(r"^(\d+(?:\.\d+)*)\b", title)
        if match:
            return match.group(1).count(".") + 1
        if re.match(r"^[A-Z]\b", title):
            return 1
        return 1

    def _infer_section_kind(self, title: str) -> str:
        lowered = title.lower()
        if "abstract" in lowered:
            return "abstract"
        if "introduction" in lowered:
            return "introduction"
        if "conclusion" in lowered:
            return "conclusion"
        if any(key in lowered for key in ("references", "bibliography")):
            return "references"
        if any(key in lowered for key in ("appendix", "appendices")):
            return "appendix"
        return "main"

    def _estimate_line_height(self, block: dict[str, Any]) -> float:
        for line in block.get("lines", []):
            bbox = line.get("bbox")
            if bbox and len(bbox) == 4:
                return max(0.0, float(bbox[3]) - float(bbox[1]))
        return 0.0

    def _last_line_text(self, block: dict[str, Any]) -> str:
        lines = block.get("lines", [])
        if not lines:
            return ""
        return "".join(span.get("text", "") for span in lines[-1].get("spans", []))

    def _first_line_text(self, block: dict[str, Any]) -> str:
        lines = block.get("lines", [])
        if not lines:
            return ""
        return "".join(span.get("text", "") for span in lines[0].get("spans", []))

    def _build_paragraph_from_blocks(
        self,
        blocks: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]], float]:
        paragraph_text = ""
        line_meta: list[dict[str, Any]] = []
        line_in_paragraph = 0
        max_font_size = 0.0

        for block in blocks:
            for line in block.get("lines", []):
                line_text = "".join(span.get("text", "") for span in line.get("spans", []))
                if not line_text.strip():
                    continue

                if paragraph_text:
                    paragraph_text += "\n"
                start = len(paragraph_text)
                paragraph_text += line_text
                end = len(paragraph_text)

                line_in_paragraph += 1
                sizes = [span.get("size") for span in line.get("spans", []) if span.get("size")]
                line_font_size = float(sum(sizes) / len(sizes)) if sizes else 0.0
                max_font_size = max(max_font_size, line_font_size)
                bbox = line.get("bbox")
                bbox_tuple = (
                    tuple(bbox) if isinstance(bbox, (list, tuple)) and len(bbox) == 4 else None
                )

                line_meta.append(
                    {
                        "start": start,
                        "end": end,
                        "line_in_paragraph": line_in_paragraph,
                        "bbox": bbox_tuple,
                        "font_size": line_font_size,
                    }
                )

        return paragraph_text, line_meta, max_font_size

    def _split_sentences_with_spans(self, text: str) -> list[tuple[str, int, int]]:
        spans: list[tuple[str, int, int]] = []
        start = 0

        for match in self.sentence_split_regex.finditer(text):
            end = match.start()
            candidate = text[start:end].strip()
            if candidate and self._ends_with_abbreviation(candidate):
                continue
            if candidate:
                spans.append((self._normalize_sentence(candidate), start, end))
            start = match.end()

        tail = text[start:].strip()
        if tail:
            spans.append((self._normalize_sentence(tail), start, len(text)))

        return spans

    def _ends_with_abbreviation(self, sentence: str) -> bool:
        lowered = sentence.strip().lower()
        return any(lowered.endswith(abbrev) for abbrev in self.SENTENCE_ABBREVIATIONS)

    def _normalize_sentence(self, sentence: str) -> str:
        return " ".join(sentence.split())

    def _extract_sentence_citations(self, sentence: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        for match in self.citation_regex.finditer(sentence):
            marker = match.group(0)
            numbers = self._expand_numeric_marker(marker)
            results.append({"kind": "numeric", "marker": marker, "numbers": numbers})

        for match in self.author_year_inline_regex.finditer(sentence):
            results.append(
                {
                    "kind": "author_year",
                    "marker": match.group(0),
                    "author": match.group(1),
                    "year": match.group(2),
                }
            )

        for match in self.author_year_paren_regex.finditer(sentence):
            group = match.group(1)
            parts = [p.strip() for p in group.split(";") if p.strip()]
            last_author = ""
            for part in parts:
                parsed = self._parse_author_year_part(part, last_author)
                if not parsed:
                    continue
                author, year = parsed
                last_author = author or last_author
                marker = f"{author}, {year}" if author else year
                results.append(
                    {
                        "kind": "author_year",
                        "marker": marker,
                        "author": author,
                        "year": year,
                    }
                )

        return results

    def _parse_author_year_part(
        self,
        part: str,
        fallback_author: str,
    ) -> Optional[tuple[str, str]]:
        match = re.search(r"(.+?)[,\s]+((?:19|20)\d{2}[a-z]?)", part)
        if match:
            author = match.group(1).strip()
            year = match.group(2).strip()
            return author, year
        match = re.search(r"((?:19|20)\d{2}[a-z]?)", part)
        if match and fallback_author:
            return fallback_author, match.group(1)
        return None

    def _expand_numeric_marker(self, marker: str) -> list[int]:
        inner = marker.strip("[]")
        numbers: set[int] = set()
        for part in inner.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                try:
                    start, end = map(int, part.split("-", 1))
                    numbers.update(range(start, end + 1))
                except ValueError:
                    continue
            else:
                try:
                    numbers.add(int(part))
                except ValueError:
                    continue
        return sorted(numbers)

    def _find_line_for_span(
        self,
        line_meta: list[dict[str, Any]],
        start: int,
        end: int,
    ) -> dict[str, Any]:
        for meta in line_meta:
            if meta["start"] <= start < meta["end"]:
                return meta
            if start <= meta["start"] < end:
                return meta
        return {"line_in_paragraph": 0, "bbox": None}

    def _link_citations_to_references(
        self,
        citations: list[CitationSpan],
        references: list[ReferenceEntry],
    ) -> None:
        ref_by_number = {ref.reference_number: ref for ref in references if ref.reference_number}
        ref_by_author_year: dict[str, list[ReferenceEntry]] = {}
        for ref in references:
            key = self._author_year_key(ref.author, ref.year)
            if key:
                ref_by_author_year.setdefault(key, []).append(ref)

        for citation in citations:
            if citation.kind == "numeric" and citation.reference_number:
                ref = ref_by_number.get(citation.reference_number)
                if ref:
                    citation.ref_key = ref.key
            elif citation.kind == "author_year":
                key = self._author_year_key(citation.author, citation.year)
                candidates = ref_by_author_year.get(key, [])
                if candidates:
                    citation.ref_candidates = [c.key for c in candidates]
                    citation.ref_key = candidates[0].key

    def _author_year_key(self, author: str, year: str) -> str:
        author_key = self._normalize_author_key(author)
        year_key = str(year).strip()
        if not author_key or not year_key:
            return ""
        return f"{author_key}|{year_key}"

    def _normalize_author_key(self, author: str) -> str:
        if not author:
            return ""
        lowered = author.lower()
        lowered = re.sub(r"et al\.?", "", lowered)
        lowered = lowered.replace("&", "and")
        primary = lowered.split("and")[0]
        tokens = re.findall(r"[a-z]+", primary)
        if not tokens:
            return ""
        return tokens[-1]

    def _find_reference_block(self, text: str) -> str:
        lines = text.splitlines()
        heading_pattern = re.compile(
            r"^\s*(?:#*\s*)?(%s)\s*$" % "|".join(self.REFERENCE_HEADINGS),
            re.IGNORECASE,
        )

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if heading_pattern.match(stripped):
                return "\n".join(lines[idx + 1 :])
            if len(stripped) <= 40 and re.search(
                r"\b(%s)\b" % "|".join(self.REFERENCE_HEADINGS), stripped, re.IGNORECASE
            ):
                return "\n".join(lines[idx + 1 :])

        candidate_indices = [i for i, line in enumerate(lines) if self._is_reference_start(line)]
        if candidate_indices:
            cutoff = int(len(lines) * 0.6)
            start_index = next((i for i in candidate_indices if i >= cutoff), candidate_indices[0])
            return "\n".join(lines[start_index:])

        fallback_start = int(len(lines) * 0.7)
        return "\n".join(lines[fallback_start:])

    def _split_reference_entries(self, reference_block: str) -> List[str]:
        lines = []
        for raw_line in reference_block.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.lower().startswith("## page"):
                continue
            lines.append(line)

        entries: List[str] = []
        current = ""
        for line in lines:
            if self._is_reference_start(line):
                if current:
                    entries.append(current.strip())
                current = line
            else:
                current = f"{current} {line}".strip() if current else line

        if current:
            entries.append(current.strip())

        if entries:
            return entries

        # Fallback: split by blank lines and keep chunks with year patterns.
        chunks = re.split(r"\n\s*\n", reference_block)
        for chunk in chunks:
            chunk_line = " ".join(part.strip() for part in chunk.splitlines()).strip()
            if not chunk_line:
                continue
            if re.search(r"\b(19|20)\d{2}\b", chunk_line):
                entries.append(chunk_line)

        return entries

    def _is_reference_start(self, line: str) -> bool:
        for pattern in self.REF_ENTRY_PATTERNS:
            if re.match(pattern, line):
                return True
        if re.match(self.REF_AUTHOR_YEAR_PATTERN, line):
            return True
        return False

    def _parse_reference_entries(self, entries: List[str]) -> List[Dict[str, Any]]:
        parsed: List[Dict[str, Any]] = []
        for index, entry in enumerate(entries, start=1):
            cleaned, ref_number = self._strip_reference_index(entry)
            doi = self._extract_doi(cleaned)
            arxiv_id = self._extract_arxiv_id(cleaned)
            year = self._extract_year(cleaned)
            title = self._extract_title(cleaned, year)
            author = self._extract_authors(cleaned, year)

            ref_key = f"ref_{ref_number or index}"
            parsed.append(
                {
                    "key": ref_key,
                    "title": title,
                    "author": author,
                    "year": year,
                    "doi": doi,
                    "arxiv_id": arxiv_id,
                    "entry_type": "reference",
                    "reference_number": ref_number or index,
                    "raw": entry,
                }
            )

        return parsed

    def _strip_reference_index(self, entry: str) -> tuple[str, Optional[int]]:
        match = re.match(r"^\[(\d+)\]\s+(.*)$", entry)
        if match:
            return match.group(2).strip(), int(match.group(1))

        match = re.match(r"^(\d+)[\.)]\s+(.*)$", entry)
        if match:
            return match.group(2).strip(), int(match.group(1))

        return entry.strip(), None

    def _extract_doi(self, text: str) -> str:
        doi_match = re.search(
            r"(10\.\d{4,9}/[^\s\"<>]+)",
            text,
            flags=re.IGNORECASE,
        )
        if doi_match:
            return doi_match.group(1).rstrip(").,;")
        doi_url = re.search(r"doi\.org/([^\s\"<>]+)", text, flags=re.IGNORECASE)
        if doi_url:
            return doi_url.group(1).rstrip(").,;")
        return ""

    def _extract_arxiv_id(self, text: str) -> str:
        match = re.search(r"arXiv:\s*([^\s,;]+)", text, flags=re.IGNORECASE)
        if match:
            return match.group(1)

        match = re.search(
            r"(\d{4}\.\d{4,5}(?:v\d+)?)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1)

        match = re.search(
            r"([a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1)

        return ""

    def _extract_year(self, text: str) -> str:
        match = re.search(r"\b(19|20)\d{2}\b", text)
        if match:
            return match.group(0)
        return ""

    def _extract_title(self, text: str, year: str) -> str:
        quote_match = re.findall(r"[\"“”](.+?)[\"“”]", text)
        if quote_match:
            return max(quote_match, key=len).strip()

        cleaned = text.strip()
        if year:
            year_match = re.search(rf"\(?{year}\)?", cleaned)
            if year_match:
                after = cleaned[year_match.end() :].lstrip(").,;:- ")
                title = after.split(".")[0].strip()
                if title:
                    return title

        parts = [p.strip() for p in cleaned.split(".") if p.strip()]
        if len(parts) >= 2:
            return parts[1]
        if parts:
            return parts[0]
        return cleaned[:200]

    def _extract_authors(self, text: str, year: str) -> str:
        cleaned = text.strip()
        if year:
            year_match = re.search(rf"\(?{year}\)?", cleaned)
            if year_match:
                cleaned = cleaned[: year_match.start()]

        parts = [p.strip() for p in cleaned.split(".") if p.strip()]
        if parts:
            return parts[0]
        return cleaned


# MCP Server implementation for Citation Checker
def create_citation_checker_mcp_server():
    """Create an MCP server for citation checking functionality.

    Returns:
        Configured MCP Server instance.
    """
    from mcp.server import Server
    from mcp.types import Tool, TextContent

    app = Server("citation-checker")
    checker = CitationChecker()
    metadata_checker = CitationMetadataChecker()

    @app.list_tools()
    async def list_tools():
        bib_entry_schema = {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "BibTeX entry key"},
                "title": {"type": "string", "description": "Paper title"},
                "author": {"type": "string", "description": "Author string"},
                "year": {"type": "string", "description": "Publication year"},
                "doi": {"type": "string", "description": "DOI"},
                "arxiv_id": {"type": "string", "description": "arXiv identifier"},
                "entry_type": {"type": "string", "description": "BibTeX entry type"},
            },
            "required": ["title"],
        }

        return [
            Tool(
                name="extract_citations",
                description="Extract all citations from text",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Text to search for citations",
                        },
                    },
                    "required": ["text"],
                },
            ),
            Tool(
                name="validate_citations",
                description="Validate that all citations have corresponding references",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Text containing citations",
                        },
                        "reference_list": {
                            "type": "object",
                            "description": (
                                "Dictionary of references (citation_number -> reference_text)"
                            ),
                        },
                    },
                    "required": ["text"],
                },
            ),
            Tool(
                name="parse_reference_list",
                description="Parse a reference list into a structured format",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "reference_text": {
                            "type": "string",
                            "description": "The reference list text to parse",
                        },
                    },
                    "required": ["reference_text"],
                },
            ),
            Tool(
                name="parse_pdf_references",
                description="Parse a PDF paper and extract references and citations",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pdf_path": {
                            "type": "string",
                            "description": "Path to the PDF file",
                        },
                    },
                    "required": ["pdf_path"],
                },
            ),
            Tool(
                name="compare_metadata",
                description="Compare a BibTeX entry with provided metadata",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "bib_entry": bib_entry_schema,
                        "metadata": {
                            "type": "object",
                            "description": "Metadata with title/authors/year fields",
                        },
                        "source": {
                            "type": "string",
                            "description": "Source label (e.g., crossref, arxiv)",
                        },
                    },
                    "required": ["bib_entry", "metadata", "source"],
                },
            ),
            Tool(
                name="verify_bib_entry",
                description="Fetch metadata from external sources and compare with a BibTeX entry",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "bib_entry": bib_entry_schema,
                        "sources": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Ordered list of sources to query",
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
                        "title_threshold": {
                            "type": "number",
                            "description": "Override title match threshold",
                        },
                        "author_threshold": {
                            "type": "number",
                            "description": "Override author match threshold",
                        },
                    },
                    "required": ["bib_entry"],
                },
            ),
            Tool(
                name="extract_citations_with_context",
                description=(
                    "Extract citations from a PDF with sentence, page, and line context. "
                    "Optionally verify references against external sources."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pdf_path": {
                            "type": "string",
                            "description": "Path to the PDF file",
                        },
                        "verify_references": {
                            "type": "boolean",
                            "description": "Verify references via external sources",
                        },
                        "verify_sources": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Ordered list of sources to query",
                        },
                        "verify_limit": {
                            "type": "integer",
                            "description": "Max number of references to verify",
                        },
                    },
                    "required": ["pdf_path"],
                },
            ),
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict):
        import json

        try:
            if name == "extract_citations":
                citations = checker.extract_citations(arguments["text"])
                return [TextContent(type="text", text=json.dumps(citations))]

            elif name == "validate_citations":
                refs = arguments.get("reference_list", {})
                result = checker.validate_citations(arguments["text"], refs)
                return [TextContent(type="text", text=json.dumps(result))]

            elif name == "parse_reference_list":
                refs = checker.parse_reference_list(arguments["reference_text"])
                return [TextContent(type="text", text=json.dumps(refs))]

            elif name == "parse_pdf_references":
                content = checker.parse_pdf(arguments["pdf_path"])
                references = checker.extract_references_from_text(content)
                citations = checker.extract_citations(content)
                payload = {
                    "references": references,
                    "citations": citations,
                }
                return [TextContent(type="text", text=json.dumps(payload))]

            elif name == "compare_metadata":
                bib_entry = bib_entry_from_dict(arguments["bib_entry"])
                comparison = metadata_checker.compare_metadata(
                    bib_entry=bib_entry,
                    metadata=arguments["metadata"],
                    source=arguments["source"],
                )
                return [TextContent(type="text", text=json.dumps(comparison.to_dict()))]

            elif name == "verify_bib_entry":
                bib_entry = bib_entry_from_dict(arguments["bib_entry"])
                sources = arguments.get("sources")

                if any(
                    key in arguments
                    for key in (
                        "crossref_mailto",
                        "semantic_scholar_api_key",
                        "openalex_email",
                        "title_threshold",
                        "author_threshold",
                    )
                ):
                    metadata_checker_override = CitationMetadataChecker(
                        crossref_mailto=arguments.get(
                            "crossref_mailto",
                            "surveymae@example.com",
                        ),
                        semantic_scholar_api_key=arguments.get("semantic_scholar_api_key"),
                        openalex_email=arguments.get("openalex_email"),
                        title_threshold=arguments.get("title_threshold"),
                        author_threshold=arguments.get("author_threshold"),
                    )
                    report = await metadata_checker_override.verify_bib_entry(
                        bib_entry=bib_entry,
                        sources=sources,
                    )
                else:
                    report = await metadata_checker.verify_bib_entry(
                        bib_entry=bib_entry,
                        sources=sources,
                    )

                return [TextContent(type="text", text=json.dumps(report.to_dict()))]

            elif name == "extract_citations_with_context":
                verify = bool(arguments.get("verify_references", False))
                sources = arguments.get("verify_sources")
                verify_limit = arguments.get("verify_limit")
                # Unified async interface - always use await
                payload = await checker.extract_citations_with_context_from_pdf(
                    arguments["pdf_path"],
                    verify_references=verify,
                    sources=sources,
                    verify_limit=verify_limit,
                )
                return [TextContent(type="text", text=json.dumps(payload))]

            else:
                return [
                    TextContent(
                        type="text",
                        text=f"Unknown tool: {name}",
                        isError=True,
                    )
                ]

        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=str(e),
                    isError=True,
                )
            ]

    return app
