"""Base Agent Class.

Abstract base class for all evaluation agents.
Provides common functionality for LLM calls, tool invocation, and state management.
"""

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI

# Optional Anthropic support
try:
    from anthropic import AsyncAnthropic

    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    AsyncAnthropic = None

from src.core.config import AgentConfig, LLMConfig, MultiModelConfig
from src.core.mcp_client import MCPManager
from src.core.state import SurveyState, EvaluationRecord

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base class for all SurveyMAE evaluation agents.

    This class encapsulates common agent functionality:
    - LLM configuration and invocation (single or multi-model)
    - MCP tool integration
    - Prompt template loading
    - Error handling and retry logic

    Attributes:
        name: Unique identifier for the agent.
        config: Agent configuration instance.
        mcp: Optional MCP manager for tool access.
        llm: The primary language model instance.
        multi_model_config: Optional configuration for multi-model support.
    """

    def __init__(
        self,
        name: str,
        config: Optional[AgentConfig] = None,
        mcp: Optional[MCPManager] = None,
        multi_model_config: Optional[MultiModelConfig] = None,
    ):
        """Initialize the agent.

        Args:
            name: Unique identifier for the agent.
            config: Optional agent configuration.
            mcp: Optional MCP manager for tool access.
            multi_model_config: Optional multi-model configuration.
        """
        self.name = name
        self.config = config or AgentConfig(name=name)
        self.mcp = mcp
        self.multi_model_config = multi_model_config
        self.llm = self._init_llm()
        self._llm_pool: Dict[str, Runnable] = {}
        if multi_model_config and multi_model_config.models:
            self._init_llm_pool()

    def _init_llm(self) -> Runnable:
        """Initialize the primary language model.

        Returns:
            A LangChain Runnable compatible LLM instance.
        """
        llm_config = self.config.llm or LLMConfig()

        # Map provider names to their base URLs and env keys
        provider_urls = {
            "openai": (None, "OPENAI_API_KEY"),
            "anthropic": (None, "ANTHROPIC_API_KEY"),
            "kimi": ("https://api.moonshot.cn/v1", "KIMI_API_KEY"),
            "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
            "chatglm": ("https://open.bigmodel.cn/api/paas/v4", "ZHIPU_API_KEY"),
            "step": ("https://api.stepfun.com/v1", "STEP_API_KEY"),
            "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
            "gemini": ("https://generativelanguage.googleapis.com/v1beta", "GOOGLE_API_KEY"),
            "seed": ("https://ark.cn-beijing.volces.com/api/v3", "BYTEAPI_KEY"),
        }

        provider = llm_config.provider or "openai"

        if provider == "anthropic":
            return self._create_anthropic_llm(llm_config)

        # For OpenAI-compatible APIs (most providers)
        if provider in provider_urls:
            base_url, env_key = provider_urls[provider]
            # Use config base_url if provided, otherwise use default
            base_url = llm_config.base_url or base_url
            # Get API key from config or environment
            api_key = llm_config.api_key or os.getenv(env_key)

            return ChatOpenAI(
                model=llm_config.model,
                api_key=api_key,
                base_url=base_url,
                temperature=llm_config.temperature,
                max_tokens=llm_config.max_tokens,
            )

        # Default to OpenAI
        return ChatOpenAI(
            model=llm_config.model,
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
        )

    def _create_anthropic_llm(self, llm_config: LLMConfig) -> Runnable:
        """Create an Anthropic-compatible LLM instance.

        Args:
            llm_config: LLM configuration.

        Returns:
            Anthropic-compatible Runnable.
        """
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(
                "Anthropic package not installed. Install with: pip install anthropic"
            )

        api_key = llm_config.api_key or os.getenv("ANTHROPIC_API_KEY")
        client = AsyncAnthropic(api_key=api_key)

        # Return a wrapper that makes it compatible with LangChain
        class AnthropicWrapper:
            def __init__(
                self, client: AsyncAnthropic, model: str, temperature: float, max_tokens: int
            ):
                self.client = client
                self.model = model
                self.temperature = temperature
                self.max_tokens = max_tokens

            async def ainvoke(self, messages: List[BaseMessage]) -> BaseMessage:
                # Convert LangChain messages to Anthropic format
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
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    messages=anthropic_messages,
                )
                return HumanMessage(content=response.content[0].text)

            def bind_tools(self, tools: List[Dict]) -> Runnable:
                return self

        return AnthropicWrapper(
            client=client,
            model=llm_config.model,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
        )

    def _init_llm_pool(self) -> None:
        """Initialize the pool of LLMs for multi-model support."""
        if not self.multi_model_config:
            return

        # Provider base URLs mapping
        provider_urls = {
            "openai": (None, "OPENAI_API_KEY"),
            "anthropic": (None, "ANTHROPIC_API_KEY"),
            "kimi": ("https://api.moonshot.cn/v1", "KIMI_API_KEY"),
            "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
            "chatglm": ("https://open.bigmodel.cn/api/paas/v4", "ZHIPU_API_KEY"),
            "step": ("https://api.stepfun.com/v1", "STEP_API_KEY"),
            "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
            "gemini": ("https://generativelanguage.googleapis.com/v1beta", "GOOGLE_API_KEY"),
            "seed": ("https://ark.cn-beijing.volces.com/api/v3", "BYTEAPI_KEY"),
        }

        for i, model_config in enumerate(self.multi_model_config.models):
            provider = model_config.provider or "openai"
            key = f"{provider}_{model_config.model}_{i}"

            if provider == "anthropic":
                self._llm_pool[key] = self._create_anthropic_llm(model_config)
            elif provider in provider_urls:
                base_url, env_key = provider_urls[provider]
                base_url = model_config.base_url or base_url
                api_key = model_config.api_key or os.getenv(env_key)
                self._llm_pool[key] = ChatOpenAI(
                    model=model_config.model,
                    api_key=api_key,
                    base_url=base_url,
                    temperature=model_config.temperature,
                    max_tokens=model_config.max_tokens,
                )
            else:
                # Default to OpenAI
                self._llm_pool[key] = ChatOpenAI(
                    model=model_config.model,
                    api_key=model_config.api_key,
                    base_url=model_config.base_url,
                    temperature=model_config.temperature,
                    max_tokens=model_config.max_tokens,
                )

    async def _call_llm(
        self,
        messages: List[BaseMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_attempts: Optional[int] = None,
    ) -> str:
        """Call the language model with retry logic.

        Args:
            messages: List of messages to send.
            tools: Optional list of tools in LangChain format.
            max_attempts: Override for retry attempts (default from config).

        Returns:
            The model's response text.
        """
        max_attempts = max_attempts or self.config.retry_attempts
        attempt = 0

        while attempt < max_attempts:
            try:
                # If tools are provided, bind them to the LLM
                llm_with_tools = self.llm
                if tools:
                    llm_with_tools = self.llm.bind_tools(tools)

                response = await llm_with_tools.ainvoke(messages)
                return response.content

            except Exception as e:
                attempt += 1
                logger.warning(f"LLM call attempt {attempt}/{max_attempts} failed: {e}")
                if attempt >= max_attempts:
                    logger.error(f"All {max_attempts} attempts failed")
                    raise

                await asyncio.sleep(2**attempt * 0.1)

        return ""

    async def _call_llm_pool(
        self,
        messages: List[BaseMessage],
    ) -> List[Dict[str, Any]]:
        """Call multiple LLMs in parallel for voting.

        Args:
            messages: List of messages to send to each model.

        Returns:
            List of responses with model identifier.
        """
        if not self._llm_pool:
            # Fallback to single model
            response = await self._call_llm(messages)
            return [{"model": "default", "response": response}]

        tasks = []
        model_keys = []

        for key, llm in self._llm_pool.items():
            tasks.append(llm.ainvoke(messages))
            model_keys.append(key)

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        results = []
        for key, resp in zip(model_keys, responses):
            if isinstance(resp, Exception):
                logger.error(f"Model {key} failed: {resp}")
                results.append({"model": key, "response": "", "error": str(resp)})
            else:
                content = resp.content if hasattr(resp, "content") else str(resp)
                results.append({"model": key, "response": content})

        return results

    async def _call_mcp_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Any:
        """Call an MCP tool.

        Args:
            tool_name: Name of the tool to call.
            arguments: Tool arguments.

        Returns:
            Tool result.
        """
        if not self.mcp:
            logger.warning(f"MCP not configured, skipping tool call: {tool_name}")
            return None

        try:
            # Try to call via MCP manager
            result = await self.mcp.call_tool(
                server="citation_checker",
                tool=tool_name,
                args=arguments,
            )
            return result
        except Exception as e:
            logger.error(f"MCP tool call failed: {tool_name}, error: {e}")
            return None

    def _load_prompt(self, prompt_name: str, **kwargs: Any) -> str:
        """Load a prompt template and format it with provided arguments.

        Args:
            prompt_name: Name of the prompt file (without extension).
            **kwargs: Variables to substitute in the prompt template.

        Returns:
            Formatted prompt string.
        """
        # Look for prompt in standard locations
        prompt_paths = [
            Path(f"config/prompts/{prompt_name}.yaml"),
            Path(f"../config/prompts/{prompt_name}.yaml"),
            Path(__file__).parent.parent.parent / "config" / "prompts" / f"{prompt_name}.yaml",
        ]

        for prompt_path in prompt_paths:
            if prompt_path.exists():
                import yaml

                with open(prompt_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    template = data.get("template", data.get("prompt", ""))
                    return template.format(**kwargs)

        # Fallback: return the prompt name as-is
        logger.warning(f"Prompt template not found: {prompt_name}")
        return kwargs.get("default_prompt", f"Evaluate: {kwargs}")

    def _create_messages(
        self,
        system_prompt: str,
        user_content: str,
    ) -> List[BaseMessage]:
        """Create a message list from prompt and content.

        Args:
            system_prompt: The system message.
            user_content: The human message content.

        Returns:
            List of BaseMessage objects.
        """
        messages = [SystemMessage(content=system_prompt)]
        messages.append(HumanMessage(content=user_content))
        return messages

    @abstractmethod
    async def evaluate(
        self,
        state: SurveyState,
        section_name: Optional[str] = None,
    ) -> EvaluationRecord:
        """Perform evaluation and return a record.

        This is the main method that subclasses must implement.
        It should analyze the survey content and produce an evaluation record.

        Args:
            state: The current workflow state containing survey content.
            section_name: Optional specific section to evaluate.

        Returns:
            An EvaluationRecord with the evaluation result.
        """
        pass

    async def process(
        self,
        state: SurveyState,
    ) -> Dict[str, Any]:
        """Process the current state and return state updates.

        This method is called by LangGraph nodes.
        It wraps the evaluate method to return updates in the expected format.

        Args:
            state: The current workflow state.

        Returns:
            A dictionary of state updates to be merged.
        """
        from src.core.state import AgentOutput, AgentSubScore
        import json
        import re

        def extract_json(text: str) -> dict:
            """Extract JSON object from text that may have extra content."""
            if not text:
                return {}
            text = text.strip()
            # Try direct parse first
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
            # Try to find JSON in markdown code blocks
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass
            # Try to find any {...} pattern
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
            return {}

        try:
            record = await self.evaluate(state)

            # Handle case where evaluate() returns a dict (including TypedDict)
            # TypedDict doesn't support isinstance() with the TypedDict type,
            # so we check if it's a dict and then create a proper EvaluationRecord
            # TypedDict instances are dict subclasses at runtime
            if hasattr(record, 'get') and hasattr(record, 'keys'):
                # It's dict-like - convert to EvaluationRecord
                try:
                    record = EvaluationRecord(
                        agent_name=record.get("agent_name", self.name),
                        dimension=record.get("dimension", "unknown"),
                        score=record.get("score", record.get("overall_score", 5.0)),
                        reasoning=str(record.get("reasoning", record.get("evidence_summary", ""))),
                        evidence=record.get("evidence", record.get("evidence_summary")),
                        confidence=record.get("confidence", 0.5),
                    )
                except Exception:
                    # If conversion fails, create default
                    record = EvaluationRecord(
                        agent_name=self.name,
                        dimension="unknown",
                        score=5.0,
                        reasoning="Evaluation conversion failed",
                        evidence=None,
                        confidence=0.5,
                    )

            # Now record should be an EvaluationRecord
            # Convert EvaluationRecord to AgentOutput format
            # Parse the JSON from reasoning if possible
            # Note: TypedDict is dict at runtime, use dict access pattern
            sub_scores = {}
            reasoning_text = str(record.get("reasoning", "")) if record.get("reasoning") else ""
            parsed = extract_json(reasoning_text)
            if parsed and "sub_scores" in parsed:
                # Convert parsed sub_scores to AgentSubScore format
                for key, value in parsed["sub_scores"].items():
                    sub_scores[key] = AgentSubScore(
                        score=value.get("score", record.get("score", 5.0)),
                        llm_involved=value.get("llm_involved", True),
                        tool_evidence=value.get("tool_evidence", {}),
                        llm_reasoning=value.get("llm_reasoning", ""),
                        flagged_items=value.get("flagged_items"),
                        variance=value.get("variance"),
                    )
            else:
                # Create a simple sub_score from the overall record
                reasoning_str = str(record.get("reasoning", ""))[:500] if record.get("reasoning") else ""
                sub_scores = {
                    f"{record.get('dimension', 'unknown')}_overall": AgentSubScore(
                        score=record.get("score", 5.0),
                        llm_involved=True,
                        tool_evidence={},
                        llm_reasoning=reasoning_str,
                        flagged_items=None,
                        variance=None,
                    )
                }

            # Ensure record attributes are strings
            agent_name = str(record.get("agent_name", "")) if record.get("agent_name") else self.name
            dimension = str(record.get("dimension", "")) if record.get("dimension") else "unknown"
            evidence_summary = str(record.get("evidence", "")) if record.get("evidence") else ""

            agent_output = AgentOutput(
                agent_name=agent_name,
                dimension=dimension,
                sub_scores=sub_scores,
                overall_score=float(record.get("score", 5.0)) if record.get("score") else 5.0,
                confidence=float(record.get("confidence", 0.5)) if record.get("confidence") else 0.5,
                evidence_summary=evidence_summary,
            )

            return {
                "evaluations": [record],
                "agent_outputs": {self.name: agent_output},
            }
        except Exception as e:
            import traceback
            logger.error(f"Agent {self.name} evaluation failed: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "evaluations": [
                    EvaluationRecord(
                        agent_name=self.name,
                        dimension="error",
                        score=0.0,
                        reasoning=f"Evaluation failed: {str(e)}",
                        evidence=None,
                        confidence=0.0,
                    )
                ],
                "agent_outputs": {
                    self.name: AgentOutput(
                        agent_name=self.name,
                        dimension="error",
                        sub_scores={},
                        overall_score=0.0,
                        confidence=0.0,
                        evidence_summary=f"Evaluation failed: {str(e)}",
                    )
                },
            }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"
