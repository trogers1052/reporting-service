"""Pytest configuration and shared fixtures."""

from datetime import datetime, timedelta

import pytest

from reporting_service.config import ReportingSettings
from reporting_service.models.analysis import ExitType, RuleEvaluation, TradeAnalysis
from reporting_service.models.position import Position, Trade


@pytest.fixture
def settings():
    """Create default test settings."""
    return ReportingSettings()


@pytest.fixture
def sample_position():
    """Create a sample closed position."""
    return Position(
        id=1,
        symbol="AAPL",
        entry_order_id="order-123",
        entry_price=150.0,
        quantity=100,
        entry_date=datetime(2024, 1, 15, 10, 30),
        status="closed",
        exit_order_id="order-456",
        exit_price=165.0,
        exit_date=datetime(2024, 2, 1, 14, 0),
        realized_pl=1500.0,
        realized_pl_pct=10.0,
        holding_days=17,
    )


@pytest.fixture
def losing_position():
    """Create a sample losing position."""
    return Position(
        id=2,
        symbol="GOOGL",
        entry_order_id="order-789",
        entry_price=140.0,
        quantity=50,
        entry_date=datetime(2024, 1, 20, 11, 0),
        status="closed",
        exit_order_id="order-012",
        exit_price=133.0,
        exit_date=datetime(2024, 1, 25, 15, 30),
        realized_pl=-350.0,
        realized_pl_pct=-5.0,
        holding_days=5,
    )


@pytest.fixture
def sample_trade():
    """Create a sample trade."""
    return Trade(
        id=1,
        order_id="order-123",
        symbol="AAPL",
        side="buy",
        quantity=100,
        price=150.0,
        total_amount=15000.0,
        fees=0.0,
        executed_at=datetime(2024, 1, 15, 10, 30),
        position_id=1,
    )


@pytest.fixture
def sample_indicators():
    """Create sample indicator values."""
    return {
        "close": 150.0,
        "open": 148.0,
        "high": 152.0,
        "low": 147.0,
        "volume": 1000000,
        "atr_14": 3.0,
        "rsi_14": 55.0,
        "sma_20": 148.0,
        "sma_50": 145.0,
        "sma_200": 140.0,
        "avg_volume_20": 900000,
    }


@pytest.fixture
def sample_analysis(sample_position):
    """Create a sample trade analysis."""
    return TradeAnalysis(
        position_id=sample_position.id,
        symbol=sample_position.symbol,
        entry_date=sample_position.entry_date,
        entry_price=sample_position.entry_price,
        actual_shares=sample_position.quantity,
        exit_date=sample_position.exit_date,
        exit_price=sample_position.exit_price,
        entry_signal_matched=True,
        entry_signal_type="BUY",
        entry_signal_confidence=0.75,
        recommended_shares=90,
        position_size_deviation=0.11,
        exit_type=ExitType.PROFIT_TARGET,
        entry_rules_evaluated=[
            RuleEvaluation(
                rule_name="trend_following",
                triggered=True,
                signal_type="BUY",
                confidence=0.7,
                reasoning="Price above SMA200",
            ),
            RuleEvaluation(
                rule_name="rsi_oversold",
                triggered=True,
                signal_type="BUY",
                confidence=0.8,
                reasoning="RSI recovering from oversold",
            ),
        ],
        risk_metrics={"atr": 3.0, "rsi": 55.0},
    )


@pytest.fixture
def bearish_indicators():
    """Create indicators for a bearish scenario."""
    return {
        "close": 130.0,
        "sma_200": 145.0,  # Price below SMA200
        "rsi_14": 35.0,
        "atr_14": 4.0,
        "volume": 500000,
        "avg_volume_20": 800000,
    }
