"""Pytest configuration for SurveyMAE tests.

This module provides shared fixtures and utilities for all tests.
Automatically loads .env file when pytest starts.
"""

from pathlib import Path
from dotenv import load_dotenv

# Auto-load environment variables when conftest is imported
# This ensures API keys are available for all tests
_project_root = Path(__file__).parent.parent
load_dotenv(_project_root / ".env")
