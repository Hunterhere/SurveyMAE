"""Base Agent Class.

Abstract base class for all evaluation agents.
Provides common functionality for LLM calls, tool invocation, and state management.
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI

from src.core.config import AgentConfig, LLMConfig
from src.core.mcp_client import MCPManager
from src.core.state import SurveyState, EvaluationRecord

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base class for all SurveyMAE evaluation agents.

    This class encapsulates common agent functionality:
    - LLM configuration and invocation
    - MCP tool integration
    - Prompt template loading
    - Error handling and retry logic

    Attributes:
        name: Unique identifier for the agent.
        config: Agent configuration instance.
        mcp: Optional MCP manager for tool access.
        llm: The language model instance.
    """

    def __init__(
        self,
        name: str,
        config: Optional[AgentConfig] = None,
        mcp: Optional[MCPManager] = None,
    ):
        """Initialize the agent.

        Args:
            name: Unique identifier for the agent.
            config: Optional agent configuration.
            mcp: Optional MCP manager for tool access.
        """
        self.name = name
        self.config = config or AgentConfig(name=name)
        self.mcp = mcp
        self.llm = self._init_llm()

    def _init_llm(self) -> Runnable:
        """Initialize the language model.

        Returns:
            A LangChain Runnable compatible LLM instance.
        """
        llm_config = self.config.llm or LLMConfig()

        return ChatOpenAI(
            model=llm_config.model,
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
        )

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
            Path(__file__).parent.parent.parent
            / "config"
            / "prompts"
            / f"{prompt_name}.yaml",
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
                logger.warning(
                    f"LLM call attempt {attempt}/{max_attempts} failed: {e}"
                )
                if attempt >= max_attempts:
                    logger.error(f"All {max_attempts} attempts failed")
                    raise

                # Exponential backoff
                import asyncio

                await asyncio.sleep(2**attempt * 0.1)

        return ""

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
        try:
            record = await self.evaluate(state)
            return {
                "evaluations": [record],
            }
        except Exception as e:
            logger.error(f"Agent {self.name} evaluation failed: {e}")
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
            }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"
