"""Extended tests for RuleEvaluator — fallback paths, get_exit_strategy, edge cases."""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from reporting_service.analysis.rule_evaluator import RuleEvaluator
from reporting_service.config import ReportingSettings


# ---------------------------------------------------------------------------
# Fallback evaluation — signal combinations
# ---------------------------------------------------------------------------


class TestFallbackEvaluationSignals:
    """Test _evaluate_fallback with various indicator combos."""

    def test_only_rsi_oversold(self, settings):
        evaluator = RuleEvaluator(settings)
        evaluator.initialize()
        indicators = {"close": 50.0, "rsi_14": 25.0}
        evals, signal, conf = evaluator.evaluate_at_time(
            "AAPL", indicators, datetime.utcnow()
        )
        # RSI < 30 → BUY signal from rsi_oversold
        assert signal == "BUY"
        assert conf == 0.65
        rule_names = [e.rule_name for e in evals if e.triggered]
        assert "rsi_oversold" in rule_names

    def test_only_rsi_overbought(self, settings):
        evaluator = RuleEvaluator(settings)
        evaluator.initialize()
        indicators = {"close": 50.0, "rsi_14": 80.0}
        evals, signal, conf = evaluator.evaluate_at_time(
            "AAPL", indicators, datetime.utcnow()
        )
        assert signal == "SELL"
        assert conf == 0.6
        rule_names = [e.rule_name for e in evals if e.triggered]
        assert "rsi_overbought" in rule_names

    def test_rsi_neutral_no_sma(self, settings):
        """RSI between 30-70 with no SMA data → no signals."""
        evaluator = RuleEvaluator(settings)
        evaluator.initialize()
        indicators = {"close": 50.0, "rsi_14": 50.0}
        evals, signal, conf = evaluator.evaluate_at_time(
            "AAPL", indicators, datetime.utcnow()
        )
        assert signal is None
        assert conf == 0.0

    def test_golden_cross(self, settings):
        """SMA50 > SMA200 → BUY signal from moving_average_crossover."""
        evaluator = RuleEvaluator(settings)
        evaluator.initialize()
        indicators = {"close": 50.0, "sma_50": 48.0, "sma_200": 45.0}
        evals, signal, conf = evaluator.evaluate_at_time(
            "AAPL", indicators, datetime.utcnow()
        )
        assert signal == "BUY"
        rule_names = [e.rule_name for e in evals if e.triggered]
        assert "moving_average_crossover" in rule_names

    def test_death_cross_not_triggered(self, settings):
        """SMA50 < SMA200 → crossover rule doesn't fire (only fires on golden)."""
        evaluator = RuleEvaluator(settings)
        evaluator.initialize()
        # close below sma_200 → trend_following SELL; sma_50 < sma_200 → no crossover
        indicators = {"close": 40.0, "sma_50": 42.0, "sma_200": 45.0}
        evals, signal, conf = evaluator.evaluate_at_time(
            "AAPL", indicators, datetime.utcnow()
        )
        rule_names = [e.rule_name for e in evals if e.triggered]
        assert "moving_average_crossover" not in rule_names
        # trend_following SELL fires because close < sma_200
        assert "trend_following" in rule_names
        assert signal == "SELL"

    def test_price_above_sma200_trend_buy(self, settings):
        evaluator = RuleEvaluator(settings)
        evaluator.initialize()
        indicators = {"close": 150.0, "sma_200": 140.0}
        evals, signal, conf = evaluator.evaluate_at_time(
            "AAPL", indicators, datetime.utcnow()
        )
        rule_names = [e.rule_name for e in evals if e.triggered]
        assert "trend_following" in rule_names
        assert signal == "BUY"
        assert conf == 0.6

    def test_price_below_sma200_trend_sell(self, settings):
        evaluator = RuleEvaluator(settings)
        evaluator.initialize()
        indicators = {"close": 130.0, "sma_200": 145.0}
        evals, signal, conf = evaluator.evaluate_at_time(
            "AAPL", indicators, datetime.utcnow()
        )
        rule_names = [e.rule_name for e in evals if e.triggered]
        assert "trend_following" in rule_names
        assert signal == "SELL"

    def test_no_indicators_at_all(self, settings):
        """Empty indicators → no signals triggered."""
        evaluator = RuleEvaluator(settings)
        evaluator.initialize()
        evals, signal, conf = evaluator.evaluate_at_time(
            "AAPL", {}, datetime.utcnow()
        )
        assert signal is None
        assert conf == 0.0
        assert len(evals) == 0

    def test_close_zero_no_sma(self, settings):
        """Close=0, no SMAs → close(0) is falsy but sma_200 is None."""
        evaluator = RuleEvaluator(settings)
        evaluator.initialize()
        indicators = {"close": 0}
        evals, signal, conf = evaluator.evaluate_at_time(
            "AAPL", indicators, datetime.utcnow()
        )
        assert signal is None

    def test_multiple_buy_signals_average_confidence(self, settings):
        """Multiple BUY signals → confidence is averaged."""
        evaluator = RuleEvaluator(settings)
        evaluator.initialize()
        # trend BUY (0.6) + golden cross BUY (0.55) + RSI oversold BUY (0.65)
        indicators = {
            "close": 150.0,
            "sma_200": 140.0,
            "sma_50": 148.0,
            "rsi_14": 25.0,
        }
        evals, signal, conf = evaluator.evaluate_at_time(
            "AAPL", indicators, datetime.utcnow()
        )
        assert signal == "BUY"
        # Average of 0.6 + 0.55 + 0.65 = 1.8/3 = 0.6
        assert abs(conf - 0.6) < 0.01

    def test_mixed_buy_sell_more_buys_win(self, settings):
        """When buy signals outnumber sell signals, BUY wins."""
        evaluator = RuleEvaluator(settings)
        evaluator.initialize()
        # close > sma_200 → trend BUY (0.6)
        # sma_50 > sma_200 → crossover BUY (0.55)
        # RSI > 70 → SELL (0.6)
        indicators = {
            "close": 150.0,
            "sma_200": 140.0,
            "sma_50": 148.0,
            "rsi_14": 75.0,
        }
        evals, signal, conf = evaluator.evaluate_at_time(
            "AAPL", indicators, datetime.utcnow()
        )
        # 2 BUY vs 1 SELL → BUY wins
        assert signal == "BUY"

    def test_sell_only_signals(self, settings):
        """Only SELL signals → SELL returned."""
        evaluator = RuleEvaluator(settings)
        evaluator.initialize()
        # close < sma_200 → trend SELL (0.5)
        # RSI > 70 → overbought SELL (0.6)
        indicators = {
            "close": 130.0,
            "sma_200": 145.0,
            "rsi_14": 80.0,
        }
        evals, signal, conf = evaluator.evaluate_at_time(
            "AAPL", indicators, datetime.utcnow()
        )
        assert signal == "SELL"
        # Average of 0.5 and 0.6
        assert abs(conf - 0.55) < 0.01


# ---------------------------------------------------------------------------
# evaluate_at_time — auto-initialization
# ---------------------------------------------------------------------------


class TestEvaluateAutoInit:
    def test_auto_initializes_if_not_initialized(self, settings):
        evaluator = RuleEvaluator(settings)
        # Don't call initialize() explicitly
        evals, signal, conf = evaluator.evaluate_at_time(
            "AAPL", {"close": 150.0, "sma_200": 140.0}, datetime.utcnow()
        )
        assert evaluator._initialized is True
        assert signal == "BUY"


# ---------------------------------------------------------------------------
# get_exit_strategy
# ---------------------------------------------------------------------------


class TestGetExitStrategy:
    def test_with_rules_client(self, settings):
        mock_client = Mock()
        mock_client.get_exit_strategy.return_value = {
            "profit_target": 0.12,
            "stop_loss": 0.06,
        }
        evaluator = RuleEvaluator(settings, rules_client=mock_client)
        result = evaluator.get_exit_strategy("AAPL")
        assert result == {"profit_target": 0.12, "stop_loss": 0.06}
        mock_client.get_exit_strategy.assert_called_once_with("AAPL")

    def test_without_rules_client_no_config(self, settings):
        evaluator = RuleEvaluator(settings)
        result = evaluator.get_exit_strategy("AAPL")
        assert result == {"profit_target": 0.07, "stop_loss": 0.05}

    def test_with_config_default_exit_strategy(self, settings):
        evaluator = RuleEvaluator(settings)
        evaluator._config = {
            "exit_strategy": {"profit_target": 0.10, "stop_loss": 0.04},
        }
        result = evaluator.get_exit_strategy("AAPL")
        assert result == {"profit_target": 0.10, "stop_loss": 0.04}

    def test_with_config_symbol_override(self, settings):
        evaluator = RuleEvaluator(settings)
        evaluator._config = {
            "exit_strategy": {"profit_target": 0.07, "stop_loss": 0.05},
            "symbol_overrides": {
                "TSLA": {
                    "exit_strategy": {"profit_target": 0.15, "stop_loss": 0.10},
                },
            },
        }
        result = evaluator.get_exit_strategy("TSLA")
        assert result == {"profit_target": 0.15, "stop_loss": 0.10}

    def test_with_config_symbol_no_override(self, settings):
        """Symbol not in overrides → falls back to default exit_strategy."""
        evaluator = RuleEvaluator(settings)
        evaluator._config = {
            "exit_strategy": {"profit_target": 0.07, "stop_loss": 0.05},
            "symbol_overrides": {
                "TSLA": {"exit_strategy": {"profit_target": 0.15}},
            },
        }
        result = evaluator.get_exit_strategy("AAPL")
        assert result == {"profit_target": 0.07, "stop_loss": 0.05}

    def test_with_config_no_exit_strategy_key(self, settings):
        """Config exists but has no exit_strategy → returns default."""
        evaluator = RuleEvaluator(settings)
        evaluator._config = {"rules": {}}
        result = evaluator.get_exit_strategy("AAPL")
        assert result == {"profit_target": 0.07, "stop_loss": 0.05}

    def test_rules_client_takes_priority_over_config(self, settings):
        mock_client = Mock()
        mock_client.get_exit_strategy.return_value = {
            "profit_target": 0.20,
            "stop_loss": 0.08,
        }
        evaluator = RuleEvaluator(settings, rules_client=mock_client)
        evaluator._config = {
            "exit_strategy": {"profit_target": 0.07, "stop_loss": 0.05},
        }
        result = evaluator.get_exit_strategy("AAPL")
        assert result["profit_target"] == 0.20  # rules client wins


# ---------------------------------------------------------------------------
# get_required_indicators — fallback list
# ---------------------------------------------------------------------------


class TestGetRequiredIndicators:
    def test_fallback_list_contents(self, settings):
        evaluator = RuleEvaluator(settings)
        evaluator.initialize()
        indicators = evaluator.get_required_indicators()
        expected = [
            "close", "sma_20", "sma_50", "sma_200",
            "rsi_14", "atr_14", "volume", "avg_volume_20",
        ]
        for ind in expected:
            assert ind in indicators

    def test_returns_list_type(self, settings):
        evaluator = RuleEvaluator(settings)
        evaluator.initialize()
        assert isinstance(evaluator.get_required_indicators(), list)


# ---------------------------------------------------------------------------
# initialize — paths
# ---------------------------------------------------------------------------


class TestInitialize:
    def test_without_decision_engine(self, settings):
        evaluator = RuleEvaluator(settings)
        result = evaluator.initialize()
        assert result is True
        assert evaluator._initialized is True

    def test_double_initialize(self, settings):
        evaluator = RuleEvaluator(settings)
        evaluator.initialize()
        evaluator.initialize()
        assert evaluator._initialized is True
