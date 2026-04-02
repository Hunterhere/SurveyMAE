"""Unit tests for evidence_dispatch module."""

import pytest
from src.graph.nodes.evidence_dispatch import (
    METRIC_REGISTRY,
    AGENT_REGISTRY,
)


class TestMetricDefinitions:
    """Tests for metric definitions from METRIC_REGISTRY."""

    def test_verifier_metrics(self):
        """Test verifier metric definitions."""
        # C3, C5, C6 are verifier metrics
        assert "C3" in METRIC_REGISTRY
        assert "C5" in METRIC_REGISTRY
        assert "C6" in METRIC_REGISTRY
        assert METRIC_REGISTRY["C3"].llm_involved is False
        assert METRIC_REGISTRY["C5"].llm_involved is False
        assert METRIC_REGISTRY["C6"].llm_involved is True

    def test_expert_metrics(self):
        """Test expert metric definitions."""
        # G1-G6, S5 are expert metrics
        assert "G4" in METRIC_REGISTRY
        assert METRIC_REGISTRY["G4"].llm_involved is True
        assert METRIC_REGISTRY["G4"].hallucination_risk == "low"

    def test_reader_metrics(self):
        """Test reader metric definitions."""
        # T1-T5, S1-S4 are reader metrics
        assert "T1" in METRIC_REGISTRY
        assert "T5" in METRIC_REGISTRY
        assert METRIC_REGISTRY["T5"].llm_involved is True
