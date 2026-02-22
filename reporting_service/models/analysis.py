"""
Analysis result models.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from .signal_analysis import SignalOutcomeReport


class ExitType(Enum):
    """How the position was exited."""

    PROFIT_TARGET = "profit_target"
    STOP_LOSS = "stop_loss"
    TRAILING_STOP = "trailing_stop"
    TIME_BASED = "time_based"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class ComplianceLevel(Enum):
    """Rule compliance classification."""

    EXCELLENT = "excellent"  # 90-100%
    GOOD = "good"  # 70-89%
    FAIR = "fair"  # 50-69%
    POOR = "poor"  # 30-49%
    NON_COMPLIANT = "non_compliant"  # 0-29%

    @classmethod
    def from_score(cls, score: float) -> "ComplianceLevel":
        """Determine compliance level from score."""
        if score >= 0.90:
            return cls.EXCELLENT
        elif score >= 0.70:
            return cls.GOOD
        elif score >= 0.50:
            return cls.FAIR
        elif score >= 0.30:
            return cls.POOR
        else:
            return cls.NON_COMPLIANT


@dataclass
class RuleEvaluation:
    """Result of evaluating a single rule at a point in time."""

    rule_name: str
    triggered: bool
    signal_type: Optional[str] = None  # BUY, SELL, WATCH
    confidence: float = 0.0
    reasoning: Optional[str] = None
    indicators_used: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "rule_name": self.rule_name,
            "triggered": self.triggered,
            "signal_type": self.signal_type,
            "confidence": round(self.confidence, 4),
            "reasoning": self.reasoning,
        }


@dataclass
class TradeAnalysis:
    """Complete analysis of a single trade/position."""

    position_id: int
    symbol: str

    # Entry analysis
    entry_date: datetime
    entry_price: float
    entry_rules_evaluated: List[RuleEvaluation] = field(default_factory=list)
    entry_signal_matched: bool = False
    entry_signal_confidence: float = 0.0
    entry_signal_type: Optional[str] = None

    # Position sizing analysis
    recommended_shares: Optional[int] = None
    actual_shares: float = 0.0
    position_size_deviation: float = 0.0  # % deviation from recommended

    # Exit analysis (for closed positions)
    exit_date: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_type: ExitType = ExitType.UNKNOWN
    exit_rules_evaluated: List[RuleEvaluation] = field(default_factory=list)

    # Risk metrics at entry
    risk_metrics: Dict[str, float] = field(default_factory=dict)

    # Overall compliance
    rule_compliance_score: float = 0.0
    compliance_level: ComplianceLevel = ComplianceLevel.NON_COMPLIANT

    # Notes and warnings
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    analyzed_at: datetime = field(default_factory=datetime.utcnow)

    def calculate_compliance_score(self) -> float:
        """Calculate overall rule compliance score."""
        scores = []

        # Entry signal match (40% weight)
        if self.entry_signal_matched:
            scores.append(self.entry_signal_confidence * 0.4)
        else:
            scores.append(0.0)

        # Position sizing (30% weight)
        if self.recommended_shares and self.recommended_shares > 0:
            size_accuracy = 1.0 - min(abs(self.position_size_deviation), 1.0)
            scores.append(size_accuracy * 0.3)
        else:
            scores.append(0.15)  # Neutral if no recommendation

        # Exit discipline (30% weight)
        if self.exit_type in (ExitType.PROFIT_TARGET, ExitType.STOP_LOSS):
            scores.append(0.3)  # Full points for disciplined exit
        elif self.exit_type == ExitType.TRAILING_STOP:
            scores.append(0.25)
        elif self.exit_type == ExitType.TIME_BASED:
            scores.append(0.2)
        else:
            scores.append(0.1)  # Manual/unknown exits

        self.rule_compliance_score = sum(scores)
        self.compliance_level = ComplianceLevel.from_score(self.rule_compliance_score)
        return self.rule_compliance_score

    def to_dict(self) -> Dict:
        """Convert to dictionary for storage/serialization."""
        return {
            "position_id": self.position_id,
            "symbol": self.symbol,
            "entry_date": self.entry_date.isoformat(),
            "entry_price": self.entry_price,
            "entry_signal_matched": self.entry_signal_matched,
            "entry_signal_confidence": round(self.entry_signal_confidence, 4),
            "entry_signal_type": self.entry_signal_type,
            "entry_rules": [r.to_dict() for r in self.entry_rules_evaluated],
            "recommended_shares": self.recommended_shares,
            "actual_shares": self.actual_shares,
            "position_size_deviation": round(self.position_size_deviation, 4),
            "exit_date": self.exit_date.isoformat() if self.exit_date else None,
            "exit_price": self.exit_price,
            "exit_type": self.exit_type.value,
            "risk_metrics": self.risk_metrics,
            "rule_compliance_score": round(self.rule_compliance_score, 4),
            "compliance_level": self.compliance_level.value,
            "notes": self.notes,
            "warnings": self.warnings,
            "analyzed_at": self.analyzed_at.isoformat(),
        }


@dataclass
class ComplianceMetrics:
    """Aggregate compliance metrics across multiple trades."""

    total_positions: int = 0
    analyzed_positions: int = 0

    # Compliance distribution
    excellent_count: int = 0
    good_count: int = 0
    fair_count: int = 0
    poor_count: int = 0
    non_compliant_count: int = 0

    # Averages
    avg_compliance_score: float = 0.0
    avg_entry_confidence: float = 0.0
    avg_position_size_deviation: float = 0.0

    # Entry signal stats
    entries_with_buy_signal: int = 0
    entries_without_signal: int = 0

    # Exit type distribution
    profit_target_exits: int = 0
    stop_loss_exits: int = 0
    manual_exits: int = 0
    other_exits: int = 0

    # Performance correlation
    compliant_win_rate: float = 0.0  # Win rate for compliant trades
    non_compliant_win_rate: float = 0.0  # Win rate for non-compliant trades

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "total_positions": self.total_positions,
            "analyzed_positions": self.analyzed_positions,
            "compliance_distribution": {
                "excellent": self.excellent_count,
                "good": self.good_count,
                "fair": self.fair_count,
                "poor": self.poor_count,
                "non_compliant": self.non_compliant_count,
            },
            "avg_compliance_score": round(self.avg_compliance_score, 4),
            "avg_entry_confidence": round(self.avg_entry_confidence, 4),
            "avg_position_size_deviation": round(self.avg_position_size_deviation, 4),
            "entry_signal_stats": {
                "with_signal": self.entries_with_buy_signal,
                "without_signal": self.entries_without_signal,
            },
            "exit_distribution": {
                "profit_target": self.profit_target_exits,
                "stop_loss": self.stop_loss_exits,
                "manual": self.manual_exits,
                "other": self.other_exits,
            },
            "win_rate_by_compliance": {
                "compliant": round(self.compliant_win_rate, 4),
                "non_compliant": round(self.non_compliant_win_rate, 4),
            },
        }


@dataclass
class DeviationReport:
    """Report on deviations from trading rules."""

    generated_at: datetime = field(default_factory=datetime.utcnow)
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None

    # Summary metrics
    metrics: ComplianceMetrics = field(default_factory=ComplianceMetrics)

    # Individual analyses
    analyses: List[TradeAnalysis] = field(default_factory=list)

    # Top deviations
    worst_deviations: List[TradeAnalysis] = field(default_factory=list)
    best_compliant: List[TradeAnalysis] = field(default_factory=list)

    # Insights
    common_issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    # Signal-to-outcome analysis (optional, populated when available)
    signal_outcome: Optional["SignalOutcomeReport"] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        result = {
            "generated_at": self.generated_at.isoformat(),
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "metrics": self.metrics.to_dict(),
            "analyses_count": len(self.analyses),
            "worst_deviations": [a.to_dict() for a in self.worst_deviations[:5]],
            "best_compliant": [a.to_dict() for a in self.best_compliant[:5]],
            "common_issues": self.common_issues,
            "recommendations": self.recommendations,
        }
        if self.signal_outcome:
            result["signal_outcome"] = self.signal_outcome.to_dict()
        return result
