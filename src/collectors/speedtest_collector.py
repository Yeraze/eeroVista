"""Speedtest collector for passive speedtest result collection."""

import logging
from datetime import datetime

from src.collectors.base import BaseCollector
from src.models.database import Speedtest

logger = logging.getLogger(__name__)


class SpeedtestCollector(BaseCollector):
    """Passively collects speedtest results run by Eero (read-only)."""

    def collect(self) -> dict:
        """Collect speedtest results from Eero API."""
        try:
            # Get network info to access speedtest endpoint
            networks = self.eero_client.get_networks()
            if not networks:
                logger.warning("No networks found")
                return {"items_collected": 0, "errors": 1}

            network_url = networks[0].get("url")
            if not network_url:
                return {"items_collected": 0, "errors": 1}

            # Try to get speedtest results
            # Note: The exact endpoint might vary based on eero-client implementation
            try:
                eero = self.eero_client._get_client()
                speedtest_data = eero.get(network_url + "/speedtest")

                if not speedtest_data:
                    # No speedtest data available
                    return {"items_collected": 0, "errors": 0}

                # Check if we already have this speedtest result
                # (to avoid duplicates)
                test_date = speedtest_data.get("date")
                if test_date:
                    # Check if we already have a test from this time
                    existing = (
                        self.db.query(Speedtest)
                        .filter(Speedtest.timestamp >= test_date)
                        .first()
                    )

                    if existing:
                        # Already have this result
                        return {"items_collected": 0, "errors": 0}

                # Create speedtest record
                speedtest = Speedtest(
                    timestamp=datetime.fromisoformat(test_date)
                    if test_date
                    else datetime.utcnow(),
                    download_mbps=speedtest_data.get("down", {}).get("value"),
                    upload_mbps=speedtest_data.get("up", {}).get("value"),
                    latency_ms=speedtest_data.get("latency", {}).get("value"),
                    jitter_ms=None,  # Not typically provided by Eero
                    server_location=speedtest_data.get("server", {}).get("location"),
                    isp=speedtest_data.get("isp"),
                )
                self.db.add(speedtest)
                self.db.commit()

                return {"items_collected": 1, "errors": 0}

            except Exception as e:
                # Speedtest endpoint might not be available or data format might differ
                logger.debug(f"Could not fetch speedtest data: {e}")
                return {"items_collected": 0, "errors": 0}

        except Exception as e:
            self.db.rollback()
            raise
