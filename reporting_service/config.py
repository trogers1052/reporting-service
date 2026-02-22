"""
Reporting service configuration.
"""

import os
from typing import Any, Dict, Optional

import yaml
from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings


class DatabaseConfig(BaseSettings):
    """Database connection configuration."""

    # Journal database (PostgreSQL)
    journal_host: str = "localhost"
    journal_port: int = 5432
    journal_db: str = "trading_journal"
    journal_user: str = "postgres"
    journal_password: str = ""

    # TimescaleDB for market data
    timescale_host: str = "localhost"
    timescale_port: int = 5432
    timescale_db: str = "market_data"
    timescale_user: str = "postgres"
    timescale_password: str = ""


class AnalysisConfig(BaseSettings):
    """Analysis configuration."""

    # Exit type detection thresholds
    profit_target_threshold: float = 0.05  # 5% gain = profit target
    stop_loss_threshold: float = -0.03  # 3% loss = stop loss

    # Position sizing tolerance
    position_size_tolerance: float = 0.20  # 20% deviation is acceptable

    # Lookback for indicator data
    indicator_lookback_minutes: int = 60  # Look back 1 hour for entry indicators

    # Minimum confidence to consider a signal valid
    min_signal_confidence: float = 0.50


class ReportingSettings(BaseSettings):
    """Main reporting service settings."""

    # Database configs
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)

    # Analysis configs
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)

    # Redis configuration (for rules cache)
    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379)
    redis_db: int = Field(default=1)
    redis_password: str = Field(default="")

    # Whether to use Redis rules cache (vs YAML file)
    use_redis_rules: bool = Field(default=True)

    # Decision engine rules config path (fallback if Redis unavailable)
    decision_engine_config: str = Field(
        default="/app/config/rules.yaml",
        alias="DECISION_ENGINE_CONFIG_PATH",
    )

    # Risk engine config path
    risk_engine_config: Optional[str] = Field(
        default="/app/config/risk_config.yaml",
        alias="RISK_ENGINE_CONFIG_PATH",
    )

    # Stock-service URL (for feedback data)
    stock_service_url: str = Field(default="http://stock-service:8081")

    # Output settings
    report_output_dir: str = Field(default="./reports")

    # Logging
    log_level: str = Field(default="INFO")

    # Daemon mode settings
    daemon_interval: int = Field(default=300)  # 5 minutes

    model_config = ConfigDict(
        env_prefix="REPORTING_",
        env_nested_delimiter="__",
    )

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "ReportingSettings":
        """Load settings from YAML file."""
        if not os.path.exists(yaml_path):
            return cls()

        with open(yaml_path, "r") as f:
            yaml_config = yaml.safe_load(f) or {}

        return cls._parse_yaml_config(yaml_config)

    @classmethod
    def _parse_yaml_config(cls, config: Dict) -> "ReportingSettings":
        """Parse YAML config into settings."""
        kwargs = {}

        if "database" in config:
            kwargs["database"] = DatabaseConfig(**config["database"])

        if "analysis" in config:
            kwargs["analysis"] = AnalysisConfig(**config["analysis"])

        for key in [
            "decision_engine_config",
            "risk_engine_config",
            "report_output_dir",
            "log_level",
        ]:
            if key in config:
                kwargs[key] = config[key]

        return cls(**kwargs)


def load_settings(config_path: Optional[str] = None) -> ReportingSettings:
    """Load reporting settings."""
    if config_path is None:
        # Look for config in standard locations
        search_paths = [
            "config/reporting_config.yaml",
            "/etc/reporting-service/config.yaml",
        ]
        for path in search_paths:
            if os.path.exists(path):
                config_path = path
                break

    if config_path:
        return ReportingSettings.from_yaml(config_path)

    return ReportingSettings()
