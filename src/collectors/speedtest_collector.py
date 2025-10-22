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

            # Networks can be Pydantic models or dicts, handle both
            first_network = networks[0]
            if isinstance(first_network, dict):
                network_name = first_network.get('name')
            else:
                network_name = first_network.name

            if not network_name:
                return {"items_collected": 0, "errors": 1}

            # Try to get speedtest results from network client
            try:
                eero = self.eero_client._get_client()
                network_client = eero.network_clients.get(network_name)

                if not network_client:
                    logger.warning(f"Network '{network_name}' not found")
                    return {"items_collected": 0, "errors": 1}

                # Get speedtest data from network details
                speedtest_data = network_client.speedtest

                if not speedtest_data:
                    # No speedtest data available
                    return {"items_collected": 0, "errors": 0}

                # Check if we already have this speedtest result (to avoid duplicates)
                test_date = speedtest_data.date
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
                    timestamp=test_date if test_date else datetime.utcnow(),
                    download_mbps=speedtest_data.down.value if speedtest_data.down else None,
                    upload_mbps=speedtest_data.up.value if speedtest_data.up else None,
                    latency_ms=None,  # Not typically provided by Eero
                    jitter_ms=None,  # Not typically provided by Eero
                    server_location=None,  # Not in the Speed model
                    isp=None,  # Not in the Speed model
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
