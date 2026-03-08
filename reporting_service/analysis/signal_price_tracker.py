"""
Signal price outcome tracker.

Checks whether unresolved signals (with trade plan data) hit their
target or stop by examining subsequent price action in TimescaleDB.
Classifies each signal as TARGET_1_HIT, TARGET_2_HIT, STOPPED_OUT,
or EXPIRED and PUTs the outcome back to stock-service.

This answers: "What if the trades I ignored were better than the
ones I took?"
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
import requests

logger = logging.getLogger(__name__)

# Outcomes
TARGET_1_HIT = "TARGET_1_HIT"
TARGET_2_HIT = "TARGET_2_HIT"
STOPPED_OUT = "STOPPED_OUT"
EXPIRED = "EXPIRED"


@dataclass
class UnresolvedSignal:
    """A signal with trade plan data but no outcome yet."""

    id: int
    symbol: str
    signal: str
    action: str
    entry_price: float
    stop_price: float
    target_1: float
    target_2: float
    valid_until: Optional[datetime]
    feedback_timestamp: datetime
    rules_triggered: List[str]
    regime_id: str

    @classmethod
    def from_dict(cls, data: dict) -> "UnresolvedSignal":
        valid_until = None
        if data.get("valid_until"):
            try:
                vu = str(data["valid_until"]).replace("Z", "+00:00")
                valid_until = datetime.fromisoformat(vu)
            except (ValueError, TypeError):
                pass

        fb_ts = datetime.now(timezone.utc)
        if data.get("feedback_timestamp"):
            try:
                ts = str(data["feedback_timestamp"]).replace("Z", "+00:00")
                fb_ts = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                pass

        return cls(
            id=data.get("id", 0),
            symbol=data.get("symbol", ""),
            signal=data.get("signal", ""),
            action=data.get("action", ""),
            entry_price=data.get("entry_price", 0.0),
            stop_price=data.get("stop_price", 0.0),
            target_1=data.get("target_1", 0.0),
            target_2=data.get("target_2", 0.0),
            valid_until=valid_until,
            feedback_timestamp=fb_ts,
            rules_triggered=data.get("rules_triggered") or [],
            regime_id=data.get("regime_id", ""),
        )


class SignalPriceTracker:
    """
    Checks price action after signals fire to classify outcomes.

    Uses TimescaleDB OHLCV data to determine whether price hit
    target_1, target_2, stop_price, or expired without hitting any.
    """

    def __init__(
        self,
        stock_service_url: str,
        timescale_host: str,
        timescale_port: int,
        timescale_db: str,
        timescale_user: str,
        timescale_password: str,
        max_lookforward_days: int = 30,
    ):
        self._stock_service_url = stock_service_url.rstrip("/")
        self._ts_host = timescale_host
        self._ts_port = timescale_port
        self._ts_db = timescale_db
        self._ts_user = timescale_user
        self._ts_password = timescale_password
        self._max_lookforward_days = max_lookforward_days
        self._conn = None
        self._timeout = 10

    def connect(self) -> bool:
        """Connect to TimescaleDB."""
        try:
            self._conn = psycopg2.connect(
                host=self._ts_host,
                port=self._ts_port,
                dbname=self._ts_db,
                user=self._ts_user,
                password=self._ts_password,
                connect_timeout=10,
                options="-c statement_timeout=30000",
            )
            self._conn.set_session(autocommit=False)
            logger.info("SignalPriceTracker connected to TimescaleDB")
            return True
        except psycopg2.Error as e:
            logger.error(f"Failed to connect to TimescaleDB: {e}")
            return False

    def close(self):
        """Close database connection."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _ensure_connected(self) -> bool:
        """Reconnect if needed."""
        if self._conn is None:
            return self.connect()
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT 1")
            return True
        except psycopg2.Error:
            logger.warning("TimescaleDB connection lost, reconnecting")
            self.close()
            return self.connect()

    def run(self) -> int:
        """
        Fetch unresolved signals, classify outcomes, update stock-service.

        Returns number of signals resolved.
        """
        signals = self._fetch_unresolved()
        if not signals:
            logger.debug("No unresolved signals to process")
            return 0

        if not self._ensure_connected():
            logger.error("Cannot connect to TimescaleDB, skipping outcome check")
            return 0

        resolved = 0
        for sig in signals:
            outcome = self._classify_outcome(sig)
            if outcome is None:
                continue

            if self._update_outcome(sig.id, outcome):
                resolved += 1
                logger.info(
                    f"Signal outcome: {sig.symbol} {sig.signal} "
                    f"(id={sig.id}, action={sig.action}) -> {outcome}"
                )

        if resolved > 0:
            logger.info(f"Resolved {resolved}/{len(signals)} signal outcomes")
        return resolved

    def _fetch_unresolved(self) -> List[UnresolvedSignal]:
        """Fetch unresolved signals from stock-service REST API."""
        try:
            resp = requests.get(
                f"{self._stock_service_url}/api/v1/feedback/unresolved",
                params={"limit": "200"},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return []
            return [UnresolvedSignal.from_dict(entry) for entry in data]
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch unresolved signals: {e}")
            return []

    def _classify_outcome(self, sig: UnresolvedSignal) -> Optional[str]:
        """
        Check price action after signal timestamp to classify outcome.

        For BUY signals:
          - Price hit stop_price (low <= stop) -> STOPPED_OUT
          - Price hit target_2 (high >= target_2) -> TARGET_2_HIT
          - Price hit target_1 (high >= target_1) -> TARGET_1_HIT
          - valid_until passed with no hit -> EXPIRED

        Checks bars in chronological order so the first level hit wins.
        Stop is checked before targets on each bar (conservative).
        """
        if sig.entry_price <= 0 or sig.stop_price <= 0:
            return None

        # Determine lookforward window
        start_time = sig.feedback_timestamp
        if sig.valid_until and sig.valid_until > start_time:
            end_time = sig.valid_until
        else:
            end_time = start_time + timedelta(days=self._max_lookforward_days)

        now = datetime.now(timezone.utc)

        # Need at least 1 trading day of data after signal
        min_data_time = start_time + timedelta(hours=6)
        if now < min_data_time:
            return None  # Too soon to classify

        # Cap end_time at now
        if end_time > now:
            end_time = now

        bars = self._get_daily_bars(sig.symbol, start_time, end_time)
        if not bars:
            # If valid_until has passed and we have no data, mark expired
            if sig.valid_until and now > sig.valid_until:
                return EXPIRED
            return None

        is_buy = sig.signal.upper() == "BUY"

        for bar in bars:
            high = float(bar["high"])
            low = float(bar["low"])

            if is_buy:
                # Check stop first (conservative)
                if sig.stop_price > 0 and low <= sig.stop_price:
                    return STOPPED_OUT
                # Check target_2 first (higher target takes priority)
                if sig.target_2 > 0 and high >= sig.target_2:
                    return TARGET_2_HIT
                if sig.target_1 > 0 and high >= sig.target_1:
                    return TARGET_1_HIT
            else:
                # SELL signal — inverted logic
                if sig.stop_price > 0 and high >= sig.stop_price:
                    return STOPPED_OUT
                if sig.target_2 > 0 and low <= sig.target_2:
                    return TARGET_2_HIT
                if sig.target_1 > 0 and low <= sig.target_1:
                    return TARGET_1_HIT

        # No level hit — check if expired
        if sig.valid_until and now > sig.valid_until:
            return EXPIRED

        # Max lookforward exceeded
        expired_cutoff = start_time + timedelta(days=self._max_lookforward_days)
        if now > expired_cutoff:
            return EXPIRED

        return None  # Still within window, no outcome yet

    def _get_daily_bars(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
    ) -> List[dict]:
        """Get daily OHLCV bars from TimescaleDB."""
        query = """
            SELECT
                time_bucket('1 day', time) AS date,
                first(open, time) AS open,
                max(high) AS high,
                min(low) AS low,
                last(close, time) AS close,
                sum(volume) AS volume
            FROM ohlcv_1min
            WHERE symbol = %s
              AND time >= %s
              AND time <= %s
            GROUP BY date
            ORDER BY date ASC
        """

        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (symbol, start_time, end_time))
                return cur.fetchall()
        except psycopg2.Error as e:
            logger.error(f"Error fetching bars for {symbol}: {e}")
            try:
                self._conn.rollback()
            except Exception:
                pass
            return []

    def _update_outcome(self, feedback_id: int, outcome: str) -> bool:
        """PUT outcome to stock-service REST API."""
        try:
            resp = requests.put(
                f"{self._stock_service_url}/api/v1/feedback/{feedback_id}/outcome",
                json={"outcome": outcome},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.warning(
                f"Failed to update outcome for feedback {feedback_id}: {e}"
            )
            return False
