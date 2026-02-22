"""
Position and trade models matching trading-journal schema.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class Trade:
    """Trade record from journal_trades table."""

    id: int
    order_id: str
    symbol: str
    side: str  # "buy" or "sell"
    quantity: float
    price: float
    total_amount: float
    fees: float
    executed_at: datetime
    position_id: Optional[int] = None
    created_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: Dict) -> "Trade":
        """Create from database row."""
        return cls(
            id=row["id"],
            order_id=row["order_id"],
            symbol=row["symbol"],
            side=row["side"],
            quantity=float(row["quantity"]),
            price=float(row["price"]),
            total_amount=float(row["total_amount"]),
            fees=float(row.get("fees", 0)),
            executed_at=row["executed_at"],
            position_id=row.get("position_id"),
            created_at=row.get("created_at"),
        )


@dataclass
class Position:
    """Position record from journal_positions table."""

    id: int
    symbol: str
    entry_order_id: str
    entry_price: float
    quantity: float
    entry_date: datetime
    status: str  # "open" or "closed"

    # Exit fields (optional for open positions)
    exit_order_id: Optional[str] = None
    exit_price: Optional[float] = None
    exit_date: Optional[datetime] = None
    realized_pl: Optional[float] = None
    realized_pl_pct: Optional[float] = None
    holding_days: Optional[int] = None

    # Analysis fields (added by reporting-service)
    rule_compliance_score: Optional[float] = None
    entry_signal_confidence: Optional[float] = None
    entry_signal_type: Optional[str] = None
    position_size_deviation: Optional[float] = None
    exit_type: Optional[str] = None  # profit_target, stop_loss, manual, time_based
    risk_metrics_at_entry: Optional[Dict] = None
    analysis_notes: Optional[str] = None
    analyzed_at: Optional[datetime] = None

    created_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: Dict) -> "Position":
        """Create from database row."""
        return cls(
            id=row["id"],
            symbol=row["symbol"],
            entry_order_id=row["entry_order_id"],
            entry_price=float(row["entry_price"]),
            quantity=float(row["quantity"]),
            entry_date=row["entry_date"],
            status=row["status"],
            exit_order_id=row.get("exit_order_id"),
            exit_price=float(row["exit_price"]) if row.get("exit_price") is not None else None,
            exit_date=row.get("exit_date"),
            realized_pl=float(row["realized_pl"]) if row.get("realized_pl") is not None else None,
            realized_pl_pct=(
                float(row["realized_pl_pct"]) if row.get("realized_pl_pct") is not None else None
            ),
            holding_days=row.get("holding_days"),
            rule_compliance_score=(
                float(row["rule_compliance_score"])
                if row.get("rule_compliance_score") is not None
                else None
            ),
            entry_signal_confidence=(
                float(row["entry_signal_confidence"])
                if row.get("entry_signal_confidence") is not None
                else None
            ),
            entry_signal_type=row.get("entry_signal_type"),
            position_size_deviation=(
                float(row["position_size_deviation"])
                if row.get("position_size_deviation") is not None
                else None
            ),
            exit_type=row.get("exit_type"),
            risk_metrics_at_entry=cls._parse_risk_metrics(
                row.get("risk_metrics_at_entry")
            ),
            analyzed_at=row.get("analyzed_at"),
            created_at=row.get("created_at"),
        )

    @staticmethod
    def _parse_risk_metrics(raw) -> Optional[Dict]:
        """Parse risk_metrics_at_entry from DB (JSONB comes as dict or str)."""
        if raw is None:
            return None
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return None
        return None

    @property
    def is_winner(self) -> bool:
        """Check if this was a winning trade."""
        return self.realized_pl is not None and self.realized_pl > 0

    @property
    def is_analyzed(self) -> bool:
        """Check if this position has been analyzed."""
        return self.analyzed_at is not None


@dataclass
class JournalEntry:
    """Journal entry from journal_entries table."""

    id: int
    position_id: int
    symbol: str
    entry_reasoning: Optional[str] = None
    exit_reasoning: Optional[str] = None
    what_worked: Optional[str] = None
    what_didnt_work: Optional[str] = None
    lessons_learned: Optional[str] = None
    emotional_state: Optional[str] = None
    would_repeat: Optional[bool] = None
    rating: Optional[int] = None
    tags: List[str] = field(default_factory=list)
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: Dict) -> "JournalEntry":
        """Create from database row."""
        return cls(
            id=row["id"],
            position_id=row["position_id"],
            symbol=row["symbol"],
            entry_reasoning=row.get("entry_reasoning"),
            exit_reasoning=row.get("exit_reasoning"),
            what_worked=row.get("what_worked"),
            what_didnt_work=row.get("what_didnt_work"),
            lessons_learned=row.get("lessons_learned"),
            emotional_state=row.get("emotional_state"),
            would_repeat=row.get("would_repeat"),
            rating=row.get("rating"),
            tags=row.get("tags", []),
            notes=row.get("notes"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
