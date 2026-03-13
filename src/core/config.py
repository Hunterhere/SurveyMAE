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


class MultiModelConfig(BaseModel):
    """Configuration for multi-model voting.

    Attributes:
        enabled: Whether to enable multi-model voting.
        models: List of model configurations for voting.
        use_parallel: Whether to use parallel calls for voting.
    """

    enabled: bool = False
    models: List[LLMConfig] = Field(default_factory=list)
    use_parallel: bool = True


class AgentModelConfig(BaseModel):
    """Configuration for a specific agent's model.

    Attributes:
        name: Agent name (verifier, expert, reader, corrector, reporter).
        provider: LLM provider.
        model: Model identifier.
        temperature: Generation temperature.
        max_tokens: Maximum tokens.
        multi_model: Multi-model voting configuration.
    """

    name: str
    provider: str = "openai"
    model: str = "gpt-4o"
    temperature: float = 0.0
    max_tokens: int = 4096
    multi_model: Optional[MultiModelConfig] = None


class ModelConfig(BaseModel):
    """Configuration for all agent models.

    Attributes:
        default: Default LLM configuration.
        agents: Agent-specific model configurations.
        providers: Provider-level configurations.
    """

    default: LLMConfig = Field(default_factory=LLMConfig)
    agents: Dict[str, AgentModelConfig] = Field(default_factory=dict)
    providers: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    @classmethod
    def from_yaml(cls, config_path: str) -> "ModelConfig":
        """Load model configuration from YAML file.

        Args:
            config_path: Path to models.yaml.

        Returns:
            ModelConfig instance.
        """
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Parse default
        default = LLMConfig(**data.get("default", {}))

        # Parse agent configs
        agents = {}
        if "agents" in data:
            for name, agent_data in data["agents"].items():
                multi_model = None
                if "multi_model" in agent_data:
                    mm_data = agent_data["multi_model"]
                    models = [LLMConfig(**m) for m in mm_data.get("models", [])]
                    multi_model = MultiModelConfig(
                        enabled=mm_data.get("enabled", False),
                        models=models,
                    )
                agents[name] = AgentModelConfig(
                    name=name,
                    provider=agent_data.get("provider", "openai"),
                    model=agent_data.get("model", "gpt-4o"),
                    temperature=agent_data.get("temperature", 0.0),
                    max_tokens=agent_data.get("max_tokens", 4096),
                    multi_model=multi_model,
                )

        return cls(
            default=default,
            agents=agents,
            providers=data.get("providers", {}),
        )

    def get_agent_config(self, agent_name: str) -> LLMConfig:
        """Get LLM config for a specific agent.

        Args:
            agent_name: Name of the agent.

        Returns:
            LLMConfig for the agent, or default if not found.
        """
        if agent_name in self.agents:
            agent = self.agents[agent_name]
            return LLMConfig(
                provider=agent.provider,
                model=agent.model,
                temperature=agent.temperature,
                max_tokens=agent.max_tokens,
            )
        return self.default

    def get_multi_model_config(self, agent_name: str) -> Optional[MultiModelConfig]:
        """Get multi-model config for a specific agent.

        Args:
            agent_name: Name of the agent.

        Returns:
            MultiModelConfig if configured, None otherwise.
        """
        if agent_name in self.agents:
            return self.agents[agent_name].multi_model
        return None


class AgentConfig(BaseModel):
    """Configuration for a specific evaluation agent.

    Attributes:
        name: Agent identifier.
        llm: LLM configuration for this agent.
        system_prompt: Path to the system prompt file.
        tools: List of tool names this agent can use.
        retry_attempts: Number of retry attempts on failure.
        timeout: Timeout in seconds for agent execution.
        multi_model: Multi-model voting configuration (for CorrectorAgent).
    """

    name: str
    llm: Optional[LLMConfig] = None
    system_prompt: Optional[str] = None
    tools: List[str] = Field(default_factory=list)
    retry_attempts: int = 3
    timeout: int = 120
    multi_model: Optional[MultiModelConfig] = None


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
    weights: Dict[str, float] = Field(
        default_factory=lambda: {
            "verifier": 1.0,
            "expert": 1.2,
            "reader": 1.0,
            "corrector": 0.8,
            "reporter": 1.0,
        }
    )


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


class EvidenceConfig(BaseModel):
    """Configuration for evidence collection.

    Attributes:
        foundational_top_k: Number of top-cited papers to retrieve for G4.
        foundational_match_threshold: Title matching threshold for G4 (0-1).
        trend_query_count: Number of query groups for field trend retrieval.
        trend_year_range: Year range for trend retrieval.
        clustering_algorithm: Clustering algorithm for S5 ("louvain", "spectral", "leiden").
        clustering_seed: Random seed for clustering.
        citation_sample_size: Number of citation-claim pairs to sample.
        api_timeout_seconds: Timeout for API requests.
        fallback_order: Ordered list of sources for fallback.
    """

    foundational_top_k: int = 30
    foundational_match_threshold: float = 0.85
    trend_query_count: int = 5
    trend_year_range: tuple[int, int] = (2015, 2025)
    clustering_algorithm: str = "louvain"
    clustering_seed: int = 42
    citation_sample_size: int = 15
    api_timeout_seconds: int = 30
    fallback_order: list[str] = field(default_factory=lambda: ["semantic_scholar", "openalex"])


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
    evidence: EvidenceConfig = Field(default_factory=EvidenceConfig)

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

        if "evidence" in data and isinstance(data["evidence"], dict):
            data["evidence"] = EvidenceConfig(**data["evidence"])

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


def load_model_config(config_path: Optional[str] = None) -> ModelConfig:
    """Load model configuration from file.

    Args:
        config_path: Optional path to models.yaml.
                    If not provided, looks for config/models.yaml.

    Returns:
        ModelConfig instance.
    """
    if config_path is None:
        # Look for config in standard locations
        possible_paths = [
            Path("config/models.yaml"),
            Path("../config/models.yaml"),
            Path(__file__).parent.parent.parent / "config" / "models.yaml",
        ]

        for path in possible_paths:
            if path.exists():
                config_path = str(path)
                break

    if config_path and Path(config_path).exists():
        return ModelConfig.from_yaml(config_path)

    # Return default config if no file found
    return ModelConfig()
