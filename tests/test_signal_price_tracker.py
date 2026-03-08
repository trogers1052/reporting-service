"""
Tests for signal price outcome tracker.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from reporting_service.analysis.signal_price_tracker import (
    EXPIRED,
    STOPPED_OUT,
    TARGET_1_HIT,
    TARGET_2_HIT,
    SignalPriceTracker,
    UnresolvedSignal,
)


def _make_signal(**kwargs):
    """Helper to create an UnresolvedSignal with sensible defaults."""
    defaults = {
        "id": 1,
        "symbol": "AAPL",
        "signal": "BUY",
        "action": "skipped",
        "entry_price": 100.0,
        "stop_price": 95.0,
        "target_1": 110.0,
        "target_2": 120.0,
        "valid_until": datetime.now(timezone.utc) + timedelta(days=14),
        "feedback_timestamp": datetime.now(timezone.utc) - timedelta(days=5),
        "rules_triggered": ["RSIOversold"],
        "regime_id": "BULL",
    }
    defaults.update(kwargs)
    return UnresolvedSignal(**defaults)


def _make_bar(high, low, close=None):
    """Helper to create a mock daily bar dict."""
    return {
        "date": datetime.now(timezone.utc),
        "open": close or (high + low) / 2,
        "high": high,
        "low": low,
        "close": close or (high + low) / 2,
        "volume": 1000000,
    }


class TestUnresolvedSignalFromDict:
    def test_basic_fields(self):
        data = {
            "id": 42,
            "symbol": "XYZ",
            "signal": "BUY",
            "action": "skipped",
            "entry_price": 25.50,
            "stop_price": 24.00,
            "target_1": 28.00,
            "target_2": 30.00,
            "valid_until": "2026-03-15T16:00:00Z",
            "feedback_timestamp": "2026-03-01T14:30:00Z",
            "rules_triggered": ["MomentumReversal"],
            "regime_id": "BULL",
        }
        sig = UnresolvedSignal.from_dict(data)
        assert sig.id == 42
        assert sig.symbol == "XYZ"
        assert sig.entry_price == 25.50
        assert sig.stop_price == 24.00
        assert sig.target_1 == 28.00
        assert sig.target_2 == 30.00
        assert sig.valid_until is not None
        assert sig.rules_triggered == ["MomentumReversal"]

    def test_missing_optional_fields(self):
        data = {
            "id": 1,
            "symbol": "ABC",
            "signal": "BUY",
            "action": "traded",
            "entry_price": 10.0,
            "stop_price": 9.0,
        }
        sig = UnresolvedSignal.from_dict(data)
        assert sig.target_1 == 0.0
        assert sig.target_2 == 0.0
        assert sig.valid_until is None
        assert sig.rules_triggered == []
        assert sig.regime_id == ""


class TestClassifyOutcome:
    def _make_tracker(self):
        tracker = SignalPriceTracker(
            stock_service_url="http://localhost:8081",
            timescale_host="localhost",
            timescale_port=5432,
            timescale_db="market_data",
            timescale_user="postgres",
            timescale_password="",
        )
        return tracker

    def test_stopped_out(self):
        """Price drops to stop level -> STOPPED_OUT."""
        tracker = self._make_tracker()
        sig = _make_signal()

        bars = [_make_bar(high=102, low=94)]  # low < stop (95)
        with patch.object(tracker, "_get_daily_bars", return_value=bars):
            result = tracker._classify_outcome(sig)
        assert result == STOPPED_OUT

    def test_target_1_hit(self):
        """Price reaches target_1 but not target_2 -> TARGET_1_HIT."""
        tracker = self._make_tracker()
        sig = _make_signal()

        bars = [_make_bar(high=112, low=99)]  # high > target_1 (110), < target_2 (120)
        with patch.object(tracker, "_get_daily_bars", return_value=bars):
            result = tracker._classify_outcome(sig)
        assert result == TARGET_1_HIT

    def test_target_2_hit(self):
        """Price reaches target_2 -> TARGET_2_HIT."""
        tracker = self._make_tracker()
        sig = _make_signal()

        bars = [_make_bar(high=125, low=99)]  # high > target_2 (120)
        with patch.object(tracker, "_get_daily_bars", return_value=bars):
            result = tracker._classify_outcome(sig)
        assert result == TARGET_2_HIT

    def test_stop_checked_before_target(self):
        """On the same bar, if both stop and target are hit, stop wins (conservative)."""
        tracker = self._make_tracker()
        sig = _make_signal()

        # Low hits stop AND high hits target_1 on same bar
        bars = [_make_bar(high=115, low=93)]
        with patch.object(tracker, "_get_daily_bars", return_value=bars):
            result = tracker._classify_outcome(sig)
        assert result == STOPPED_OUT

    def test_multi_day_target_1_on_day_3(self):
        """Price reaches target_1 on day 3."""
        tracker = self._make_tracker()
        sig = _make_signal()

        bars = [
            _make_bar(high=101, low=98),  # Day 1 — nothing
            _make_bar(high=105, low=99),  # Day 2 — nothing
            _make_bar(high=112, low=104),  # Day 3 — target_1 hit
        ]
        with patch.object(tracker, "_get_daily_bars", return_value=bars):
            result = tracker._classify_outcome(sig)
        assert result == TARGET_1_HIT

    def test_expired_past_valid_until(self):
        """No level hit and valid_until has passed -> EXPIRED."""
        tracker = self._make_tracker()
        sig = _make_signal(
            valid_until=datetime.now(timezone.utc) - timedelta(days=1),
        )

        bars = [
            _make_bar(high=105, low=97),
            _make_bar(high=103, low=96),
        ]
        with patch.object(tracker, "_get_daily_bars", return_value=bars):
            result = tracker._classify_outcome(sig)
        assert result == EXPIRED

    def test_expired_max_lookforward(self):
        """No level hit and max lookforward exceeded -> EXPIRED."""
        tracker = self._make_tracker()
        tracker._max_lookforward_days = 30
        sig = _make_signal(
            feedback_timestamp=datetime.now(timezone.utc) - timedelta(days=35),
            valid_until=None,
        )

        bars = [_make_bar(high=105, low=97)] * 30  # 30 days of no-hit bars
        with patch.object(tracker, "_get_daily_bars", return_value=bars):
            result = tracker._classify_outcome(sig)
        assert result == EXPIRED

    def test_still_pending_within_window(self):
        """No level hit but still within valid_until -> None (not resolved yet)."""
        tracker = self._make_tracker()
        sig = _make_signal(
            valid_until=datetime.now(timezone.utc) + timedelta(days=7),
            feedback_timestamp=datetime.now(timezone.utc) - timedelta(days=2),
        )

        bars = [_make_bar(high=105, low=97)]
        with patch.object(tracker, "_get_daily_bars", return_value=bars):
            result = tracker._classify_outcome(sig)
        assert result is None

    def test_too_soon_to_classify(self):
        """Signal just fired (< 6 hours ago) -> None."""
        tracker = self._make_tracker()
        sig = _make_signal(
            feedback_timestamp=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        result = tracker._classify_outcome(sig)
        assert result is None

    def test_no_bars_returns_none(self):
        """No price data available -> None (unless expired)."""
        tracker = self._make_tracker()
        sig = _make_signal()

        with patch.object(tracker, "_get_daily_bars", return_value=[]):
            result = tracker._classify_outcome(sig)
        assert result is None

    def test_sell_signal_inverted_logic(self):
        """SELL signal: stop is hit when price goes UP, target when DOWN."""
        tracker = self._make_tracker()
        sig = _make_signal(
            signal="SELL",
            entry_price=100.0,
            stop_price=105.0,  # Stop above entry for sell
            target_1=90.0,  # Target below entry for sell
            target_2=80.0,
        )

        # Price drops to target_1
        bars = [_make_bar(high=101, low=89)]
        with patch.object(tracker, "_get_daily_bars", return_value=bars):
            result = tracker._classify_outcome(sig)
        assert result == TARGET_1_HIT

    def test_sell_signal_stopped_out(self):
        """SELL signal stopped out when price rises above stop."""
        tracker = self._make_tracker()
        sig = _make_signal(
            signal="SELL",
            entry_price=100.0,
            stop_price=105.0,
            target_1=90.0,
            target_2=80.0,
        )

        bars = [_make_bar(high=106, low=99)]  # High > stop (105)
        with patch.object(tracker, "_get_daily_bars", return_value=bars):
            result = tracker._classify_outcome(sig)
        assert result == STOPPED_OUT

    def test_zero_entry_price_returns_none(self):
        """Invalid signal with zero entry -> skip."""
        tracker = self._make_tracker()
        sig = _make_signal(entry_price=0.0)
        result = tracker._classify_outcome(sig)
        assert result is None


class TestFetchAndUpdate:
    def test_fetch_unresolved_success(self):
        tracker = SignalPriceTracker(
            stock_service_url="http://localhost:8081",
            timescale_host="localhost",
            timescale_port=5432,
            timescale_db="test",
            timescale_user="test",
            timescale_password="",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "id": 1,
                "symbol": "XYZ",
                "signal": "BUY",
                "action": "skipped",
                "entry_price": 25.0,
                "stop_price": 23.0,
                "target_1": 28.0,
                "target_2": 31.0,
                "feedback_timestamp": "2026-03-01T14:00:00Z",
            }
        ]
        mock_response.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_response) as mock_get:
            signals = tracker._fetch_unresolved()

        assert len(signals) == 1
        assert signals[0].symbol == "XYZ"
        assert signals[0].entry_price == 25.0

    def test_fetch_unresolved_empty(self):
        tracker = SignalPriceTracker(
            stock_service_url="http://localhost:8081",
            timescale_host="localhost",
            timescale_port=5432,
            timescale_db="test",
            timescale_user="test",
            timescale_password="",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_response):
            signals = tracker._fetch_unresolved()
        assert signals == []

    def test_update_outcome_success(self):
        tracker = SignalPriceTracker(
            stock_service_url="http://localhost:8081",
            timescale_host="localhost",
            timescale_port=5432,
            timescale_db="test",
            timescale_user="test",
            timescale_password="",
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("requests.put", return_value=mock_response) as mock_put:
            result = tracker._update_outcome(42, TARGET_1_HIT)

        assert result is True
        mock_put.assert_called_once()
        call_kwargs = mock_put.call_args
        assert "42" in call_kwargs[0][0]
        assert call_kwargs[1]["json"]["outcome"] == TARGET_1_HIT

    def test_update_outcome_network_error(self):
        import requests as req_lib

        tracker = SignalPriceTracker(
            stock_service_url="http://localhost:8081",
            timescale_host="localhost",
            timescale_port=5432,
            timescale_db="test",
            timescale_user="test",
            timescale_password="",
        )

        with patch("requests.put", side_effect=req_lib.ConnectionError("refused")):
            result = tracker._update_outcome(42, TARGET_1_HIT)
        assert result is False
