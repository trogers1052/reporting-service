"""
Exit type classifier.

Determines how a position was exited based on price movement
and position characteristics.
"""

import logging
from typing import Optional

from ..config import ReportingSettings
from ..data.rules_client import RulesClient
from ..models.analysis import ExitType
from ..models.position import Position

logger = logging.getLogger(__name__)


class ExitClassifier:
    """Classifies how positions were exited."""

    def __init__(
        self,
        settings: ReportingSettings,
        rules_client: Optional[RulesClient] = None,
    ):
        self.settings = settings
        self._rules_client = rules_client
        # Default thresholds from config (used as fallback)
        self._default_profit_threshold = settings.analysis.profit_target_threshold
        self._default_stop_threshold = settings.analysis.stop_loss_threshold

    def _get_thresholds(self, symbol: str) -> tuple[float, float]:
        """Get profit target and stop loss thresholds for a symbol."""
        if self._rules_client:
            exit_strategy = self._rules_client.get_exit_strategy(symbol)
            return (
                exit_strategy.get("profit_target", self._default_profit_threshold),
                -exit_strategy.get("stop_loss", abs(self._default_stop_threshold)),
            )
        return (self._default_profit_threshold, self._default_stop_threshold)

    def classify(
        self,
        position: Position,
        indicators_at_exit: Optional[dict] = None,
    ) -> ExitType:
        """
        Classify the exit type for a closed position.

        Args:
            position: The closed position
            indicators_at_exit: Optional indicator values at exit time

        Returns:
            ExitType classification
        """
        if position.status != "closed" or position.realized_pl_pct is None:
            return ExitType.UNKNOWN

        pl_pct = position.realized_pl_pct / 100  # Convert from percentage

        # Get symbol-specific thresholds
        profit_threshold, stop_threshold = self._get_thresholds(position.symbol)

        # Check for profit target hit
        if pl_pct >= profit_threshold:
            return ExitType.PROFIT_TARGET

        # Check for stop loss hit
        if pl_pct <= stop_threshold:
            return ExitType.STOP_LOSS

        # Check for time-based exit (long holding period with small P&L)
        if position.holding_days and position.holding_days > 20:
            if abs(pl_pct) < 0.02:  # Less than 2% after 20+ days
                return ExitType.TIME_BASED

        # Check indicators for trailing stop pattern
        if indicators_at_exit:
            if self._check_trailing_stop_pattern(position, indicators_at_exit):
                return ExitType.TRAILING_STOP

        # Default to manual exit
        return ExitType.MANUAL

    def _check_trailing_stop_pattern(
        self,
        position: Position,
        indicators: dict,
    ) -> bool:
        """
        Check if exit looks like a trailing stop.

        Trailing stop pattern:
        - Position was profitable at some point
        - Exit is slightly negative or break-even
        - Price dropped from recent highs
        """
        if position.realized_pl_pct is None:
            return False

        pl_pct = position.realized_pl_pct / 100

        # Exit is near break-even or slightly negative
        if -0.03 < pl_pct < 0.02:
            # Check if we have ATR data to estimate trailing stop
            atr = indicators.get("atr_14")
            close = indicators.get("close")
            high = indicators.get("high")

            if atr and close and high:
                # If price is within 2 ATR of recent high, likely trailing stop
                if (high - close) <= atr * 2:
                    return True

        return False

    def get_exit_summary(self, exit_type: ExitType) -> str:
        """Get human-readable summary of exit type."""
        summaries = {
            ExitType.PROFIT_TARGET: "Exited at profit target",
            ExitType.STOP_LOSS: "Stopped out at loss",
            ExitType.TRAILING_STOP: "Trailing stop triggered",
            ExitType.TIME_BASED: "Exited due to time/stagnation",
            ExitType.MANUAL: "Manual/discretionary exit",
            ExitType.UNKNOWN: "Exit type unknown",
        }
        return summaries.get(exit_type, "Unknown exit type")
