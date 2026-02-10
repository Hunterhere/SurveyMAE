"""Citation Checker Tool.

Provides citation extraction and verification functionality.
Can be used to check if cited papers exist and match claims.
"""

import re
import logging
from typing import List, Dict, Optional, Any

from src.tools.citation_metadata import (
    CitationMetadataChecker,
    bib_entry_from_dict,
)
from src.tools.pdf_parser import PDFParser

logger = logging.getLogger(__name__)


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

    def __init__(self):
        """Initialize the citation checker."""
        self.citation_regex = re.compile(self.CITATION_PATTERN)
        self.ref_regex = re.compile(self.REF_PATTERN, re.MULTILINE)

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
            if (
                len(stripped) <= 40
                and re.search(r"\b(%s)\b" % "|".join(self.REFERENCE_HEADINGS), stripped, re.IGNORECASE)
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

            else:
                return [TextContent(
                    type="text",
                    text=f"Unknown tool: {name}",
                    isError=True,
                )]

        except Exception as e:
            return [TextContent(
                type="text",
                text=str(e),
                isError=True,
            )]

    return app
