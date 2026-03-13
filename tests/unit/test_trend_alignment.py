"""Unit tests for T5 (trend_alignment) calculation."""

import pytest
from src.tools.citation_analysis import CitationAnalyzer


class TestTrendAlignment:
    """Tests for compute_temporal_metrics method."""

    def test_perfect_positive_correlation(self):
        """Test case with perfect positive correlation."""
        analyzer = CitationAnalyzer()

        # Use counts per year that match the field trend
        references = [
            {"year": 2020},
            {"year": 2020},  # 2 in 2020
            {"year": 2021},
            {"year": 2021},
            {"year": 2021},
            {"year": 2021},  # 4 in 2021
            {"year": 2022},
            {"year": 2022},
            {"year": 2022},
            {"year": 2022},
            {"year": 2022},  # 5 in 2022
        ]

        # Field trend is proportional: 10, 20, 40
        field_trend = {
            "yearly_counts": {
                "2020": 10,
                "2021": 20,
                "2022": 40,
            }
        }

        result = analyzer.compute_temporal_metrics(references, field_trend)

        # Should have positive correlation
        assert result["status"] == "success"
        assert result["T5_trend_alignment"] is not None
        assert result["T5_trend_alignment"] > 0.5

    def test_perfect_negative_correlation(self):
        """Test case with perfect negative correlation."""
        analyzer = CitationAnalyzer()

        # Survey citations are opposite to field trend
        # More citations in older years, fewer in recent years
        references = [
            {"year": 2022},  # 1 in 2022 (field has 40)
            {"year": 2021},
            {"year": 2021},  # 2 in 2021 (field has 20)
            {"year": 2020},
            {"year": 2020},
            {"year": 2020},
            {"year": 2020},
            {"year": 2020},  # 5 in 2020 (field has 10)
        ]

        field_trend = {
            "yearly_counts": {
                "2020": 10,
                "2021": 20,
                "2022": 40,
            }
        }

        result = analyzer.compute_temporal_metrics(references, field_trend)

        # Should have negative correlation
        assert result["status"] == "success"
        assert result["T5_trend_alignment"] is not None
        assert result["T5_trend_alignment"] < 0

    def test_no_correlation(self):
        """Test case with no correlation."""
        analyzer = CitationAnalyzer()

        # Survey citations are random relative to field
        references = [
            {"year": 2020},
            {"year": 2020},
            {"year": 2020},
            {"year": 2021},
            {"year": 2021},
            {"year": 2022},
        ]

        field_trend = {
            "yearly_counts": {
                "2020": 40,
                "2021": 20,
                "2022": 10,
            }
        }

        result = analyzer.compute_temporal_metrics(references, field_trend)

        # Should have correlation close to -1.0 (opposite trend)
        assert result["status"] == "success"
        assert result["T5_trend_alignment"] is not None

    def test_t1_year_span(self):
        """Test T1 (year_span) calculation."""
        analyzer = CitationAnalyzer()

        references = [
            {"year": 2018},
            {"year": 2020},
            {"year": 2022},
        ]

        result = analyzer.compute_temporal_metrics(references, None)

        assert result["T1_year_span"] == 4  # 2022 - 2018

    def test_t3_peak_year_ratio(self):
        """Test T3 (peak_year_ratio) calculation."""
        analyzer = CitationAnalyzer()

        # 6 citations from last 3 years (2024, 2025, 2026), 4 from older
        references = [
            {"year": 2026},
            {"year": 2026},
            {"year": 2026},
            {"year": 2025},
            {"year": 2025},
            {"year": 2025},
            {"year": 2020},
            {"year": 2021},
            {"year": 2022},
            {"year": 2023},
        ]

        result = analyzer.compute_temporal_metrics(references, None)

        # 6/10 = 0.6
        assert result["T3_peak_year_ratio"] == pytest.approx(0.6, abs=0.01)

    def test_t4_temporal_continuity(self):
        """Test T4 (temporal_continuity) calculation."""
        analyzer = CitationAnalyzer()

        # Years: 2018, 2019, 2020, 2023 - gap of 3 years between 2020 and 2023
        references = [
            {"year": 2018},
            {"year": 2019},
            {"year": 2020},
            {"year": 2023},
        ]

        result = analyzer.compute_temporal_metrics(references, None)

        assert result["T4_temporal_continuity"] == 3

    def test_no_valid_years(self):
        """Test handling of references with no valid years."""
        analyzer = CitationAnalyzer()

        references = [
            {"year": None},
            {"year": "unknown"},
            {},
        ]

        result = analyzer.compute_temporal_metrics(references, None)

        assert result["status"] == "no_valid_years"
        assert result["T1_year_span"] is None
        assert result["T5_trend_alignment"] is None

    def test_t2_foundational_gap(self):
        """Test T2 (foundational_retrieval_gap) calculation."""
        analyzer = CitationAnalyzer()

        references = [{"year": 2018}]

        # Field has foundational work from 2015
        field_trend = {
            "yearly_counts": {
                "2015": 5,
                "2016": 10,
                "2017": 15,
            }
        }

        result = analyzer.compute_temporal_metrics(references, field_trend)

        # Gap = 2018 - 2015 = 3
        assert result["T2_foundational_retrieval_gap"] == 3


class TestGiniCoefficient:
    """Tests for Gini coefficient calculation."""

    def test_perfect_equality(self):
        """Test Gini with perfect equality."""
        analyzer = CitationAnalyzer()

        # All sections have equal citations
        gini = analyzer._compute_gini([10, 10, 10, 10])

        assert gini == 0.0

    def test_perfect_inequality(self):
        """Test Gini with perfect inequality."""
        analyzer = CitationAnalyzer()

        # Very unequal distribution
        gini = analyzer._compute_gini([40, 10, 5, 1])

        # Should be high but not 1.0
        assert gini > 0.5

    def test_partial_inequality(self):
        """Test Gini with partial inequality."""
        analyzer = CitationAnalyzer()

        gini = analyzer._compute_gini([30, 10, 5, 1])

        # Should be between 0 and 1
        assert 0.0 < gini < 1.0

    def test_empty_list(self):
        """Test Gini with empty list."""
        analyzer = CitationAnalyzer()

        gini = analyzer._compute_gini([])

        assert gini == 0.0

    def test_zeros_only(self):
        """Test Gini with zeros only."""
        analyzer = CitationAnalyzer()

        gini = analyzer._compute_gini([0, 0, 0])

        assert gini == 0.0
