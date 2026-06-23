"""Data usage collector — polls eero's server-computed bandwidth totals."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

from src.collectors.base import BaseCollector
from src.models.database import DailyBandwidth, Device, HourlyBandwidth

logger = logging.getLogger(__name__)

BYTES_PER_MB = 1_000_000


class DataUsageCollector(BaseCollector):
    """Collects bandwidth data from eero's data_usage endpoint.

    The data_usage endpoint returns server-computed hourly bandwidth totals,
    which are far more accurate than rate-based accumulation from instantaneous
    Mbps snapshots.
    """

    def collect(self) -> dict:
        networks_processed = 0
        errors = 0

        try:
            networks = self.eero_client.get_networks()
            if not networks:
                logger.warning("No networks found for data usage collection")
                return {"items_collected": 0, "errors": 0}

            for network in networks:
                if isinstance(network, dict):
                    network_name = network.get('name')
                else:
                    network_name = network.name

                if not network_name:
                    continue

                try:
                    self._collect_network_usage(network_name)
                    self._collect_device_usage(network_name)
                    networks_processed += 1
                except Exception as e:
                    logger.error(f"Error collecting data usage for '{network_name}': {e}", exc_info=True)
                    errors += 1

            self.db.commit()
            return {"items_collected": networks_processed, "errors": errors}

        except Exception as e:
            logger.error(f"Data usage collector error: {e}", exc_info=True)
            self.db.rollback()
            return {"items_collected": 0, "errors": 1}

    def _get_today_window(self) -> tuple[str, str, str, datetime]:
        """Return (start_iso, end_iso, tz_name, now_local) for today's query window."""
        from src.config import get_settings
        settings = get_settings()
        tz = settings.get_timezone()
        now_local = datetime.now(tz)
        today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1) - timedelta(seconds=1)

        start_iso = today_start.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_iso = today_end.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
        return start_iso, end_iso, str(tz), now_local

    def _collect_network_usage(self, network_name: str) -> None:
        """Fetch and store network-level data_usage."""
        start, end, tz_name, now_local = self._get_today_window()

        result = self.eero_client.get_data_usage(
            start=start, end=end, cadence="hourly",
            timezone_str=tz_name, network_name=network_name,
        )
        if not result:
            logger.debug(f"No data_usage response for network '{network_name}'")
            return

        series = self._extract_series(result)
        if not series:
            return

        upload_series = series.get("upload", {})
        download_series = series.get("download", {})

        # Store hourly breakdown
        self._store_hourly_values(network_name, None, download_series.get("values", []), upload_series.get("values", []))

        # Update daily total from server sums
        download_sum = download_series.get("sum", 0) or 0
        upload_sum = upload_series.get("sum", 0) or 0
        self._update_daily_from_server(network_name, None, now_local.date(), download_sum, upload_sum)

        logger.info(
            f"Network data_usage for '{network_name}': "
            f"{download_sum / BYTES_PER_MB:.1f} MB down, {upload_sum / BYTES_PER_MB:.1f} MB up"
        )

    def _collect_device_usage(self, network_name: str) -> None:
        """Fetch and store per-device data_usage."""
        start, end, tz_name, now_local = self._get_today_window()

        result = self.eero_client.get_data_usage_devices(
            start=start, end=end, cadence="hourly",
            timezone_str=tz_name, network_name=network_name,
        )
        if not result:
            logger.debug(f"No device data_usage response for network '{network_name}'")
            return

        # The device endpoint returns per-device entries
        data = result.get("data") if isinstance(result, dict) else result
        if isinstance(data, dict):
            devices_list = data.get("devices", [])
        elif isinstance(data, list):
            devices_list = data
        else:
            devices_list = []

        devices_updated = 0
        for device_entry in devices_list:
            if not isinstance(device_entry, dict):
                continue

            mac = device_entry.get("mac")
            if not mac:
                continue

            device = (
                self.db.query(Device)
                .filter(Device.network_name == network_name, Device.mac_address == mac)
                .first()
            )
            if not device:
                logger.debug(f"Unknown device MAC {mac} in data_usage response, skipping")
                continue

            series = self._extract_series(device_entry)
            if not series:
                continue

            upload_series = series.get("upload", {})
            download_series = series.get("download", {})

            self._store_hourly_values(
                network_name, device.id,
                download_series.get("values", []),
                upload_series.get("values", []),
            )

            download_sum = download_series.get("sum", 0) or 0
            upload_sum = upload_series.get("sum", 0) or 0
            self._update_daily_from_server(network_name, device.id, now_local.date(), download_sum, upload_sum)
            devices_updated += 1

        if devices_updated:
            logger.info(f"Updated data_usage for {devices_updated} devices in '{network_name}'")

    def _extract_series(self, payload: dict) -> Optional[dict]:
        """Extract {type: {sum, values}} from a data_usage response."""
        data = payload.get("data", payload)
        if isinstance(data, dict):
            raw_series = data.get("series", [])
        else:
            raw_series = []

        if not raw_series:
            return None

        return {s["type"]: s for s in raw_series if isinstance(s, dict) and "type" in s}

    def _store_hourly_values(
        self,
        network_name: str,
        device_id: Optional[int],
        download_values: list,
        upload_values: list,
    ) -> None:
        """Upsert hourly bandwidth records from the data_usage values arrays."""
        # Build a lookup for upload values by time
        upload_by_time = {v["time"]: v.get("value", 0) or 0 for v in upload_values if isinstance(v, dict) and "time" in v}

        for entry in download_values:
            if not isinstance(entry, dict) or "time" not in entry:
                continue

            time_str = entry["time"]
            download_bytes = entry.get("value", 0) or 0
            upload_bytes = upload_by_time.get(time_str, 0)

            # Parse the hour start time
            try:
                hour_start = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                hour_start_naive = hour_start.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
            except (ValueError, TypeError):
                continue

            record = (
                self.db.query(HourlyBandwidth)
                .filter(
                    HourlyBandwidth.network_name == network_name,
                    HourlyBandwidth.device_id == device_id,
                    HourlyBandwidth.hour_start == hour_start_naive,
                )
                .first()
            )

            if record:
                record.download_bytes = download_bytes
                record.upload_bytes = upload_bytes
                record.updated_at = datetime.now(timezone.utc)
            else:
                self.db.add(HourlyBandwidth(
                    network_name=network_name,
                    device_id=device_id,
                    hour_start=hour_start_naive,
                    download_bytes=download_bytes,
                    upload_bytes=upload_bytes,
                ))

    def _update_daily_from_server(
        self,
        network_name: str,
        device_id: Optional[int],
        today: object,
        download_bytes: int,
        upload_bytes: int,
    ) -> None:
        """Set DailyBandwidth from server-computed totals (bytes → MB)."""
        record = (
            self.db.query(DailyBandwidth)
            .filter(
                DailyBandwidth.network_name == network_name,
                DailyBandwidth.device_id == device_id,
                DailyBandwidth.date == today,
            )
            .first()
        )

        download_mb = download_bytes / BYTES_PER_MB
        upload_mb = upload_bytes / BYTES_PER_MB

        if record:
            record.download_mb = download_mb
            record.upload_mb = upload_mb
            record.source = "data_usage"
            record.updated_at = datetime.now(timezone.utc)
        else:
            self.db.add(DailyBandwidth(
                network_name=network_name,
                device_id=device_id,
                date=today,
                download_mb=download_mb,
                upload_mb=upload_mb,
                source="data_usage",
            ))
