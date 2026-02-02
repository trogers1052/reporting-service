"""
Deviation analyzer.

Analyzes how actual trades deviated from recommended rules
and generates insights for improvement.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from ..config import ReportingSettings
from ..data.journal_repository import JournalRepository
from ..data.market_data import MarketDataLoader
from ..data.rules_client import RulesClient
from ..models.analysis import (
    ComplianceLevel,
    ComplianceMetrics,
    DeviationReport,
    ExitType,
    TradeAnalysis,
)
from ..models.position import Position
from .exit_classifier import ExitClassifier
from .rule_evaluator import RuleEvaluator

logger = logging.getLogger(__name__)

# Try to import risk engine for position sizing
try:
    from risk_engine import RiskAdapter

    HAS_RISK_ENGINE = True
except ImportError:
    HAS_RISK_ENGINE = False


class DeviationAnalyzer:
    """
    Analyzes trades for rule compliance and deviations.

    Compares actual trades against:
    1. Entry signals from decision-engine rules
    2. Position sizing from risk-engine
    3. Exit discipline (profit targets, stop losses)

    Uses RulesClient to load rules from Redis cache when available.
    """

    def __init__(
        self,
        settings: ReportingSettings,
        journal_repo: JournalRepository,
        market_data: MarketDataLoader,
        rules_client: Optional[RulesClient] = None,
    ):
        self.settings = settings
        self.journal_repo = journal_repo
        self.market_data = market_data
        self._rules_client = rules_client
        self.rule_evaluator = RuleEvaluator(settings, rules_client)
        self.exit_classifier = ExitClassifier(settings, rules_client)
        self._risk_adapter = None

    def initialize(self) -> bool:
        """Initialize analyzers and rules client."""
        # Initialize rules client if not provided
        if self._rules_client is None and self.settings.use_redis_rules:
            self._rules_client = RulesClient(self.settings)
            if self._rules_client.connect():
                logger.info("Rules client connected for deviation analysis")
                # Update evaluator and classifier with rules client
                self.rule_evaluator = RuleEvaluator(self.settings, self._rules_client)
                self.exit_classifier = ExitClassifier(self.settings, self._rules_client)
            else:
                logger.warning("Rules client failed to connect, using YAML config")
                self._rules_client = None

        success = self.rule_evaluator.initialize()

        if HAS_RISK_ENGINE:
            try:
                self._risk_adapter = RiskAdapter(
                    config_path=self.settings.risk_engine_config
                )
                if not self._risk_adapter.initialize():
                    logger.warning("Risk adapter failed to initialize")
                    self._risk_adapter = None
            except Exception as e:
                logger.warning(f"Could not initialize risk adapter: {e}")

        return success

    def close(self) -> None:
        """Clean up resources."""
        if self._rules_client:
            self._rules_client.close()
        if self._risk_adapter:
            self._risk_adapter.shutdown()

    def analyze_position(self, position: Position) -> TradeAnalysis:
        """
        Analyze a single position for rule compliance.

        Args:
            position: The position to analyze

        Returns:
            TradeAnalysis with compliance metrics
        """
        analysis = TradeAnalysis(
            position_id=position.id,
            symbol=position.symbol,
            entry_date=position.entry_date,
            entry_price=position.entry_price,
            actual_shares=position.quantity,
            exit_date=position.exit_date,
            exit_price=position.exit_price,
        )

        # Get indicators at entry time
        entry_indicators = self.market_data.get_indicators_at_time(
            position.symbol,
            position.entry_date,
            self.settings.analysis.indicator_lookback_minutes,
        )

        if entry_indicators:
            # Evaluate rules at entry
            evaluations, signal_type, confidence = self.rule_evaluator.evaluate_at_time(
                position.symbol,
                entry_indicators,
                position.entry_date,
            )

            analysis.entry_rules_evaluated = evaluations
            analysis.entry_signal_type = signal_type
            analysis.entry_signal_confidence = confidence
            analysis.entry_signal_matched = (
                signal_type == "BUY"
                and confidence >= self.settings.analysis.min_signal_confidence
            )

            # Store risk metrics
            if "atr_14" in entry_indicators:
                analysis.risk_metrics["atr"] = entry_indicators["atr_14"]
            if "rsi_14" in entry_indicators:
                analysis.risk_metrics["rsi"] = entry_indicators["rsi_14"]
            if "sma_200" in entry_indicators:
                analysis.risk_metrics["sma_200"] = entry_indicators["sma_200"]

            # Check position sizing
            if self._risk_adapter:
                try:
                    risk_result = self._risk_adapter.check_risk(
                        symbol=position.symbol,
                        signal_type="BUY",
                        confidence=confidence,
                        indicators=entry_indicators,
                    )
                    analysis.recommended_shares = risk_result.recommended_shares

                    if risk_result.recommended_shares > 0:
                        deviation = (
                            position.quantity - risk_result.recommended_shares
                        ) / risk_result.recommended_shares
                        analysis.position_size_deviation = deviation
                    else:
                        analysis.position_size_deviation = 0.0

                    analysis.risk_metrics.update(risk_result.risk_metrics)

                except Exception as e:
                    logger.debug(f"Risk check failed for {position.symbol}: {e}")
                    analysis.notes.append(f"Risk check unavailable: {e}")
        else:
            analysis.warnings.append("No indicator data available at entry time")

        # Classify exit type
        exit_indicators = None
        if position.exit_date:
            exit_indicators = self.market_data.get_indicators_at_time(
                position.symbol,
                position.exit_date,
                self.settings.analysis.indicator_lookback_minutes,
            )

        analysis.exit_type = self.exit_classifier.classify(position, exit_indicators)

        # Calculate overall compliance score
        analysis.calculate_compliance_score()

        # Add notes based on analysis
        self._add_analysis_notes(analysis, position)

        return analysis

    def _add_analysis_notes(
        self,
        analysis: TradeAnalysis,
        position: Position,
    ) -> None:
        """Add contextual notes to the analysis."""
        # Entry signal notes
        if not analysis.entry_signal_matched:
            if analysis.entry_signal_type is None:
                analysis.notes.append("No clear entry signal at time of purchase")
            elif analysis.entry_signal_type == "SELL":
                analysis.warnings.append("Entry was against a SELL signal")
            elif analysis.entry_signal_confidence < self.settings.analysis.min_signal_confidence:
                analysis.notes.append(
                    f"Entry signal confidence ({analysis.entry_signal_confidence:.0%}) "
                    f"below threshold ({self.settings.analysis.min_signal_confidence:.0%})"
                )

        # Position sizing notes
        if abs(analysis.position_size_deviation) > self.settings.analysis.position_size_tolerance:
            if analysis.position_size_deviation > 0:
                analysis.warnings.append(
                    f"Position {analysis.position_size_deviation:.0%} larger than recommended"
                )
            else:
                analysis.notes.append(
                    f"Position {abs(analysis.position_size_deviation):.0%} smaller than recommended"
                )

        # Exit notes
        if analysis.exit_type == ExitType.STOP_LOSS:
            analysis.notes.append("Proper stop loss discipline maintained")
        elif analysis.exit_type == ExitType.PROFIT_TARGET:
            analysis.notes.append("Profit target achieved")
        elif analysis.exit_type == ExitType.MANUAL:
            if position.is_winner:
                analysis.notes.append("Manual exit - profitable but may have left gains")
            else:
                analysis.warnings.append("Manual exit at a loss - review exit discipline")

    def analyze_positions(
        self,
        positions: List[Position],
    ) -> List[TradeAnalysis]:
        """Analyze multiple positions."""
        analyses = []
        for position in positions:
            try:
                analysis = self.analyze_position(position)
                analyses.append(analysis)
            except Exception as e:
                logger.error(f"Error analyzing position {position.id}: {e}")
        return analyses

    def generate_report(
        self,
        analyses: List[TradeAnalysis],
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
    ) -> DeviationReport:
        """
        Generate a comprehensive deviation report.

        Args:
            analyses: List of trade analyses
            period_start: Optional start of reporting period
            period_end: Optional end of reporting period

        Returns:
            DeviationReport with metrics and insights
        """
        report = DeviationReport(
            period_start=period_start,
            period_end=period_end,
            analyses=analyses,
        )

        if not analyses:
            return report

        # Calculate aggregate metrics
        metrics = ComplianceMetrics(
            total_positions=len(analyses),
            analyzed_positions=len(analyses),
        )

        # Compliance distribution
        compliance_scores = []
        entry_confidences = []
        size_deviations = []

        compliant_wins = 0
        compliant_losses = 0
        non_compliant_wins = 0
        non_compliant_losses = 0

        for analysis in analyses:
            compliance_scores.append(analysis.rule_compliance_score)
            entry_confidences.append(analysis.entry_signal_confidence)
            size_deviations.append(abs(analysis.position_size_deviation))

            # Count by compliance level
            if analysis.compliance_level == ComplianceLevel.EXCELLENT:
                metrics.excellent_count += 1
            elif analysis.compliance_level == ComplianceLevel.GOOD:
                metrics.good_count += 1
            elif analysis.compliance_level == ComplianceLevel.FAIR:
                metrics.fair_count += 1
            elif analysis.compliance_level == ComplianceLevel.POOR:
                metrics.poor_count += 1
            else:
                metrics.non_compliant_count += 1

            # Entry signal stats
            if analysis.entry_signal_matched:
                metrics.entries_with_buy_signal += 1
            else:
                metrics.entries_without_signal += 1

            # Exit type stats
            if analysis.exit_type == ExitType.PROFIT_TARGET:
                metrics.profit_target_exits += 1
            elif analysis.exit_type == ExitType.STOP_LOSS:
                metrics.stop_loss_exits += 1
            elif analysis.exit_type == ExitType.MANUAL:
                metrics.manual_exits += 1
            else:
                metrics.other_exits += 1

            # Win rate by compliance
            position = self.journal_repo.get_position_by_id(analysis.position_id)
            if position:
                is_compliant = analysis.rule_compliance_score >= 0.50
                is_winner = position.is_winner

                if is_compliant:
                    if is_winner:
                        compliant_wins += 1
                    else:
                        compliant_losses += 1
                else:
                    if is_winner:
                        non_compliant_wins += 1
                    else:
                        non_compliant_losses += 1

        # Calculate averages
        metrics.avg_compliance_score = (
            sum(compliance_scores) / len(compliance_scores) if compliance_scores else 0
        )
        metrics.avg_entry_confidence = (
            sum(entry_confidences) / len(entry_confidences) if entry_confidences else 0
        )
        metrics.avg_position_size_deviation = (
            sum(size_deviations) / len(size_deviations) if size_deviations else 0
        )

        # Win rates
        if compliant_wins + compliant_losses > 0:
            metrics.compliant_win_rate = compliant_wins / (
                compliant_wins + compliant_losses
            )
        if non_compliant_wins + non_compliant_losses > 0:
            metrics.non_compliant_win_rate = non_compliant_wins / (
                non_compliant_wins + non_compliant_losses
            )

        report.metrics = metrics

        # Find worst and best
        sorted_by_compliance = sorted(analyses, key=lambda a: a.rule_compliance_score)
        report.worst_deviations = sorted_by_compliance[:5]
        report.best_compliant = sorted_by_compliance[-5:][::-1]

        # Generate insights
        report.common_issues = self._identify_common_issues(analyses, metrics)
        report.recommendations = self._generate_recommendations(analyses, metrics)

        return report

    def _identify_common_issues(
        self,
        analyses: List[TradeAnalysis],
        metrics: ComplianceMetrics,
    ) -> List[str]:
        """Identify common issues across trades."""
        issues = []

        # Check for entries without signals
        pct_without_signal = (
            metrics.entries_without_signal / len(analyses) if analyses else 0
        )
        if pct_without_signal > 0.3:
            issues.append(
                f"{pct_without_signal:.0%} of entries had no valid buy signal"
            )

        # Check for position sizing issues
        if metrics.avg_position_size_deviation > 0.2:
            issues.append(
                f"Average position size deviation of {metrics.avg_position_size_deviation:.0%}"
            )

        # Check for manual exit overuse
        manual_pct = metrics.manual_exits / len(analyses) if analyses else 0
        if manual_pct > 0.5:
            issues.append(f"{manual_pct:.0%} of exits were manual/discretionary")

        # Check for stop loss underuse
        stop_pct = metrics.stop_loss_exits / len(analyses) if analyses else 0
        losing_trades = sum(
            1
            for a in analyses
            if self.journal_repo.get_position_by_id(a.position_id)
            and not self.journal_repo.get_position_by_id(a.position_id).is_winner
        )
        if losing_trades > 0 and stop_pct < 0.3:
            issues.append("Many losing trades without stop loss exits")

        return issues

    def _generate_recommendations(
        self,
        analyses: List[TradeAnalysis],
        metrics: ComplianceMetrics,
    ) -> List[str]:
        """Generate recommendations based on analysis."""
        recommendations = []

        # Signal-based entry
        if metrics.entries_without_signal > metrics.entries_with_buy_signal:
            recommendations.append(
                "Wait for valid buy signals before entering positions"
            )

        # Position sizing
        if metrics.avg_position_size_deviation > 0.2:
            recommendations.append(
                "Use risk-engine position sizing recommendations more consistently"
            )

        # Exit discipline
        if metrics.manual_exits > metrics.profit_target_exits + metrics.stop_loss_exits:
            recommendations.append(
                "Set and honor profit targets and stop losses before entry"
            )

        # Compliance correlation
        if metrics.compliant_win_rate > metrics.non_compliant_win_rate + 0.1:
            recommendations.append(
                f"Compliant trades win {metrics.compliant_win_rate:.0%} vs "
                f"{metrics.non_compliant_win_rate:.0%} for non-compliant - stick to the rules"
            )

        return recommendations
