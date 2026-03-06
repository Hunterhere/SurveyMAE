"""SurveyMAE Configuration Management.

Provides centralized configuration loading using pydantic-settings.
All configuration is separated from code per Document 4 engineering standards.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

import yaml
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """Configuration for LLM providers.

    Attributes:
        provider: The LLM provider (e.g., "openai", "anthropic").
        model: The model identifier.
        api_key: API key (loaded from environment if not set).
        base_url: Optional base URL for API endpoints.
        temperature: Generation temperature [0.0, 2.0].
        max_tokens: Maximum tokens in response.
    """

    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.0
    max_tokens: int = 4096


class AgentConfig(BaseModel):
    """Configuration for a specific evaluation agent.

    Attributes:
        name: Agent identifier.
        llm: LLM configuration for this agent.
        system_prompt: Path to the system prompt file.
        tools: List of tool names this agent can use.
        retry_attempts: Number of retry attempts on failure.
        timeout: Timeout in seconds for agent execution.
    """

    name: str
    llm: Optional[LLMConfig] = None
    system_prompt: Optional[str] = None
    tools: List[str] = Field(default_factory=list)
    retry_attempts: int = 3
    timeout: int = 120


class MCPServerConfig(BaseModel):
    """Configuration for MCP server connections.

    Attributes:
        name: Server identifier.
        command: Command to launch server.
        args: Command arguments.
        env: Environment variables.
        url: HTTP URL for SSE connection.
    """

    name: str
    command: Optional[str] = None
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    url: Optional[str] = None


class DebateConfig(BaseModel):
    """Configuration for the debate/consensus mechanism.

    Attributes:
        max_rounds: Maximum debate rounds before forcing consensus.
        score_threshold: Score difference threshold to trigger debate.
        aggregator: Strategy for aggregating scores ("weighted", "average", "max").
        weights: Per-agent weights for weighted aggregation.
    """

    max_rounds: int = 3
    score_threshold: float = 2.0
    aggregator: str = "weighted"
    weights: Dict[str, float] = Field(default_factory=lambda: {
        "verifier": 1.0,
        "expert": 1.2,
        "reader": 1.0,
        "corrector": 0.8,
        "reporter": 1.0,
    })


class ReportConfig(BaseModel):
    """Configuration for report generation.

    Attributes:
        output_dir: Directory for output reports.
        include_evidence: Whether to include supporting evidence.
        include_radar: Whether to generate radar chart data.
        format: Output format ("markdown", "html", "json").
    """

    output_dir: str = "./output"
    include_evidence: bool = True
    include_radar: bool = True
    format: str = "markdown"


class CitationConfig(BaseModel):
    """Configuration for citation extraction backends.

    Attributes:
        backend: Backend selector ("auto", "grobid", "mupdf").
        grobid_url: Base URL for the GROBID service.
        grobid_timeout_s: HTTP timeout for GROBID requests in seconds.
        grobid_consolidate: Whether to enable GROBID citation consolidation.
    """

    backend: str = "auto"
    grobid_url: str = "http://localhost:8070"
    grobid_timeout_s: int = 30
    grobid_consolidate: bool = False


class SurveyMAEConfig(BaseModel):
    """Main configuration class for SurveyMAE.

    This class aggregates all configuration sections and provides
    environment variable overrides.

    Attributes:
        general: General configuration settings.
        llm: Default LLM configuration.
        agents: Agent-specific configurations.
        mcp_servers: MCP server configurations.
        debate: Debate mechanism settings.
        report: Report generation settings.
    """

    general: Dict[str, Any] = Field(default_factory=dict)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    agents: List[AgentConfig] = Field(default_factory=list)
    mcp_servers: List[MCPServerConfig] = Field(default_factory=list)
    debate: DebateConfig = Field(default_factory=DebateConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    citation: CitationConfig = Field(default_factory=CitationConfig)

    @classmethod
    def from_yaml(cls, config_path: str) -> "SurveyMAEConfig":
        """Load configuration from a YAML file.

        Args:
            config_path: Path to the YAML configuration file.

        Returns:
            SurveyMAEConfig instance.
        """
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Convert dict-based configs to proper models
        if "llm" in data and isinstance(data["llm"], dict):
            data["llm"] = LLMConfig(**data["llm"])

        if "agents" in data:
            agents = []
            for agent_data in data["agents"]:
                if isinstance(agent_data, dict):
                    llm_config = None
                    if "llm" in agent_data:
                        llm_config = LLMConfig(**agent_data.pop("llm"))
                    agent_data["llm"] = llm_config
                    agents.append(AgentConfig(**agent_data))
            data["agents"] = agents

        if "mcp_servers" in data:
            servers = []
            for server_data in data["mcp_servers"]:
                if isinstance(server_data, dict):
                    servers.append(MCPServerConfig(**server_data))
            data["mcp_servers"] = servers

        if "debate" in data and isinstance(data["debate"], dict):
            data["debate"] = DebateConfig(**data["debate"])

        if "report" in data and isinstance(data["report"], dict):
            data["report"] = ReportConfig(**data["report"])

        if "citation" in data and isinstance(data["citation"], dict):
            data["citation"] = CitationConfig(**data["citation"])

        return cls(**data)

    @classmethod
    def from_env(cls) -> "SurveyMAEConfig":
        """Create configuration from environment variables.

        Environment variables follow the pattern: SURVEYMAE_*.

        Returns:
            SurveyMAEConfig instance with environment overrides.
        """
        # This is a simplified version - full implementation would
        # parse all SURVEYMAE_* environment variables
        return cls()


def load_config(config_path: Optional[str] = None) -> SurveyMAEConfig:
    """Load configuration from file or environment.

    Args:
        config_path: Optional path to configuration file.
                    If not provided, looks for config/main.yaml.

    Returns:
        SurveyMAEConfig instance.
    """
    if config_path is None:
        # Look for config in standard locations
        possible_paths = [
            Path("config/main.yaml"),
            Path("../config/main.yaml"),
            Path(__file__).parent.parent.parent / "config" / "main.yaml",
        ]

        for path in possible_paths:
            if path.exists():
                config_path = str(path)
                break

    if config_path and Path(config_path).exists():
        return SurveyMAEConfig.from_yaml(config_path)

    # Return default config if no file found
    return SurveyMAEConfig.from_env()
