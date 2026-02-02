"""
Reporting Service - Trade analysis and rule compliance reporting.

Analyzes historical trades against decision-engine rules to identify
deviations and update journal positions with compliance metrics.
"""

from .analyzer import TradeAnalyzer
from .runner import ReportingRunner

__version__ = "0.1.0"
__all__ = ["TradeAnalyzer", "ReportingRunner"]
