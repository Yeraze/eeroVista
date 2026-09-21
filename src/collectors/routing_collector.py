"""Routing collector for IP reservations and port forwards."""

import logging
from datetime import datetime, timezone

from sqlalchemy.dialects.sqlite import insert

from src.collectors.base import BaseCollector
from src.models.database import IpReservation, PortForward

logger = logging.getLogger(__name__)


class RoutingCollector(BaseCollector):
    """Collects IP reservations and port forwarding rules."""

    def collect(self) -> dict:
        """Collect routing information from Eero API for all networks."""
        total_reservations_added = 0
        total_reservations_updated = 0
        total_forwards_added = 0
        total_forwards_updated = 0
        total_errors = 0
        networks_processed = 0

        try:
            # Get all networks
            networks = self.eero_client.get_networks()
            if not networks:
                logger.warning("No networks found")
                return {"items_collected": 0, "errors": 1, "networks": 0}

            logger.info(f"Collecting routing data for {len(networks)} network(s)")

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
                    total_reservations_added += result.get("reservations_added", 0)
                    total_reservations_updated += result.get("reservations_updated", 0)
                    total_forwards_added += result.get("forwards_added", 0)
                    total_forwards_updated += result.get("forwards_updated", 0)
                    total_errors += result.get("errors", 0)
                    networks_processed += 1
                except Exception as e:
                    logger.error(f"Error collecting for network '{network_name}': {e}")
                    total_errors += 1

            total_items = (total_reservations_added + total_reservations_updated +
                          total_forwards_added + total_forwards_updated)

            return {
                "items_collected": total_items,
                "errors": total_errors,
                "networks": networks_processed,
                "reservations_added": total_reservations_added,
                "reservations_updated": total_reservations_updated,
                "forwards_added": total_forwards_added,
                "forwards_updated": total_forwards_updated,
            }

        except Exception as e:
            logger.error(f"Error in routing collector: {e}")
            self.db.rollback()
            return {"items_collected": 0, "errors": 1, "networks": 0}

    def _collect_for_network(self, network_name: str) -> dict:
        """Collect routing information for a specific network."""
        try:
            # Fetch routing data via raw API calls that bypass pydantic
            # marshalling. Using network_client.routing here caused the eero
            # library's strict pydantic validation to fail for some accounts,
            # silently yielding zero reservations/forwards (issue #137).
            #
            # A None return means the fetch itself failed (network error, auth
            # expiry, unexpected response). Treat that as an error rather than
            # collapsing it into "no data" — otherwise a transient failure
            # masquerades as an empty network, the same failure class as #137.
            # An empty list is a legitimate "network has none" and is fine.
            reservations = self.eero_client.get_reservations(network_name)
            forwards = self.eero_client.get_forwards(network_name)
            if reservations is None or forwards is None:
                raise RuntimeError(
                    f"Failed to fetch routing data for network '{network_name}' "
                    f"(reservations={'ok' if reservations is not None else 'FAILED'}, "
                    f"forwards={'ok' if forwards is not None else 'FAILED'})"
                )

            # Track stats
            reservations_added = 0
            reservations_updated = 0
            forwards_added = 0
            forwards_updated = 0
            current_time = datetime.now(timezone.utc)

            # Process IP reservations using upsert to avoid race conditions
            for res in reservations:
                mac = res.get('mac')
                ip = res.get('ip')
                # mac_address and ip_address are NOT NULL. Skip loudly on a
                # missing/renamed key instead of letting it surface as an
                # opaque IntegrityError far from the cause.
                if not mac or not ip:
                    logger.warning(
                        f"Skipping reservation with missing mac/ip on network "
                        f"'{network_name}': {res}"
                    )
                    continue
                # Check if exists (for statistics tracking)
                exists = self.db.query(IpReservation).filter(
                    IpReservation.network_name == network_name,
                    IpReservation.mac_address == mac
                ).first() is not None

                # Upsert reservation atomically
                stmt = insert(IpReservation).values(
                    network_name=network_name,
                    mac_address=mac,
                    ip_address=ip,
                    description=res.get('description'),
                    eero_url=res.get('url'),
                    last_seen=current_time,
                    created_at=current_time,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=['network_name', 'mac_address'],
                    set_=dict(
                        ip_address=ip,
                        description=res.get('description'),
                        eero_url=res.get('url'),
                        last_seen=current_time,
                    )
                )
                self.db.execute(stmt)

                # Track statistics
                if exists:
                    reservations_updated += 1
                else:
                    reservations_added += 1

            # Process port forwards using upsert to avoid race conditions
            # Use a composite unique key of (network_name, ip_address, gateway_port, protocol)
            for fwd in forwards:
                ip = fwd.get('ip')
                gateway_port = fwd.get('gateway_port')
                protocol = fwd.get('protocol')
                # ip_address, gateway_port and protocol are NOT NULL. Skip
                # loudly on a missing/renamed key rather than emitting an
                # opaque IntegrityError at insert time.
                if not ip or gateway_port is None or not protocol:
                    logger.warning(
                        f"Skipping forward with missing ip/gateway_port/protocol "
                        f"on network '{network_name}': {fwd}"
                    )
                    continue
                # Check if exists (for statistics tracking)
                exists = self.db.query(PortForward).filter(
                    PortForward.network_name == network_name,
                    PortForward.ip_address == ip,
                    PortForward.gateway_port == gateway_port,
                    PortForward.protocol == protocol
                ).first() is not None

                # Upsert forward atomically
                stmt = insert(PortForward).values(
                    network_name=network_name,
                    ip_address=ip,
                    gateway_port=gateway_port,
                    client_port=fwd.get('client_port'),
                    protocol=protocol,
                    description=fwd.get('description'),
                    enabled=fwd.get('enabled'),
                    reservation_url=fwd.get('reservation'),
                    eero_url=fwd.get('url'),
                    last_seen=current_time,
                    created_at=current_time,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=['network_name', 'ip_address', 'gateway_port', 'protocol'],
                    set_=dict(
                        client_port=fwd.get('client_port'),
                        description=fwd.get('description'),
                        enabled=fwd.get('enabled'),
                        reservation_url=fwd.get('reservation'),
                        eero_url=fwd.get('url'),
                        last_seen=current_time,
                    )
                )
                self.db.execute(stmt)

                # Track statistics
                if exists:
                    forwards_updated += 1
                else:
                    forwards_added += 1

            self.db.commit()

            total_items = reservations_added + reservations_updated + forwards_added + forwards_updated

            logger.info(
                f"Network '{network_name}' routing collection completed: "
                f"{reservations_added} reservations added, {reservations_updated} updated, "
                f"{forwards_added} forwards added, {forwards_updated} updated"
            )

            return {
                "items_collected": total_items,
                "errors": 0,
                "reservations_added": reservations_added,
                "reservations_updated": reservations_updated,
                "forwards_added": forwards_added,
                "forwards_updated": forwards_updated,
            }

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error collecting routing data for network '{network_name}': {e}", exc_info=True)
            raise
