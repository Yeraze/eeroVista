"""Routing collector for IP reservations and port forwards."""

import logging
from datetime import datetime

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

            # Get network client
            eero = self.eero_client._get_client()
            network_client = eero.network_clients.get(network.name)

            if not network_client:
                logger.warning(f"Network client for '{network.name}' not found")
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

            # Process IP reservations
            for res in routing.reservations.data:
                # Check if reservation exists
                existing = self.db.query(IpReservation).filter(
                    IpReservation.mac_address == res.mac
                ).first()

                if existing:
                    # Update existing reservation
                    existing.ip_address = res.ip
                    existing.description = res.description
                    existing.eero_url = res.url
                    existing.last_seen = current_time
                    reservations_updated += 1
                else:
                    # Create new reservation
                    reservation = IpReservation(
                        mac_address=res.mac,
                        ip_address=res.ip,
                        description=res.description,
                        eero_url=res.url,
                        last_seen=current_time,
                    )
                    self.db.add(reservation)
                    reservations_added += 1

            # Process port forwards
            # Use a composite key of (ip, gateway_port, protocol) to identify unique forwards
            for fwd in routing.forwards.data:
                # Check if forward exists
                existing = self.db.query(PortForward).filter(
                    PortForward.ip_address == fwd.ip,
                    PortForward.gateway_port == fwd.gateway_port,
                    PortForward.protocol == fwd.protocol
                ).first()

                if existing:
                    # Update existing forward
                    existing.client_port = fwd.client_port
                    existing.description = fwd.description
                    existing.enabled = fwd.enabled
                    existing.reservation_url = fwd.reservation
                    existing.eero_url = fwd.url
                    existing.last_seen = current_time
                    forwards_updated += 1
                else:
                    # Create new forward
                    forward = PortForward(
                        ip_address=fwd.ip,
                        gateway_port=fwd.gateway_port,
                        client_port=fwd.client_port,
                        protocol=fwd.protocol,
                        description=fwd.description,
                        enabled=fwd.enabled,
                        reservation_url=fwd.reservation,
                        eero_url=fwd.url,
                        last_seen=current_time,
                    )
                    self.db.add(forward)
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
