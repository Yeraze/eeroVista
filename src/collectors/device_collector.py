"""Device collector for tracking connected devices."""

import logging
from datetime import datetime
from typing import Dict

from src.collectors.base import BaseCollector
from src.models.database import Device, DeviceConnection, EeroNode

logger = logging.getLogger(__name__)


class DeviceCollector(BaseCollector):
    """Collects device connection information and metrics."""

    def collect(self) -> dict:
        """Collect device metrics from Eero API."""
        devices_processed = 0
        errors = 0

        try:
            # Get eero nodes first
            eeros_data = self.eero_client.get_eeros()
            if not eeros_data:
                logger.warning("No eero nodes found")
                return {"items_collected": 0, "errors": 1}

            # Create/update eero nodes in database
            eero_node_map = self._process_eero_nodes(eeros_data)

            # Get devices from Eero API
            devices_data = self.eero_client.get_devices()
            if not devices_data:
                logger.warning("No devices found")
                return {"items_collected": 0, "errors": 0}

            # Process each device
            for device_data in devices_data:
                try:
                    self._process_device(device_data, eero_node_map)
                    devices_processed += 1
                except Exception as e:
                    logger.error(f"Error processing device: {e}")
                    errors += 1

            self.db.commit()

            return {
                "items_collected": devices_processed,
                "errors": errors,
                "nodes_count": len(eero_node_map),
            }

        except Exception as e:
            self.db.rollback()
            raise

    def _process_eero_nodes(self, eeros_data: list) -> Dict[str, int]:
        """
        Process eero nodes and return mapping of eero_id to database id.

        Returns:
            Dict mapping eero API URL to database ID
        """
        eero_node_map = {}

        for eero_data in eeros_data:
            try:
                eero_url = eero_data.get("url", "")
                if not eero_url:
                    continue

                # Extract eero_id from URL (last part)
                eero_id = eero_url.split("/")[-1]

                # Check if node exists
                node = (
                    self.db.query(EeroNode)
                    .filter(EeroNode.eero_id == eero_id)
                    .first()
                )

                if not node:
                    # Create new node
                    node = EeroNode(
                        eero_id=eero_id,
                        location=eero_data.get("location", {}).get("name"),
                        model=eero_data.get("model"),
                        mac_address=eero_data.get("mac_address"),
                        is_gateway=eero_data.get("gateway", False),
                    )
                    self.db.add(node)
                    self.db.flush()  # Get the ID
                else:
                    # Update existing node
                    node.location = eero_data.get("location", {}).get("name")
                    node.model = eero_data.get("model")
                    node.mac_address = eero_data.get("mac_address")
                    node.is_gateway = eero_data.get("gateway", False)
                    node.last_seen = datetime.utcnow()

                eero_node_map[eero_url] = node.id

            except Exception as e:
                logger.error(f"Error processing eero node: {e}")

        return eero_node_map

    def _process_device(self, device_data: dict, eero_node_map: Dict[str, int]) -> None:
        """Process a single device and create connection record."""
        # Get device MAC address
        mac_address = device_data.get("mac")
        if not mac_address:
            logger.warning("Device missing MAC address, skipping")
            return

        # Get or create device
        device = (
            self.db.query(Device).filter(Device.mac_address == mac_address).first()
        )

        if not device:
            device = Device(
                mac_address=mac_address,
                hostname=device_data.get("hostname"),
                nickname=device_data.get("nickname"),
                device_type=self._guess_device_type(device_data),
                first_seen=datetime.utcnow(),
            )
            self.db.add(device)
            self.db.flush()  # Get the ID
        else:
            # Update device info
            device.hostname = device_data.get("hostname") or device.hostname
            device.nickname = device_data.get("nickname") or device.nickname
            device.last_seen = datetime.utcnow()

        # Get connection info
        is_connected = device_data.get("connected", False)
        connection_type = device_data.get("connection_type", "wireless")

        # Get connected eero node
        eero_node_id = None
        connected_to = device_data.get("source", {}).get("location")
        if connected_to:
            # Try to match by eero URL
            eero_url = device_data.get("source", {}).get("url")
            if eero_url and eero_url in eero_node_map:
                eero_node_id = eero_node_map[eero_url]

        # Get signal and bandwidth info
        signal_strength = None
        bandwidth_down = None
        bandwidth_up = None

        # Signal strength (for wireless connections)
        if connection_type == "wireless":
            # Signal is in the wireless dict
            wireless_data = device_data.get("wireless", {})
            signal_strength = wireless_data.get("signal_strength")

        # Bandwidth (if available)
        usage = device_data.get("usage", {})
        if usage:
            bandwidth_down = usage.get("download_mbps")
            bandwidth_up = usage.get("upload_mbps")

        # Create connection record
        connection = DeviceConnection(
            device_id=device.id,
            eero_node_id=eero_node_id,
            timestamp=datetime.utcnow(),
            is_connected=is_connected,
            connection_type=connection_type,
            signal_strength=signal_strength,
            ip_address=device_data.get("ip"),
            bandwidth_down_mbps=bandwidth_down,
            bandwidth_up_mbps=bandwidth_up,
        )
        self.db.add(connection)

    def _guess_device_type(self, device_data: dict) -> str:
        """Guess device type based on available data."""
        # Check device_type field first
        device_type = device_data.get("device_type")
        if device_type:
            return device_type

        # Try to guess from manufacturer or hostname
        manufacturer = device_data.get("manufacturer", "").lower()
        hostname = device_data.get("hostname", "").lower()

        if any(x in manufacturer or x in hostname for x in ["apple", "iphone", "ipad", "mac"]):
            return "mobile"
        elif any(x in manufacturer or x in hostname for x in ["samsung", "android"]):
            return "mobile"
        elif any(x in manufacturer or x in hostname for x in ["tv", "roku", "chromecast"]):
            return "entertainment"
        elif any(x in manufacturer or x in hostname for x in ["printer", "canon", "hp"]):
            return "printer"
        else:
            return "unknown"
