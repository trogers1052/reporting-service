"""Tests for DeviationAnalyzer — _add_analysis_notes, _identify_common_issues,
_generate_recommendations, analyze_positions error handling."""

from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

from reporting_service.analysis.deviation_analyzer import DeviationAnalyzer
from reporting_service.config import ReportingSettings
from reporting_service.models.analysis import (
    ComplianceLevel,
    ComplianceMetrics,
    ExitType,
    TradeAnalysis,
)
from reporting_service.models.position import Position


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings():
    return ReportingSettings()


def _analysis(**overrides):
    defaults = dict(
        position_id=1,
        symbol="AAPL",
        entry_date=datetime(2026, 1, 15),
        entry_price=100.0,
        entry_signal_matched=True,
        entry_signal_type="BUY",
        entry_signal_confidence=0.75,
        exit_type=ExitType.PROFIT_TARGET,
        position_size_deviation=0.0,
        recommended_shares=50,
    )
    defaults.update(overrides)
    return TradeAnalysis(**defaults)


def _position(id=1, is_winner=True, **overrides):
    defaults = dict(
        id=id,
        symbol="AAPL",
        entry_order_id=f"o-{id}",
        entry_price=100.0,
        quantity=50,
        entry_date=datetime(2026, 1, 15),
        status="closed",
        realized_pl=50.0 if is_winner else -50.0,
        realized_pl_pct=5.0 if is_winner else -5.0,
    )
    defaults.update(overrides)
    return Position(**defaults)


def _make_analyzer():
    settings = _settings()
    journal_repo = MagicMock()
    market_data = MagicMock()
    return DeviationAnalyzer(settings, journal_repo, market_data)


# ---------------------------------------------------------------------------
# _add_analysis_notes — entry signal notes
# ---------------------------------------------------------------------------


class TestAddAnalysisNotesEntry:
    def test_no_signal_at_entry(self):
        analyzer = _make_analyzer()
        analysis = _analysis(
            entry_signal_matched=False,
            entry_signal_type=None,
        )
        pos = _position()
        analyzer._add_analysis_notes(analysis, pos)
        assert any("No clear entry signal" in n for n in analysis.notes)

    def test_sell_signal_at_entry(self):
        analyzer = _make_analyzer()
        analysis = _analysis(
            entry_signal_matched=False,
            entry_signal_type="SELL",
        )
        pos = _position()
        analyzer._add_analysis_notes(analysis, pos)
        assert any("against a SELL signal" in w for w in analysis.warnings)

    def test_low_confidence_signal(self):
        analyzer = _make_analyzer()
        analysis = _analysis(
            entry_signal_matched=False,
            entry_signal_type="BUY",
            entry_signal_confidence=0.3,
        )
        pos = _position()
        analyzer._add_analysis_notes(analysis, pos)
        assert any("confidence" in n and "below threshold" in n for n in analysis.notes)

    def test_matched_signal_no_entry_notes(self):
        analyzer = _make_analyzer()
        analysis = _analysis(entry_signal_matched=True)
        pos = _position()
        analyzer._add_analysis_notes(analysis, pos)
        # No entry-related notes or warnings
        entry_notes = [
            n for n in analysis.notes
            if "entry signal" in n.lower() or "no clear" in n.lower()
        ]
        entry_warnings = [w for w in analysis.warnings if "SELL signal" in w]
        assert len(entry_notes) == 0
        assert len(entry_warnings) == 0


# ---------------------------------------------------------------------------
# _add_analysis_notes — position sizing notes
# ---------------------------------------------------------------------------


class TestAddAnalysisNotesPositionSizing:
    def test_oversized_position(self):
        analyzer = _make_analyzer()
        analysis = _analysis(position_size_deviation=0.5)  # 50% larger
        pos = _position()
        analyzer._add_analysis_notes(analysis, pos)
        assert any("larger than recommended" in w for w in analysis.warnings)

    def test_undersized_position(self):
        analyzer = _make_analyzer()
        analysis = _analysis(position_size_deviation=-0.4)  # 40% smaller
        pos = _position()
        analyzer._add_analysis_notes(analysis, pos)
        assert any("smaller than recommended" in n for n in analysis.notes)

    def test_within_tolerance_no_note(self):
        """Deviation within tolerance → no sizing note."""
        analyzer = _make_analyzer()
        analysis = _analysis(position_size_deviation=0.1)  # 10%, within 20% tolerance
        pos = _position()
        analyzer._add_analysis_notes(analysis, pos)
        sizing_notes = [
            n for n in analysis.notes + analysis.warnings
            if "recommended" in n
        ]
        assert len(sizing_notes) == 0

    def test_exact_tolerance_boundary_no_note(self):
        """Deviation exactly at tolerance (0.20) → abs(0.20) > 0.20 is False."""
        analyzer = _make_analyzer()
        analysis = _analysis(position_size_deviation=0.20)
        pos = _position()
        analyzer._add_analysis_notes(analysis, pos)
        sizing_notes = [
            n for n in analysis.notes + analysis.warnings
            if "recommended" in n
        ]
        assert len(sizing_notes) == 0


# ---------------------------------------------------------------------------
# _add_analysis_notes — exit notes
# ---------------------------------------------------------------------------


class TestAddAnalysisNotesExit:
    def test_stop_loss_exit_note(self):
        analyzer = _make_analyzer()
        analysis = _analysis(exit_type=ExitType.STOP_LOSS)
        pos = _position()
        analyzer._add_analysis_notes(analysis, pos)
        assert any("stop loss discipline" in n for n in analysis.notes)

    def test_profit_target_exit_note(self):
        analyzer = _make_analyzer()
        analysis = _analysis(exit_type=ExitType.PROFIT_TARGET)
        pos = _position()
        analyzer._add_analysis_notes(analysis, pos)
        assert any("Profit target achieved" in n for n in analysis.notes)

    def test_manual_exit_winner(self):
        analyzer = _make_analyzer()
        analysis = _analysis(exit_type=ExitType.MANUAL)
        pos = _position(is_winner=True)
        analyzer._add_analysis_notes(analysis, pos)
        assert any("may have left gains" in n for n in analysis.notes)

    def test_manual_exit_loser(self):
        analyzer = _make_analyzer()
        analysis = _analysis(exit_type=ExitType.MANUAL)
        pos = _position(is_winner=False)
        analyzer._add_analysis_notes(analysis, pos)
        assert any("review exit discipline" in w for w in analysis.warnings)

    def test_trailing_stop_no_special_note(self):
        analyzer = _make_analyzer()
        analysis = _analysis(exit_type=ExitType.TRAILING_STOP)
        pos = _position()
        analyzer._add_analysis_notes(analysis, pos)
        # No specific note for trailing stop
        exit_notes = [
            n for n in analysis.notes
            if "stop loss" in n or "Profit target" in n or "Manual" in n.lower()
        ]
        assert len(exit_notes) == 0

    def test_unknown_exit_no_special_note(self):
        analyzer = _make_analyzer()
        analysis = _analysis(exit_type=ExitType.UNKNOWN)
        pos = _position()
        analyzer._add_analysis_notes(analysis, pos)
        exit_notes = [
            n for n in analysis.notes
            if "stop loss" in n or "Profit target" in n or "Manual" in n.lower()
        ]
        assert len(exit_notes) == 0

    def test_time_based_exit_no_special_note(self):
        analyzer = _make_analyzer()
        analysis = _analysis(exit_type=ExitType.TIME_BASED)
        pos = _position()
        analyzer._add_analysis_notes(analysis, pos)
        exit_notes = [
            n for n in analysis.notes
            if "stop loss" in n or "Profit target" in n or "Manual" in n.lower()
        ]
        assert len(exit_notes) == 0


# ---------------------------------------------------------------------------
# _identify_common_issues
# ---------------------------------------------------------------------------


class TestIdentifyCommonIssues:
    def test_high_pct_without_signal(self):
        analyzer = _make_analyzer()
        analyses = [_analysis() for _ in range(10)]
        metrics = ComplianceMetrics(
            entries_without_signal=5,
            entries_with_buy_signal=5,
            avg_position_size_deviation=0.1,
            manual_exits=2,
            stop_loss_exits=3,
        )
        issues = analyzer._identify_common_issues(analyses, metrics)
        assert any("no valid buy signal" in i for i in issues)

    def test_no_signal_issue_below_threshold(self):
        analyzer = _make_analyzer()
        analyses = [_analysis() for _ in range(10)]
        metrics = ComplianceMetrics(
            entries_without_signal=2,  # 20% < 30%
            entries_with_buy_signal=8,
            avg_position_size_deviation=0.1,
            manual_exits=2,
            stop_loss_exits=5,
        )
        issues = analyzer._identify_common_issues(analyses, metrics)
        assert not any("no valid buy signal" in i for i in issues)

    def test_position_size_deviation_issue(self):
        analyzer = _make_analyzer()
        analyses = [_analysis()]
        metrics = ComplianceMetrics(
            entries_without_signal=0,
            entries_with_buy_signal=1,
            avg_position_size_deviation=0.35,
            manual_exits=0,
            stop_loss_exits=1,
        )
        issues = analyzer._identify_common_issues(analyses, metrics)
        assert any("position size deviation" in i.lower() for i in issues)

    def test_manual_exit_overuse(self):
        analyzer = _make_analyzer()
        analyses = [_analysis() for _ in range(10)]
        metrics = ComplianceMetrics(
            entries_without_signal=0,
            entries_with_buy_signal=10,
            avg_position_size_deviation=0.1,
            manual_exits=6,
            stop_loss_exits=2,
        )
        issues = analyzer._identify_common_issues(analyses, metrics)
        assert any("manual/discretionary" in i.lower() for i in issues)

    def test_losing_trades_without_stops(self):
        analyzer = _make_analyzer()
        analyses = [_analysis(position_id=i) for i in range(1, 6)]
        metrics = ComplianceMetrics(
            entries_without_signal=0,
            entries_with_buy_signal=5,
            avg_position_size_deviation=0.1,
            manual_exits=4,
            stop_loss_exits=1,  # 1/5 = 20% < 30%
        )
        positions_by_id = {
            i: _position(id=i, is_winner=False) for i in range(1, 6)
        }
        issues = analyzer._identify_common_issues(
            analyses, metrics, positions_by_id
        )
        assert any("stop loss" in i.lower() for i in issues)

    def test_no_issues_clean_metrics(self):
        analyzer = _make_analyzer()
        analyses = [_analysis() for _ in range(10)]
        metrics = ComplianceMetrics(
            entries_without_signal=1,  # 10% < 30%
            entries_with_buy_signal=9,
            avg_position_size_deviation=0.1,  # < 0.2
            manual_exits=2,  # 20% < 50%
            stop_loss_exits=5,  # 50% > 30%
        )
        issues = analyzer._identify_common_issues(analyses, metrics)
        assert len(issues) == 0

    def test_empty_analyses(self):
        analyzer = _make_analyzer()
        metrics = ComplianceMetrics()
        issues = analyzer._identify_common_issues([], metrics)
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# _generate_recommendations
# ---------------------------------------------------------------------------


class TestGenerateRecommendations:
    def test_signal_based_entry_rec(self):
        analyzer = _make_analyzer()
        analyses = [_analysis()]
        metrics = ComplianceMetrics(
            entries_without_signal=6,
            entries_with_buy_signal=4,
        )
        recs = analyzer._generate_recommendations(analyses, metrics)
        assert any("valid buy signals" in r.lower() for r in recs)

    def test_position_sizing_rec(self):
        analyzer = _make_analyzer()
        analyses = [_analysis()]
        metrics = ComplianceMetrics(
            entries_without_signal=0,
            entries_with_buy_signal=10,
            avg_position_size_deviation=0.3,
        )
        recs = analyzer._generate_recommendations(analyses, metrics)
        assert any("position sizing" in r.lower() for r in recs)

    def test_exit_discipline_rec(self):
        analyzer = _make_analyzer()
        analyses = [_analysis()]
        metrics = ComplianceMetrics(
            entries_without_signal=0,
            entries_with_buy_signal=10,
            manual_exits=6,
            profit_target_exits=2,
            stop_loss_exits=2,
        )
        recs = analyzer._generate_recommendations(analyses, metrics)
        assert any("profit targets and stop losses" in r.lower() for r in recs)

    def test_compliance_correlation_rec(self):
        analyzer = _make_analyzer()
        analyses = [_analysis()]
        metrics = ComplianceMetrics(
            entries_without_signal=0,
            entries_with_buy_signal=10,
            compliant_win_rate=0.80,
            non_compliant_win_rate=0.40,
        )
        recs = analyzer._generate_recommendations(analyses, metrics)
        assert any("stick to the rules" in r.lower() for r in recs)

    def test_no_recommendations_good_metrics(self):
        analyzer = _make_analyzer()
        analyses = [_analysis()]
        metrics = ComplianceMetrics(
            entries_without_signal=2,
            entries_with_buy_signal=8,
            avg_position_size_deviation=0.1,
            manual_exits=2,
            profit_target_exits=5,
            stop_loss_exits=3,
            compliant_win_rate=0.60,
            non_compliant_win_rate=0.55,
        )
        recs = analyzer._generate_recommendations(analyses, metrics)
        assert len(recs) == 0

    def test_slight_compliance_edge_not_recommended(self):
        """Compliant win rate only slightly better → no recommendation."""
        analyzer = _make_analyzer()
        analyses = [_analysis()]
        metrics = ComplianceMetrics(
            entries_without_signal=2,
            entries_with_buy_signal=8,
            avg_position_size_deviation=0.1,
            manual_exits=2,
            profit_target_exits=4,
            stop_loss_exits=4,
            compliant_win_rate=0.55,
            non_compliant_win_rate=0.50,  # difference < 0.1
        )
        recs = analyzer._generate_recommendations(analyses, metrics)
        assert not any("stick to the rules" in r.lower() for r in recs)


# ---------------------------------------------------------------------------
# analyze_positions — error handling
# ---------------------------------------------------------------------------


class TestAnalyzePositions:
    def test_error_in_one_position_continues(self):
        """If one position fails analysis, others still proceed."""
        analyzer = _make_analyzer()
        analyzer.market_data.get_indicators_at_time.side_effect = [
            Exception("boom"),
            {"close": 100.0},
        ]
        pos1 = _position(id=1)
        pos2 = _position(id=2)

        # Mock the exit classifier to avoid issues
        analyzer.exit_classifier = MagicMock()
        analyzer.exit_classifier.classify.return_value = ExitType.MANUAL

        # First call raises, second succeeds
        results = analyzer.analyze_positions([pos1, pos2])
        # Only the successful one should be in results
        assert len(results) == 1

    def test_empty_positions_list(self):
        analyzer = _make_analyzer()
        results = analyzer.analyze_positions([])
        assert results == []


# ---------------------------------------------------------------------------
# generate_report — empty analyses
# ---------------------------------------------------------------------------


class TestGenerateReport:
    def test_empty_analyses_returns_empty_report(self):
        analyzer = _make_analyzer()
        report = analyzer.generate_report([])
        assert report.metrics.total_positions == 0
        assert report.worst_deviations == []
        assert report.best_compliant == []
