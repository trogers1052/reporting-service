"""Tests for signal-to-outcome analysis."""

from datetime import datetime

import pytest

from reporting_service.analysis.signal_outcome_analyzer import SignalOutcomeAnalyzer
from reporting_service.models.analysis import ExitType, RuleEvaluation, TradeAnalysis
from reporting_service.models.position import Position
from reporting_service.models.signal_analysis import (
    ConditionBucketMetrics,
    ConfidenceBucket,
    RuleMetrics,
    SignalOutcomeReport,
    SignalTypeMetrics,
)


# ─── Fixtures ───────────────────────────────────────────────────────


def _make_position(
    id: int,
    symbol: str,
    entry_price: float,
    exit_price: float,
    realized_pl_pct: float,
    holding_days: int = 10,
    risk_metrics_at_entry: dict = None,
) -> Position:
    """Helper to build a Position."""
    realized_pl = (exit_price - entry_price) * 100
    return Position(
        id=id,
        symbol=symbol,
        entry_order_id=f"order-{id}-entry",
        entry_price=entry_price,
        quantity=100,
        entry_date=datetime(2026, 1, 15, 10, 0),
        status="closed",
        exit_order_id=f"order-{id}-exit",
        exit_price=exit_price,
        exit_date=datetime(2026, 1, 25, 14, 0),
        realized_pl=realized_pl,
        realized_pl_pct=realized_pl_pct,
        holding_days=holding_days,
        risk_metrics_at_entry=risk_metrics_at_entry,
    )


def _make_analysis(
    position_id: int,
    symbol: str,
    entry_price: float,
    signal_type: str = "BUY",
    confidence: float = 0.75,
    exit_type: ExitType = ExitType.PROFIT_TARGET,
    rules: list = None,
    risk_metrics: dict = None,
) -> TradeAnalysis:
    """Helper to build a TradeAnalysis."""
    if rules is None:
        rules = [
            RuleEvaluation(
                rule_name="trend_following",
                triggered=True,
                signal_type="BUY",
                confidence=0.7,
            ),
        ]
    return TradeAnalysis(
        position_id=position_id,
        symbol=symbol,
        entry_date=datetime(2026, 1, 15, 10, 0),
        entry_price=entry_price,
        entry_signal_matched=signal_type == "BUY" and confidence >= 0.5,
        entry_signal_type=signal_type,
        entry_signal_confidence=confidence,
        exit_type=exit_type,
        entry_rules_evaluated=rules,
        risk_metrics=risk_metrics or {},
    )


@pytest.fixture
def analyzer():
    return SignalOutcomeAnalyzer()


@pytest.fixture
def winning_pair():
    """A winning BUY trade."""
    pos = _make_position(1, "SOFI", 12.0, 13.20, 10.0, holding_days=7)
    analysis = _make_analysis(1, "SOFI", 12.0, "BUY", 0.80, ExitType.PROFIT_TARGET)
    return analysis, pos


@pytest.fixture
def losing_pair():
    """A losing BUY trade."""
    pos = _make_position(2, "CCJ", 50.0, 47.5, -5.0, holding_days=5)
    analysis = _make_analysis(2, "CCJ", 50.0, "BUY", 0.60, ExitType.STOP_LOSS)
    return analysis, pos


@pytest.fixture
def no_signal_pair():
    """A trade entered without a signal."""
    pos = _make_position(3, "WPM", 45.0, 43.0, -4.4, holding_days=12)
    analysis = _make_analysis(
        3, "WPM", 45.0, signal_type=None, confidence=0.0, exit_type=ExitType.MANUAL,
        rules=[],
    )
    return analysis, pos


@pytest.fixture
def mixed_pairs(winning_pair, losing_pair, no_signal_pair):
    """Collection of mixed trade outcomes."""
    analyses = [winning_pair[0], losing_pair[0], no_signal_pair[0]]
    positions = {
        winning_pair[1].id: winning_pair[1],
        losing_pair[1].id: losing_pair[1],
        no_signal_pair[1].id: no_signal_pair[1],
    }
    return analyses, positions


# ─── Model Tests ────────────────────────────────────────────────────


class TestSignalTypeMetrics:
    def test_to_dict(self):
        m = SignalTypeMetrics(
            signal_type="BUY",
            trade_count=5,
            win_count=3,
            loss_count=2,
            win_rate=0.6,
            avg_return_pct=4.5,
            avg_holding_days=8.0,
            exit_distribution={"profit_target": 3, "stop_loss": 2},
        )
        d = m.to_dict()
        assert d["signal_type"] == "BUY"
        assert d["win_rate"] == 0.6
        assert d["exit_distribution"]["profit_target"] == 3


class TestRuleMetrics:
    def test_to_dict(self):
        m = RuleMetrics(
            rule_name="trend_following",
            trigger_count=10,
            win_rate_when_triggered=0.7,
            avg_return_when_triggered=5.5,
            avg_confidence=0.75,
        )
        d = m.to_dict()
        assert d["rule_name"] == "trend_following"
        assert d["trigger_count"] == 10
        assert d["avg_confidence"] == 0.75


class TestConfidenceBucket:
    def test_to_dict(self):
        b = ConfidenceBucket(
            range_label="75-100%",
            trade_count=4,
            win_rate=0.75,
            avg_return_pct=8.2,
        )
        d = b.to_dict()
        assert d["range"] == "75-100%"
        assert d["win_rate"] == 0.75


class TestSignalOutcomeReport:
    def test_to_dict_empty(self):
        report = SignalOutcomeReport()
        d = report.to_dict()
        assert d["total_trades_analyzed"] == 0
        assert d["signal_type_metrics"] == []
        assert d["key_insights"] == []

    def test_to_dict_with_data(self):
        report = SignalOutcomeReport(
            total_trades_analyzed=10,
            signal_type_metrics=[
                SignalTypeMetrics(signal_type="BUY", trade_count=10),
            ],
            key_insights=["Test insight"],
        )
        d = report.to_dict()
        assert d["total_trades_analyzed"] == 10
        assert len(d["signal_type_metrics"]) == 1
        assert d["key_insights"] == ["Test insight"]


# ─── Analyzer Tests ─────────────────────────────────────────────────


class TestSignalOutcomeAnalyzerEmpty:
    def test_empty_analyses(self, analyzer):
        report = analyzer.analyze([], {})
        assert report.total_trades_analyzed == 0
        assert report.signal_type_metrics == []

    def test_no_matching_positions(self, analyzer):
        analysis = _make_analysis(99, "FAKE", 10.0)
        report = analyzer.analyze([analysis], {})
        # No position found → no pairs → empty metrics
        assert report.total_trades_analyzed == 1
        assert all(m.trade_count == 0 for m in report.signal_type_metrics)


class TestSignalTypeAnalysis:
    def test_single_buy_winner(self, analyzer, winning_pair):
        analysis, pos = winning_pair
        report = analyzer.analyze([analysis], {pos.id: pos})

        assert len(report.signal_type_metrics) == 1
        m = report.signal_type_metrics[0]
        assert m.signal_type == "BUY"
        assert m.trade_count == 1
        assert m.win_count == 1
        assert m.win_rate == 1.0
        assert m.avg_return_pct == 10.0

    def test_buy_vs_no_signal(self, analyzer, mixed_pairs):
        analyses, positions = mixed_pairs
        report = analyzer.analyze(analyses, positions)

        types = {m.signal_type: m for m in report.signal_type_metrics}
        assert "BUY" in types
        assert "NONE" in types
        assert types["BUY"].trade_count == 2
        assert types["NONE"].trade_count == 1

    def test_exit_distribution(self, analyzer, winning_pair, losing_pair):
        analyses = [winning_pair[0], losing_pair[0]]
        positions = {
            winning_pair[1].id: winning_pair[1],
            losing_pair[1].id: losing_pair[1],
        }
        report = analyzer.analyze(analyses, positions)

        buy_metrics = report.signal_type_metrics[0]
        assert buy_metrics.signal_type == "BUY"
        assert buy_metrics.exit_distribution.get("profit_target", 0) == 1
        assert buy_metrics.exit_distribution.get("stop_loss", 0) == 1

    def test_best_and_worst_trade(self, analyzer, winning_pair, losing_pair):
        analyses = [winning_pair[0], losing_pair[0]]
        positions = {
            winning_pair[1].id: winning_pair[1],
            losing_pair[1].id: losing_pair[1],
        }
        report = analyzer.analyze(analyses, positions)

        buy_metrics = report.signal_type_metrics[0]
        assert buy_metrics.best_trade["return_pct"] == 10.0
        assert buy_metrics.worst_trade["return_pct"] == -5.0


class TestRuleAnalysis:
    def test_single_rule_triggered(self, analyzer, winning_pair):
        analysis, pos = winning_pair
        report = analyzer.analyze([analysis], {pos.id: pos})

        assert len(report.rule_metrics) == 1
        rm = report.rule_metrics[0]
        assert rm.rule_name == "trend_following"
        assert rm.trigger_count == 1
        assert rm.win_rate_when_triggered == 1.0

    def test_multiple_rules(self, analyzer):
        pos = _make_position(1, "SOFI", 12.0, 13.2, 10.0)
        analysis = _make_analysis(
            1, "SOFI", 12.0,
            rules=[
                RuleEvaluation(
                    rule_name="trend_following",
                    triggered=True,
                    signal_type="BUY",
                    confidence=0.7,
                ),
                RuleEvaluation(
                    rule_name="rsi_oversold",
                    triggered=True,
                    signal_type="BUY",
                    confidence=0.8,
                ),
            ],
        )
        report = analyzer.analyze([analysis], {pos.id: pos})

        assert len(report.rule_metrics) == 2
        names = {rm.rule_name for rm in report.rule_metrics}
        assert "trend_following" in names
        assert "rsi_oversold" in names

    def test_untriggered_rules_excluded(self, analyzer):
        pos = _make_position(1, "SOFI", 12.0, 13.2, 10.0)
        analysis = _make_analysis(
            1, "SOFI", 12.0,
            rules=[
                RuleEvaluation(
                    rule_name="triggered_rule",
                    triggered=True,
                    signal_type="BUY",
                    confidence=0.7,
                ),
                RuleEvaluation(
                    rule_name="not_triggered",
                    triggered=False,
                    signal_type=None,
                    confidence=0.0,
                ),
            ],
        )
        report = analyzer.analyze([analysis], {pos.id: pos})
        assert len(report.rule_metrics) == 1
        assert report.rule_metrics[0].rule_name == "triggered_rule"


class TestConfidenceAnalysis:
    def test_high_confidence_bucket(self, analyzer, winning_pair):
        analysis, pos = winning_pair
        report = analyzer.analyze([analysis], {pos.id: pos})

        buckets = {b.range_label: b for b in report.confidence_buckets}
        assert buckets["75-100%"].trade_count == 1
        assert buckets["75-100%"].win_rate == 1.0
        assert buckets["0-25%"].trade_count == 0

    def test_multiple_buckets(self, analyzer, mixed_pairs):
        analyses, positions = mixed_pairs
        report = analyzer.analyze(analyses, positions)

        non_empty = [b for b in report.confidence_buckets if b.trade_count > 0]
        assert len(non_empty) >= 1

    def test_zero_confidence_in_first_bucket(self, analyzer, no_signal_pair):
        analysis, pos = no_signal_pair
        report = analyzer.analyze([analysis], {pos.id: pos})

        buckets = {b.range_label: b for b in report.confidence_buckets}
        assert buckets["0-25%"].trade_count == 1


class TestConditionAnalysis:
    def test_regime_from_risk_metrics_at_entry(self, analyzer):
        pos = _make_position(
            1, "SOFI", 12.0, 13.2, 10.0,
            risk_metrics_at_entry={"regime": "BULL", "rsi_14": 35.0},
        )
        analysis = _make_analysis(
            1, "SOFI", 12.0,
            risk_metrics={"rsi": 35.0},
        )
        report = analyzer.analyze([analysis], {pos.id: pos})

        conditions = {c.condition: c for c in report.condition_metrics}
        assert "regime:BULL" in conditions
        assert conditions["regime:BULL"].trade_count == 1
        assert conditions["regime:BULL"].win_rate == 1.0

    def test_rsi_buckets(self, analyzer):
        pos = _make_position(1, "SOFI", 12.0, 13.2, 10.0)
        analysis = _make_analysis(
            1, "SOFI", 12.0,
            risk_metrics={"rsi": 25.0},
        )
        report = analyzer.analyze([analysis], {pos.id: pos})

        conditions = {c.condition: c for c in report.condition_metrics}
        assert "rsi:oversold" in conditions
        assert conditions["rsi:oversold"].trade_count == 1

    def test_no_conditions_without_metrics(self, analyzer, no_signal_pair):
        analysis, pos = no_signal_pair
        report = analyzer.analyze([analysis], {pos.id: pos})
        # No risk_metrics and no risk_metrics_at_entry → no condition data
        assert len(report.condition_metrics) == 0

    def test_rsi_from_entry_metrics(self, analyzer):
        """RSI should also be read from risk_metrics_at_entry."""
        pos = _make_position(
            1, "SOFI", 12.0, 11.0, -8.3,
            risk_metrics_at_entry={"rsi_14": 75.0},
        )
        analysis = _make_analysis(
            1, "SOFI", 12.0,
            risk_metrics={},  # no rsi in analysis risk_metrics
        )
        report = analyzer.analyze([analysis], {pos.id: pos})

        conditions = {c.condition: c for c in report.condition_metrics}
        assert "rsi:overbought" in conditions


class TestInsights:
    def test_buy_vs_no_signal_insight(self, analyzer, mixed_pairs):
        analyses, positions = mixed_pairs
        report = analyzer.analyze(analyses, positions)

        # Should have some insights generated
        assert len(report.key_insights) > 0

    def test_empty_trades_insight(self, analyzer):
        report = analyzer.analyze([], {})
        assert any("Insufficient" in i for i in report.key_insights)

    def test_best_rule_insight(self, analyzer):
        pos1 = _make_position(1, "SOFI", 12.0, 13.2, 10.0)
        pos2 = _make_position(2, "CCJ", 50.0, 55.0, 10.0)
        analysis1 = _make_analysis(
            1, "SOFI", 12.0,
            rules=[
                RuleEvaluation(
                    rule_name="great_rule",
                    triggered=True,
                    signal_type="BUY",
                    confidence=0.9,
                ),
            ],
        )
        analysis2 = _make_analysis(
            2, "CCJ", 50.0,
            rules=[
                RuleEvaluation(
                    rule_name="great_rule",
                    triggered=True,
                    signal_type="BUY",
                    confidence=0.85,
                ),
            ],
        )
        report = analyzer.analyze(
            [analysis1, analysis2],
            {pos1.id: pos1, pos2.id: pos2},
        )
        assert any("great_rule" in i for i in report.key_insights)

    def test_poor_regime_insight(self, analyzer):
        """Regime with <40% win rate should generate a warning insight."""
        pos1 = _make_position(
            1, "X", 20.0, 18.0, -10.0,
            risk_metrics_at_entry={"regime": "BEAR"},
        )
        pos2 = _make_position(
            2, "Y", 30.0, 27.0, -10.0,
            risk_metrics_at_entry={"regime": "BEAR"},
        )
        a1 = _make_analysis(1, "X", 20.0, exit_type=ExitType.STOP_LOSS,
                            risk_metrics={})
        a2 = _make_analysis(2, "Y", 30.0, exit_type=ExitType.STOP_LOSS,
                            risk_metrics={})

        report = analyzer.analyze([a1, a2], {pos1.id: pos1, pos2.id: pos2})
        assert any("regime:BEAR" in i for i in report.key_insights)


class TestPositionRiskMetricsParsing:
    def test_from_row_with_dict(self):
        """risk_metrics_at_entry as dict (from psycopg2 JSONB)."""
        row = {
            "id": 1, "symbol": "SOFI", "entry_order_id": "o1",
            "entry_price": 12.0, "quantity": 100,
            "entry_date": datetime(2026, 1, 1), "status": "closed",
            "risk_metrics_at_entry": {"regime": "BULL", "rsi_14": 35.0},
        }
        pos = Position.from_row(row)
        assert pos.risk_metrics_at_entry == {"regime": "BULL", "rsi_14": 35.0}

    def test_from_row_with_json_string(self):
        """risk_metrics_at_entry as JSON string."""
        row = {
            "id": 1, "symbol": "SOFI", "entry_order_id": "o1",
            "entry_price": 12.0, "quantity": 100,
            "entry_date": datetime(2026, 1, 1), "status": "closed",
            "risk_metrics_at_entry": '{"regime": "SIDEWAYS"}',
        }
        pos = Position.from_row(row)
        assert pos.risk_metrics_at_entry == {"regime": "SIDEWAYS"}

    def test_from_row_with_none(self):
        """risk_metrics_at_entry as None."""
        row = {
            "id": 1, "symbol": "SOFI", "entry_order_id": "o1",
            "entry_price": 12.0, "quantity": 100,
            "entry_date": datetime(2026, 1, 1), "status": "closed",
            "risk_metrics_at_entry": None,
        }
        pos = Position.from_row(row)
        assert pos.risk_metrics_at_entry is None

    def test_from_row_with_invalid_json(self):
        """Invalid JSON string should be handled gracefully."""
        row = {
            "id": 1, "symbol": "SOFI", "entry_order_id": "o1",
            "entry_price": 12.0, "quantity": 100,
            "entry_date": datetime(2026, 1, 1), "status": "closed",
            "risk_metrics_at_entry": "not valid json",
        }
        pos = Position.from_row(row)
        assert pos.risk_metrics_at_entry is None
