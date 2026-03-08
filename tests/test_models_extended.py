"""Extended model tests — from_row, to_dict, compliance scoring edge cases, config."""

import json
from datetime import datetime

import pytest

from reporting_service.config import (
    AnalysisConfig,
    DatabaseConfig,
    ReportingSettings,
    load_settings,
)
from reporting_service.models.analysis import (
    ComplianceLevel,
    ComplianceMetrics,
    DeviationReport,
    ExitType,
    RuleEvaluation,
    TradeAnalysis,
)
from reporting_service.models.position import JournalEntry, Position, Trade
from reporting_service.models.signal_analysis import (
    ConditionBucketMetrics,
    ConfidenceBucket,
    RuleMetrics,
    SignalOutcomeReport,
    SignalTypeMetrics,
)


# ---------------------------------------------------------------------------
# Trade.from_row
# ---------------------------------------------------------------------------


class TestTradeFromRow:
    def test_full_row(self):
        row = {
            "id": 42,
            "order_id": "ord-abc",
            "symbol": "SOFI",
            "side": "buy",
            "quantity": "10.5",
            "price": "12.30",
            "total_amount": "129.15",
            "fees": "0.02",
            "executed_at": datetime(2026, 2, 1, 10, 0),
            "position_id": 7,
            "created_at": datetime(2026, 2, 1, 10, 1),
        }
        trade = Trade.from_row(row)
        assert trade.id == 42
        assert trade.order_id == "ord-abc"
        assert trade.quantity == 10.5
        assert trade.price == 12.30
        assert trade.total_amount == 129.15
        assert trade.fees == 0.02
        assert trade.position_id == 7

    def test_missing_optional_fields(self):
        row = {
            "id": 1,
            "order_id": "o1",
            "symbol": "AAPL",
            "side": "sell",
            "quantity": 5,
            "price": 150,
            "total_amount": 750,
            "executed_at": datetime(2026, 1, 1),
            # no fees, position_id, created_at
        }
        trade = Trade.from_row(row)
        assert trade.fees == 0
        assert trade.position_id is None
        assert trade.created_at is None

    def test_string_numeric_fields(self):
        """Numeric fields as strings should be converted to float."""
        row = {
            "id": 1,
            "order_id": "o1",
            "symbol": "X",
            "side": "buy",
            "quantity": "100",
            "price": "25.50",
            "total_amount": "2550.00",
            "fees": "0.00",
            "executed_at": datetime(2026, 1, 1),
        }
        trade = Trade.from_row(row)
        assert isinstance(trade.quantity, float)
        assert isinstance(trade.price, float)


# ---------------------------------------------------------------------------
# Position.from_row
# ---------------------------------------------------------------------------


class TestPositionFromRow:
    def test_full_closed_position(self):
        row = {
            "id": 5,
            "symbol": "GOOG",
            "entry_order_id": "o-entry",
            "entry_price": "140.0",
            "quantity": "25",
            "entry_date": datetime(2026, 1, 10),
            "status": "closed",
            "exit_order_id": "o-exit",
            "exit_price": "155.0",
            "exit_date": datetime(2026, 1, 25),
            "realized_pl": "375.0",
            "realized_pl_pct": "10.71",
            "holding_days": 15,
            "rule_compliance_score": "0.85",
            "entry_signal_confidence": "0.72",
            "entry_signal_type": "BUY",
            "position_size_deviation": "0.05",
            "exit_type": "profit_target",
            "risk_metrics_at_entry": {"atr": 3.0},
            "analyzed_at": datetime(2026, 1, 26),
            "created_at": datetime(2026, 1, 10, 12, 0),
        }
        pos = Position.from_row(row)
        assert pos.id == 5
        assert pos.exit_price == 155.0
        assert pos.realized_pl == 375.0
        assert pos.realized_pl_pct == 10.71
        assert pos.rule_compliance_score == 0.85
        assert pos.entry_signal_confidence == 0.72
        assert pos.position_size_deviation == 0.05
        assert pos.risk_metrics_at_entry == {"atr": 3.0}

    def test_open_position_minimal(self):
        row = {
            "id": 1,
            "symbol": "AAPL",
            "entry_order_id": "o1",
            "entry_price": 150,
            "quantity": 10,
            "entry_date": datetime(2026, 2, 1),
            "status": "open",
        }
        pos = Position.from_row(row)
        assert pos.exit_price is None
        assert pos.exit_date is None
        assert pos.realized_pl is None
        assert pos.realized_pl_pct is None
        assert pos.holding_days is None
        assert pos.rule_compliance_score is None
        assert pos.risk_metrics_at_entry is None
        assert pos.analyzed_at is None


# ---------------------------------------------------------------------------
# Position._parse_risk_metrics
# ---------------------------------------------------------------------------


class TestParseRiskMetrics:
    def test_dict_input(self):
        assert Position._parse_risk_metrics({"a": 1}) == {"a": 1}

    def test_string_input(self):
        assert Position._parse_risk_metrics('{"b": 2}') == {"b": 2}

    def test_none_input(self):
        assert Position._parse_risk_metrics(None) is None

    def test_invalid_json_string(self):
        assert Position._parse_risk_metrics("not json") is None

    def test_integer_input(self):
        """Non-dict, non-str type returns None."""
        assert Position._parse_risk_metrics(42) is None

    def test_list_input(self):
        assert Position._parse_risk_metrics([1, 2, 3]) is None

    def test_empty_dict(self):
        assert Position._parse_risk_metrics({}) == {}

    def test_empty_string(self):
        """Empty string is not valid JSON → None."""
        assert Position._parse_risk_metrics("") is None


# ---------------------------------------------------------------------------
# Position.is_winner / is_analyzed
# ---------------------------------------------------------------------------


class TestPositionProperties:
    def test_is_winner_positive_pl(self):
        pos = Position(
            id=1, symbol="X", entry_order_id="o", entry_price=10,
            quantity=1, entry_date=datetime(2026, 1, 1), status="closed",
            realized_pl=10.0,
        )
        assert pos.is_winner is True

    def test_is_winner_zero_pl(self):
        pos = Position(
            id=1, symbol="X", entry_order_id="o", entry_price=10,
            quantity=1, entry_date=datetime(2026, 1, 1), status="closed",
            realized_pl=0.0,
        )
        assert pos.is_winner is False

    def test_is_winner_negative_pl(self):
        pos = Position(
            id=1, symbol="X", entry_order_id="o", entry_price=10,
            quantity=1, entry_date=datetime(2026, 1, 1), status="closed",
            realized_pl=-5.0,
        )
        assert pos.is_winner is False

    def test_is_winner_none_pl(self):
        pos = Position(
            id=1, symbol="X", entry_order_id="o", entry_price=10,
            quantity=1, entry_date=datetime(2026, 1, 1), status="open",
        )
        assert pos.is_winner is False

    def test_is_analyzed_with_analyzed_at(self):
        pos = Position(
            id=1, symbol="X", entry_order_id="o", entry_price=10,
            quantity=1, entry_date=datetime(2026, 1, 1), status="closed",
            analyzed_at=datetime(2026, 1, 2),
        )
        assert pos.is_analyzed is True

    def test_is_analyzed_without_analyzed_at(self):
        pos = Position(
            id=1, symbol="X", entry_order_id="o", entry_price=10,
            quantity=1, entry_date=datetime(2026, 1, 1), status="closed",
        )
        assert pos.is_analyzed is False


# ---------------------------------------------------------------------------
# JournalEntry.from_row
# ---------------------------------------------------------------------------


class TestJournalEntryFromRow:
    def test_full_row(self):
        row = {
            "id": 10,
            "position_id": 5,
            "symbol": "AAPL",
            "entry_reasoning": "Strong trend",
            "exit_reasoning": "Hit target",
            "what_worked": "Waited for pullback",
            "what_didnt_work": "Entered too early",
            "lessons_learned": "Be patient",
            "emotional_state": "calm",
            "would_repeat": True,
            "rating": 4,
            "tags": ["swing", "tech"],
            "notes": "Good trade",
            "created_at": datetime(2026, 1, 20),
            "updated_at": datetime(2026, 1, 21),
        }
        entry = JournalEntry.from_row(row)
        assert entry.id == 10
        assert entry.position_id == 5
        assert entry.entry_reasoning == "Strong trend"
        assert entry.would_repeat is True
        assert entry.tags == ["swing", "tech"]
        assert entry.rating == 4

    def test_minimal_row(self):
        row = {
            "id": 1,
            "position_id": 1,
            "symbol": "X",
        }
        entry = JournalEntry.from_row(row)
        assert entry.entry_reasoning is None
        assert entry.emotional_state is None
        assert entry.would_repeat is None
        assert entry.tags == []
        assert entry.rating is None
        assert entry.notes is None


# ---------------------------------------------------------------------------
# ComplianceMetrics.to_dict
# ---------------------------------------------------------------------------


class TestComplianceMetricsToDict:
    def test_default_values(self):
        m = ComplianceMetrics()
        d = m.to_dict()
        assert d["total_positions"] == 0
        assert d["compliance_distribution"]["excellent"] == 0
        assert d["avg_compliance_score"] == 0.0
        assert d["entry_signal_stats"]["with_signal"] == 0
        assert d["exit_distribution"]["profit_target"] == 0
        assert d["win_rate_by_compliance"]["compliant"] == 0.0

    def test_populated_values(self):
        m = ComplianceMetrics(
            total_positions=20,
            analyzed_positions=20,
            excellent_count=5,
            good_count=8,
            fair_count=4,
            poor_count=2,
            non_compliant_count=1,
            avg_compliance_score=0.7234,
            avg_entry_confidence=0.6589,
            avg_position_size_deviation=0.1234,
            entries_with_buy_signal=15,
            entries_without_signal=5,
            profit_target_exits=8,
            stop_loss_exits=4,
            manual_exits=6,
            other_exits=2,
            compliant_win_rate=0.7512,
            non_compliant_win_rate=0.3456,
        )
        d = m.to_dict()
        assert d["total_positions"] == 20
        assert d["compliance_distribution"]["excellent"] == 5
        assert d["compliance_distribution"]["non_compliant"] == 1
        assert d["avg_compliance_score"] == 0.7234
        assert d["entry_signal_stats"]["with_signal"] == 15
        assert d["exit_distribution"]["stop_loss"] == 4
        assert d["win_rate_by_compliance"]["compliant"] == 0.7512


# ---------------------------------------------------------------------------
# TradeAnalysis.calculate_compliance_score — edge cases
# ---------------------------------------------------------------------------


class TestComplianceScoreEdgeCases:
    def test_no_signal_no_recommended_manual_exit(self):
        """Lowest possible compliance: no signal, neutral sizing, manual exit."""
        a = TradeAnalysis(
            position_id=1,
            symbol="X",
            entry_date=datetime(2026, 1, 1),
            entry_price=10.0,
            entry_signal_matched=False,
            recommended_shares=None,
            exit_type=ExitType.MANUAL,
        )
        score = a.calculate_compliance_score()
        # 0 + 0.15 + 0.1 = 0.25
        assert abs(score - 0.25) < 0.01
        assert a.compliance_level == ComplianceLevel.NON_COMPLIANT

    def test_no_signal_no_recommended_unknown_exit(self):
        a = TradeAnalysis(
            position_id=1,
            symbol="X",
            entry_date=datetime(2026, 1, 1),
            entry_price=10.0,
            entry_signal_matched=False,
            recommended_shares=None,
            exit_type=ExitType.UNKNOWN,
        )
        score = a.calculate_compliance_score()
        # 0 + 0.15 + 0.1 = 0.25
        assert abs(score - 0.25) < 0.01

    def test_signal_matched_no_recommended_trailing_stop(self):
        a = TradeAnalysis(
            position_id=1,
            symbol="X",
            entry_date=datetime(2026, 1, 1),
            entry_price=10.0,
            entry_signal_matched=True,
            entry_signal_confidence=0.80,
            recommended_shares=None,
            exit_type=ExitType.TRAILING_STOP,
        )
        score = a.calculate_compliance_score()
        # 0.8 * 0.4 + 0.15 + 0.25 = 0.32 + 0.15 + 0.25 = 0.72
        assert abs(score - 0.72) < 0.01
        assert a.compliance_level == ComplianceLevel.GOOD

    def test_signal_matched_exact_sizing_stop_loss(self):
        a = TradeAnalysis(
            position_id=1,
            symbol="X",
            entry_date=datetime(2026, 1, 1),
            entry_price=10.0,
            entry_signal_matched=True,
            entry_signal_confidence=1.0,
            recommended_shares=50,
            position_size_deviation=0.0,
            exit_type=ExitType.STOP_LOSS,
        )
        score = a.calculate_compliance_score()
        # 1.0 * 0.4 + (1.0 - 0) * 0.3 + 0.3 = 0.4 + 0.3 + 0.3 = 1.0
        assert abs(score - 1.0) < 0.01
        assert a.compliance_level == ComplianceLevel.EXCELLENT

    def test_signal_matched_large_deviation_time_based(self):
        a = TradeAnalysis(
            position_id=1,
            symbol="X",
            entry_date=datetime(2026, 1, 1),
            entry_price=10.0,
            entry_signal_matched=True,
            entry_signal_confidence=0.60,
            recommended_shares=50,
            position_size_deviation=0.8,  # 80% deviation
            exit_type=ExitType.TIME_BASED,
        )
        score = a.calculate_compliance_score()
        # 0.6 * 0.4 + (1.0 - 0.8) * 0.3 + 0.2 = 0.24 + 0.06 + 0.2 = 0.50
        assert abs(score - 0.50) < 0.01
        assert a.compliance_level == ComplianceLevel.FAIR

    def test_deviation_capped_at_1(self):
        """Position size deviation > 1.0 is capped at 1.0."""
        a = TradeAnalysis(
            position_id=1,
            symbol="X",
            entry_date=datetime(2026, 1, 1),
            entry_price=10.0,
            entry_signal_matched=True,
            entry_signal_confidence=0.80,
            recommended_shares=50,
            position_size_deviation=2.0,  # 200% deviation → capped at 1.0
            exit_type=ExitType.PROFIT_TARGET,
        )
        score = a.calculate_compliance_score()
        # 0.8 * 0.4 + (1.0 - 1.0) * 0.3 + 0.3 = 0.32 + 0 + 0.3 = 0.62
        assert abs(score - 0.62) < 0.01

    def test_recommended_shares_zero(self):
        """recommended_shares=0 → neutral sizing (0.15)."""
        a = TradeAnalysis(
            position_id=1,
            symbol="X",
            entry_date=datetime(2026, 1, 1),
            entry_price=10.0,
            entry_signal_matched=True,
            entry_signal_confidence=0.70,
            recommended_shares=0,
            exit_type=ExitType.PROFIT_TARGET,
        )
        score = a.calculate_compliance_score()
        # 0.7 * 0.4 + 0.15 + 0.3 = 0.28 + 0.15 + 0.3 = 0.73
        assert abs(score - 0.73) < 0.01


# ---------------------------------------------------------------------------
# TradeAnalysis.to_dict — edge cases
# ---------------------------------------------------------------------------


class TestTradeAnalysisToDict:
    def test_none_exit_date(self):
        a = TradeAnalysis(
            position_id=1,
            symbol="X",
            entry_date=datetime(2026, 1, 1),
            entry_price=10.0,
        )
        d = a.to_dict()
        assert d["exit_date"] is None
        assert d["exit_price"] is None

    def test_with_exit_date(self):
        a = TradeAnalysis(
            position_id=1,
            symbol="X",
            entry_date=datetime(2026, 1, 1),
            entry_price=10.0,
            exit_date=datetime(2026, 1, 15),
            exit_price=12.0,
        )
        d = a.to_dict()
        assert d["exit_date"] == "2026-01-15T00:00:00"

    def test_risk_metrics_in_dict(self):
        a = TradeAnalysis(
            position_id=1,
            symbol="X",
            entry_date=datetime(2026, 1, 1),
            entry_price=10.0,
            risk_metrics={"atr": 2.5, "rsi": 55.0},
        )
        d = a.to_dict()
        assert d["risk_metrics"] == {"atr": 2.5, "rsi": 55.0}

    def test_notes_and_warnings_in_dict(self):
        a = TradeAnalysis(
            position_id=1,
            symbol="X",
            entry_date=datetime(2026, 1, 1),
            entry_price=10.0,
            notes=["Note 1", "Note 2"],
            warnings=["Warn 1"],
        )
        d = a.to_dict()
        assert d["notes"] == ["Note 1", "Note 2"]
        assert d["warnings"] == ["Warn 1"]


# ---------------------------------------------------------------------------
# ComplianceLevel.from_score — boundary values
# ---------------------------------------------------------------------------


class TestComplianceLevelBoundaries:
    def test_score_0(self):
        assert ComplianceLevel.from_score(0.0) == ComplianceLevel.NON_COMPLIANT

    def test_score_0_29(self):
        assert ComplianceLevel.from_score(0.29) == ComplianceLevel.NON_COMPLIANT

    def test_score_0_30(self):
        assert ComplianceLevel.from_score(0.30) == ComplianceLevel.POOR

    def test_score_0_49(self):
        assert ComplianceLevel.from_score(0.49) == ComplianceLevel.POOR

    def test_score_0_50(self):
        assert ComplianceLevel.from_score(0.50) == ComplianceLevel.FAIR

    def test_score_0_69(self):
        assert ComplianceLevel.from_score(0.69) == ComplianceLevel.FAIR

    def test_score_0_70(self):
        assert ComplianceLevel.from_score(0.70) == ComplianceLevel.GOOD

    def test_score_0_89(self):
        assert ComplianceLevel.from_score(0.89) == ComplianceLevel.GOOD

    def test_score_0_90(self):
        assert ComplianceLevel.from_score(0.90) == ComplianceLevel.EXCELLENT

    def test_score_1_0(self):
        assert ComplianceLevel.from_score(1.0) == ComplianceLevel.EXCELLENT

    def test_negative_score(self):
        assert ComplianceLevel.from_score(-0.5) == ComplianceLevel.NON_COMPLIANT


# ---------------------------------------------------------------------------
# ExitType enum — all values
# ---------------------------------------------------------------------------


class TestExitTypeComplete:
    def test_all_values(self):
        expected = {
            "profit_target", "stop_loss", "trailing_stop",
            "time_based", "manual", "unknown",
        }
        actual = {e.value for e in ExitType}
        assert actual == expected

    def test_count(self):
        assert len(ExitType) == 6


# ---------------------------------------------------------------------------
# DeviationReport.to_dict — with signal_outcome
# ---------------------------------------------------------------------------


class TestDeviationReportToDict:
    def test_with_signal_outcome(self):
        signal_report = SignalOutcomeReport(
            total_trades_analyzed=5,
            key_insights=["Insight 1"],
        )
        report = DeviationReport(
            signal_outcome=signal_report,
        )
        d = report.to_dict()
        assert "signal_outcome" in d
        assert d["signal_outcome"]["total_trades_analyzed"] == 5

    def test_without_signal_outcome(self):
        report = DeviationReport()
        d = report.to_dict()
        assert "signal_outcome" not in d

    def test_period_dates(self):
        report = DeviationReport(
            period_start=datetime(2026, 1, 1),
            period_end=datetime(2026, 1, 31),
        )
        d = report.to_dict()
        assert d["period_start"] == "2026-01-01T00:00:00"
        assert d["period_end"] == "2026-01-31T00:00:00"

    def test_none_period_dates(self):
        report = DeviationReport()
        d = report.to_dict()
        assert d["period_start"] is None
        assert d["period_end"] is None


# ---------------------------------------------------------------------------
# ConditionBucketMetrics.to_dict
# ---------------------------------------------------------------------------


class TestConditionBucketMetricsToDict:
    def test_basic(self):
        m = ConditionBucketMetrics(
            condition="regime:BULL",
            trade_count=10,
            win_rate=0.7,
            avg_return_pct=5.5,
        )
        d = m.to_dict()
        assert d["condition"] == "regime:BULL"
        assert d["trade_count"] == 10
        assert d["win_rate"] == 0.7
        assert d["avg_return_pct"] == 5.5

    def test_rounding(self):
        m = ConditionBucketMetrics(
            condition="rsi:oversold",
            trade_count=3,
            win_rate=0.66666,
            avg_return_pct=3.14159,
        )
        d = m.to_dict()
        assert d["win_rate"] == 0.6667
        assert d["avg_return_pct"] == 3.14


# ---------------------------------------------------------------------------
# RuleEvaluation.to_dict — indicators_used not in output
# ---------------------------------------------------------------------------


class TestRuleEvaluationToDict:
    def test_indicators_not_in_output(self):
        """to_dict does NOT include indicators_used (by design)."""
        r = RuleEvaluation(
            rule_name="test",
            triggered=True,
            indicators_used={"close": 150.0},
        )
        d = r.to_dict()
        assert "indicators_used" not in d

    def test_none_reasoning(self):
        r = RuleEvaluation(rule_name="test", triggered=False)
        d = r.to_dict()
        assert d["reasoning"] is None
        assert d["signal_type"] is None
        assert d["confidence"] == 0.0


# ---------------------------------------------------------------------------
# Config — ReportingSettings defaults
# ---------------------------------------------------------------------------


class TestReportingSettingsDefaults:
    def test_analysis_defaults(self):
        s = ReportingSettings()
        assert s.analysis.profit_target_threshold == 0.05
        assert s.analysis.stop_loss_threshold == -0.03
        assert s.analysis.position_size_tolerance == 0.20
        assert s.analysis.min_signal_confidence == 0.50
        assert s.analysis.indicator_lookback_minutes == 60

    def test_database_defaults(self):
        s = ReportingSettings()
        assert s.database.journal_host == "localhost"
        assert s.database.journal_port == 5432
        assert s.database.timescale_host == "localhost"

    def test_redis_defaults(self):
        s = ReportingSettings()
        assert s.redis_host == "localhost"
        assert s.redis_port == 6379
        assert s.redis_db == 1

    def test_use_redis_rules_default(self):
        s = ReportingSettings()
        assert s.use_redis_rules is True

    def test_log_level_default(self):
        s = ReportingSettings()
        assert s.log_level == "INFO"


class TestLoadSettings:
    def test_no_config_path(self):
        """Without config file → returns defaults."""
        settings = load_settings("/nonexistent/path.yaml")
        # from_yaml returns defaults if file doesn't exist
        assert settings.analysis.profit_target_threshold == 0.05

    def test_none_config_path_no_files(self, tmp_path, monkeypatch):
        """When no config files exist at search paths, returns defaults."""
        monkeypatch.chdir(tmp_path)  # no config/ subdir here
        settings = load_settings(None)
        assert isinstance(settings, ReportingSettings)


# ---------------------------------------------------------------------------
# SignalOutcomeReport.to_dict — completeness
# ---------------------------------------------------------------------------


class TestSignalOutcomeReportToDict:
    def test_with_period(self):
        r = SignalOutcomeReport(
            period_start=datetime(2026, 1, 1),
            period_end=datetime(2026, 1, 31),
            total_trades_analyzed=10,
        )
        d = r.to_dict()
        assert d["period_start"] == "2026-01-01T00:00:00"
        assert d["period_end"] == "2026-01-31T00:00:00"

    def test_none_period(self):
        r = SignalOutcomeReport()
        d = r.to_dict()
        assert d["period_start"] is None
        assert d["period_end"] is None

    def test_all_metrics_present(self):
        r = SignalOutcomeReport(
            signal_type_metrics=[SignalTypeMetrics(signal_type="BUY")],
            rule_metrics=[RuleMetrics(rule_name="test")],
            confidence_buckets=[ConfidenceBucket(range_label="0-25%")],
            condition_metrics=[ConditionBucketMetrics(condition="test")],
        )
        d = r.to_dict()
        assert len(d["signal_type_metrics"]) == 1
        assert len(d["rule_metrics"]) == 1
        assert len(d["confidence_buckets"]) == 1
        assert len(d["condition_metrics"]) == 1
