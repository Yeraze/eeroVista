"""Base collector class for all data collectors."""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.eero_client import EeroClientWrapper
from src.models.database import Config

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """Base class for all data collectors."""

    def __init__(self, db: Session, eero_client: EeroClientWrapper):
        """Initialize collector."""
        self.db = db
        self.eero_client = eero_client
        self.name = self.__class__.__name__

    @abstractmethod
    def collect(self) -> dict:
        """
        Collect data and store in database.

        Returns:
            dict with collection stats (items_collected, errors, etc.)
        """
        pass

    def update_last_collection(self, collector_type: str) -> None:
        """Update the last collection timestamp for this collector type."""
        try:
            timestamp = datetime.utcnow().isoformat()
            config_key = f"last_collection_{collector_type}"

            config = self.db.query(Config).filter(Config.key == config_key).first()
            if config:
                config.value = timestamp
            else:
                config = Config(key=config_key, value=timestamp)
                self.db.add(config)

            self.db.commit()
            logger.debug(f"Updated {config_key} to {timestamp}")

        except Exception as e:
            logger.error(f"Failed to update last collection timestamp: {e}")
            self.db.rollback()

    def get_last_collection(self, collector_type: str) -> Optional[datetime]:
        """Get the last collection timestamp for this collector type."""
        try:
            config_key = f"last_collection_{collector_type}"
            config = self.db.query(Config).filter(Config.key == config_key).first()

            if config and config.value:
                return datetime.fromisoformat(config.value)
            return None

        except Exception as e:
            logger.error(f"Failed to get last collection timestamp: {e}")
            return None

    def run(self) -> dict:
        """
        Run the collector with error handling and logging.

        Returns:
            dict with collection stats
        """
        logger.info(f"Starting {self.name}")
        start_time = datetime.utcnow()

        try:
            # Check authentication
            if not self.eero_client.is_authenticated():
                logger.warning(f"{self.name} skipped - not authenticated")
                return {
                    "success": False,
                    "error": "Not authenticated",
                    "duration_seconds": 0,
                }

            # Run collection
            result = self.collect()

            # Update timestamp
            collector_type = self.name.replace("Collector", "").lower()
            self.update_last_collection(collector_type)

            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.info(
                f"{self.name} completed in {duration:.2f}s - "
                f"{result.get('items_collected', 0)} items"
            )

            return {
                "success": True,
                "duration_seconds": duration,
                **result,
            }

        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.error(f"{self.name} failed after {duration:.2f}s: {e}", exc_info=True)

            # Attempt session refresh on API failures
            if self._should_refresh_session(e):
                logger.warning(f"{self.name} attempting session refresh due to API error")
                try:
                    if self.eero_client.refresh_session():
                        logger.info(f"{self.name} session refresh successful")
                    else:
                        logger.warning(f"{self.name} session refresh failed")
                except Exception as refresh_error:
                    logger.error(f"{self.name} session refresh error: {refresh_error}")

            return {
                "success": False,
                "error": str(e),
                "duration_seconds": duration,
            }

    def _should_refresh_session(self, error: Exception) -> bool:
        """
        Determine if session refresh should be attempted based on error type.

        Args:
            error: The exception that occurred

        Returns:
            bool: True if session refresh should be attempted
        """
        error_str = str(error).lower()
        # Refresh on common API/network errors
        refresh_indicators = [
            "connection",
            "timeout",
            "unauthorized",
            "401",
            "403",
            "network",
            "unreachable",
            "refused",
        ]
        return any(indicator in error_str for indicator in refresh_indicators)
