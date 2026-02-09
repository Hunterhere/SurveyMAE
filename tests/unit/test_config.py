"""Unit tests for configuration management."""

import pytest
import os
from pathlib import Path

from src.core.config import SurveyMAEConfig, load_config


class TestSurveyMAEConfig:
    """Tests for SurveyMAEConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = SurveyMAEConfig()

        assert config.llm.model == "gpt-4o"
        assert config.llm.temperature == 0.0
        assert config.debate.max_rounds == 3
        assert config.debate.score_threshold == 2.0
        assert config.report.output_dir == "./output"

    def test_config_from_yaml(self):
        """Test loading configuration from YAML file."""
        yaml_content = """
llm:
  model: gpt-4
  temperature: 0.5

agents:
  - name: verifier
    retry_attempts: 5

debate:
  max_rounds: 5
"""
        # Use a temp file in the project directory
        temp_dir = Path(__file__).parent.parent.parent
        temp_file = temp_dir / "temp_test_config.yaml"

        try:
            temp_file.write_text(yaml_content)

            config = SurveyMAEConfig.from_yaml(str(temp_file))

            assert config.llm.model == "gpt-4"
            assert config.llm.temperature == 0.5
            assert config.debate.max_rounds == 5
            assert len(config.agents) == 1
            assert config.agents[0].name == "verifier"
            assert config.agents[0].retry_attempts == 5
        finally:
            if temp_file.exists():
                temp_file.unlink()

    def test_config_agent_defaults(self):
        """Test agent configuration defaults."""
        config = SurveyMAEConfig()

        assert len(config.agents) == 0  # No agents by default

    def test_debate_config_defaults(self):
        """Test debate configuration defaults."""
        config = SurveyMAEConfig()

        assert config.debate.aggregator == "weighted"
        assert config.debate.weights["verifier"] == 1.0
        assert config.debate.weights["expert"] == 1.2


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_nonexistent(self):
        """Test loading config when file doesn't exist."""
        config = load_config("/nonexistent/path.yaml")

        # Should return default config
        assert isinstance(config, SurveyMAEConfig)

    def test_load_config_with_file(self):
        """Test loading config with a valid file."""
        yaml_content = """
llm:
  model: claude-3
  temperature: 0.2
"""
        # Use a temp file in the project directory
        temp_dir = Path(__file__).parent.parent.parent
        temp_file = temp_dir / "temp_test_config2.yaml"

        try:
            temp_file.write_text(yaml_content)

            config = load_config(str(temp_file))
            assert config.llm.model == "claude-3"
            assert config.llm.temperature == 0.2
        finally:
            if temp_file.exists():
                temp_file.unlink()
