"""Routing collector for IP reservations and port forwards."""

import logging
from datetime import datetime

from sqlalchemy.dialects.sqlite import insert

from src.collectors.base import BaseCollector
from src.models.database import IpReservation, PortForward

logger = logging.getLogger(__name__)


class RoutingCollector(BaseCollector):
    """Collects IP reservations and port forwarding rules."""

    def collect(self) -> dict:
        """Collect routing information from Eero API."""
        try:
            # Get network info
            networks = self.eero_client.get_networks()
            if not networks:
                logger.warning("No networks found")
                return {"items_collected": 0, "errors": 1}

            # Use first network
            network = networks[0]

            # Networks can be Pydantic models or dicts, handle both
            if isinstance(network, dict):
                network_name = network.get('name')
            else:
                network_name = network.name

            # Get network client
            network_client = self.eero_client.get_network_client(network_name)

            if not network_client:
                logger.warning(f"Network client for '{network_name}' not found")
                return {"items_collected": 0, "errors": 1}

            # Get routing data
            routing = network_client.routing
            if not routing:
                logger.warning("No routing data available")
                return {"items_collected": 0, "errors": 1}

            # Track stats
            reservations_added = 0
            reservations_updated = 0
            forwards_added = 0
            forwards_updated = 0
            current_time = datetime.utcnow()

            # Process IP reservations using upsert to avoid race conditions
            for res in routing.reservations.data:
                # Check if exists (for statistics tracking)
                exists = self.db.query(IpReservation).filter(
                    IpReservation.mac_address == res.mac
                ).first() is not None

                # Upsert reservation atomically
                stmt = insert(IpReservation).values(
                    mac_address=res.mac,
                    ip_address=res.ip,
                    description=res.description,
                    eero_url=res.url,
                    last_seen=current_time,
                    created_at=current_time,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=['mac_address'],
                    set_=dict(
                        ip_address=res.ip,
                        description=res.description,
                        eero_url=res.url,
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
            # Use a composite unique key of (ip_address, gateway_port, protocol)
            for fwd in routing.forwards.data:
                # Check if exists (for statistics tracking)
                exists = self.db.query(PortForward).filter(
                    PortForward.ip_address == fwd.ip,
                    PortForward.gateway_port == fwd.gateway_port,
                    PortForward.protocol == fwd.protocol
                ).first() is not None

                # Upsert forward atomically
                stmt = insert(PortForward).values(
                    ip_address=fwd.ip,
                    gateway_port=fwd.gateway_port,
                    client_port=fwd.client_port,
                    protocol=fwd.protocol,
                    description=fwd.description,
                    enabled=fwd.enabled,
                    reservation_url=fwd.reservation,
                    eero_url=fwd.url,
                    last_seen=current_time,
                    created_at=current_time,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=['ip_address', 'gateway_port', 'protocol'],
                    set_=dict(
                        client_port=fwd.client_port,
                        description=fwd.description,
                        enabled=fwd.enabled,
                        reservation_url=fwd.reservation,
                        eero_url=fwd.url,
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
                f"Routing collection completed: "
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
            logger.error(f"Error collecting routing data: {e}", exc_info=True)
            raise
