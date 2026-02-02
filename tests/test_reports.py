"""Tests for report generation."""

from datetime import datetime

import pytest

from reporting_service.models.analysis import (
    ComplianceMetrics,
    DeviationReport,
    ExitType,
    TradeAnalysis,
)
from reporting_service.reports.generator import ReportGenerator


class TestReportGenerator:
    """Tests for ReportGenerator."""

    @pytest.fixture
    def sample_report(self, sample_analysis):
        """Create a sample deviation report."""
        sample_analysis.calculate_compliance_score()

        metrics = ComplianceMetrics(
            total_positions=10,
            analyzed_positions=10,
            excellent_count=2,
            good_count=3,
            fair_count=3,
            poor_count=1,
            non_compliant_count=1,
            avg_compliance_score=0.65,
            avg_entry_confidence=0.70,
            avg_position_size_deviation=0.15,
            entries_with_buy_signal=7,
            entries_without_signal=3,
            profit_target_exits=4,
            stop_loss_exits=2,
            manual_exits=3,
            other_exits=1,
            compliant_win_rate=0.75,
            non_compliant_win_rate=0.40,
        )

        return DeviationReport(
            period_start=datetime(2024, 1, 1),
            period_end=datetime(2024, 1, 31),
            metrics=metrics,
            analyses=[sample_analysis],
            worst_deviations=[sample_analysis],
            best_compliant=[sample_analysis],
            common_issues=["50% of entries had no valid buy signal"],
            recommendations=["Wait for valid buy signals before entering"],
        )

    def test_to_markdown(self, settings, sample_report):
        # Create a mock analyzer (not used for markdown generation)
        from unittest.mock import MagicMock

        mock_analyzer = MagicMock()

        generator = ReportGenerator(settings, mock_analyzer)
        markdown = generator.to_markdown(sample_report)

        assert "# Trade Deviation Report" in markdown
        assert "## Summary" in markdown
        assert "Average Compliance Score" in markdown
        assert "Compliance Distribution" in markdown
        assert "Exit Type Distribution" in markdown

    def test_to_summary(self, settings, sample_report):
        from unittest.mock import MagicMock

        mock_analyzer = MagicMock()

        generator = ReportGenerator(settings, mock_analyzer)
        summary = generator.to_summary(sample_report)

        assert "10 positions" in summary
        assert "65%" in summary  # avg compliance
        assert "75%" in summary  # compliant win rate


class TestDeviationReport:
    """Tests for DeviationReport model."""

    def test_to_dict(self, sample_analysis):
        sample_analysis.calculate_compliance_score()

        report = DeviationReport(
            analyses=[sample_analysis],
            common_issues=["Test issue"],
            recommendations=["Test recommendation"],
        )

        d = report.to_dict()
        assert "generated_at" in d
        assert "metrics" in d
        assert d["analyses_count"] == 1
        assert len(d["common_issues"]) == 1
