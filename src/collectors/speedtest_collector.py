"""Speedtest collector for passive speedtest result collection."""

import logging
import re
from datetime import datetime, timezone

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
        """Collect speedtest results for a specific network.

        The eero API returns a list of recent speedtest results at the
        /speedtest endpoint. We try the eero-client library first, and
        fall back to a raw API call if the Pydantic model fails to parse.
        """
        try:
            speedtest_list = self._fetch_speedtest_data(network_name)

            if not speedtest_list:
                logger.debug(f"No speedtest data available for network '{network_name}'")
                return {"items_collected": 0, "errors": 0}

            collected = 0
            for entry in speedtest_list:
                test_date = self._parse_date(entry.get("date"))
                download_mbps = entry.get("down_mbps")
                upload_mbps = entry.get("up_mbps")

                if not test_date:
                    continue

                # Strip timezone for SQLite comparison (DB stores naive datetimes)
                test_date_naive = test_date.replace(tzinfo=None) if test_date.tzinfo else test_date

                # Deduplicate: check if we already have this exact timestamp
                existing = (
                    self.db.query(Speedtest)
                    .filter(
                        Speedtest.network_name == network_name,
                        Speedtest.timestamp == test_date_naive,
                    )
                    .first()
                )
                if existing:
                    # If existing record has NULL values, update it with real data
                    if existing.download_mbps is None and download_mbps is not None:
                        existing.download_mbps = download_mbps
                        existing.upload_mbps = upload_mbps
                        collected += 1
                    continue

                speedtest = Speedtest(
                    network_name=network_name,
                    timestamp=test_date_naive,
                    download_mbps=download_mbps,
                    upload_mbps=upload_mbps,
                    latency_ms=None,
                    jitter_ms=None,
                    server_location=None,
                    isp=None,
                )
                self.db.add(speedtest)
                collected += 1

            if collected > 0:
                self.db.commit()
                logger.info(
                    f"Network '{network_name}': {collected} new speedtest result(s) collected"
                )

            return {"items_collected": collected, "errors": 0}

        except Exception as e:
            self.db.rollback()
            logger.warning(f"Could not fetch speedtest data for network '{network_name}': {e}")
            return {"items_collected": 0, "errors": 0}

    @staticmethod
    def _parse_date(date_val) -> datetime:
        """Parse a date value into a datetime object."""
        if date_val is None:
            return None
        if isinstance(date_val, datetime):
            return date_val
        if isinstance(date_val, str):
            try:
                # Handle "+0000" timezone format (no colon) by normalizing
                # "2026-03-24T10:13:10+0000" -> "2026-03-24T10:13:10+00:00"
                normalized = re.sub(r'([+-])(\d{2})(\d{2})$', r'\1\2:\3', date_val)
                return datetime.fromisoformat(normalized)
            except ValueError:
                pass
            try:
                return datetime.strptime(date_val, "%Y-%m-%dT%H:%M:%S%z")
            except ValueError:
                pass
            try:
                return datetime.strptime(date_val, "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                pass
        logger.warning(f"Could not parse speedtest date: {date_val}")
        return None

    def _fetch_speedtest_data(self, network_name: str) -> list:
        """Fetch speedtest results, with raw API fallback.

        Returns a normalized list of dicts with keys: date, down_mbps, up_mbps.
        """
        # Try the eero-client library first
        try:
            network_client = self.eero_client.get_network_client(network_name)
            if network_client:
                speedtest_data = network_client.speedtest
                if speedtest_data:
                    results = self._normalize_speedtest(speedtest_data)
                    logger.info(f"Speedtest: got {len(results)} results via eero-client for '{network_name}'")
                    return results
        except Exception as e:
            logger.info(f"Speedtest: eero-client failed for '{network_name}', trying raw API fallback")

        # Fallback: raw API call to /speedtest endpoint
        results = self._fetch_speedtest_raw(network_name)
        logger.info(f"Speedtest: raw API returned {len(results)} results for '{network_name}'")
        return results

    def _fetch_speedtest_raw(self, network_name: str) -> list:
        """Fetch speedtest data via raw HTTP, bypassing eero-client models.

        The speedtest endpoint returns raw JSON without the standard eero
        meta/data wrapper, so we use requests directly instead of APIClient.
        """
        try:
            import requests
            from src.eero_client.auth import AuthManager

            am = AuthManager(self.db)
            token = am.get_session_token()
            if not token:
                return []

            session = requests.Session()
            session.cookies.set('s', token)

            # Get account to find network URL
            r = session.get('https://api-user.e2ro.com/2.2/account')
            if not r.ok:
                return []

            account = r.json()
            net_data = account.get('data', {}).get('networks', {}).get('data', [])

            net_url = None
            for net in net_data:
                if net.get('name') == network_name:
                    net_url = net.get('url')
                    break

            if not net_url and net_data:
                net_url = net_data[0].get('url')

            if not net_url:
                return []

            # Fetch speedtest results
            r2 = session.get(f'https://api-user.e2ro.com{net_url}/speedtest')
            if not r2.ok:
                return []

            raw = r2.json()
            # Response may be wrapped in {data: [...]} or be a bare list
            if isinstance(raw, dict):
                raw = raw.get('data', raw)

            if isinstance(raw, list):
                return [
                    {
                        "date": entry.get("date"),
                        "down_mbps": entry.get("down_mbps"),
                        "up_mbps": entry.get("up_mbps"),
                    }
                    for entry in raw
                    if entry.get("date")
                ]

            return []

        except Exception as e:
            logger.warning(f"Speedtest: raw API fallback failed for '{network_name}': {e}")
            return []

    def _normalize_speedtest(self, data) -> list:
        """Normalize speedtest data from eero-client into standard format."""
        if isinstance(data, list):
            results = []
            for entry in data:
                if isinstance(entry, dict):
                    results.append({
                        "date": entry.get("date"),
                        "down_mbps": entry.get("down_mbps") or (entry.get("down", {}) or {}).get("value"),
                        "up_mbps": entry.get("up_mbps") or (entry.get("up", {}) or {}).get("value"),
                    })
                else:
                    results.append({
                        "date": getattr(entry, "date", None),
                        "down_mbps": entry.down.value if hasattr(entry, "down") and entry.down else None,
                        "up_mbps": entry.up.value if hasattr(entry, "up") and entry.up else None,
                    })
            return results

        if isinstance(data, dict):
            return [{
                "date": data.get("date"),
                "down_mbps": data.get("down_mbps") or (data.get("down", {}) or {}).get("value"),
                "up_mbps": data.get("up_mbps") or (data.get("up", {}) or {}).get("value"),
            }]

        # Pydantic model (single result)
        return [{
            "date": getattr(data, "date", None),
            "down_mbps": data.down.value if hasattr(data, "down") and data.down else None,
            "up_mbps": data.up.value if hasattr(data, "up") and data.up else None,
        }]
