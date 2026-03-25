"""Keyword extraction tool for survey evaluation.

LLM-assisted extraction of topic keywords from survey metadata for use in
field trend analysis (T2/T5) and foundational coverage analysis (G4).
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from anthropic import AsyncAnthropic

from src.core.config import LLMConfig, load_config, ModelConfig

logger = logging.getLogger(__name__)


@dataclass
class KeywordExtractionResult:
    """Result of keyword extraction."""

    keywords: list[str]
    llm_involved: bool
    hallucination_risk: str  # "low" for LLM-assisted extraction
    raw_response: Optional[str] = None


class KeywordExtractor:
    """Extract topic keywords from survey metadata using LLM.

    This is a low-risk LLM use case as it only performs NLU tasks
    (keyword extraction) with well-defined input/output formats.
    """

    DEFAULT_PROMPT = """You are a keyword extraction assistant for academic survey evaluation.

Given the following survey metadata, extract 3-5 keyword groups for searching
academic databases. Each group should be a short query (2-5 words) targeting
the core topic and sub-topics of this survey.

Survey Title: {title}
Abstract: {abstract}
Section Headings: {section_headings}
Top Venues in References: {top_venues}
Top Keywords in References: {top_keywords}

Output as JSON array of strings. Only output the JSON, no explanation.
Example: ["retrieval augmented generation", "RAG LLM", "dense passage retrieval", "knowledge grounded generation"]
"""

    def __init__(
        self,
        llm: Optional[Runnable] = None,
        llm_config: Optional[LLMConfig] = None,
        prompt_template: Optional[str] = None,
    ):
        """Initialize the keyword extractor.

        Args:
            llm: Pre-configured LLM (if None, will create from config).
            llm_config: LLM configuration (used if llm is None).
            prompt_template: Custom prompt template.
        """
        self.llm = llm
        self.llm_config = llm_config
        self.prompt_template = prompt_template or self.DEFAULT_PROMPT

    def _get_llm(self) -> Runnable:
        """Get or create LLM instance.

        Uses ModelConfig.get_tool_config("keyword_extractor") which resolves
        base_url from models.yaml providers section automatically.
        """
        if self.llm is not None:
            return self.llm

        if self.llm_config is None:
            try:
                model_config = ModelConfig.from_yaml("config/models.yaml")
                self.llm_config = model_config.get_tool_config("keyword_extractor")
            except Exception:
                # Fallback to qwen if config loading fails
                self.llm_config = LLMConfig(
                    provider="qwen",
                    model="qwen3.5-flash",
                    temperature=0.0,
                )

        provider = self.llm_config.provider or "openai"

        if provider == "anthropic":
            return self._create_anthropic_llm(self.llm_config)

        return ChatOpenAI(
            model=self.llm_config.model,
            api_key=self.llm_config.api_key,
            base_url=self.llm_config.base_url,
            temperature=self.llm_config.temperature,
            max_tokens=self.llm_config.max_tokens,
        )

    def _create_anthropic_llm(self, llm_config: LLMConfig) -> Runnable:
        """Create an Anthropic-compatible LLM instance."""
        api_key = llm_config.api_key or os.getenv("ANTHROPIC_API_KEY")
        client = AsyncAnthropic(api_key=api_key)

        class AnthropicWrapper:
            def __init__(
                self, client: AsyncAnthropic, model: str, temperature: float, max_tokens: int
            ):
                self.client = client
                self.model = model
                self.temperature = temperature
                self.max_tokens = max_tokens

            async def ainvoke(self, messages: list[BaseMessage]) -> BaseMessage:
                anthropic_messages = []
                for msg in messages:
                    if isinstance(msg, SystemMessage):
                        anthropic_messages.append({"role": "user", "content": msg.content})
                        anthropic_messages.append({"role": "assistant", "content": ""})
                    elif isinstance(msg, HumanMessage):
                        anthropic_messages.append({"role": "user", "content": msg.content})

                if not anthropic_messages:
                    anthropic_messages = [{"role": "user", "content": "Hello"}]

                response = await self.client.messages.create(
                    model=self.model,
                    messages=anthropic_messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
                return HumanMessage(content=response.content[0].text)

        return AnthropicWrapper(
            client=client,
            model=llm_config.model,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
        )

    async def extract_keywords(
        self,
        title: str,
        abstract: str,
        section_headings: Optional[list[str]] = None,
        top_venues: Optional[list[str]] = None,
        top_keywords: Optional[list[str]] = None,
    ) -> KeywordExtractionResult:
        """Extract keywords from survey metadata.

        Args:
            title: Survey title.
            abstract: Survey abstract.
            section_headings: List of section headings.
            top_venues: Top venues from references (if available).
            top_keywords: Top keywords from references (if available).

        Returns:
            KeywordExtractionResult with extracted keywords.
        """
        section_str = "\n".join(f"- {h}" for h in (section_headings or []))
        venues_str = ", ".join(top_venues or [])
        keywords_str = ", ".join(top_keywords or [])

        prompt = self.prompt_template.format(
            title=title,
            abstract=abstract,
            section_headings=section_str,
            top_venues=venues_str,
            top_keywords=keywords_str,
        )

        try:
            llm = self._get_llm()
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            content = response.content if hasattr(response, "content") else str(response)

            # Parse JSON response
            keywords = self._parse_keywords(content)

            return KeywordExtractionResult(
                keywords=keywords,
                llm_involved=True,
                hallucination_risk="low",
                raw_response=content,
            )
        except Exception as e:
            logger.warning(f"Keyword extraction failed: {e}")
            # Fallback: extract keywords from title using simple method
            fallback_keywords = self._fallback_extract(title, abstract)
            return KeywordExtractionResult(
                keywords=fallback_keywords,
                llm_involved=True,
                hallucination_risk="medium",  # Higher risk for fallback
                raw_response=None,
            )

    def _parse_keywords(self, response: str) -> list[str]:
        """Parse keywords from LLM response."""
        # Try to extract JSON array from response
        response = response.strip()

        # Handle markdown code blocks
        if response.startswith("```"):
            # Find the JSON array
            import re

            json_match = re.search(r"\[.*\]", response, re.DOTALL)
            if json_match:
                response = json_match.group(0)

        try:
            keywords = json.loads(response)
            if isinstance(keywords, list):
                return [str(k).strip() for k in keywords if k]
        except json.JSONDecodeError:
            # Fallback: split by common delimiters
            import re

            keywords = re.split(r"[,;\n]", response)
            keywords = [k.strip().strip('"').strip("'") for k in keywords if k.strip()]
            return keywords[:5]  # Limit to 5

        return []

    def _fallback_extract(self, title: str, abstract: str) -> list[str]:
        """Fallback keyword extraction without LLM."""
        import re

        # Simple keyword extraction from title
        text = f"{title} {abstract}".lower()

        # Remove common stopwords
        stopwords = {
            "a",
            "an",
            "the",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "can",
            "this",
            "that",
            "these",
            "those",
            "i",
            "you",
            "he",
            "she",
            "it",
            "we",
            "they",
            "what",
            "which",
            "who",
            "whom",
            "whose",
            "where",
            "when",
            "why",
            "how",
        }

        # Extract 2-4 word phrases
        words = re.findall(r"\b[a-z]{2,}\b", text)
        phrases = []
        for i in range(len(words) - 1):
            if words[i] not in stopwords and words[i + 1] not in stopwords:
                phrases.append(f"{words[i]} {words[i + 1]}")

        # Return unique phrases
        unique_phrases = list(dict.fromkeys(phrases))
        return unique_phrases[:5]


def create_keyword_extractor_mcp_server():
    """Create an MCP server for keyword extraction."""
    from mcp.server import Server
    from mcp.types import Tool, TextContent

    app = Server("keyword-extractor")
    extractor = KeywordExtractor()

    @app.list_tools()
    async def list_tools():
        return [
            Tool(
                name="extract_keywords",
                description="Extract 3-5 keyword groups from survey metadata for academic database search",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Survey title"},
                        "abstract": {"type": "string", "description": "Survey abstract"},
                        "section_headings": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of section headings",
                        },
                        "top_venues": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Top venues from references",
                        },
                        "top_keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Top keywords from references",
                        },
                    },
                    "required": ["title", "abstract"],
                },
            )
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict):
        if name != "extract_keywords":
            return [TextContent(type="text", text=f"Unknown tool: {name}", isError=True)]

        try:
            result = await extractor.extract_keywords(
                title=arguments["title"],
                abstract=arguments["abstract"],
                section_headings=arguments.get("section_headings"),
                top_venues=arguments.get("top_venues"),
                top_keywords=arguments.get("top_keywords"),
            )
            output = {
                "keywords": result.keywords,
                "llm_involved": result.llm_involved,
                "hallucination_risk": result.hallucination_risk,
            }
            return [TextContent(type="text", text=json.dumps(output, ensure_ascii=False))]
        except Exception as exc:
            return [TextContent(type="text", text=str(exc), isError=True)]

    return app


if __name__ == "__main__":
    import asyncio

    async def test():
        extractor = KeywordExtractor()
        result = await extractor.extract_keywords(
            title="A Survey on Retrieval-Augmented Generation for Large Language Models",
            abstract="Retrieval-Augmented Generation (RAG) combines the power of retrieval systems with large language models...",
            section_headings=[
                "Introduction",
                "Retrieval Methods",
                "Generation Models",
                "Applications",
            ],
        )
        print(result.keywords)

    asyncio.run(test())
