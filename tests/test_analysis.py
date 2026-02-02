"""Tests for analysis components."""

import pytest

from reporting_service.analysis.exit_classifier import ExitClassifier
from reporting_service.analysis.rule_evaluator import RuleEvaluator
from reporting_service.models.analysis import ExitType


class TestExitClassifier:
    """Tests for ExitClassifier."""

    def test_classify_profit_target(self, settings, sample_position):
        classifier = ExitClassifier(settings)
        # Position has 10% gain
        exit_type = classifier.classify(sample_position)
        assert exit_type == ExitType.PROFIT_TARGET

    def test_classify_stop_loss(self, settings, losing_position):
        classifier = ExitClassifier(settings)
        # Position has -5% loss
        exit_type = classifier.classify(losing_position)
        assert exit_type == ExitType.STOP_LOSS

    def test_classify_manual_small_gain(self, settings, sample_position):
        classifier = ExitClassifier(settings)
        # Small gain - not hitting profit target
        sample_position.realized_pl_pct = 2.0  # 2%
        exit_type = classifier.classify(sample_position)
        assert exit_type == ExitType.MANUAL

    def test_classify_time_based(self, settings, sample_position):
        classifier = ExitClassifier(settings)
        # Long hold, small P&L
        sample_position.holding_days = 30
        sample_position.realized_pl_pct = 1.0  # 1%
        exit_type = classifier.classify(sample_position)
        assert exit_type == ExitType.TIME_BASED


class TestRuleEvaluator:
    """Tests for RuleEvaluator."""

    def test_initialize(self, settings):
        evaluator = RuleEvaluator(settings)
        result = evaluator.initialize()
        assert result is True

    def test_fallback_evaluation_bullish(self, settings, sample_indicators):
        evaluator = RuleEvaluator(settings)
        evaluator.initialize()

        from datetime import datetime

        evaluations, signal, confidence = evaluator.evaluate_at_time(
            "AAPL",
            sample_indicators,
            datetime.utcnow(),
        )

        # Price above SMA200, should trigger bullish signals
        assert len(evaluations) > 0
        assert signal == "BUY"
        assert confidence > 0

    def test_fallback_evaluation_bearish(self, settings, bearish_indicators):
        evaluator = RuleEvaluator(settings)
        evaluator.initialize()

        from datetime import datetime

        evaluations, signal, confidence = evaluator.evaluate_at_time(
            "GOOGL",
            bearish_indicators,
            datetime.utcnow(),
        )

        # Price below SMA200
        assert len(evaluations) > 0
        # May be SELL or no signal depending on other indicators

    def test_get_required_indicators(self, settings):
        evaluator = RuleEvaluator(settings)
        evaluator.initialize()

        indicators = evaluator.get_required_indicators()
        assert "close" in indicators
        assert "sma_200" in indicators
