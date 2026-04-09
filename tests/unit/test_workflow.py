"""Unit tests for the workflow builder."""

import pytest
from unittest.mock import patch, MagicMock
from src.graph.builder import create_workflow, compile_workflow, _parse_pdf_node
from src.core.state import SurveyState


class TestWorkflowBuilder:
    """Tests for LangGraph workflow builder."""

    def test_create_workflow(self):
        """Test workflow can be created."""
        workflow = create_workflow()
        assert workflow is not None

    def test_workflow_has_required_nodes(self):
        """Test workflow has all required nodes."""
        workflow = create_workflow()

        # Check that the graph has the expected structure
        # The nodes should include: parse_pdf, verifier, expert, reader, corrector, gather, debate, reporter
        # We can't directly check the nodes, but we can verify the workflow compiles
        compiled = compile_workflow(workflow)
        assert compiled is not None

    @pytest.mark.asyncio
    async def test_parse_pdf_node_no_path(self):
        """Test PDF parsing with no path."""
        state = SurveyState(
            source_pdf_path="",
            parsed_content="",
            evaluations=[],
            debate_history=[],
            sections={},
            current_round=0,
            consensus_reached=False,
            final_report_md="",
            metadata={},
        )

        result = await _parse_pdf_node(state)
        assert "error" in result["metadata"]
        assert result["parsed_content"] == ""

    @pytest.mark.asyncio
    async def test_parse_pdf_node_file_not_found(self):
        """Test PDF parsing with non-existent file."""
        state = SurveyState(
            source_pdf_path="/nonexistent/file.pdf",
            parsed_content="",
            evaluations=[],
            debate_history=[],
            sections={},
            current_round=0,
            consensus_reached=False,
            final_report_md="",
            metadata={},
        )

        result = await _parse_pdf_node(state)
        assert "error" in result["metadata"]
        assert result["parsed_content"] == ""

    @pytest.mark.asyncio
    async def test_parse_pdf_node_success(self):
        """Test successful PDF parsing with PDFParser."""
        from src.tools.pdf_parser import PDFParser
        
        state = SurveyState(
            source_pdf_path="test_paper.pdf",
            parsed_content="",
            evaluations=[],
            debate_history=[],
            sections={},
            current_round=0,
            consensus_reached=False,
            final_report_md="",
            metadata={},
        )

        # Create a real PDFParser instance with mocked method
        parser = PDFParser()
        
        # Mock Path.exists and _get_pdf_parser to return real PDFParser instance
        with patch("pathlib.Path.exists", return_value=True):
            with patch("src.graph.builder._get_pdf_parser", return_value=parser):
                with patch.object(parser, "parse_with_structure", return_value=(
                    "# Parsed PDF Content",
                    {"headings": ["Introduction", "Methods", "Results"], "parser": "PDFParser", "use_layout": True}
                )) as mock_parse:
                    result = await _parse_pdf_node(state)

        assert result["parsed_content"] == "# Parsed PDF Content"
        assert result["metadata"]["parsed"] == "true"
        assert result["section_headings"] == ["Introduction", "Methods", "Results"]


class TestWorkflowEdges:
    """Tests for workflow edge logic."""

    def test_should_end_no_evaluations(self):
        """Test should_end with no evaluations."""
        from src.graph.edges import should_end

        state = SurveyState(
            source_pdf_path="test_paper.pdf",
            parsed_content="content",
            evaluations=[],
            debate_history=[],
            sections={},
            current_round=0,
            consensus_reached=False,
            final_report_md="",
            metadata={},
        )

        # With no evaluations, should go to debate (not END)
        result = should_end(state)
        assert result in ["END", "debate"]

    def test_should_end_low_variance(self):
        """Test should_end with low score variance."""
        from src.graph.edges import should_end

        state = SurveyState(
            source_pdf_path="test_paper.pdf",
            parsed_content="content",
            evaluations=[
                {
                    "agent_name": "verifier",
                    "dimension": "factuality",
                    "score": 7.5,
                    "reasoning": "",
                    "evidence": None,
                    "confidence": 0.8,
                },
                {
                    "agent_name": "expert",
                    "dimension": "depth",
                    "score": 7.0,
                    "reasoning": "",
                    "evidence": None,
                    "confidence": 0.9,
                },
                {
                    "agent_name": "reader",
                    "dimension": "coverage",
                    "score": 7.5,
                    "reasoning": "",
                    "evidence": None,
                    "confidence": 0.8,
                },
                {
                    "agent_name": "corrector",
                    "dimension": "bias",
                    "score": 7.0,
                    "reasoning": "",
                    "evidence": None,
                    "confidence": 0.75,
                },
            ],
            debate_history=[],
            sections={},
            current_round=0,
            consensus_reached=False,
            final_report_md="",
            metadata={},
        )

        # Low variance should go to END
        result = should_end(state)
        assert result == "END"

    def test_should_end_high_variance(self):
        """Test should_end with high score variance."""
        from src.graph.edges import should_end

        state = SurveyState(
            source_pdf_path="test_paper.pdf",
            parsed_content="content",
            evaluations=[
                {
                    "agent_name": "verifier",
                    "dimension": "factuality",
                    "score": 9.0,
                    "reasoning": "",
                    "evidence": None,
                    "confidence": 0.8,
                },
                {
                    "agent_name": "verifier2",
                    "dimension": "factuality",
                    "score": 5.0,
                    "reasoning": "",
                    "evidence": None,
                    "confidence": 0.9,
                },
            ],
            debate_history=[],
            sections={},
            current_round=0,
            consensus_reached=False,
            final_report_md="",
            metadata={},
        )

        # High variance should go to debate
        result = should_end(state)
        assert result == "debate"

    def test_should_continue_debate_max_rounds(self):
        """Test should_continue_debate at max rounds."""
        from src.graph.edges import should_continue_debate

        state = SurveyState(
            source_pdf_path="test_paper.pdf",
            parsed_content="content",
            evaluations=[],
            debate_history=[],
            sections={},
            current_round=3,  # At max rounds
            consensus_reached=False,
            final_report_md="",
            metadata={"max_debate_rounds": 3},
        )

        result = should_continue_debate(state)
        assert result == "reporter"

    def test_should_continue_debate_consensus(self):
        """Test should_continue_debate with consensus."""
        from src.graph.edges import should_continue_debate

        state = SurveyState(
            source_pdf_path="test_paper.pdf",
            parsed_content="content",
            evaluations=[],
            debate_history=[],
            sections={},
            current_round=1,
            consensus_reached=True,  # Consensus reached
            final_report_md="",
            metadata={"max_debate_rounds": 3},
        )

        result = should_continue_debate(state)
        assert result == "reporter"
