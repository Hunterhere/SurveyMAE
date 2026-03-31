"""Search engine configuration loader.

Supports the extended parallel-dispatch YAML format with per-source configs,
concurrency settings, and degradation strategy.  Backward-compatible with
the legacy flat YAML layout.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


# ---------------------------------------------------------------------------
# Per-source runtime config
# ---------------------------------------------------------------------------

@dataclass
class SourceConfig:
    """Runtime configuration for a single search source."""

    enabled: bool = True
    priority: int = 99
    concurrent: bool = False
    max_retries: int = 2
    retry_delay_seconds: float = 1.0
    retry_backoff: float = 2.0
    retry_on_status: list[int] = field(
        default_factory=lambda: [429, 500, 502, 503, 504]
    )
    timeout_seconds: float = 10.0
    # Source-specific credentials
    api_key: Optional[str] = None
    email: Optional[str] = None
    mailto: Optional[str] = None


# ---------------------------------------------------------------------------
# Concurrency & degradation configs
# ---------------------------------------------------------------------------

@dataclass
class ConcurrencyConfig:
    """Global concurrency settings for parallel dispatch."""

    max_concurrent_sources: int = 3
    merge_strategy: str = "weighted_union"  # first_wins | union | weighted_union
    per_source_timeout_seconds: float = 10.0


@dataclass
class DegradationConfig:
    """Fallback / degradation strategy when primary sources fail."""

    fallback_order: list[str] = field(
        default_factory=lambda: ["crossref", "dblp"]
    )
    on_all_failed: str = "empty"  # "empty" | "raise"


# ---------------------------------------------------------------------------
# Top-level search engine config
# ---------------------------------------------------------------------------

@dataclass
class SearchEngineConfig:
    """Full configuration for literature search engines.

    Backward-compatible: if the YAML only has the legacy flat keys
    (``semantic_scholar``, ``crossref``, ``openalex`` sections plus
    ``verify_limit`` / ``api_timeout_seconds`` / ``fallback_order``),
    they are still loaded and used to construct sensible defaults.
    """

    verify_limit: int = 50
    api_timeout_seconds: float = 15.0
    concurrency: ConcurrencyConfig = field(default_factory=ConcurrencyConfig)
    degradation: DegradationConfig = field(default_factory=DegradationConfig)
    sources: dict[str, SourceConfig] = field(default_factory=dict)

    # Legacy convenience accessors (used by LiteratureSearch.__init__)
    @property
    def semantic_scholar_api_key(self) -> Optional[str]:
        src = self.sources.get("semantic_scholar")
        return src.api_key if src else None

    @property
    def crossref_mailto(self) -> str:
        src = self.sources.get("crossref")
        return src.mailto or "surveymae@example.com" if src else "surveymae@example.com"

    @property
    def openalex_email(self) -> Optional[str]:
        src = self.sources.get("openalex")
        return src.email if src else None

    @property
    def fallback_order(self) -> list[str]:
        return self.degradation.fallback_order

    def get_concurrent_sources(self) -> list[str]:
        """Return source names that participate in the concurrent batch,
        sorted by priority (lower number = higher priority)."""
        return sorted(
            (
                name
                for name, cfg in self.sources.items()
                if cfg.enabled and cfg.concurrent
            ),
            key=lambda n: self.sources[n].priority,
        )

    def get_enabled_sources(self) -> list[str]:
        """Return all enabled source names sorted by priority."""
        return sorted(
            (name for name, cfg in self.sources.items() if cfg.enabled),
            key=lambda n: self.sources[n].priority,
        )


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------

ENV_PATTERN = re.compile(r"^\$\{([A-Z0-9_]+)\}$")

# Default source configs when YAML has no ``sources:`` section.
_DEFAULT_SOURCES: dict[str, dict[str, Any]] = {
    "semantic_scholar": {
        "enabled": True,
        "priority": 1,
        "concurrent": True,
        "max_retries": 2,
        "retry_delay_seconds": 2.0,
        "retry_backoff": 2.0,
        "timeout_seconds": 8,
    },
    "openalex": {
        "enabled": True,
        "priority": 2,
        "concurrent": True,
        "max_retries": 1,
        "retry_delay_seconds": 1.0,
        "retry_backoff": 1.5,
        "timeout_seconds": 10,
    },
    "crossref": {
        "enabled": True,
        "priority": 3,
        "concurrent": False,
        "max_retries": 2,
        "retry_delay_seconds": 1.0,
        "retry_backoff": 2.0,
        "timeout_seconds": 12,
    },
    "arxiv": {
        "enabled": True,
        "priority": 4,
        "concurrent": False,
        "max_retries": 1,
        "retry_delay_seconds": 3.0,
        "retry_backoff": 1.0,
        "timeout_seconds": 15,
    },
    "dblp": {
        "enabled": True,
        "priority": 5,
        "concurrent": False,
        "max_retries": 1,
        "retry_delay_seconds": 1.5,
        "retry_backoff": 1.5,
        "timeout_seconds": 10,
    },
    "scholar": {
        "enabled": False,
        "priority": 6,
        "concurrent": False,
        "max_retries": 0,
        "timeout_seconds": 20,
    },
}


def load_search_engine_config(
    config_path: Optional[str] = "config/search_engines.yaml",
) -> SearchEngineConfig:
    """Load search engine configuration from YAML.

    Supports both the new extended format (with ``sources:``,
    ``concurrency:``, ``degradation:`` sections) and the legacy flat
    format.  Missing sections fall back to sensible defaults.
    """
    resolved_path = _resolve_config_path(config_path)
    if not resolved_path:
        return _build_default_config()

    try:
        with open(resolved_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return _build_default_config()

    if not isinstance(data, dict):
        return _build_default_config()

    # -- top-level scalars ---------------------------------------------------
    verify_limit = data.get("verify_limit", 50)
    api_timeout_seconds = data.get("api_timeout_seconds", 15.0)

    # -- concurrency ---------------------------------------------------------
    conc_raw = data.get("concurrency", {}) or {}
    concurrency = ConcurrencyConfig(
        max_concurrent_sources=conc_raw.get("max_concurrent_sources", 3),
        merge_strategy=conc_raw.get("merge_strategy", "weighted_union"),
        per_source_timeout_seconds=conc_raw.get(
            "per_source_timeout_seconds", 10.0
        ),
    )

    # -- degradation ---------------------------------------------------------
    deg_raw = data.get("degradation", {}) or {}
    # Also accept legacy top-level ``fallback_order``
    fallback = deg_raw.get(
        "fallback_order", data.get("fallback_order", ["crossref", "dblp"])
    )
    degradation = DegradationConfig(
        fallback_order=fallback,
        on_all_failed=deg_raw.get("on_all_failed", "empty"),
    )

    # -- per-source configs --------------------------------------------------
    sources_raw: dict[str, Any] = data.get("sources", {}) or {}
    sources: dict[str, SourceConfig] = {}

    if sources_raw:
        # New format: explicit per-source blocks
        for name, src_dict in sources_raw.items():
            if not isinstance(src_dict, dict):
                continue
            sources[name] = _parse_source_config(name, src_dict)
    else:
        # Legacy format: build from flat credential sections + defaults
        sources = _build_legacy_sources(data)

    return SearchEngineConfig(
        verify_limit=verify_limit,
        api_timeout_seconds=api_timeout_seconds,
        concurrency=concurrency,
        degradation=degradation,
        sources=sources,
    )


def _parse_source_config(name: str, raw: dict[str, Any]) -> SourceConfig:
    """Parse a single source block from YAML."""
    defaults = _DEFAULT_SOURCES.get(name, {})
    return SourceConfig(
        enabled=raw.get("enabled", defaults.get("enabled", True)),
        priority=raw.get("priority", defaults.get("priority", 99)),
        concurrent=raw.get("concurrent", defaults.get("concurrent", False)),
        max_retries=raw.get("max_retries", defaults.get("max_retries", 2)),
        retry_delay_seconds=raw.get(
            "retry_delay_seconds",
            defaults.get("retry_delay_seconds", 1.0),
        ),
        retry_backoff=raw.get(
            "retry_backoff", defaults.get("retry_backoff", 2.0)
        ),
        retry_on_status=raw.get(
            "retry_on_status",
            defaults.get("retry_on_status", [429, 500, 502, 503, 504]),
        ),
        timeout_seconds=raw.get(
            "timeout_seconds", defaults.get("timeout_seconds", 10.0)
        ),
        api_key=_resolve_env_value(raw.get("api_key")),
        email=_resolve_env_value(raw.get("email")),
        mailto=_resolve_env_value(raw.get("mailto")),
    )


def _build_legacy_sources(data: dict[str, Any]) -> dict[str, SourceConfig]:
    """Build SourceConfig entries from a legacy YAML without ``sources:``."""
    sources: dict[str, SourceConfig] = {}

    for name, defaults in _DEFAULT_SOURCES.items():
        cfg = SourceConfig(**{k: v for k, v in defaults.items() if k in SourceConfig.__dataclass_fields__})
        # Overlay credentials from legacy flat sections
        section = data.get(name, {})
        if isinstance(section, dict):
            if "api_key" in section:
                cfg.api_key = _resolve_env_value(section["api_key"])
            if "email" in section:
                cfg.email = _resolve_env_value(section["email"])
            if "mailto" in section:
                cfg.mailto = _resolve_env_value(section["mailto"])
        sources[name] = cfg

    return sources


def _build_default_config() -> SearchEngineConfig:
    """Construct a config with hardcoded defaults (no YAML found)."""
    sources = {
        name: SourceConfig(**{k: v for k, v in defaults.items() if k in SourceConfig.__dataclass_fields__})
        for name, defaults in _DEFAULT_SOURCES.items()
    }
    return SearchEngineConfig(sources=sources)


# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------

def _resolve_config_path(config_path: Optional[str]) -> Optional[Path]:
    if config_path:
        path = Path(config_path)
        if path.exists():
            return path

    env_path = os.getenv("SURVEYMAE_SEARCH_CONFIG")
    if env_path:
        path = Path(env_path)
        if path.exists():
            return path

    possible_paths = [
        Path("config/search_engines.yaml"),
        Path(__file__).parent.parent.parent / "config" / "search_engines.yaml",
    ]
    for path in possible_paths:
        if path.exists():
            return path
    return None


def _resolve_env_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)

    match = ENV_PATTERN.match(value.strip())
    if match:
        return os.getenv(match.group(1))
    return value.strip()
