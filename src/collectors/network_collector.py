"""Network collector for overall network statistics."""

import logging
from datetime import datetime

from src.collectors.base import BaseCollector
from src.models.database import NetworkMetric

logger = logging.getLogger(__name__)


class NetworkCollector(BaseCollector):
    """Collects network-wide statistics."""

    def collect(self) -> dict:
        """Collect network metrics from Eero API for all networks."""
        total_collected = 0
        total_errors = 0
        networks_processed = 0

        try:
            # Get all networks
            networks = self.eero_client.get_networks()
            if not networks:
                logger.warning("No networks found")
                return {"items_collected": 0, "errors": 1, "networks": 0}

            logger.info(f"Collecting network metrics for {len(networks)} network(s)")

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
            logger.error(f"Error in network collector: {e}")
            self.db.rollback()
            return {"items_collected": 0, "errors": 1, "networks": 0}

    def _collect_for_network(self, network_name: str) -> dict:
        """Collect network metrics for a specific network."""
        try:
            # Count devices for this network
            devices_data = self.eero_client.get_devices(network_name=network_name)
            total_devices = len(devices_data) if devices_data else 0
            online_devices = (
                sum(1 for d in devices_data if (d.get("connected") if isinstance(d, dict) else d.connected))
                if devices_data
                else 0
            )

            # Get full network details from network client
            network_client = self.eero_client.get_network_client(network_name)

            if not network_client:
                logger.warning(f"Network client for '{network_name}' not found")
                return {"items_collected": 0, "errors": 1}

            # Get full network details (returns a dict)
            network_details = network_client.networks

            # Check guest network status
            guest_network = network_details.get('guest_network', {})
            guest_enabled = guest_network.get('enabled', False) if isinstance(guest_network, dict) else False

            # WAN status - access from dict
            raw_status = network_details.get('status', 'unknown')

            wan_status = self._map_wan_status(raw_status)
            logger.info(f"Network '{network_name}' WAN status: {raw_status} -> {wan_status}")

            # Get connection mode (bridge mode detection)
            connection = network_details.get('connection', {})
            connection_mode = connection.get('mode', None) if isinstance(connection, dict) else None
            if connection_mode:
                logger.info(f"Network '{network_name}' connection mode: {connection_mode}")

            # Create network metric record
            metric = NetworkMetric(
                network_name=network_name,
                timestamp=datetime.utcnow(),
                total_devices=total_devices,
                total_devices_online=online_devices,
                guest_network_enabled=guest_enabled,
                wan_status=wan_status,
                connection_mode=connection_mode,
            )
            self.db.add(metric)
            self.db.commit()

            return {
                "items_collected": 1,
                "errors": 0,
                "total_devices": total_devices,
                "online_devices": online_devices,
            }

        except Exception as e:
            self.db.rollback()
            raise

    def _map_wan_status(self, status: str) -> str:
        """Map eero API WAN status to our status format."""
        status_lower = status.lower()
        if status_lower == "connected":
            return "online"
        elif status_lower == "disconnected":
            return "offline"
        else:
            return "unknown"
