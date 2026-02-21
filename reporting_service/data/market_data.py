"""
Market data loader for historical indicators.

Fetches indicator values from TimescaleDB at specific points in time
for rule evaluation.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from ..config import ReportingSettings

logger = logging.getLogger(__name__)


class MarketDataLoader:
    """Loads historical market data and indicators from TimescaleDB."""

    def __init__(self, settings: ReportingSettings):
        self.settings = settings
        self._conn = None

    def connect(self) -> bool:
        """Connect to TimescaleDB."""
        try:
            db = self.settings.database
            self._conn = psycopg2.connect(
                host=db.timescale_host,
                port=db.timescale_port,
                dbname=db.timescale_db,
                user=db.timescale_user,
                password=db.timescale_password,
            )
            logger.info(f"Connected to TimescaleDB at {db.timescale_host}")
            return True
        except psycopg2.Error as e:
            logger.error(f"Failed to connect to TimescaleDB: {e}")
            return False

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def get_indicators_at_time(
        self,
        symbol: str,
        timestamp: datetime,
        lookback_minutes: int = 60,
    ) -> Optional[Dict[str, float]]:
        """
        Get indicator values around a specific timestamp.

        Looks for the closest indicator record within the lookback window.

        Args:
            symbol: Stock symbol
            timestamp: Target timestamp
            lookback_minutes: How far back to look for data

        Returns:
            Dict of indicator values or None
        """
        if not self._conn:
            return None

        start_time = timestamp - timedelta(minutes=lookback_minutes)

        # Try to get from indicators table first
        indicators = self._get_from_indicators_table(symbol, start_time, timestamp)
        if indicators:
            return indicators

        # Fall back to computing from OHLCV
        return self._compute_from_ohlcv(symbol, timestamp)

    def _get_from_indicators_table(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Optional[Dict[str, float]]:
        """Get indicators from the indicators table if available."""
        # Check if indicators table exists and has data
        query = """
            SELECT *
            FROM stock_indicators
            WHERE symbol = %s
              AND time >= %s
              AND time <= %s
            ORDER BY time DESC
            LIMIT 1
        """

        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (symbol, start_time, end_time))
                row = cur.fetchone()

            if row:
                # Convert row to dict, excluding non-indicator columns
                indicators = {}
                exclude_cols = {"id", "symbol", "time", "created_at"}
                for key, value in dict(row).items():
                    if key not in exclude_cols and value is not None:
                        try:
                            indicators[key] = float(value)
                        except (ValueError, TypeError):
                            pass
                return indicators if indicators else None

        except psycopg2.Error as e:
            logger.debug(f"Indicators table query failed: {e}")

        return None

    def _compute_from_ohlcv(
        self,
        symbol: str,
        timestamp: datetime,
    ) -> Optional[Dict[str, float]]:
        """Compute basic indicators from OHLCV data."""
        # Get recent OHLCV data for computing indicators
        lookback_days = 250  # Enough for SMA 200

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
              AND time <= %s
              AND time >= %s - interval '250 days'
            GROUP BY date
            ORDER BY date DESC
            LIMIT 250
        """

        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (symbol, timestamp, timestamp))
                rows = cur.fetchall()

            if len(rows) < 20:
                logger.debug(f"Insufficient data for {symbol} at {timestamp}")
                return None

            # Convert to lists (most recent first)
            closes = [float(row["close"]) for row in rows]
            highs = [float(row["high"]) for row in rows]
            lows = [float(row["low"]) for row in rows]
            volumes = [float(row["volume"]) for row in rows]

            indicators = {
                "close": closes[0],
                "high": highs[0],
                "low": lows[0],
                "volume": volumes[0],
            }

            # Calculate SMAs
            if len(closes) >= 20:
                indicators["sma_20"] = sum(closes[:20]) / 20
            if len(closes) >= 50:
                indicators["sma_50"] = sum(closes[:50]) / 50
            if len(closes) >= 200:
                indicators["sma_200"] = sum(closes[:200]) / 200

            # Calculate ATR (14-period)
            if len(closes) >= 15:
                trs = []
                for i in range(1, 15):
                    tr = max(
                        highs[i - 1] - lows[i - 1],
                        abs(highs[i - 1] - closes[i]),
                        abs(lows[i - 1] - closes[i]),
                    )
                    trs.append(tr)
                indicators["atr_14"] = sum(trs) / len(trs)

            # Calculate RSI (14-period)
            if len(closes) >= 15:
                gains = []
                losses = []
                for i in range(14):
                    change = closes[i] - closes[i + 1]
                    if change > 0:
                        gains.append(change)
                        losses.append(0)
                    else:
                        gains.append(0)
                        losses.append(abs(change))

                avg_gain = sum(gains) / 14
                avg_loss = sum(losses) / 14

                if avg_loss > 0:
                    rs = avg_gain / avg_loss
                    indicators["rsi_14"] = 100 - (100 / (1 + rs))
                else:
                    indicators["rsi_14"] = 100

            # Average volume
            if len(volumes) >= 20:
                indicators["avg_volume_20"] = sum(volumes[:20]) / 20

            return indicators

        except psycopg2.Error as e:
            logger.error(f"Error computing indicators for {symbol}: {e}")
            return None

    def get_price_at_time(
        self,
        symbol: str,
        timestamp: datetime,
    ) -> Optional[float]:
        """Get the price at a specific time."""
        if not self._conn:
            return None

        # Look for closest price within 5 minutes
        query = """
            SELECT close
            FROM ohlcv_1min
            WHERE symbol = %s
              AND time <= %s
              AND time >= %s - interval '5 minutes'
            ORDER BY time DESC
            LIMIT 1
        """

        try:
            with self._conn.cursor() as cur:
                cur.execute(query, (symbol, timestamp, timestamp))
                row = cur.fetchone()

            if row:
                return float(row[0])
            return None

        except psycopg2.Error as e:
            logger.error(f"Error getting price for {symbol} at {timestamp}: {e}")
            return None

    def get_daily_returns(
        self,
        symbol: str,
        lookback_days: int = 252,
    ) -> Optional[List[float]]:
        """Get daily returns for VaR/risk calculations."""
        if not self._conn:
            return None

        lookback_days = int(lookback_days)  # ensure integer before interpolation
        fetch_days = lookback_days * 2
        query = f"""
            SELECT
                time_bucket('1 day', time) AS date,
                last(close, time) AS close
            FROM ohlcv_1min
            WHERE symbol = %s
              AND time >= NOW() - INTERVAL '{fetch_days} days'
            GROUP BY date
            ORDER BY date
        """

        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (symbol,))
                rows = cur.fetchall()

            if len(rows) < 2:
                return None

            closes = [float(row["close"]) for row in rows]
            returns = []
            for i in range(1, len(closes)):
                if closes[i - 1] > 0:
                    returns.append((closes[i] - closes[i - 1]) / closes[i - 1])

            return returns[-lookback_days:] if len(returns) > lookback_days else returns

        except psycopg2.Error as e:
            logger.error(f"Error getting returns for {symbol}: {e}")
            return None
