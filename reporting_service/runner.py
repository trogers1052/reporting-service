"""
Reporting service runner.

Main entry point for running the reporting service.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .analyzer import TradeAnalyzer
from .config import load_settings
from .reports.generator import ReportGenerator

logger = logging.getLogger(__name__)


class ReportingRunner:
    """
    Main runner for the reporting service.

    Supports multiple modes:
    - analyze: Analyze unanalyzed positions and update database
    - report: Generate deviation reports
    - stats: Show analysis statistics
    """

    def __init__(self, config_path: Optional[str] = None):
        self.settings = load_settings(config_path)
        self.analyzer = TradeAnalyzer(self.settings)
        self.report_generator: Optional[ReportGenerator] = None

    def initialize(self) -> bool:
        """Initialize the runner."""
        if not self.analyzer.initialize():
            return False

        self.report_generator = ReportGenerator(
            self.settings,
            self.analyzer,
        )
        return True

    def run_analysis(
        self,
        limit: Optional[int] = None,
        reanalyze_all: bool = False,
        since_days: Optional[int] = None,
    ) -> int:
        """
        Run analysis on positions.

        Args:
            limit: Maximum positions to analyze
            reanalyze_all: Re-analyze already analyzed positions
            since_days: Only analyze positions from last N days

        Returns:
            Number of positions analyzed
        """
        since = None
        if since_days:
            since = datetime.utcnow() - timedelta(days=since_days)

        if reanalyze_all:
            analyses = self.analyzer.analyze_all(since=since, limit=limit)
        else:
            analyses = self.analyzer.analyze_unanalyzed(limit=limit)

        # Log summary
        if analyses:
            avg_compliance = sum(a.rule_compliance_score for a in analyses) / len(
                analyses
            )
            entries_with_signal = sum(1 for a in analyses if a.entry_signal_matched)

            logger.info(
                f"Analysis complete: {len(analyses)} positions, "
                f"avg compliance {avg_compliance:.0%}, "
                f"{entries_with_signal} had valid entry signals"
            )

        return len(analyses)

    def generate_report(
        self,
        output_path: Optional[str] = None,
        format: str = "json",
        since_days: Optional[int] = None,
    ) -> str:
        """
        Generate a deviation report.

        Args:
            output_path: Where to save the report
            format: Output format (json, markdown, html)
            since_days: Report on last N days

        Returns:
            Path to generated report
        """
        since = None
        if since_days:
            since = datetime.utcnow() - timedelta(days=since_days)

        report = self.analyzer.generate_report(period_start=since)

        if output_path is None:
            output_dir = Path(self.settings.report_output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(output_dir / f"deviation_report_{timestamp}.{format}")

        if format == "json":
            with open(output_path, "w") as f:
                json.dump(report.to_dict(), f, indent=2, default=str)
        elif format == "markdown":
            content = self.report_generator.to_markdown(report)
            with open(output_path, "w") as f:
                f.write(content)
        else:
            raise ValueError(f"Unsupported format: {format}")

        logger.info(f"Report saved to {output_path}")
        return output_path

    def show_stats(self) -> None:
        """Display analysis statistics."""
        stats = self.analyzer.get_stats()

        print("\n=== Trade Analysis Statistics ===\n")
        print(f"Total closed positions: {stats.get('total_closed', 0)}")
        print(f"Analyzed positions:     {stats.get('total_analyzed', 0)}")
        print(
            f"Pending analysis:       {stats.get('total_closed', 0) - stats.get('total_analyzed', 0)}"
        )
        print()

        avg_compliance = stats.get("avg_compliance")
        if avg_compliance:
            print(f"Average compliance score: {float(avg_compliance):.1%}")

        avg_confidence = stats.get("avg_confidence")
        if avg_confidence:
            print(f"Average entry confidence: {float(avg_confidence):.1%}")

        print("\nExit type distribution:")
        for exit_type, count in stats.get("exit_types", {}).items():
            print(f"  {exit_type}: {count}")

        print("\nCompliance by outcome:")
        for outcome, data in stats.get("compliance_by_outcome", {}).items():
            print(
                f"  {outcome}: {data['avg_compliance']:.1%} avg compliance ({data['count']} trades)"
            )

        print()

    def shutdown(self) -> None:
        """Clean up resources."""
        self.analyzer.shutdown()


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Trade reporting and analysis service"
    )
    parser.add_argument(
        "--config",
        "-c",
        help="Path to config file",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze trades")
    analyze_parser.add_argument(
        "--limit",
        "-n",
        type=int,
        help="Maximum positions to analyze",
    )
    analyze_parser.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="Re-analyze all positions",
    )
    analyze_parser.add_argument(
        "--since-days",
        type=int,
        help="Only analyze positions from last N days",
    )

    # Report command
    report_parser = subparsers.add_parser("report", help="Generate report")
    report_parser.add_argument(
        "--output",
        "-o",
        help="Output file path",
    )
    report_parser.add_argument(
        "--format",
        "-f",
        choices=["json", "markdown"],
        default="json",
        help="Output format",
    )
    report_parser.add_argument(
        "--since-days",
        type=int,
        help="Report on last N days",
    )

    # Stats command
    subparsers.add_parser("stats", help="Show analysis statistics")

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if not args.command:
        parser.print_help()
        sys.exit(1)

    runner = ReportingRunner(args.config)

    if not runner.initialize():
        logger.error("Failed to initialize runner")
        sys.exit(1)

    try:
        if args.command == "analyze":
            count = runner.run_analysis(
                limit=args.limit,
                reanalyze_all=args.all,
                since_days=args.since_days,
            )
            print(f"Analyzed {count} positions")

        elif args.command == "report":
            path = runner.generate_report(
                output_path=args.output,
                format=args.format,
                since_days=args.since_days,
            )
            print(f"Report saved to: {path}")

        elif args.command == "stats":
            runner.show_stats()

    finally:
        runner.shutdown()


if __name__ == "__main__":
    main()
