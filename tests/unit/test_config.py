"""Unit tests for configuration management."""

from src.core.config import SurveyMAEConfig, load_config


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_nonexistent(self):
        """Test loading config when file doesn't exist."""
        config = load_config("/nonexistent/path.yaml")

        # Should return default config
        assert isinstance(config, SurveyMAEConfig)
