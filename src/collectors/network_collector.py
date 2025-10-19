"""Network collector for overall network statistics."""

import logging
from datetime import datetime

from src.collectors.base import BaseCollector
from src.models.database import NetworkMetric

logger = logging.getLogger(__name__)


class NetworkCollector(BaseCollector):
    """Collects network-wide statistics."""

    def collect(self) -> dict:
        """Collect network metrics from Eero API."""
        try:
            # Get network info
            networks = self.eero_client.get_networks()
            if not networks:
                logger.warning("No networks found")
                return {"items_collected": 0, "errors": 1}

            # Use first network
            network = networks[0]

            # Count devices
            devices_data = self.eero_client.get_devices()
            total_devices = len(devices_data) if devices_data else 0
            online_devices = (
                sum(1 for d in devices_data if (d.get("connected") if isinstance(d, dict) else d.connected))
                if devices_data
                else 0
            )

            # Get full network details from network client
            eero = self.eero_client._get_client()
            network_client = eero.network_clients.get(network.name)

            if not network_client:
                logger.warning(f"Network client for '{network.name}' not found")
                return {"items_collected": 0, "errors": 1}

            # Get full network details
            network_details = network_client.networks

            # Check guest network status
            guest_enabled = network_details.guest_network.enabled if hasattr(network_details, 'guest_network') else False

            # WAN status
            wan_status = network_details.status if hasattr(network_details, 'status') else "unknown"

            # Create network metric record
            metric = NetworkMetric(
                timestamp=datetime.utcnow(),
                total_devices=total_devices,
                total_devices_online=online_devices,
                guest_network_enabled=guest_enabled,
                wan_status=wan_status,
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
