"""SurveyMAE Integration Tests."""

from __future__ import annotations

import os
from pathlib import Path


def load_test_env(dotenv_path: Path | None = None) -> None:
    """Load .env for integration tests without extra dependencies."""
    if dotenv_path is None:
        dotenv_path = Path(__file__).resolve().parents[2] / ".env"
    if not dotenv_path.exists():
        return

    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# Auto-load .env for integration tests.
load_test_env()
