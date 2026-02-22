"""
Report generator.

Generates formatted reports from analysis results.
"""

import logging
from datetime import datetime
from typing import Optional

from ..analyzer import TradeAnalyzer
from ..config import ReportingSettings
from ..models.analysis import DeviationReport

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generates formatted reports from analysis data."""

    def __init__(
        self,
        settings: ReportingSettings,
        analyzer: TradeAnalyzer,
    ):
        self.settings = settings
        self.analyzer = analyzer

    def to_markdown(self, report: DeviationReport) -> str:
        """
        Convert a deviation report to markdown format.

        Args:
            report: The deviation report

        Returns:
            Markdown formatted string
        """
        lines = []
        m = report.metrics

        # Header
        lines.append("# Trade Deviation Report")
        lines.append("")
        lines.append(f"Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M:%S')}")
        if report.period_start:
            lines.append(f"Period: {report.period_start.strftime('%Y-%m-%d')} to {report.period_end.strftime('%Y-%m-%d') if report.period_end else 'now'}")
        lines.append("")

        # Summary
        lines.append("## Summary")
        lines.append("")
        lines.append(f"- **Positions Analyzed:** {m.analyzed_positions}")
        lines.append(f"- **Average Compliance Score:** {m.avg_compliance_score:.1%}")
        lines.append(f"- **Average Entry Confidence:** {m.avg_entry_confidence:.1%}")
        lines.append(f"- **Average Size Deviation:** {m.avg_position_size_deviation:.1%}")
        lines.append("")

        # Compliance Distribution
        lines.append("## Compliance Distribution")
        lines.append("")
        lines.append("| Level | Count | Percentage |")
        lines.append("|-------|-------|------------|")
        total = m.analyzed_positions or 1
        lines.append(f"| Excellent (90%+) | {m.excellent_count} | {m.excellent_count/total:.1%} |")
        lines.append(f"| Good (70-89%) | {m.good_count} | {m.good_count/total:.1%} |")
        lines.append(f"| Fair (50-69%) | {m.fair_count} | {m.fair_count/total:.1%} |")
        lines.append(f"| Poor (30-49%) | {m.poor_count} | {m.poor_count/total:.1%} |")
        lines.append(f"| Non-Compliant (<30%) | {m.non_compliant_count} | {m.non_compliant_count/total:.1%} |")
        lines.append("")

        # Entry Signals
        lines.append("## Entry Signal Analysis")
        lines.append("")
        lines.append(f"- Entries with valid BUY signal: **{m.entries_with_buy_signal}** ({m.entries_with_buy_signal/total:.1%})")
        lines.append(f"- Entries without signal: **{m.entries_without_signal}** ({m.entries_without_signal/total:.1%})")
        lines.append("")

        # Exit Distribution
        lines.append("## Exit Type Distribution")
        lines.append("")
        lines.append("| Exit Type | Count | Percentage |")
        lines.append("|-----------|-------|------------|")
        lines.append(f"| Profit Target | {m.profit_target_exits} | {m.profit_target_exits/total:.1%} |")
        lines.append(f"| Stop Loss | {m.stop_loss_exits} | {m.stop_loss_exits/total:.1%} |")
        lines.append(f"| Manual | {m.manual_exits} | {m.manual_exits/total:.1%} |")
        lines.append(f"| Other | {m.other_exits} | {m.other_exits/total:.1%} |")
        lines.append("")

        # Win Rate Correlation
        lines.append("## Compliance vs Performance")
        lines.append("")
        lines.append(f"- **Compliant trades win rate:** {m.compliant_win_rate:.1%}")
        lines.append(f"- **Non-compliant trades win rate:** {m.non_compliant_win_rate:.1%}")
        if m.compliant_win_rate > m.non_compliant_win_rate:
            diff = m.compliant_win_rate - m.non_compliant_win_rate
            lines.append(f"- *Following rules improves win rate by {diff:.1%}*")
        lines.append("")

        # Common Issues
        if report.common_issues:
            lines.append("## Common Issues")
            lines.append("")
            for issue in report.common_issues:
                lines.append(f"- {issue}")
            lines.append("")

        # Recommendations
        if report.recommendations:
            lines.append("## Recommendations")
            lines.append("")
            for rec in report.recommendations:
                lines.append(f"- {rec}")
            lines.append("")

        # Worst Deviations
        if report.worst_deviations:
            lines.append("## Worst Deviations")
            lines.append("")
            lines.append("| Symbol | Entry Date | Compliance | Issues |")
            lines.append("|--------|------------|------------|--------|")
            for a in report.worst_deviations[:5]:
                issues = "; ".join(a.warnings[:2]) if a.warnings else "-"
                lines.append(
                    f"| {a.symbol} | {a.entry_date.strftime('%Y-%m-%d')} | "
                    f"{a.rule_compliance_score:.1%} | {issues} |"
                )
            lines.append("")

        # Best Compliant
        if report.best_compliant:
            lines.append("## Best Compliant Trades")
            lines.append("")
            lines.append("| Symbol | Entry Date | Compliance | Exit Type |")
            lines.append("|--------|------------|------------|-----------|")
            for a in report.best_compliant[:5]:
                lines.append(
                    f"| {a.symbol} | {a.entry_date.strftime('%Y-%m-%d')} | "
                    f"{a.rule_compliance_score:.1%} | {a.exit_type.value} |"
                )
            lines.append("")

        # Signal Effectiveness Analysis
        if report.signal_outcome and report.signal_outcome.total_trades_analyzed > 0:
            so = report.signal_outcome
            lines.append("## Signal Effectiveness Analysis")
            lines.append("")

            # Signal type performance
            if so.signal_type_metrics:
                lines.append("### Performance by Signal Type")
                lines.append("")
                lines.append("| Signal | Trades | Win Rate | Avg Return | Avg Hold |")
                lines.append("|--------|--------|----------|------------|----------|")
                for sm in so.signal_type_metrics:
                    lines.append(
                        f"| {sm.signal_type} | {sm.trade_count} | "
                        f"{sm.win_rate:.1%} | {sm.avg_return_pct:+.1f}% | "
                        f"{sm.avg_holding_days:.0f}d |"
                    )
                lines.append("")

            # Rule performance
            if so.rule_metrics:
                lines.append("### Performance by Rule")
                lines.append("")
                lines.append("| Rule | Triggers | Win Rate | Avg Return | Avg Conf |")
                lines.append("|------|----------|----------|------------|----------|")
                for rm in so.rule_metrics:
                    lines.append(
                        f"| {rm.rule_name} | {rm.trigger_count} | "
                        f"{rm.win_rate_when_triggered:.1%} | "
                        f"{rm.avg_return_when_triggered:+.1f}% | "
                        f"{rm.avg_confidence:.1%} |"
                    )
                lines.append("")

            # Confidence buckets
            if so.confidence_buckets:
                non_empty = [b for b in so.confidence_buckets if b.trade_count > 0]
                if non_empty:
                    lines.append("### Performance by Confidence Level")
                    lines.append("")
                    lines.append("| Confidence | Trades | Win Rate | Avg Return |")
                    lines.append("|------------|--------|----------|------------|")
                    for cb in so.confidence_buckets:
                        if cb.trade_count > 0:
                            lines.append(
                                f"| {cb.range_label} | {cb.trade_count} | "
                                f"{cb.win_rate:.1%} | {cb.avg_return_pct:+.1f}% |"
                            )
                    lines.append("")

            # Condition metrics
            if so.condition_metrics:
                lines.append("### Performance by Market Condition")
                lines.append("")
                lines.append("| Condition | Trades | Win Rate | Avg Return |")
                lines.append("|-----------|--------|----------|------------|")
                for cm in so.condition_metrics:
                    lines.append(
                        f"| {cm.condition} | {cm.trade_count} | "
                        f"{cm.win_rate:.1%} | {cm.avg_return_pct:+.1f}% |"
                    )
                lines.append("")

            # Key insights
            if so.key_insights:
                lines.append("### Key Insights")
                lines.append("")
                for insight in so.key_insights:
                    lines.append(f"- {insight}")
                lines.append("")

        # Footer
        lines.append("---")
        lines.append("*Report generated by reporting-service*")

        return "\n".join(lines)

    def to_summary(self, report: DeviationReport) -> str:
        """
        Generate a brief text summary.

        Args:
            report: The deviation report

        Returns:
            Brief summary string
        """
        m = report.metrics

        return (
            f"Analyzed {m.analyzed_positions} positions. "
            f"Average compliance: {m.avg_compliance_score:.0%}. "
            f"{m.entries_with_buy_signal} had valid entry signals. "
            f"Compliant win rate: {m.compliant_win_rate:.0%} vs "
            f"non-compliant: {m.non_compliant_win_rate:.0%}."
        )
