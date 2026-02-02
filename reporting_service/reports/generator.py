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
