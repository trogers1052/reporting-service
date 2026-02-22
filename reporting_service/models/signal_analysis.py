"""
Signal-to-outcome analysis models.

Tracks how different signal types, rules, confidence levels,
and market conditions correlate with trade outcomes.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class SignalTypeMetrics:
    """Performance metrics for a specific signal type (BUY, SELL, NONE)."""

    signal_type: str
    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    avg_return_pct: float = 0.0
    avg_holding_days: float = 0.0
    exit_distribution: Dict[str, int] = field(default_factory=dict)
    best_trade: Optional[Dict] = None
    worst_trade: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {
            "signal_type": self.signal_type,
            "trade_count": self.trade_count,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "win_rate": round(self.win_rate, 4),
            "avg_return_pct": round(self.avg_return_pct, 2),
            "avg_holding_days": round(self.avg_holding_days, 1),
            "exit_distribution": self.exit_distribution,
            "best_trade": self.best_trade,
            "worst_trade": self.worst_trade,
        }


@dataclass
class RuleMetrics:
    """Performance metrics for a specific decision-engine rule."""

    rule_name: str
    trigger_count: int = 0
    win_rate_when_triggered: float = 0.0
    avg_return_when_triggered: float = 0.0
    avg_confidence: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "rule_name": self.rule_name,
            "trigger_count": self.trigger_count,
            "win_rate_when_triggered": round(self.win_rate_when_triggered, 4),
            "avg_return_when_triggered": round(self.avg_return_when_triggered, 2),
            "avg_confidence": round(self.avg_confidence, 4),
        }


@dataclass
class ConfidenceBucket:
    """Performance metrics for a confidence range."""

    range_label: str
    range_low: float = 0.0
    range_high: float = 1.0
    trade_count: int = 0
    win_rate: float = 0.0
    avg_return_pct: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "range": self.range_label,
            "trade_count": self.trade_count,
            "win_rate": round(self.win_rate, 4),
            "avg_return_pct": round(self.avg_return_pct, 2),
        }


@dataclass
class ConditionBucketMetrics:
    """Performance metrics for a market condition bucket."""

    condition: str
    trade_count: int = 0
    win_rate: float = 0.0
    avg_return_pct: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "condition": self.condition,
            "trade_count": self.trade_count,
            "win_rate": round(self.win_rate, 4),
            "avg_return_pct": round(self.avg_return_pct, 2),
        }


@dataclass
class SignalOutcomeReport:
    """Complete signal-to-outcome analysis report."""

    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    total_trades_analyzed: int = 0

    signal_type_metrics: List[SignalTypeMetrics] = field(default_factory=list)
    rule_metrics: List[RuleMetrics] = field(default_factory=list)
    confidence_buckets: List[ConfidenceBucket] = field(default_factory=list)
    condition_metrics: List[ConditionBucketMetrics] = field(default_factory=list)
    key_insights: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "period_start": (
                self.period_start.isoformat() if self.period_start else None
            ),
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "total_trades_analyzed": self.total_trades_analyzed,
            "signal_type_metrics": [m.to_dict() for m in self.signal_type_metrics],
            "rule_metrics": [m.to_dict() for m in self.rule_metrics],
            "confidence_buckets": [b.to_dict() for b in self.confidence_buckets],
            "condition_metrics": [c.to_dict() for c in self.condition_metrics],
            "key_insights": self.key_insights,
        }
