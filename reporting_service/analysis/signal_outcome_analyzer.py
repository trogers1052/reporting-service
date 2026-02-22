"""
Signal-to-outcome analyzer.

Analyzes correlations between entry signals, rules, confidence levels,
market conditions, and trade outcomes. Answers: "Which signals actually
make money?"
"""

import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from ..models.analysis import TradeAnalysis
from ..models.position import Position
from ..models.signal_analysis import (
    ConditionBucketMetrics,
    ConfidenceBucket,
    RuleMetrics,
    SignalOutcomeReport,
    SignalTypeMetrics,
)

logger = logging.getLogger(__name__)

# Confidence bucket boundaries
CONFIDENCE_BUCKETS = [
    ("0-25%", 0.0, 0.25),
    ("25-50%", 0.25, 0.50),
    ("50-75%", 0.50, 0.75),
    ("75-100%", 0.75, 1.01),
]

# RSI bucket boundaries for condition analysis
RSI_BUCKETS = [
    ("rsi:oversold", 0, 30),
    ("rsi:neutral", 30, 70),
    ("rsi:overbought", 70, 101),
]


class SignalOutcomeAnalyzer:
    """
    Analyzes how signals correlate with trade outcomes.

    Takes analyzed TradeAnalysis objects (with entry rules, exit types,
    compliance scores) and the corresponding Position objects (with
    realized P&L), and produces a SignalOutcomeReport.
    """

    def analyze(
        self,
        analyses: List[TradeAnalysis],
        positions_by_id: Dict[int, Position],
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
    ) -> SignalOutcomeReport:
        """
        Run full signal-to-outcome analysis.

        Args:
            analyses: List of TradeAnalysis objects (with rules, exit types, etc.)
            positions_by_id: Map of position_id -> Position (with realized P&L)
            period_start: Optional reporting period start
            period_end: Optional reporting period end

        Returns:
            SignalOutcomeReport with all metrics and insights
        """
        report = SignalOutcomeReport(
            period_start=period_start,
            period_end=period_end,
            total_trades_analyzed=len(analyses),
        )

        if not analyses:
            report.key_insights = [
                "Insufficient data for meaningful insights - "
                "more closed trades needed"
            ]
            return report

        # Build paired data: (analysis, position) tuples
        pairs = self._build_pairs(analyses, positions_by_id)

        report.signal_type_metrics = self._analyze_by_signal_type(pairs)
        report.rule_metrics = self._analyze_by_rule(pairs)
        report.confidence_buckets = self._analyze_by_confidence(pairs)
        report.condition_metrics = self._analyze_by_condition(pairs)
        report.key_insights = self._generate_insights(report)

        return report

    def _build_pairs(
        self,
        analyses: List[TradeAnalysis],
        positions_by_id: Dict[int, Position],
    ) -> List[Tuple[TradeAnalysis, Position]]:
        """Pair analyses with their positions, filtering out missing data."""
        pairs = []
        for analysis in analyses:
            position = positions_by_id.get(analysis.position_id)
            if position and position.realized_pl_pct is not None:
                pairs.append((analysis, position))
        return pairs

    def _analyze_by_signal_type(
        self,
        pairs: List[Tuple[TradeAnalysis, Position]],
    ) -> List[SignalTypeMetrics]:
        """Break down performance by signal type (BUY, SELL, NONE)."""
        groups: Dict[str, List[Tuple[TradeAnalysis, Position]]] = defaultdict(list)

        for analysis, position in pairs:
            signal = analysis.entry_signal_type or "NONE"
            groups[signal].append((analysis, position))

        metrics = []
        for signal_type in sorted(groups.keys()):
            group = groups[signal_type]
            m = self._compute_signal_type_metrics(signal_type, group)
            metrics.append(m)

        return metrics

    def _compute_signal_type_metrics(
        self,
        signal_type: str,
        group: List[Tuple[TradeAnalysis, Position]],
    ) -> SignalTypeMetrics:
        """Compute metrics for a single signal type group."""
        m = SignalTypeMetrics(signal_type=signal_type)
        m.trade_count = len(group)

        returns = []
        holding_days = []
        exit_dist: Dict[str, int] = defaultdict(int)
        best = None
        worst = None

        for analysis, position in group:
            ret = position.realized_pl_pct
            returns.append(ret)

            if position.holding_days is not None:
                holding_days.append(position.holding_days)

            exit_dist[analysis.exit_type.value] += 1

            if position.is_winner:
                m.win_count += 1
            else:
                m.loss_count += 1

            trade_info = {
                "symbol": position.symbol,
                "return_pct": round(ret, 2),
                "date": position.entry_date.strftime("%Y-%m-%d"),
            }
            if best is None or ret > best["return_pct"]:
                best = trade_info
            if worst is None or ret < worst["return_pct"]:
                worst = trade_info

        m.win_rate = m.win_count / m.trade_count if m.trade_count > 0 else 0.0
        m.avg_return_pct = sum(returns) / len(returns) if returns else 0.0
        m.avg_holding_days = (
            sum(holding_days) / len(holding_days) if holding_days else 0.0
        )
        m.exit_distribution = dict(exit_dist)
        m.best_trade = best
        m.worst_trade = worst

        return m

    def _analyze_by_rule(
        self,
        pairs: List[Tuple[TradeAnalysis, Position]],
    ) -> List[RuleMetrics]:
        """Break down performance by individual rule."""
        rule_data: Dict[str, Dict] = defaultdict(
            lambda: {"returns": [], "wins": 0, "total": 0, "confidences": []}
        )

        for analysis, position in pairs:
            for rule_eval in analysis.entry_rules_evaluated:
                if rule_eval.triggered:
                    data = rule_data[rule_eval.rule_name]
                    data["returns"].append(position.realized_pl_pct)
                    data["total"] += 1
                    data["confidences"].append(rule_eval.confidence)
                    if position.is_winner:
                        data["wins"] += 1

        metrics = []
        for rule_name in sorted(rule_data.keys()):
            data = rule_data[rule_name]
            if data["total"] == 0:
                continue

            m = RuleMetrics(
                rule_name=rule_name,
                trigger_count=data["total"],
                win_rate_when_triggered=data["wins"] / data["total"],
                avg_return_when_triggered=(
                    sum(data["returns"]) / len(data["returns"])
                    if data["returns"]
                    else 0.0
                ),
                avg_confidence=(
                    sum(data["confidences"]) / len(data["confidences"])
                    if data["confidences"]
                    else 0.0
                ),
            )
            metrics.append(m)

        return metrics

    def _analyze_by_confidence(
        self,
        pairs: List[Tuple[TradeAnalysis, Position]],
    ) -> List[ConfidenceBucket]:
        """Break down performance by confidence bucket."""
        buckets: Dict[str, Dict] = {}
        for label, low, high in CONFIDENCE_BUCKETS:
            buckets[label] = {"low": low, "high": high, "returns": [], "wins": 0, "total": 0}

        for analysis, position in pairs:
            conf = analysis.entry_signal_confidence
            for label, low, high in CONFIDENCE_BUCKETS:
                if low <= conf < high:
                    buckets[label]["returns"].append(position.realized_pl_pct)
                    buckets[label]["total"] += 1
                    if position.is_winner:
                        buckets[label]["wins"] += 1
                    break

        result = []
        for label, low, high in CONFIDENCE_BUCKETS:
            data = buckets[label]
            b = ConfidenceBucket(
                range_label=label,
                range_low=low,
                range_high=high,
                trade_count=data["total"],
                win_rate=data["wins"] / data["total"] if data["total"] > 0 else 0.0,
                avg_return_pct=(
                    sum(data["returns"]) / len(data["returns"])
                    if data["returns"]
                    else 0.0
                ),
            )
            result.append(b)

        return result

    def _analyze_by_condition(
        self,
        pairs: List[Tuple[TradeAnalysis, Position]],
    ) -> List[ConditionBucketMetrics]:
        """Break down performance by market conditions at entry."""
        condition_data: Dict[str, Dict] = defaultdict(
            lambda: {"returns": [], "wins": 0, "total": 0}
        )

        for analysis, position in pairs:
            risk_metrics = analysis.risk_metrics or {}

            # Also check position.risk_metrics_at_entry for richer data
            entry_metrics = {}
            if position.risk_metrics_at_entry:
                if isinstance(position.risk_metrics_at_entry, str):
                    try:
                        entry_metrics = json.loads(position.risk_metrics_at_entry)
                    except (json.JSONDecodeError, TypeError):
                        pass
                elif isinstance(position.risk_metrics_at_entry, dict):
                    entry_metrics = position.risk_metrics_at_entry

            # Regime bucket (from risk_metrics_at_entry if available)
            regime = entry_metrics.get("regime")
            if regime:
                cond = f"regime:{regime}"
                condition_data[cond]["returns"].append(position.realized_pl_pct)
                condition_data[cond]["total"] += 1
                if position.is_winner:
                    condition_data[cond]["wins"] += 1

            # RSI bucket (from analysis risk_metrics or entry_metrics)
            rsi = risk_metrics.get("rsi") or entry_metrics.get("rsi_14")
            if rsi is not None:
                for label, low, high in RSI_BUCKETS:
                    if low <= rsi < high:
                        condition_data[label]["returns"].append(
                            position.realized_pl_pct
                        )
                        condition_data[label]["total"] += 1
                        if position.is_winner:
                            condition_data[label]["wins"] += 1
                        break

        metrics = []
        for condition in sorted(condition_data.keys()):
            data = condition_data[condition]
            if data["total"] == 0:
                continue

            m = ConditionBucketMetrics(
                condition=condition,
                trade_count=data["total"],
                win_rate=data["wins"] / data["total"],
                avg_return_pct=(
                    sum(data["returns"]) / len(data["returns"])
                    if data["returns"]
                    else 0.0
                ),
            )
            metrics.append(m)

        return metrics

    def _generate_insights(self, report: SignalOutcomeReport) -> List[str]:
        """Generate key insights from the analysis."""
        insights = []

        # Signal type insights
        buy_metrics = None
        none_metrics = None
        for m in report.signal_type_metrics:
            if m.signal_type == "BUY":
                buy_metrics = m
            elif m.signal_type == "NONE":
                none_metrics = m

        if buy_metrics and none_metrics and buy_metrics.trade_count > 0 and none_metrics.trade_count > 0:
            if buy_metrics.win_rate > none_metrics.win_rate:
                diff = buy_metrics.win_rate - none_metrics.win_rate
                insights.append(
                    f"Trades with BUY signals win {buy_metrics.win_rate:.0%} vs "
                    f"{none_metrics.win_rate:.0%} without signals "
                    f"(+{diff:.0%} edge)"
                )
            elif none_metrics.win_rate > buy_metrics.win_rate:
                insights.append(
                    "Trades WITHOUT signals are outperforming signal-based entries - "
                    "review signal quality"
                )

        if buy_metrics and buy_metrics.trade_count > 0:
            insights.append(
                f"BUY signals: {buy_metrics.trade_count} trades, "
                f"{buy_metrics.avg_return_pct:+.1f}% avg return, "
                f"{buy_metrics.win_rate:.0%} win rate"
            )

        # Confidence insights
        high_conf = None
        low_conf = None
        for b in report.confidence_buckets:
            if b.range_label == "75-100%" and b.trade_count > 0:
                high_conf = b
            elif b.range_label == "0-25%" and b.trade_count > 0:
                low_conf = b

        if high_conf and low_conf:
            if high_conf.win_rate > low_conf.win_rate:
                insights.append(
                    f"High confidence (75-100%) wins {high_conf.win_rate:.0%} vs "
                    f"low confidence (0-25%) at {low_conf.win_rate:.0%} - "
                    f"confidence is predictive"
                )
            elif high_conf.win_rate <= low_conf.win_rate and high_conf.trade_count >= 3:
                insights.append(
                    "High confidence signals are NOT outperforming low confidence - "
                    "calibration may need adjustment"
                )

        # Rule insights - find best and worst performing rules
        if report.rule_metrics:
            sorted_rules = sorted(
                [r for r in report.rule_metrics if r.trigger_count >= 2],
                key=lambda r: r.win_rate_when_triggered,
                reverse=True,
            )
            if sorted_rules:
                best = sorted_rules[0]
                insights.append(
                    f"Best rule: {best.rule_name} "
                    f"({best.win_rate_when_triggered:.0%} win rate, "
                    f"{best.trigger_count} triggers)"
                )
                if len(sorted_rules) > 1:
                    worst = sorted_rules[-1]
                    if worst.win_rate_when_triggered < 0.5:
                        insights.append(
                            f"Worst rule: {worst.rule_name} "
                            f"({worst.win_rate_when_triggered:.0%} win rate) - "
                            f"consider disabling or tuning"
                        )

        # Condition insights
        for cm in report.condition_metrics:
            if cm.trade_count >= 2:
                if cm.condition.startswith("regime:") and cm.win_rate < 0.4:
                    insights.append(
                        f"Poor performance in {cm.condition}: "
                        f"{cm.win_rate:.0%} win rate ({cm.trade_count} trades) - "
                        f"tighten filters for this regime"
                    )

        if not insights:
            insights.append(
                "Insufficient data for meaningful insights - "
                "more closed trades needed"
            )

        return insights
