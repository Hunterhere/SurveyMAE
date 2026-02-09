"""Citation Checker Tool.

Provides citation extraction and verification functionality.
Can be used to check if cited papers exist and match claims.
"""

import re
import logging
from typing import List, Dict, Optional, Tuple

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
    ) -> Dict[str, any]:
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

    @app.list_tools()
    async def list_tools():
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
                            "description": "Dictionary of references (citation_number -> reference_text)",
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
