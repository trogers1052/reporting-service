"""Tests for reporting service models."""

from datetime import datetime

import pytest

from reporting_service.models.analysis import (
    ComplianceLevel,
    ExitType,
    RuleEvaluation,
    TradeAnalysis,
)
from reporting_service.models.position import Position, Trade


class TestPosition:
    """Tests for Position model."""

    def test_position_creation(self, sample_position):
        assert sample_position.symbol == "AAPL"
        assert sample_position.entry_price == 150.0
        assert sample_position.status == "closed"

    def test_is_winner(self, sample_position, losing_position):
        assert sample_position.is_winner is True
        assert losing_position.is_winner is False

    def test_is_analyzed(self, sample_position):
        assert sample_position.is_analyzed is False
        sample_position.analyzed_at = datetime.utcnow()
        assert sample_position.is_analyzed is True


class TestExitType:
    """Tests for ExitType enum."""

    def test_exit_type_values(self):
        assert ExitType.PROFIT_TARGET.value == "profit_target"
        assert ExitType.STOP_LOSS.value == "stop_loss"
        assert ExitType.MANUAL.value == "manual"


class TestComplianceLevel:
    """Tests for ComplianceLevel."""

    def test_from_score_excellent(self):
        assert ComplianceLevel.from_score(0.95) == ComplianceLevel.EXCELLENT
        assert ComplianceLevel.from_score(0.90) == ComplianceLevel.EXCELLENT

    def test_from_score_good(self):
        assert ComplianceLevel.from_score(0.85) == ComplianceLevel.GOOD
        assert ComplianceLevel.from_score(0.70) == ComplianceLevel.GOOD

    def test_from_score_fair(self):
        assert ComplianceLevel.from_score(0.60) == ComplianceLevel.FAIR

    def test_from_score_poor(self):
        assert ComplianceLevel.from_score(0.40) == ComplianceLevel.POOR

    def test_from_score_non_compliant(self):
        assert ComplianceLevel.from_score(0.20) == ComplianceLevel.NON_COMPLIANT


class TestTradeAnalysis:
    """Tests for TradeAnalysis."""

    def test_calculate_compliance_score(self, sample_analysis):
        score = sample_analysis.calculate_compliance_score()
        assert 0 <= score <= 1
        assert sample_analysis.compliance_level is not None

    def test_compliance_with_signal_match(self, sample_analysis):
        sample_analysis.entry_signal_matched = True
        sample_analysis.entry_signal_confidence = 0.8
        sample_analysis.position_size_deviation = 0.0
        sample_analysis.exit_type = ExitType.PROFIT_TARGET

        score = sample_analysis.calculate_compliance_score()
        # Should be high compliance
        assert score >= 0.7

    def test_compliance_without_signal(self, sample_analysis):
        sample_analysis.entry_signal_matched = False
        sample_analysis.entry_signal_confidence = 0.0
        sample_analysis.exit_type = ExitType.MANUAL

        score = sample_analysis.calculate_compliance_score()
        # Should be low compliance
        assert score < 0.5

    def test_to_dict(self, sample_analysis):
        sample_analysis.calculate_compliance_score()
        d = sample_analysis.to_dict()

        assert d["symbol"] == "AAPL"
        assert d["entry_signal_matched"] is True
        assert "entry_rules" in d
        assert len(d["entry_rules"]) == 2


class TestRuleEvaluation:
    """Tests for RuleEvaluation."""

    def test_rule_evaluation_creation(self):
        eval = RuleEvaluation(
            rule_name="test_rule",
            triggered=True,
            signal_type="BUY",
            confidence=0.75,
            reasoning="Test reasoning",
        )
        assert eval.rule_name == "test_rule"
        assert eval.triggered is True

    def test_to_dict(self):
        eval = RuleEvaluation(
            rule_name="test_rule",
            triggered=True,
            signal_type="BUY",
            confidence=0.756789,
        )
        d = eval.to_dict()
        assert d["confidence"] == 0.7568  # Rounded
