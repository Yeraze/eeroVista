"""Configuration management for eeroVista."""

import os
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "eeroVista"
    version: str = "0.2.2"
    debug: bool = False

    # Database
    database_path: str = "/data/eerovista.db"

    # Collection intervals (seconds)
    collection_interval_devices: int = 30
    collection_interval_network: int = 60

    # Data retention (days)
    data_retention_raw_days: int = 7
    data_retention_hourly_days: int = 30
    data_retention_daily_days: int = 365

    # Logging
    log_level: str = "INFO"

    # Eero authentication (optional - normally stored in database)
    eero_session_token: Optional[str] = None

    # Encryption key for storing sensitive data (auto-generated if not provided)
    encryption_key: Optional[str] = None

    class Config:
        """Pydantic config."""

        env_file = ".env"
        case_sensitive = False


def get_settings() -> Settings:
    """Get application settings singleton."""
    return Settings()


def ensure_data_directory() -> Path:
    """Ensure data directory exists and return Path object."""
    settings = get_settings()
    db_path = Path(settings.database_path)
    data_dir = db_path.parent

    # Create directory if it doesn't exist
    data_dir.mkdir(parents=True, exist_ok=True)

    return data_dir
