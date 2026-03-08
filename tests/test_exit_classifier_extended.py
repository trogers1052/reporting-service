"""Extended tests for ExitClassifier — trailing stops, thresholds, edge cases."""

from datetime import datetime
from unittest.mock import Mock

import pytest

from reporting_service.analysis.exit_classifier import ExitClassifier
from reporting_service.config import ReportingSettings
from reporting_service.models.analysis import ExitType
from reporting_service.models.position import Position


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pos(
    status="closed",
    realized_pl_pct=10.0,
    holding_days=10,
    symbol="AAPL",
):
    return Position(
        id=1,
        symbol=symbol,
        entry_order_id="o-1",
        entry_price=100.0,
        quantity=50,
        entry_date=datetime(2026, 1, 10),
        status=status,
        realized_pl_pct=realized_pl_pct,
        holding_days=holding_days,
    )


# ---------------------------------------------------------------------------
# classify — UNKNOWN returns
# ---------------------------------------------------------------------------


class TestClassifyUnknown:
    def test_open_position_returns_unknown(self, settings):
        classifier = ExitClassifier(settings)
        pos = _pos(status="open", realized_pl_pct=5.0)
        assert classifier.classify(pos) == ExitType.UNKNOWN

    def test_none_realized_pl_pct_returns_unknown(self, settings):
        classifier = ExitClassifier(settings)
        pos = _pos(realized_pl_pct=None)
        assert classifier.classify(pos) == ExitType.UNKNOWN


# ---------------------------------------------------------------------------
# classify — profit target
# ---------------------------------------------------------------------------


class TestClassifyProfitTarget:
    def test_exactly_at_threshold(self, settings):
        """pl_pct / 100 == profit_target_threshold should be PROFIT_TARGET."""
        classifier = ExitClassifier(settings)
        threshold_pct = settings.analysis.profit_target_threshold * 100  # e.g. 5.0
        pos = _pos(realized_pl_pct=threshold_pct)
        assert classifier.classify(pos) == ExitType.PROFIT_TARGET

    def test_well_above_threshold(self, settings):
        classifier = ExitClassifier(settings)
        pos = _pos(realized_pl_pct=20.0)
        assert classifier.classify(pos) == ExitType.PROFIT_TARGET


# ---------------------------------------------------------------------------
# classify — stop loss
# ---------------------------------------------------------------------------


class TestClassifyStopLoss:
    def test_exactly_at_stop_threshold(self, settings):
        classifier = ExitClassifier(settings)
        threshold_pct = settings.analysis.stop_loss_threshold * 100  # e.g. -3.0
        pos = _pos(realized_pl_pct=threshold_pct)
        assert classifier.classify(pos) == ExitType.STOP_LOSS

    def test_large_loss(self, settings):
        classifier = ExitClassifier(settings)
        pos = _pos(realized_pl_pct=-15.0)
        assert classifier.classify(pos) == ExitType.STOP_LOSS


# ---------------------------------------------------------------------------
# classify — time-based
# ---------------------------------------------------------------------------


class TestClassifyTimeBased:
    def test_long_hold_tiny_gain(self, settings):
        classifier = ExitClassifier(settings)
        pos = _pos(realized_pl_pct=0.5, holding_days=25)
        assert classifier.classify(pos) == ExitType.TIME_BASED

    def test_long_hold_tiny_loss(self, settings):
        classifier = ExitClassifier(settings)
        pos = _pos(realized_pl_pct=-0.5, holding_days=30)
        assert classifier.classify(pos) == ExitType.TIME_BASED

    def test_long_hold_but_large_pl_not_time_based(self, settings):
        """20+ days but P&L > 2% → not time-based."""
        classifier = ExitClassifier(settings)
        pos = _pos(realized_pl_pct=3.0, holding_days=25)
        # 3% / 100 = 0.03, abs > 0.02 → not time-based, falls to manual
        assert classifier.classify(pos) == ExitType.MANUAL

    def test_short_hold_tiny_pl_not_time_based(self, settings):
        """<= 20 days with small P&L → not time-based."""
        classifier = ExitClassifier(settings)
        pos = _pos(realized_pl_pct=0.5, holding_days=15)
        assert classifier.classify(pos) == ExitType.MANUAL

    def test_none_holding_days_skips_time_check(self, settings):
        classifier = ExitClassifier(settings)
        pos = _pos(realized_pl_pct=0.5, holding_days=None)
        assert classifier.classify(pos) == ExitType.MANUAL


# ---------------------------------------------------------------------------
# classify — trailing stop (via indicators)
# ---------------------------------------------------------------------------


class TestClassifyTrailingStop:
    def test_trailing_stop_pattern_detected(self, settings):
        classifier = ExitClassifier(settings)
        pos = _pos(realized_pl_pct=1.0, holding_days=10)  # near break-even
        indicators = {"atr_14": 2.0, "close": 99.0, "high": 101.0}
        # high - close = 2 <= atr * 2 = 4 → trailing stop
        assert classifier.classify(pos, indicators) == ExitType.TRAILING_STOP

    def test_not_trailing_stop_price_too_far_from_high(self, settings):
        classifier = ExitClassifier(settings)
        pos = _pos(realized_pl_pct=1.0, holding_days=10)
        indicators = {"atr_14": 1.0, "close": 90.0, "high": 100.0}
        # high - close = 10 > atr * 2 = 2 → not trailing stop
        assert classifier.classify(pos, indicators) == ExitType.MANUAL

    def test_not_trailing_stop_pl_too_negative(self, settings):
        """pl_pct < -3% → not in trailing stop range."""
        classifier = ExitClassifier(settings)
        pos = _pos(realized_pl_pct=-4.0, holding_days=10)
        indicators = {"atr_14": 2.0, "close": 99.0, "high": 100.0}
        # -4% / 100 = -0.04, not in (-0.03, 0.02) range
        # But -4% / 100 = -0.04 <= stop_threshold -0.03 → actually STOP_LOSS
        assert classifier.classify(pos, indicators) == ExitType.STOP_LOSS

    def test_not_trailing_stop_pl_too_positive(self, settings):
        """pl_pct >= 2% → not in trailing stop range (falls to other checks)."""
        classifier = ExitClassifier(settings)
        pos = _pos(realized_pl_pct=2.5, holding_days=10)
        indicators = {"atr_14": 2.0, "close": 99.0, "high": 100.0}
        assert classifier.classify(pos, indicators) == ExitType.MANUAL

    def test_trailing_stop_missing_atr(self, settings):
        classifier = ExitClassifier(settings)
        pos = _pos(realized_pl_pct=0.5, holding_days=10)
        indicators = {"close": 99.0, "high": 100.0}  # no atr_14
        assert classifier.classify(pos, indicators) == ExitType.MANUAL

    def test_trailing_stop_missing_close(self, settings):
        classifier = ExitClassifier(settings)
        pos = _pos(realized_pl_pct=0.5, holding_days=10)
        indicators = {"atr_14": 2.0, "high": 100.0}  # no close
        assert classifier.classify(pos, indicators) == ExitType.MANUAL

    def test_trailing_stop_missing_high(self, settings):
        classifier = ExitClassifier(settings)
        pos = _pos(realized_pl_pct=0.5, holding_days=10)
        indicators = {"atr_14": 2.0, "close": 99.0}  # no high
        assert classifier.classify(pos, indicators) == ExitType.MANUAL


# ---------------------------------------------------------------------------
# _check_trailing_stop_pattern — direct tests
# ---------------------------------------------------------------------------


class TestCheckTrailingStopPattern:
    def test_none_realized_pl_pct(self, settings):
        classifier = ExitClassifier(settings)
        pos = _pos(realized_pl_pct=None)
        assert classifier._check_trailing_stop_pattern(pos, {}) is False

    def test_empty_indicators(self, settings):
        classifier = ExitClassifier(settings)
        pos = _pos(realized_pl_pct=0.5)
        assert classifier._check_trailing_stop_pattern(pos, {}) is False


# ---------------------------------------------------------------------------
# _get_thresholds — with and without rules client
# ---------------------------------------------------------------------------


class TestGetThresholds:
    def test_without_rules_client(self, settings):
        classifier = ExitClassifier(settings)
        profit, stop = classifier._get_thresholds("AAPL")
        assert profit == settings.analysis.profit_target_threshold
        assert stop == settings.analysis.stop_loss_threshold

    def test_with_rules_client(self, settings):
        mock_client = Mock()
        mock_client.get_exit_strategy.return_value = {
            "profit_target": 0.10,
            "stop_loss": 0.08,
        }
        classifier = ExitClassifier(settings, rules_client=mock_client)
        profit, stop = classifier._get_thresholds("AAPL")
        assert profit == 0.10
        assert stop == -0.08  # negated
        mock_client.get_exit_strategy.assert_called_once_with("AAPL")

    def test_rules_client_partial_response(self, settings):
        """Rules client returns exit strategy without stop_loss key."""
        mock_client = Mock()
        mock_client.get_exit_strategy.return_value = {
            "profit_target": 0.12,
        }
        classifier = ExitClassifier(settings, rules_client=mock_client)
        profit, stop = classifier._get_thresholds("AAPL")
        assert profit == 0.12
        # Falls back to default stop threshold (negated)
        assert stop == -abs(settings.analysis.stop_loss_threshold)

    def test_rules_client_affects_classify(self, settings):
        """Rules client thresholds change classification outcome."""
        mock_client = Mock()
        mock_client.get_exit_strategy.return_value = {
            "profit_target": 0.15,  # 15% — much higher threshold
            "stop_loss": 0.02,
        }
        classifier = ExitClassifier(settings, rules_client=mock_client)
        # 10% gain → below 15% profit target → MANUAL instead of PROFIT_TARGET
        pos = _pos(realized_pl_pct=10.0)
        assert classifier.classify(pos) == ExitType.MANUAL


# ---------------------------------------------------------------------------
# get_exit_summary
# ---------------------------------------------------------------------------


class TestGetExitSummary:
    def test_all_exit_types(self, settings):
        classifier = ExitClassifier(settings)
        expected = {
            ExitType.PROFIT_TARGET: "Exited at profit target",
            ExitType.STOP_LOSS: "Stopped out at loss",
            ExitType.TRAILING_STOP: "Trailing stop triggered",
            ExitType.TIME_BASED: "Exited due to time/stagnation",
            ExitType.MANUAL: "Manual/discretionary exit",
            ExitType.UNKNOWN: "Exit type unknown",
        }
        for exit_type, text in expected.items():
            assert classifier.get_exit_summary(exit_type) == text

    def test_invalid_value_fallback(self, settings):
        classifier = ExitClassifier(settings)
        # Non-ExitType value → falls through to default
        result = classifier.get_exit_summary("garbage")
        assert result == "Unknown exit type"


# ---------------------------------------------------------------------------
# classify — manual exit (default)
# ---------------------------------------------------------------------------


class TestClassifyManual:
    def test_small_gain_no_indicators(self, settings):
        classifier = ExitClassifier(settings)
        pos = _pos(realized_pl_pct=2.0, holding_days=10)
        assert classifier.classify(pos) == ExitType.MANUAL

    def test_small_loss_no_indicators(self, settings):
        """Small loss that doesn't hit stop threshold."""
        classifier = ExitClassifier(settings)
        pos = _pos(realized_pl_pct=-1.0, holding_days=10)
        assert classifier.classify(pos) == ExitType.MANUAL

    def test_zero_pl(self, settings):
        classifier = ExitClassifier(settings)
        pos = _pos(realized_pl_pct=0.0, holding_days=10)
        assert classifier.classify(pos) == ExitType.MANUAL
