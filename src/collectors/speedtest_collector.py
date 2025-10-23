"""Speedtest collector for passive speedtest result collection."""

import logging
from datetime import datetime

from src.collectors.base import BaseCollector
from src.models.database import Speedtest

logger = logging.getLogger(__name__)


class SpeedtestCollector(BaseCollector):
    """Passively collects speedtest results run by Eero (read-only)."""

    def collect(self) -> dict:
        """Collect speedtest results from Eero API for all networks."""
        total_collected = 0
        total_errors = 0
        networks_processed = 0

        try:
            # Get all networks
            networks = self.eero_client.get_networks()
            if not networks:
                logger.warning("No networks found")
                return {"items_collected": 0, "errors": 1, "networks": 0}

            logger.info(f"Collecting speedtest data for {len(networks)} network(s)")

            # Process each network
            for network in networks:
                # Networks can be Pydantic models or dicts, handle both
                if isinstance(network, dict):
                    network_name = network.get('name')
                else:
                    network_name = network.name

                if not network_name:
                    logger.warning("Network has no name, skipping")
                    continue

                logger.info(f"Processing network: {network_name}")

                try:
                    result = self._collect_for_network(network_name)
                    total_collected += result.get("items_collected", 0)
                    total_errors += result.get("errors", 0)
                    networks_processed += 1
                except Exception as e:
                    logger.error(f"Error collecting for network '{network_name}': {e}")
                    total_errors += 1

            return {
                "items_collected": total_collected,
                "errors": total_errors,
                "networks": networks_processed
            }

        except Exception as e:
            logger.error(f"Error in speedtest collector: {e}")
            self.db.rollback()
            return {"items_collected": 0, "errors": 1, "networks": 0}

    def _collect_for_network(self, network_name: str) -> dict:
        """Collect speedtest results for a specific network."""
        try:
            # Try to get speedtest results from network client
            network_client = self.eero_client.get_network_client(network_name)

            if not network_client:
                logger.warning(f"Network client for '{network_name}' not found")
                return {"items_collected": 0, "errors": 1}

            # Get speedtest data from network details
            speedtest_data = network_client.speedtest

            if not speedtest_data:
                # No speedtest data available
                logger.debug(f"No speedtest data available for network '{network_name}'")
                return {"items_collected": 0, "errors": 0}

            # Check if we already have this speedtest result (to avoid duplicates)
            test_date = speedtest_data.date
            if test_date:
                # Check if we already have a test from this time for this network
                existing = (
                    self.db.query(Speedtest)
                    .filter(Speedtest.network_name == network_name)
                    .filter(Speedtest.timestamp >= test_date)
                    .first()
                )

                if existing:
                    # Already have this result
                    logger.debug(f"Speedtest result for network '{network_name}' already exists")
                    return {"items_collected": 0, "errors": 0}

            # Create speedtest record
            speedtest = Speedtest(
                network_name=network_name,
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

            logger.info(f"Network '{network_name}' speedtest result collected")
            return {"items_collected": 1, "errors": 0}

        except Exception as e:
            self.db.rollback()
            # Speedtest endpoint might not be available or data format might differ
            logger.debug(f"Could not fetch speedtest data for network '{network_name}': {e}")
            return {"items_collected": 0, "errors": 0}
