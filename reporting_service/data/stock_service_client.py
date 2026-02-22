"""
Stock-service REST client.

Reads signal feedback entries from stock-service's PostgreSQL-backed
REST API, replacing the old Redis-based FeedbackReader.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class FeedbackEntry:
    """A single feedback entry from stock-service."""

    symbol: str
    signal: str
    action: str  # "traded" or "skipped"
    confidence: float = 0.0
    feedback_timestamp: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: dict) -> "FeedbackEntry":
        ts = None
        if data.get("feedback_timestamp"):
            try:
                ts = datetime.fromisoformat(
                    str(data["feedback_timestamp"]).replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass
        return cls(
            symbol=data.get("symbol", ""),
            signal=data.get("signal", ""),
            action=data.get("action", ""),
            confidence=data.get("confidence", 0.0),
            feedback_timestamp=ts,
        )


class StockServiceClient:
    """Reads feedback data from stock-service REST API."""

    def __init__(self, base_url: str = "http://stock-service:8081"):
        self._base_url = base_url.rstrip("/")
        self._timeout = 10

    def get_feedback(
        self,
        since_days: int = 90,
        symbol: Optional[str] = None,
    ) -> List[FeedbackEntry]:
        """Get feedback entries from stock-service."""
        params: Dict[str, str] = {"since_days": str(since_days)}
        if symbol:
            params["symbol"] = symbol

        try:
            resp = requests.get(
                f"{self._base_url}/api/v1/feedback",
                params=params,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            if data is None:
                return []
            return [FeedbackEntry.from_dict(entry) for entry in data]
        except requests.RequestException as e:
            logger.warning(f"Failed to get feedback from stock-service: {e}")
            return []

    def get_feedback_summary(self) -> Dict[str, int]:
        """Get aggregate feedback counts from stock-service."""
        try:
            resp = requests.get(
                f"{self._base_url}/api/v1/feedback/summary",
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning(f"Failed to get feedback summary from stock-service: {e}")
            return {"total": 0, "traded": 0, "skipped": 0}
