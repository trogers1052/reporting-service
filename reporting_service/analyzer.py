"""
Main trade analyzer.

Orchestrates the analysis of trades and updates the journal database.
"""

import logging
from datetime import datetime
from typing import List, Optional

from .analysis.deviation_analyzer import DeviationAnalyzer
from .config import ReportingSettings
from .data.journal_repository import JournalRepository
from .data.market_data import MarketDataLoader
from .models.analysis import DeviationReport, TradeAnalysis
from .models.position import Position

logger = logging.getLogger(__name__)


class TradeAnalyzer:
    """
    Main entry point for trade analysis.

    Coordinates data loading, rule evaluation, and database updates.
    """

    def __init__(self, settings: ReportingSettings):
        self.settings = settings
        self.journal_repo = JournalRepository(settings)
        self.market_data = MarketDataLoader(settings)
        self.deviation_analyzer: Optional[DeviationAnalyzer] = None
        self._initialized = False

    def initialize(self) -> bool:
        """Initialize all components."""
        try:
            # Connect to databases
            if not self.journal_repo.connect():
                logger.error("Failed to connect to journal database")
                return False

            if not self.market_data.connect():
                logger.warning("Failed to connect to market data - some analysis limited")

            # Ensure analysis columns exist
            self.journal_repo.ensure_analysis_columns()

            # Initialize deviation analyzer
            self.deviation_analyzer = DeviationAnalyzer(
                self.settings,
                self.journal_repo,
                self.market_data,
            )
            self.deviation_analyzer.initialize()

            self._initialized = True
            logger.info("Trade analyzer initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize trade analyzer: {e}")
            return False

    def analyze_unanalyzed(
        self,
        limit: Optional[int] = None,
        update_db: bool = True,
    ) -> List[TradeAnalysis]:
        """
        Analyze all positions that haven't been analyzed yet.

        Args:
            limit: Maximum number of positions to analyze
            update_db: Whether to update the database with results

        Returns:
            List of trade analyses
        """
        if not self._initialized:
            if not self.initialize():
                return []

        positions = self.journal_repo.get_closed_positions(
            limit=limit,
            unanalyzed_only=True,
        )

        logger.info(f"Found {len(positions)} unanalyzed positions")

        analyses = []
        for position in positions:
            try:
                analysis = self.deviation_analyzer.analyze_position(position)
                analyses.append(analysis)

                if update_db:
                    self._update_position(position.id, analysis)

                logger.debug(
                    f"Analyzed {position.symbol}: "
                    f"compliance={analysis.rule_compliance_score:.2f}, "
                    f"exit={analysis.exit_type.value}"
                )

            except Exception as e:
                logger.error(f"Error analyzing position {position.id}: {e}")

        logger.info(f"Analyzed {len(analyses)} positions")
        return analyses

    def analyze_position(
        self,
        position_id: int,
        update_db: bool = True,
    ) -> Optional[TradeAnalysis]:
        """
        Analyze a single position.

        Args:
            position_id: ID of the position to analyze
            update_db: Whether to update the database

        Returns:
            TradeAnalysis or None
        """
        if not self._initialized:
            if not self.initialize():
                return None

        position = self.journal_repo.get_position_by_id(position_id)
        if not position:
            logger.error(f"Position {position_id} not found")
            return None

        analysis = self.deviation_analyzer.analyze_position(position)

        if update_db:
            self._update_position(position_id, analysis)

        return analysis

    def analyze_all(
        self,
        since: Optional[datetime] = None,
        limit: Optional[int] = None,
        update_db: bool = True,
    ) -> List[TradeAnalysis]:
        """
        Analyze all closed positions (including previously analyzed).

        Args:
            since: Only analyze positions closed after this date
            limit: Maximum number to analyze
            update_db: Whether to update the database

        Returns:
            List of trade analyses
        """
        if not self._initialized:
            if not self.initialize():
                return []

        positions = self.journal_repo.get_closed_positions(
            limit=limit,
            unanalyzed_only=False,
            since=since,
        )

        logger.info(f"Analyzing {len(positions)} positions")

        analyses = []
        for position in positions:
            try:
                analysis = self.deviation_analyzer.analyze_position(position)
                analyses.append(analysis)

                if update_db:
                    self._update_position(position.id, analysis)

            except Exception as e:
                logger.error(f"Error analyzing position {position.id}: {e}")

        return analyses

    def generate_report(
        self,
        analyses: Optional[List[TradeAnalysis]] = None,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
    ) -> DeviationReport:
        """
        Generate a deviation report.

        Args:
            analyses: Pre-computed analyses (or will analyze all)
            period_start: Start of reporting period
            period_end: End of reporting period

        Returns:
            DeviationReport
        """
        if not self._initialized:
            self.initialize()

        if analyses is None:
            analyses = self.analyze_all(since=period_start, update_db=False)

        return self.deviation_analyzer.generate_report(
            analyses,
            period_start=period_start,
            period_end=period_end,
        )

    def _update_position(self, position_id: int, analysis: TradeAnalysis) -> None:
        """Update position with analysis results."""
        notes = "; ".join(analysis.notes + analysis.warnings)

        self.journal_repo.update_position_analysis(
            position_id=position_id,
            rule_compliance_score=analysis.rule_compliance_score,
            entry_signal_confidence=analysis.entry_signal_confidence,
            entry_signal_type=analysis.entry_signal_type,
            position_size_deviation=analysis.position_size_deviation,
            exit_type=analysis.exit_type.value,
            risk_metrics=analysis.risk_metrics,
            analysis_notes=notes if notes else None,
        )

    def get_stats(self) -> dict:
        """Get analysis statistics."""
        if not self._initialized:
            self.initialize()

        return self.journal_repo.get_analysis_stats()

    def shutdown(self) -> None:
        """Clean up connections."""
        self.journal_repo.close()
        self.market_data.close()
        logger.info("Trade analyzer shut down")
