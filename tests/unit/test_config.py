"""Unit tests for configuration management."""

from src.core.config import SurveyMAEConfig, load_config, PdfParserConfig, Pymupdf4llmConfig


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_nonexistent(self):
        """Test loading config when file doesn't exist."""
        config = load_config("/nonexistent/path.yaml")

        # Should return default config
        assert isinstance(config, SurveyMAEConfig)


class TestPdfParserConfig:
    """Tests for PDF parser configuration."""

    def test_default_pymupdf4llm_config(self):
        """Test default PyMuPDF4LLM configuration values."""
        config = Pymupdf4llmConfig()
        
        assert config.use_layout is True
        assert config.show_header is False
        assert config.show_footer is False

    def test_custom_pymupdf4llm_config(self):
        """Test custom PyMuPDF4LLM configuration."""
        config = Pymupdf4llmConfig(
            use_layout=False,
            show_header=True,
            show_footer=True,
        )
        
        assert config.use_layout is False
        assert config.show_header is True
        assert config.show_footer is True

    def test_pdf_parser_config_with_pymupdf4llm(self):
        """Test PdfParserConfig includes pymupdf4llm settings."""
        pymupdf_config = Pymupdf4llmConfig(use_layout=True)
        config = PdfParserConfig(
            backend="auto",
            pymupdf4llm=pymupdf_config,
        )
        
        assert config.backend == "auto"
        assert isinstance(config.pymupdf4llm, Pymupdf4llmConfig)
        assert config.pymupdf4llm.use_layout is True

    def test_load_config_with_pymupdf4llm_from_yaml(self):
        """Test loading config with pymupdf4llm section from YAML."""
        # This test assumes config/main.yaml exists and has the structure
        config = load_config("config/main.yaml")
        
        assert isinstance(config, SurveyMAEConfig)
        assert config.pdf_parser is not None
        assert isinstance(config.pdf_parser.pymupdf4llm, Pymupdf4llmConfig)
        
        # Verify default values from main.yaml
        assert config.pdf_parser.pymupdf4llm.use_layout is True
        assert config.pdf_parser.pymupdf4llm.show_header is False
        assert config.pdf_parser.pymupdf4llm.show_footer is False
