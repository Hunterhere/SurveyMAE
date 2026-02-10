"""Search engine configuration loader."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass
class SearchEngineConfig:
    """Configuration for literature search engines."""

    semantic_scholar_api_key: Optional[str] = None
    crossref_mailto: str = "surveymae@example.com"
    openalex_email: Optional[str] = None


ENV_PATTERN = re.compile(r"^\$\{([A-Z0-9_]+)\}$")


def load_search_engine_config(
    config_path: Optional[str] = "config/search_engines.yaml",
) -> SearchEngineConfig:
    """Load search engine configuration from YAML.

    Args:
        config_path: Optional path to search_engines.yaml. Defaults to
            "config/search_engines.yaml" if not provided, then falls back to
            SURVEYMAE_SEARCH_CONFIG if set.
    """
    resolved_path = _resolve_config_path(config_path)
    if not resolved_path:
        return SearchEngineConfig()

    try:
        with open(resolved_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return SearchEngineConfig()

    semantic = data.get("semantic_scholar", {}) if isinstance(data, dict) else {}
    crossref = data.get("crossref", {}) if isinstance(data, dict) else {}
    openalex = data.get("openalex", {}) if isinstance(data, dict) else {}

    return SearchEngineConfig(
        semantic_scholar_api_key=_resolve_env_value(semantic.get("api_key")),
        crossref_mailto=_resolve_env_value(crossref.get("mailto"))
        or SearchEngineConfig.crossref_mailto,
        openalex_email=_resolve_env_value(openalex.get("email")),
    )


def _resolve_config_path(config_path: Optional[str]) -> Optional[Path]:
    if config_path:
        path = Path(config_path)
        return path if path.exists() else None

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
