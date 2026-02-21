"""
Reporting service runner.

Main entry point for running the reporting service.
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
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
        self._shutdown_called = False

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
        daemon: bool = False,
        interval_seconds: Optional[int] = None,
    ) -> int:
        """
        Run analysis on positions.

        Args:
            limit: Maximum positions to analyze
            reanalyze_all: Re-analyze already analyzed positions
            since_days: Only analyze positions from last N days
            daemon: Run continuously in daemon mode
            interval_seconds: Seconds between analysis runs in daemon mode

        Returns:
            Number of positions analyzed
        """
        if daemon:
            interval = interval_seconds or self.settings.daemon_interval
            return self._run_daemon(limit, interval)

        return self._run_once(limit, reanalyze_all, since_days)

    def _run_once(
        self,
        limit: Optional[int] = None,
        reanalyze_all: bool = False,
        since_days: Optional[int] = None,
    ) -> int:
        """Run analysis once."""
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

    def _run_daemon(
        self,
        limit: Optional[int] = None,
        interval_seconds: int = 300,
    ) -> int:
        """Run analysis continuously in daemon mode."""
        self._running = True
        total_analyzed = 0

        def handle_signal(signum, frame):
            logger.info("Received shutdown signal")
            self._running = False

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        logger.info(
            f"Starting daemon mode - analyzing every {interval_seconds} seconds"
        )

        while self._running:
            try:
                if not self.analyzer.journal_repo._ensure_connected():
                    logger.error("Failed to reconnect to journal database")
                    time.sleep(30)
                    continue
                self.analyzer.market_data._ensure_connected()

                count = self._run_once(limit=limit, reanalyze_all=False)
                total_analyzed += count

                if count > 0:
                    logger.info(f"Analyzed {count} new positions")
                else:
                    logger.debug("No new positions to analyze")

                # Sleep in small intervals to respond to signals
                for _ in range(interval_seconds):
                    if not self._running:
                        break
                    time.sleep(1)

            except Exception as e:
                logger.error(f"Error in daemon loop: {e}")
                time.sleep(30)  # Wait before retry

        logger.info(f"Daemon stopped. Total analyzed: {total_analyzed}")
        return total_analyzed

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
        """Clean up resources.

        Safe to call multiple times (idempotent).  Both the signal handler and
        the ``finally`` block in ``main()`` may invoke this method.
        """
        if not self._shutdown_called:
            self._shutdown_called = True
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
    analyze_parser.add_argument(
        "--daemon",
        "-d",
        action="store_true",
        help="Run continuously in daemon mode",
    )
    analyze_parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Seconds between analysis runs in daemon mode (default: from config)",
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

    # Register top-level signal handlers so that SIGTERM (e.g. from Docker or
    # systemd) triggers a clean shutdown with resource cleanup.  In daemon mode,
    # _run_daemon installs its own handlers that set self._running = False for a
    # graceful loop exit; the finally block below still runs afterwards.
    def _handle_shutdown(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name}, shutting down reporting-service...")
        runner.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    try:
        if args.command == "analyze":
            count = runner.run_analysis(
                limit=args.limit,
                reanalyze_all=args.all,
                since_days=args.since_days,
                daemon=args.daemon,
                interval_seconds=args.interval,
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
