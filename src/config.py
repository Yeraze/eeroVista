"""Configuration management for eeroVista."""

import logging
import os
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings

from src import __version__

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "eeroVista"
    version: str = __version__
    debug: bool = False

    # Database
    database_path: str = "/data/eerovista.db"

    # Timezone for date/time display and daily bandwidth aggregation
    # Use IANA timezone names (e.g., "America/Los_Angeles", "America/New_York", "Europe/London")
    # Supports both TZ (standard) and TIMEZONE environment variables, with TZ taking precedence
    # Defaults to UTC if not specified
    timezone: str = os.getenv("TZ", "UTC")

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

    # Notifications
    notification_check_interval: int = 60  # seconds between notification checks

    # MQTT (Home Assistant integration) - disabled by default
    mqtt_enabled: bool = False
    mqtt_broker: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: Optional[str] = None
    mqtt_password: Optional[str] = None
    mqtt_topic_prefix: str = "eerovista"
    mqtt_discovery_prefix: str = "homeassistant"
    mqtt_client_id: str = "eerovista"
    mqtt_publish_interval: int = 60  # seconds between MQTT publishes
    mqtt_qos: int = 1  # 0=at most once, 1=at least once, 2=exactly once
    mqtt_retain: bool = True  # retain messages for HA discovery

    def get_timezone(self) -> ZoneInfo:
        """Get the configured timezone as a ZoneInfo object."""
        try:
            return ZoneInfo(self.timezone)
        except Exception as e:
            # Fallback to UTC if timezone is invalid
            logger.warning(
                f"Invalid timezone '{self.timezone}': {e}. Falling back to UTC. "
                f"Use IANA timezone names (e.g., 'America/New_York', 'Europe/London')"
            )
            return ZoneInfo("UTC")

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
