"""Device collector for tracking connected devices."""

import logging
from datetime import datetime, date
from typing import Dict, Optional

from src.collectors.base import BaseCollector
from src.models.database import Device, DeviceConnection, DailyBandwidth, EeroNode

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

            # Get devices from Eero API (primary source - has all devices)
            devices_data = self.eero_client.get_devices()
            if not devices_data:
                logger.warning("No devices found")
                return {"items_collected": 0, "errors": 0}

            logger.info(f"Retrieved {len(devices_data)} device entries from Eero devices API")

            # Get profiles to overlay usage data (profiles contain usage stats when available)
            profiles_data = self.eero_client.get_profiles()
            usage_map = {}
            if profiles_data:
                # Build a map of MAC address to usage data
                for profile in profiles_data:
                    if isinstance(profile, dict) and 'devices' in profile:
                        for device in profile['devices']:
                            mac = device.get('mac')
                            usage = device.get('usage')
                            if mac and usage:
                                usage_map[mac] = usage
                logger.info(f"Retrieved usage data for {len(usage_map)} devices from profiles")

            # Overlay usage data onto devices
            for device in devices_data:
                if isinstance(device, dict):
                    mac = device.get('mac')
                    if mac and mac in usage_map:
                        device['usage'] = usage_map[mac]

            # Count entry types for debugging
            type_counts = {}
            for entry in devices_data:
                t = type(entry).__name__
                type_counts[t] = type_counts.get(t, 0) + 1
            logger.info(f"Device entry types: {type_counts}")

            # Track network-wide bandwidth totals
            network_bandwidth_down = 0.0
            network_bandwidth_up = 0.0
            timestamp = datetime.utcnow()

            # Process each device
            for device_data in devices_data:
                try:
                    # Skip non-dict entries (sometimes API returns booleans)
                    if not isinstance(device_data, dict):
                        logger.debug(f"Skipping non-dict device entry: {type(device_data)}")
                        continue

                    self._process_device(device_data, eero_node_map)
                    devices_processed += 1

                    # Accumulate network-wide bandwidth
                    usage = device_data.get("usage")
                    if isinstance(usage, dict):
                        down = usage.get("down_mbps", 0.0) or 0.0
                        up = usage.get("up_mbps", 0.0) or 0.0
                        network_bandwidth_down += down
                        network_bandwidth_up += up

                except Exception as e:
                    device_name = device_data.get("nickname") or device_data.get("hostname") or device_data.get("mac", "unknown")
                    logger.error(f"Error processing device '{device_name}': {e}", exc_info=True)
                    errors += 1

            # Update network-wide bandwidth accumulation
            self._update_bandwidth_accumulation(
                device_id=None,  # None = network-wide
                bandwidth_down_mbps=network_bandwidth_down,
                bandwidth_up_mbps=network_bandwidth_up,
                timestamp=timestamp
            )

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
                # Handle both dict (from patched eero-client) and Pydantic model
                if isinstance(eero_data, dict):
                    eero_url = eero_data.get("url", "")
                    location_data = eero_data.get("location")
                    # Location might be a string or dict
                    if isinstance(location_data, dict):
                        location = location_data.get("name")
                    else:
                        location = location_data  # Already a string
                    model = eero_data.get("model")
                    mac_address = eero_data.get("mac_address")
                    is_gateway = eero_data.get("gateway", False)
                else:
                    # Pydantic model - use attribute access
                    eero_url = eero_data.url
                    location = eero_data.location.name if hasattr(eero_data.location, 'name') else eero_data.location
                    model = eero_data.model
                    mac_address = eero_data.mac_address
                    is_gateway = eero_data.gateway if hasattr(eero_data, 'gateway') else False

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
                        location=location,
                        model=model,
                        mac_address=mac_address,
                        is_gateway=is_gateway,
                    )
                    self.db.add(node)
                    self.db.flush()  # Get the ID
                else:
                    # Update existing node
                    node.location = location
                    node.model = model
                    node.mac_address = mac_address
                    node.is_gateway = is_gateway
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
        source = device_data.get("source")
        if isinstance(source, dict):
            connected_to = source.get("location")
            if connected_to:
                # Try to match by eero URL
                eero_url = source.get("url")
                if eero_url and eero_url in eero_node_map:
                    eero_node_id = eero_node_map[eero_url]

        # Get signal and bandwidth info
        signal_strength = None
        bandwidth_down = None
        bandwidth_up = None

        # Signal strength (for wireless connections)
        if connection_type == "wireless":
            # Signal is in the connectivity dict (not wireless which is a boolean)
            connectivity = device_data.get("connectivity")
            if isinstance(connectivity, dict):
                # Signal strength
                signal = connectivity.get("signal")
                if signal:
                    # Extract numeric value from signal string (e.g., "-43 dBm")
                    try:
                        signal_strength = int(signal.split()[0]) if isinstance(signal, str) else signal
                    except (ValueError, IndexError):
                        signal_strength = None

        # Actual bandwidth usage (available from profiles endpoint)
        # Note: Eero API only populates usage data periodically (hourly/daily)
        usage = device_data.get("usage")
        if isinstance(usage, dict):
            # Usage contains actual data transfer rates in Mbps
            bandwidth_down = usage.get("down_mbps")
            bandwidth_up = usage.get("up_mbps")

        # Create connection record
        timestamp = datetime.utcnow()
        connection = DeviceConnection(
            device_id=device.id,
            eero_node_id=eero_node_id,
            timestamp=timestamp,
            is_connected=is_connected,
            connection_type=connection_type,
            signal_strength=signal_strength,
            ip_address=device_data.get("ip"),
            bandwidth_down_mbps=bandwidth_down,
            bandwidth_up_mbps=bandwidth_up,
        )
        self.db.add(connection)

        # Update accumulated bandwidth statistics for this device
        self._update_bandwidth_accumulation(
            device_id=device.id,
            bandwidth_down_mbps=bandwidth_down,
            bandwidth_up_mbps=bandwidth_up,
            timestamp=timestamp
        )

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

    def _update_bandwidth_accumulation(
        self,
        device_id: Optional[int],
        bandwidth_down_mbps: Optional[float],
        bandwidth_up_mbps: Optional[float],
        timestamp: datetime
    ) -> None:
        """
        Update accumulated bandwidth statistics for a device or network-wide.

        Args:
            device_id: Device ID (None for network-wide totals)
            bandwidth_down_mbps: Current download rate in Mbps
            bandwidth_up_mbps: Current upload rate in Mbps
            timestamp: Current collection timestamp
        """
        if bandwidth_down_mbps is None or bandwidth_up_mbps is None:
            return

        today = date.today()

        # Get or create daily bandwidth record
        bandwidth_record = (
            self.db.query(DailyBandwidth)
            .filter(
                DailyBandwidth.device_id == device_id,
                DailyBandwidth.date == today
            )
            .first()
        )

        if not bandwidth_record:
            bandwidth_record = DailyBandwidth(
                device_id=device_id,
                date=today,
                download_mb=0.0,
                upload_mb=0.0,
                last_collection_time=None,
            )
            self.db.add(bandwidth_record)

        # Calculate accumulated bandwidth since last collection
        if bandwidth_record.last_collection_time:
            # Calculate time delta in seconds
            time_delta = (timestamp - bandwidth_record.last_collection_time).total_seconds()

            # Validate time delta is reasonable
            # Skip accumulation if time_delta is too large (>10 minutes) to prevent
            # inaccurate data from stale bandwidth rates
            MAX_TIME_DELTA = 600  # 10 minutes in seconds
            EXPECTED_INTERVAL = 60  # Expected collection interval in seconds

            if time_delta > MAX_TIME_DELTA:
                logger.warning(
                    f"Skipping bandwidth accumulation for device {device_id}: "
                    f"time delta ({time_delta:.1f}s) exceeds maximum ({MAX_TIME_DELTA}s). "
                    f"This usually indicates data collection was interrupted."
                )
            elif time_delta > EXPECTED_INTERVAL * 2:
                # Log warning but still accumulate if within max threshold
                logger.warning(
                    f"Large time delta detected for device {device_id}: "
                    f"{time_delta:.1f}s (expected ~{EXPECTED_INTERVAL}s). "
                    f"Bandwidth calculations may be less accurate."
                )

                # Convert Mbps to MB: (Mbps * seconds) / 8 bits per byte
                # Mbps = megabits per second, so Mbps * seconds = megabits
                # megabits / 8 = megabytes
                download_mb = (bandwidth_down_mbps * time_delta) / 8.0
                upload_mb = (bandwidth_up_mbps * time_delta) / 8.0

                # Add to accumulated totals
                bandwidth_record.download_mb += download_mb
                bandwidth_record.upload_mb += upload_mb

                logger.debug(
                    f"Accumulated bandwidth for device {device_id}: "
                    f"+{download_mb:.4f} MB down, +{upload_mb:.4f} MB up "
                    f"(delta: {time_delta:.1f}s)"
                )
            else:
                # Normal case: time delta is within expected range
                download_mb = (bandwidth_down_mbps * time_delta) / 8.0
                upload_mb = (bandwidth_up_mbps * time_delta) / 8.0

                # Add to accumulated totals
                bandwidth_record.download_mb += download_mb
                bandwidth_record.upload_mb += upload_mb

                logger.debug(
                    f"Accumulated bandwidth for device {device_id}: "
                    f"+{download_mb:.4f} MB down, +{upload_mb:.4f} MB up "
                    f"(delta: {time_delta:.1f}s)"
                )

        # Update last collection time for next calculation
        bandwidth_record.last_collection_time = timestamp
        bandwidth_record.updated_at = timestamp
