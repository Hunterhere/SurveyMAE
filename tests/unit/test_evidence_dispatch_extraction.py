"""Unit tests for evidence_dispatch extraction functions.

This test file validates the extract_path calibration for all 19 metrics
against the actual tool_evidence schema (docs/tool_evidence_schema.json).

These tests are part of Step 0: establishing the contract between
evidence_collection output and evidence_dispatch extraction paths.
"""

import json
import os
import pytest

from src.graph.nodes.evidence_dispatch import (
    extract_metric_value,
    extract_metric_with_extra,
    METRIC_REGISTRY,
)


# Path to the dumped tool_evidence schema
SCHEMA_PATH = "docs/tool_evidence_schema.json"


@pytest.fixture(scope="module")
def tool_evidence_schema():
    """Load the tool_evidence schema from the dumped JSON file."""
    if not os.path.exists(SCHEMA_PATH):
        pytest.skip(f"Schema file not found: {SCHEMA_PATH}")

    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class TestExtractPathCalibration:
    """Test that all extract_paths in METRIC_REGISTRY are correctly calibrated."""

    def test_c3_orphan_ref_rate(self, tool_evidence_schema):
        """Test C3 extraction path."""
        value = extract_metric_value(tool_evidence_schema, "C3")
        assert value is not None, "C3 should have a value in the schema"
        assert 0 <= value <= 1, "C3 should be a rate between 0 and 1"

    def test_c5_metadata_verify_rate(self, tool_evidence_schema):
        """Test C5 extraction path."""
        value = extract_metric_value(tool_evidence_schema, "C5")
        assert value is not None, "C5 should have a value in the schema"
        assert 0 <= value <= 1, "C5 should be a rate between 0 and 1"

    def test_c6_extraction(self, tool_evidence_schema):
        """Test C6 extraction with extra_fields."""
        result = extract_metric_with_extra(tool_evidence_schema, "C6")
        assert result.get("value") is not None, "C6 contradiction_rate should exist"
        assert result.get("auto_fail") is not None, "C6 auto_fail should be extracted"
        assert result.get("support") is not None, "C6 support count should be extracted"
        assert result.get("contradict") is not None, "C6 contradict count should be extracted"
        assert result.get("insufficient") is not None, "C6 insufficient count should be extracted"

    def test_t1_year_span(self, tool_evidence_schema):
        """Test T1 extraction path."""
        value = extract_metric_value(tool_evidence_schema, "T1")
        assert value is not None, "T1 should have a value in the schema"
        assert isinstance(value, int), "T1 should be an integer (year span)"

    def test_t2_foundational_retrieval_gap(self, tool_evidence_schema):
        """Test T2 extraction path."""
        value = extract_metric_value(tool_evidence_schema, "T2")
        assert value is not None, "T2 should have a value in the schema"

    def test_t3_peak_year_ratio(self, tool_evidence_schema):
        """Test T3 extraction path."""
        value = extract_metric_value(tool_evidence_schema, "T3")
        assert value is not None, "T3 should have a value in the schema"
        assert 0 <= value <= 1, "T3 should be a ratio between 0 and 1"

    def test_t4_temporal_continuity(self, tool_evidence_schema):
        """Test T4 extraction path."""
        value = extract_metric_value(tool_evidence_schema, "T4")
        assert value is not None, "T4 should have a value in the schema"

    def test_t5_trend_alignment(self, tool_evidence_schema):
        """Test T5 extraction path."""
        value = extract_metric_value(tool_evidence_schema, "T5")
        assert value is not None, "T5 should have a value in the schema"
        assert -1 <= value <= 1, "T5 should be a correlation between -1 and 1"

    def test_s1_section_count(self, tool_evidence_schema):
        """Test S1 extraction path."""
        value = extract_metric_value(tool_evidence_schema, "S1")
        assert value is not None, "S1 should have a value in the schema"
        assert isinstance(value, int), "S1 should be an integer"

    def test_s2_citation_density(self, tool_evidence_schema):
        """Test S2 extraction path."""
        value = extract_metric_value(tool_evidence_schema, "S2")
        assert value is not None, "S2 should have a value in the schema"

    def test_s3_citation_gini(self, tool_evidence_schema):
        """Test S3 extraction path."""
        value = extract_metric_value(tool_evidence_schema, "S3")
        assert value is not None, "S3 should have a value in the schema"
        assert 0 <= value <= 1, "S3 Gini coefficient should be between 0 and 1"

    def test_s4_zero_citation_section_rate(self, tool_evidence_schema):
        """Test S4 extraction path."""
        value = extract_metric_value(tool_evidence_schema, "S4")
        assert value is not None, "S4 should have a value in the schema"
        assert 0 <= value <= 1, "S4 should be a rate between 0 and 1"

    def test_s5_nmi(self, tool_evidence_schema):
        """Test S5 extraction path."""
        value = extract_metric_value(tool_evidence_schema, "S5")
        assert value is not None, "S5 should have a value in the schema"
        assert 0 <= value <= 1, "S5 NMI should be between 0 and 1"

    def test_g1_density(self, tool_evidence_schema):
        """Test G1 extraction path."""
        value = extract_metric_value(tool_evidence_schema, "G1")
        assert value is not None, "G1 should have a value in the schema"

    def test_g2_components(self, tool_evidence_schema):
        """Test G2 extraction path."""
        value = extract_metric_value(tool_evidence_schema, "G2")
        assert value is not None, "G2 should have a value in the schema"

    def test_g3_lcc_frac(self, tool_evidence_schema):
        """Test G3 extraction path."""
        value = extract_metric_value(tool_evidence_schema, "G3")
        assert value is not None, "G3 should have a value in the schema"

    def test_g4_coverage_rate(self, tool_evidence_schema):
        """Test G4 extraction path."""
        value = extract_metric_value(tool_evidence_schema, "G4")
        assert value is not None, "G4 should have a value in the schema"

    def test_g5_clusters(self, tool_evidence_schema):
        """Test G5 extraction path."""
        value = extract_metric_value(tool_evidence_schema, "G5")
        assert value is not None, "G5 should have a value in the schema"

    def test_g6_isolates(self, tool_evidence_schema):
        """Test G6 extraction path."""
        value = extract_metric_value(tool_evidence_schema, "G6")
        assert value is not None, "G6 should have a value in the schema"


class TestAllMetricsPresent:
    """Test that all 19 metrics are present in the schema."""

    def test_all_19_metrics_have_values(self, tool_evidence_schema):
        """Verify all 19 metrics can be extracted from the schema."""
        missing = []
        for metric_id in METRIC_REGISTRY:
            value = extract_metric_value(tool_evidence_schema, metric_id)
            if value is None:
                missing.append(metric_id)

        assert len(missing) == 0, f"Metrics without values in schema: {missing}"
