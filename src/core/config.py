"""SurveyMAE Configuration Management.

Provides centralized configuration loading using pydantic-settings.
All configuration is separated from code per Document 4 engineering standards.

TODO: 未来可考虑使用 pydantic-settings 简化配置管理:
    - 安装: pip install pydantic-settings
    - 优势:
        1. 原生支持 YAML 文件、环境变量、默认值的分层优先级管理
        2. 自动从 YAML/环境变量/默认值读取，无需手动 load_config()
        3. 配置示例:
            from pydantic_settings import BaseSettings, SettingsConfigDict
            class EvidenceConfig(BaseSettings):
                model_config = SettingsConfigDict(
                    yaml_file="config/main.yaml",
                    env_prefix="SURVEYMAE_",
                )
                foundational_top_k: int = Field(default=30)
                contradiction_threshold: float = Field(default=0.05)
            config = EvidenceConfig()  # 自动加载
    - 当前方案: 使用 from_yaml() 手动加载，字段定义暂保留默认值作为 fallback
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

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
        tools: Tool-specific model configurations.
        agents: Agent-specific model configurations.
        providers: Provider-level configurations.
    """

    default: LLMConfig = Field(default_factory=LLMConfig)
    tools: Dict[str, LLMConfig] = Field(default_factory=dict)
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

        # Parse tool configs
        tools = {}
        if "tools" in data:
            for name, tool_data in data["tools"].items():
                tools[name] = LLMConfig(
                    provider=tool_data.get("provider", "openai"),
                    model=tool_data.get("model", "gpt-4o"),
                    temperature=tool_data.get("temperature", 0.0),
                    max_tokens=tool_data.get("max_tokens", 4096),
                )

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
            tools=tools,
            agents=agents,
            providers=data.get("providers", {}),
        )

    def get_agent_config(self, agent_name: str) -> LLMConfig:
        """Get LLM config for a specific agent.

        Includes base_url resolved from providers mapping, so the returned
        LLMConfig is fully usable with ChatOpenAI without additional mapping.

        Usage example:
            >>> model_config = ModelConfig.from_yaml("config/models.yaml")
            >>> llm_cfg = model_config.get_agent_config("verifier")
            >>> # llm_cfg.base_url is now "https://dashscope.aliyuncs.com/compatible-mode/v1" for qwen
            >>> from langchain_openai import ChatOpenAI
            >>> llm = ChatOpenAI(model=llm_cfg.model, api_key=llm_cfg.api_key,
            ...                  base_url=llm_cfg.base_url, temperature=llm_cfg.temperature)

        Args:
            agent_name: Name of the agent.

        Returns:
            LLMConfig for the agent (with base_url populated), or default if not found.
        """
        if agent_name in self.agents:
            agent = self.agents[agent_name]
            base_url = self.get_provider_base_url(agent.provider)
            env_key = self._get_provider_env_key(agent.provider)
            api_key = os.getenv(env_key) if env_key else None
            return LLMConfig(
                provider=agent.provider,
                model=agent.model,
                api_key=api_key,
                base_url=base_url,
                temperature=agent.temperature,
                max_tokens=agent.max_tokens,
            )
        # Fallback to default, also resolve its base_url
        base_url = self.get_provider_base_url(self.default.provider)
        env_key = self._get_provider_env_key(self.default.provider)
        api_key = os.getenv(env_key) if env_key else None
        return LLMConfig(
            provider=self.default.provider,
            model=self.default.model,
            api_key=api_key,
            base_url=base_url,
            temperature=self.default.temperature,
            max_tokens=self.default.max_tokens,
        )

    def get_tool_config(self, tool_name: str) -> LLMConfig:
        """Get LLM config for a specific tool.

        Includes base_url resolved from providers mapping, so the returned
        LLMConfig is fully usable with ChatOpenAI without additional mapping.

        Usage example:
            >>> model_config = ModelConfig.from_yaml("config/models.yaml")
            >>> llm_cfg = model_config.get_tool_config("citation_checker")
            >>> # llm_cfg.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1" for qwen
            >>> from langchain_openai import ChatOpenAI
            >>> llm = ChatOpenAI(model=llm_cfg.model, api_key=llm_cfg.api_key,
            ...                  base_url=llm_cfg.base_url, temperature=llm_cfg.temperature)

        Args:
            tool_name: Name of the tool (e.g., "citation_checker", "keyword_extractor").

        Returns:
            LLMConfig for the tool (with base_url populated), or default if not found.
        """
        if tool_name in self.tools:
            tool = self.tools[tool_name]
            base_url = self.get_provider_base_url(tool.provider)
            env_key = self._get_provider_env_key(tool.provider)
            api_key = os.getenv(env_key) if env_key else None
            return LLMConfig(
                provider=tool.provider,
                model=tool.model,
                api_key=api_key,
                base_url=base_url,
                temperature=tool.temperature,
                max_tokens=tool.max_tokens,
            )
        # Fallback to default, also resolve its base_url
        base_url = self.get_provider_base_url(self.default.provider)
        env_key = self._get_provider_env_key(self.default.provider)
        api_key = os.getenv(env_key) if env_key else None
        return LLMConfig(
            provider=self.default.provider,
            model=self.default.model,
            api_key=api_key,
            base_url=base_url,
            temperature=self.default.temperature,
            max_tokens=self.default.max_tokens,
        )

    def get_provider_base_url(self, provider: str) -> Optional[str]:
        """Get base_url for a provider from the providers mapping.

        Usage example:
            >>> model_config = ModelConfig.from_yaml("config/models.yaml")
            >>> url = model_config.get_provider_base_url("qwen")
            >>> print(url)
            https://dashscope.aliyuncs.com/compatible-mode/v1

        Args:
            provider: Provider name (e.g., "qwen", "kimi", "deepseek").

        Returns:
            base_url string if found in providers mapping, None otherwise.
        """
        return self.providers.get(provider, {}).get("base_url")

    def _get_provider_env_key(self, provider: str) -> Optional[str]:
        """Get the environment variable name for a provider's API key.

        Usage example:
            >>> model_config = ModelConfig.from_yaml("config/models.yaml")
            >>> import os
            >>> env_key = model_config._get_provider_env_key("qwen")
            >>> api_key = os.getenv(env_key)  # e.g., "DASHSCOPE_API_KEY"

        Args:
            provider: Provider name.

        Returns:
            Environment variable name (e.g., "DASHSCOPE_API_KEY") or None.
        """
        return self.providers.get(provider, {}).get("env_key")

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


class AggregationConfig(BaseModel):
    """Configuration for score aggregation (v3).

    Attributes:
        weights: Per-dimension weights for weighted aggregation.
                 Keys are dimension IDs (V1, V2, E1, E2, etc.)
    """

    weights: Dict[str, float]


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


class MarkerApiConfig(BaseModel):
    """Configuration for Datalab Marker API.

    Attributes:
        base_url: Marker API base URL.
        mode: Processing mode ("fast", "balanced", "accurate").
        include_markdown_in_chunks: Include markdown in JSON output (cost-optimal single call).
        additional_config: Extra config passed to API (e.g., page header/footer control).
        max_poll_attempts: Max polling attempts (~2 min at 2s interval).
        poll_interval_seconds: Seconds between poll attempts.
        request_timeout_seconds: Total request timeout.
    """

    base_url: str = "https://www.datalab.to"
    mode: str = "accurate"
    include_markdown_in_chunks: bool = True
    additional_config: Dict[str, Any] = Field(default_factory=lambda: {
        "keep_pageheader_in_output": False,
        "keep_pagefooter_in_output": False,
    })
    max_poll_attempts: int = 60
    poll_interval_seconds: int = 2
    request_timeout_seconds: int = 300


class Pymupdf4llmConfig(BaseModel):
    """Configuration for PyMuPDF4LLM backend.
    
    Attributes:
        use_layout: Whether to use PyMuPDF Layout engine (v0.2.0+).
        show_header: Whether to include page headers in output.
        show_footer: Whether to include page footers in output.
    """
    use_layout: bool = True
    show_header: bool = False
    show_footer: bool = False


class PdfParserConfig(BaseModel):
    """Configuration for PDF parsing backend selection.

    Attributes:
        backend: Backend selector ("marker_api" | "pymupdf4llm" | "auto").
        marker_api: Marker API-specific configuration.
        pymupdf4llm: PyMuPDF4LLM-specific configuration.
        cache_dir: Directory for disk-cached parse results.
    """

    backend: str = "auto"
    marker_api: MarkerApiConfig = Field(default_factory=MarkerApiConfig)
    pymupdf4llm: Pymupdf4llmConfig = Field(default_factory=Pymupdf4llmConfig)
    cache_dir: str = "./output/pdf_cache"


class EvidenceConfig(BaseModel):
    """Configuration for evidence collection.

    Note: 字段不设置默认值，强制从 YAML 读取，确保配置一致性。
    如 YAML 缺失字段，from_yaml() 会抛出 ValidationError。

    Attributes:
        foundational_top_k: Number of top-cited papers to retrieve for G4.
        foundational_match_threshold: Title matching threshold for G4 (0-1).
        trend_query_count: Number of query groups for field trend retrieval.
        trend_year_range: Year range for trend retrieval.
        clustering_algorithm: Clustering algorithm for S5 ("louvain", "spectral", "leiden").
        clustering_seed: Random seed for clustering.
        citation_sample_size: Number of citation-claim pairs to sample.
        c6_batch_size: Number of sentence-abstract pairs per batch for C6.
        c6_model: Model to use for C6 batch processing.
        c6_max_concurrency: Maximum concurrent batches for C6.
        contradiction_threshold: Threshold for auto-fail (0-1).
    """

    # 必填字段（无默认值，强制从 YAML 读取）
    foundational_top_k: int
    foundational_match_threshold: float
    trend_query_count: int
    trend_year_range: tuple[int, int]
    clustering_algorithm: str
    clustering_seed: int
    citation_sample_size: int
    c6_batch_size: int
    c6_model: str
    c6_max_concurrency: int
    contradiction_threshold: float

    # V2 (Citation-Assertion Alignment) scoring thresholds
    v2_score_5_threshold: float
    v2_score_4_threshold: float
    v2_score_3_threshold: float
    v2_score_2_threshold: float


class SearchEnginesConfig(BaseModel):
    """Configuration for search engines and retrieval settings.

    Reads from the new-format ``config/search_engines.yaml`` which uses
    ``concurrency:``, ``degradation:``, and ``sources:`` sections.
    Exposes legacy-compatible properties so callers don't need changes.

    配置文件: config/search_engines.yaml
    """

    verify_limit: int = 50
    api_timeout_seconds: int = 15
    fallback_order: list[str] = Field(default_factory=lambda: ["semantic_scholar", "openalex", "crossref"])

    @classmethod
    def from_yaml(cls, config_path: str = "config/search_engines.yaml") -> "SearchEnginesConfig":
        """Load search engines configuration from YAML file.

        Supports both the new extended format and the legacy flat format.
        """
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Extract verify_limit / api_timeout_seconds (same position in both formats)
        verify_limit = data.get("verify_limit", 50)
        api_timeout_seconds = data.get("api_timeout_seconds", 15)

        # fallback_order: try degradation.fallback_order first, then top-level
        degradation = data.get("degradation", {}) or {}
        fallback_order = degradation.get(
            "fallback_order",
            data.get("fallback_order", ["semantic_scholar", "openalex", "crossref"]),
        )

        return cls(
            verify_limit=verify_limit,
            api_timeout_seconds=api_timeout_seconds,
            fallback_order=fallback_order,
        )


class SurveyMAEConfig(BaseModel):
    """Main configuration class for SurveyMAE.

    This class aggregates all configuration sections and provides
    environment variable overrides.

    Attributes:
        general: General configuration settings.
        llm: Default LLM configuration.
        agents: Agent-specific configurations.
        mcp_servers: MCP server configurations.
        aggregation: Score aggregation settings (v3).
        report: Report generation settings.
    """

    general: Dict[str, Any] = Field(default_factory=dict)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    agents: List[AgentConfig] = Field(default_factory=list)
    mcp_servers: List[MCPServerConfig] = Field(default_factory=list)
    aggregation: AggregationConfig
    report: ReportConfig = Field(default_factory=ReportConfig)
    citation: CitationConfig = Field(default_factory=CitationConfig)
    evidence: EvidenceConfig = Field(default_factory=EvidenceConfig)
    pdf_parser: PdfParserConfig = Field(default_factory=PdfParserConfig)

    def get_env(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get environment variable value with fallback to default.

        Args:
            key: Environment variable name (e.g., 'OPENAI_API_KEY').
            default: Default value if not found in environment.

        Returns:
            Environment variable value or default.
        """
        import os

        return os.getenv(key, default)

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

        if "aggregation" in data and isinstance(data["aggregation"], dict):
            data["aggregation"] = AggregationConfig(**data["aggregation"])

        if "report" in data and isinstance(data["report"], dict):
            data["report"] = ReportConfig(**data["report"])

        if "citation" in data and isinstance(data["citation"], dict):
            data["citation"] = CitationConfig(**data["citation"])

        if "evidence" in data and isinstance(data["evidence"], dict):
            data["evidence"] = EvidenceConfig(**data["evidence"])

        if "pdf_parser" in data and isinstance(data["pdf_parser"], dict):
            pdf_parser_data = data["pdf_parser"].copy()
            marker_api_data = pdf_parser_data.get("marker_api", {})
            if isinstance(marker_api_data, dict):
                pdf_parser_data["marker_api"] = MarkerApiConfig(**marker_api_data)
            data["pdf_parser"] = PdfParserConfig(**pdf_parser_data)

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
