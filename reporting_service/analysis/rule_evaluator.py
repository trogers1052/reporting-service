"""
Rule evaluator for historical trades.

Evaluates decision-engine rules against historical indicator data
to determine what signals existed at entry/exit times.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from ..config import ReportingSettings
from ..data.rules_client import RulesClient
from ..models.analysis import RuleEvaluation

logger = logging.getLogger(__name__)

# Try to import decision-engine rules
try:
    from decision_engine.rules.base import Rule, SignalType, SymbolContext
    from decision_engine.rules.registry import RuleRegistry

    HAS_DECISION_ENGINE = True
except ImportError:
    HAS_DECISION_ENGINE = False
    logger.warning("decision-engine not available, using fallback rule evaluation")


class RuleEvaluator:
    """
    Evaluates trading rules against historical data.

    Uses the decision-engine rules when available, otherwise
    falls back to simplified rule evaluation.

    Can load rules from:
    1. Redis cache (if use_redis_rules=True and connected)
    2. YAML config file (fallback)
    3. Simplified rules (fallback if neither available)
    """

    def __init__(self, settings: ReportingSettings, rules_client: Optional[RulesClient] = None):
        self.settings = settings
        self._rules_client = rules_client
        self._rules: List = []
        self._rule_weights: Dict[str, float] = {}
        self._config: Optional[Dict] = None
        self._initialized = False

    def initialize(self) -> bool:
        """Load rules from Redis or decision-engine config."""
        if not HAS_DECISION_ENGINE:
            logger.info("Using fallback rule evaluation (decision-engine not installed)")
            self._initialized = True
            return True

        # Try loading from Redis first
        if self.settings.use_redis_rules and self._rules_client:
            config = self._rules_client.get_config()
            if config:
                logger.info("Loading rules from Redis cache")
                self._config = config
                try:
                    self._rules, self._rule_weights = RuleRegistry.load_rules_from_config(
                        config
                    )
                    logger.info(f"Loaded {len(self._rules)} rules from Redis cache")
                    self._initialized = True
                    return True
                except Exception as e:
                    logger.warning(f"Failed to load rules from Redis: {e}, falling back to YAML")

        # Fall back to YAML config file
        try:
            import yaml

            config_path = self.settings.decision_engine_config
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)

            self._config = config
            self._rules, self._rule_weights = RuleRegistry.load_rules_from_config(
                config
            )
            logger.info(f"Loaded {len(self._rules)} rules from YAML config")
            self._initialized = True
            return True

        except Exception as e:
            logger.error(f"Failed to load rules: {e}")
            self._initialized = True  # Continue with fallback
            return True

    def get_exit_strategy(self, symbol: str) -> Dict[str, float]:
        """
        Get exit strategy for a symbol.

        Uses RulesClient if available, otherwise falls back to config.
        """
        if self._rules_client:
            return self._rules_client.get_exit_strategy(symbol)

        # Fallback to config
        if self._config:
            # Check symbol override
            overrides = self._config.get("symbol_overrides", {})
            if symbol in overrides and "exit_strategy" in overrides[symbol]:
                return overrides[symbol]["exit_strategy"]
            # Default exit strategy
            return self._config.get("exit_strategy", {
                "profit_target": 0.07,
                "stop_loss": 0.05,
            })

        return {"profit_target": 0.07, "stop_loss": 0.05}

    def evaluate_at_time(
        self,
        symbol: str,
        indicators: Dict[str, float],
        timestamp: datetime,
    ) -> Tuple[List[RuleEvaluation], Optional[str], float]:
        """
        Evaluate all rules for a symbol at a point in time.

        Args:
            symbol: Stock symbol
            indicators: Indicator values at that time
            timestamp: The timestamp being evaluated

        Returns:
            Tuple of (rule evaluations, dominant signal type, aggregate confidence)
        """
        if not self._initialized:
            self.initialize()

        if HAS_DECISION_ENGINE and self._rules:
            return self._evaluate_with_rules(symbol, indicators, timestamp)
        else:
            return self._evaluate_fallback(symbol, indicators, timestamp)

    def _evaluate_with_rules(
        self,
        symbol: str,
        indicators: Dict[str, float],
        timestamp: datetime,
    ) -> Tuple[List[RuleEvaluation], Optional[str], float]:
        """Evaluate using decision-engine rules."""
        evaluations = []
        buy_signals = []
        sell_signals = []

        # Build context for rules
        context = SymbolContext(
            symbol=symbol,
            indicators=indicators,
            timestamp=timestamp,
            data_quality={"is_ready": True},
            previous_signals=[],
            current_position=None,
        )

        for rule in self._rules:
            try:
                if not rule.can_evaluate(context):
                    continue

                result = rule.evaluate(context)

                evaluation = RuleEvaluation(
                    rule_name=rule.name,
                    triggered=result.triggered,
                    signal_type=result.signal.value if result.signal else None,
                    confidence=result.confidence,
                    reasoning=result.reasoning,
                    indicators_used={
                        k: v
                        for k, v in indicators.items()
                        if k in str(rule.required_indicators)
                    },
                )
                evaluations.append(evaluation)

                if result.triggered:
                    if result.signal == SignalType.BUY:
                        buy_signals.append(result.confidence)
                    elif result.signal == SignalType.SELL:
                        sell_signals.append(result.confidence)

            except Exception as e:
                logger.debug(f"Error evaluating rule {rule.name}: {e}")

        # Determine dominant signal
        if buy_signals and len(buy_signals) >= len(sell_signals):
            avg_confidence = sum(buy_signals) / len(buy_signals)
            # Apply consensus boost
            consensus_boost = min(0.15, 0.05 * (len(buy_signals) - 1))
            return evaluations, "BUY", min(1.0, avg_confidence + consensus_boost)
        elif sell_signals:
            avg_confidence = sum(sell_signals) / len(sell_signals)
            return evaluations, "SELL", avg_confidence
        else:
            return evaluations, None, 0.0

    def _evaluate_fallback(
        self,
        symbol: str,
        indicators: Dict[str, float],
        timestamp: datetime,
    ) -> Tuple[List[RuleEvaluation], Optional[str], float]:
        """Fallback evaluation when decision-engine not available."""
        evaluations = []
        signals = []

        # Simple trend following check
        close = indicators.get("close", 0)
        sma_200 = indicators.get("sma_200")
        sma_50 = indicators.get("sma_50")
        rsi = indicators.get("rsi_14")

        # Trend check
        if sma_200 and close > sma_200:
            evaluation = RuleEvaluation(
                rule_name="trend_following",
                triggered=True,
                signal_type="BUY",
                confidence=0.6,
                reasoning=f"Price ${close:.2f} above SMA200 ${sma_200:.2f}",
            )
            evaluations.append(evaluation)
            signals.append(("BUY", 0.6))
        elif sma_200 and close < sma_200:
            evaluation = RuleEvaluation(
                rule_name="trend_following",
                triggered=True,
                signal_type="SELL",
                confidence=0.5,
                reasoning=f"Price ${close:.2f} below SMA200 ${sma_200:.2f}",
            )
            evaluations.append(evaluation)
            signals.append(("SELL", 0.5))

        # Golden/death cross check
        if sma_50 and sma_200:
            if sma_50 > sma_200:
                evaluation = RuleEvaluation(
                    rule_name="moving_average_crossover",
                    triggered=True,
                    signal_type="BUY",
                    confidence=0.55,
                    reasoning="SMA50 above SMA200 (bullish)",
                )
                evaluations.append(evaluation)
                signals.append(("BUY", 0.55))

        # RSI check
        if rsi:
            if rsi < 30:
                evaluation = RuleEvaluation(
                    rule_name="rsi_oversold",
                    triggered=True,
                    signal_type="BUY",
                    confidence=0.65,
                    reasoning=f"RSI {rsi:.1f} oversold",
                )
                evaluations.append(evaluation)
                signals.append(("BUY", 0.65))
            elif rsi > 70:
                evaluation = RuleEvaluation(
                    rule_name="rsi_overbought",
                    triggered=True,
                    signal_type="SELL",
                    confidence=0.6,
                    reasoning=f"RSI {rsi:.1f} overbought",
                )
                evaluations.append(evaluation)
                signals.append(("SELL", 0.6))

        # Aggregate signals
        buy_signals = [c for s, c in signals if s == "BUY"]
        sell_signals = [c for s, c in signals if s == "SELL"]

        if buy_signals and len(buy_signals) >= len(sell_signals):
            return evaluations, "BUY", sum(buy_signals) / len(buy_signals)
        elif sell_signals:
            return evaluations, "SELL", sum(sell_signals) / len(sell_signals)
        else:
            return evaluations, None, 0.0

    def get_required_indicators(self) -> List[str]:
        """Get list of indicators required by loaded rules."""
        if HAS_DECISION_ENGINE and self._rules:
            indicators = set()
            for rule in self._rules:
                indicators.update(rule.required_indicators)
            return list(indicators)
        else:
            return [
                "close",
                "sma_20",
                "sma_50",
                "sma_200",
                "rsi_14",
                "atr_14",
                "volume",
                "avg_volume_20",
            ]
