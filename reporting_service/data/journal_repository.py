"""
Journal database repository.

Loads positions and trades from the trading-journal database
and updates positions with analysis results.
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from ..config import ReportingSettings
from ..models.position import JournalEntry, Position, Trade

logger = logging.getLogger(__name__)


class JournalRepository:
    """Repository for trading journal database operations."""

    def __init__(self, settings: ReportingSettings):
        self.settings = settings
        self._conn = None

    def connect(self) -> bool:
        """Connect to the journal database."""
        try:
            db = self.settings.database
            self._conn = psycopg2.connect(
                host=db.journal_host,
                port=db.journal_port,
                dbname=db.journal_db,
                user=db.journal_user,
                password=db.journal_password,
                connect_timeout=10,
                options="-c statement_timeout=30000",
            )
            self._conn.set_session(autocommit=False)
            logger.info(f"Connected to journal database at {db.journal_host}")
            return True
        except psycopg2.Error as e:
            logger.error(f"Failed to connect to journal database: {e}")
            return False

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _ensure_connected(self) -> bool:
        """Check connection health and reconnect if needed."""
        if self._conn is None:
            return self.connect()
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT 1")
            return True
        except psycopg2.Error:
            logger.warning("Journal database connection lost, reconnecting")
            self.close()
            return self.connect()

    def ensure_analysis_columns(self) -> None:
        """Ensure the analysis columns exist in journal_positions."""
        if not self._conn:
            return

        ALLOWED_TYPES = {
            "TEXT", "FLOAT", "INTEGER", "BOOLEAN", "TIMESTAMP",
            "VARCHAR(255)", "VARCHAR(20)", "VARCHAR(50)", "JSONB",
            "DECIMAL(10, 4)", "TIMESTAMP WITH TIME ZONE",
        }

        columns = [
            ("rule_compliance_score", "DECIMAL(10, 4)"),
            ("entry_signal_confidence", "DECIMAL(10, 4)"),
            ("entry_signal_type", "VARCHAR(20)"),
            ("position_size_deviation", "DECIMAL(10, 4)"),
            ("exit_type", "VARCHAR(50)"),
            ("risk_metrics_at_entry", "JSONB"),
            ("analysis_notes", "TEXT"),
            ("analyzed_at", "TIMESTAMP WITH TIME ZONE"),
        ]

        try:
            with self._conn.cursor() as cur:
                for col_name, col_type in columns:
                    if col_type.upper() not in ALLOWED_TYPES:
                        raise ValueError(f"Invalid column type: {col_type}")
                    cur.execute(
                        f'ALTER TABLE journal_positions ADD COLUMN IF NOT EXISTS "{col_name}" {col_type}'
                    )
            self._conn.commit()
            logger.info("Analysis columns ensured in journal_positions")
        except psycopg2.Error as e:
            logger.error(f"Error adding analysis columns: {e}")
            try:
                self._conn.rollback()
            except psycopg2.Error:
                pass

    MAX_QUERY_LIMIT = 10000

    def get_closed_positions(
        self,
        limit: Optional[int] = None,
        unanalyzed_only: bool = False,
        since: Optional[datetime] = None,
    ) -> List[Position]:
        """
        Get closed positions for analysis.

        Args:
            limit: Maximum number of positions to return
            unanalyzed_only: Only return positions without analysis
            since: Only return positions closed after this date

        Returns:
            List of Position objects
        """
        if not self._conn:
            return []

        query = """
            SELECT id, symbol, entry_order_id, exit_order_id,
                   entry_price, exit_price, quantity, entry_date, exit_date,
                   realized_pl, realized_pl_pct, holding_days, status,
                   rule_compliance_score, entry_signal_confidence,
                   entry_signal_type, position_size_deviation, exit_type,
                   risk_metrics_at_entry,
                   analyzed_at, created_at
            FROM journal_positions
            WHERE status = 'closed'
        """
        params = []

        if unanalyzed_only:
            query += " AND analyzed_at IS NULL"

        if since:
            query += " AND exit_date >= %s"
            params.append(since)

        query += " ORDER BY exit_date DESC"

        effective_limit = min(limit, self.MAX_QUERY_LIMIT) if limit else self.MAX_QUERY_LIMIT
        query += " LIMIT %s"
        params.append(effective_limit)

        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

            return [Position.from_row(dict(row)) for row in rows]

        except psycopg2.OperationalError as e:
            logger.error(f"Database connection error fetching positions: {e}")
            raise
        except psycopg2.Error as e:
            logger.error(f"Error fetching positions: {e}")
            return []

    def get_position_by_id(self, position_id: int) -> Optional[Position]:
        """Get a single position by ID."""
        if not self._conn:
            return None

        query = """
            SELECT id, symbol, entry_order_id, exit_order_id,
                   entry_price, exit_price, quantity, entry_date, exit_date,
                   realized_pl, realized_pl_pct, holding_days, status,
                   rule_compliance_score, entry_signal_confidence,
                   entry_signal_type, position_size_deviation, exit_type,
                   risk_metrics_at_entry,
                   analyzed_at, created_at
            FROM journal_positions
            WHERE id = %s
        """

        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (position_id,))
                row = cur.fetchone()

            if row:
                return Position.from_row(dict(row))
            return None

        except psycopg2.Error as e:
            logger.error(f"Error fetching position {position_id}: {e}")
            return None

    def get_positions_by_ids(self, position_ids: List[int]) -> List[Position]:
        if not position_ids or not self._conn:
            return []
        placeholders = ",".join(["%s"] * len(position_ids))
        query = f"""
            SELECT id, symbol, entry_order_id, exit_order_id,
                   entry_price, exit_price, quantity, entry_date, exit_date,
                   realized_pl, realized_pl_pct, holding_days, status,
                   rule_compliance_score, entry_signal_confidence,
                   entry_signal_type, position_size_deviation, exit_type,
                   risk_metrics_at_entry,
                   analyzed_at, created_at
            FROM journal_positions
            WHERE id IN ({placeholders})
        """
        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, list(position_ids))
                rows = cur.fetchall()
            return [Position.from_row(dict(row)) for row in rows]
        except psycopg2.Error as e:
            logger.error(f"Error fetching positions by ids: {e}")
            return []

    def get_trades_for_position(self, position_id: int) -> List[Trade]:
        """Get all trades associated with a position."""
        if not self._conn:
            return []

        query = """
            SELECT id, order_id, symbol, side, quantity, price,
                   total_amount, fees, executed_at, position_id, created_at
            FROM journal_trades
            WHERE position_id = %s
            ORDER BY executed_at
        """

        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (position_id,))
                rows = cur.fetchall()

            return [Trade.from_row(dict(row)) for row in rows]

        except psycopg2.Error as e:
            logger.error(f"Error fetching trades for position {position_id}: {e}")
            return []

    def get_entry_trade(self, entry_order_id: str) -> Optional[Trade]:
        """Get the entry trade by order ID."""
        if not self._conn:
            return None

        query = """
            SELECT id, order_id, symbol, side, quantity, price,
                   total_amount, fees, executed_at, position_id, created_at
            FROM journal_trades
            WHERE order_id = %s
        """

        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (entry_order_id,))
                row = cur.fetchone()

            if row:
                return Trade.from_row(dict(row))
            return None

        except psycopg2.Error as e:
            logger.error(f"Error fetching trade {entry_order_id}: {e}")
            return None

    def get_journal_entry(self, position_id: int) -> Optional[JournalEntry]:
        """Get journal entry for a position."""
        if not self._conn:
            return None

        query = """
            SELECT id, position_id, symbol, entry_reasoning, exit_reasoning,
                   what_worked, what_didnt_work, lessons_learned,
                   emotional_state, would_repeat, rating, tags, notes,
                   created_at, updated_at
            FROM journal_entries
            WHERE position_id = %s
        """

        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (position_id,))
                row = cur.fetchone()

            if row:
                return JournalEntry.from_row(dict(row))
            return None

        except psycopg2.Error as e:
            logger.error(f"Error fetching journal entry for {position_id}: {e}")
            return None

    def update_position_analysis(
        self,
        position_id: int,
        rule_compliance_score: float,
        entry_signal_confidence: float,
        entry_signal_type: Optional[str],
        position_size_deviation: float,
        exit_type: str,
        risk_metrics: Optional[Dict] = None,
        analysis_notes: Optional[str] = None,
    ) -> bool:
        """
        Update a position with analysis results.

        Args:
            position_id: Position to update
            rule_compliance_score: Overall compliance score (0-1)
            entry_signal_confidence: Confidence of entry signal
            entry_signal_type: Type of signal at entry (BUY, SELL, etc.)
            position_size_deviation: Deviation from recommended size
            exit_type: How the position was exited
            risk_metrics: Risk metrics at entry time
            analysis_notes: Additional notes

        Returns:
            True if update successful
        """
        if not self._conn:
            return False

        query = """
            UPDATE journal_positions
            SET rule_compliance_score = %s,
                entry_signal_confidence = %s,
                entry_signal_type = %s,
                position_size_deviation = %s,
                exit_type = %s,
                risk_metrics_at_entry = %s,
                analysis_notes = %s,
                analyzed_at = %s
            WHERE id = %s
        """

        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    query,
                    (
                        rule_compliance_score,
                        entry_signal_confidence,
                        entry_signal_type,
                        position_size_deviation,
                        exit_type,
                        json.dumps(risk_metrics) if risk_metrics else None,
                        analysis_notes,
                        datetime.utcnow(),
                        position_id,
                    ),
                )
            self._conn.commit()
            logger.debug(f"Updated analysis for position {position_id}")
            return True

        except psycopg2.OperationalError as e:
            logger.error(f"Database connection error updating position {position_id}: {e}")
            raise
        except psycopg2.Error as e:
            logger.error(f"Error updating position {position_id}: {e}")
            try:
                self._conn.rollback()
            except psycopg2.Error:
                pass
            return False

    def get_analysis_stats(self) -> Dict:
        """Get aggregate statistics on analyzed positions."""
        if not self._conn:
            return {}

        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Total and analyzed counts
                cur.execute(
                    """
                    SELECT
                        COUNT(*) as total_closed,
                        COUNT(analyzed_at) as total_analyzed,
                        AVG(rule_compliance_score) as avg_compliance,
                        AVG(entry_signal_confidence) as avg_confidence,
                        AVG(ABS(position_size_deviation)) as avg_size_deviation
                    FROM journal_positions
                    WHERE status = 'closed'
                    """
                )
                stats = dict(cur.fetchone())

                # Exit type distribution
                cur.execute(
                    """
                    SELECT exit_type, COUNT(*) as count
                    FROM journal_positions
                    WHERE status = 'closed' AND exit_type IS NOT NULL
                    GROUP BY exit_type
                    """
                )
                stats["exit_types"] = {
                    row["exit_type"]: row["count"] for row in cur.fetchall()
                }

                # Compliance by win/loss
                cur.execute(
                    """
                    SELECT
                        CASE WHEN realized_pl > 0 THEN 'win' ELSE 'loss' END as outcome,
                        AVG(rule_compliance_score) as avg_compliance,
                        COUNT(*) as count
                    FROM journal_positions
                    WHERE status = 'closed' AND rule_compliance_score IS NOT NULL
                    GROUP BY outcome
                    """
                )
                stats["compliance_by_outcome"] = {
                    row["outcome"]: {
                        "avg_compliance": float(row["avg_compliance"]) if row["avg_compliance"] is not None else 0.0,
                        "count": row["count"],
                    }
                    for row in cur.fetchall()
                }

            return stats

        except psycopg2.Error as e:
            logger.error(f"Error fetching analysis stats: {e}")
            return {}
