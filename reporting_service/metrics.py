"""Prometheus metrics for reporting-service."""

import logging
import os

logger = logging.getLogger(__name__)

_DEFAULT_PORT = 9099

# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------
# Guarded behind a try/except so the service can still start if
# prometheus_client is not installed (metrics will simply be no-ops).
# ---------------------------------------------------------------------------

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server

    ANALYSIS_CYCLES = Counter(
        "reporting_analysis_cycles_total",
        "Analysis runs completed",
    )

    POSITIONS_ANALYZED = Counter(
        "reporting_positions_analyzed_total",
        "Positions analyzed",
        ["status"],
    )

    ANALYSIS_DURATION = Histogram(
        "reporting_analysis_duration_seconds",
        "Per-position analysis duration",
    )

    EXIT_CLASSIFICATIONS = Counter(
        "reporting_exit_classifications_total",
        "Exit type classifications",
        ["exit_type"],
    )

    RULE_EVALUATIONS = Counter(
        "reporting_rule_evaluations_total",
        "Rule evaluations at entry/exit",
        ["rule_name"],
    )

    SIGNAL_OUTCOMES_RESOLVED = Counter(
        "reporting_signal_outcomes_resolved_total",
        "Signals correlated with price outcomes",
    )

    DB_ERRORS = Counter(
        "reporting_db_errors_total",
        "Database operation failures",
    )

    MARKET_DATA_ERRORS = Counter(
        "reporting_market_data_errors_total",
        "TimescaleDB / market data load failures",
    )

    _PROMETHEUS_AVAILABLE = True

except ImportError:
    _PROMETHEUS_AVAILABLE = False
    start_http_server = None  # type: ignore[assignment]

    # Provide no-op stand-ins so instrumented code doesn't need guards
    class _NoOpMetric:
        """Dummy metric that silently discards all operations."""
        def inc(self, *a, **kw): pass
        def dec(self, *a, **kw): pass
        def set(self, *a, **kw): pass
        def observe(self, *a, **kw): pass
        def labels(self, **kw): return self

    ANALYSIS_CYCLES = _NoOpMetric()  # type: ignore[assignment]
    POSITIONS_ANALYZED = _NoOpMetric()  # type: ignore[assignment]
    ANALYSIS_DURATION = _NoOpMetric()  # type: ignore[assignment]
    EXIT_CLASSIFICATIONS = _NoOpMetric()  # type: ignore[assignment]
    RULE_EVALUATIONS = _NoOpMetric()  # type: ignore[assignment]
    SIGNAL_OUTCOMES_RESOLVED = _NoOpMetric()  # type: ignore[assignment]
    DB_ERRORS = _NoOpMetric()  # type: ignore[assignment]
    MARKET_DATA_ERRORS = _NoOpMetric()  # type: ignore[assignment]


def start_metrics_server() -> None:
    """Start Prometheus metrics HTTP server on METRICS_PORT (default 9099)."""
    if not _PROMETHEUS_AVAILABLE:
        logger.warning("prometheus_client not installed — metrics endpoint disabled")
        return
    port = int(os.environ.get("METRICS_PORT", str(_DEFAULT_PORT)))
    start_http_server(port)
    logger.info(f"Metrics server listening on :{port}/metrics")
