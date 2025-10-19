"""Eero API client wrapper with authentication and error handling."""

import logging
from typing import Any, Dict, Optional

from eero import Eero
from sqlalchemy.orm import Session

from src.eero_client.auth import AuthManager

logger = logging.getLogger(__name__)


class EeroClientWrapper:
    """Wrapper around eero-client with session management and error handling."""

    def __init__(self, db: Session):
        """Initialize Eero client wrapper."""
        self.db = db
        self.auth_manager = AuthManager(db)
        self._eero: Optional[Eero] = None

    def _get_client(self) -> Eero:
        """Get or create Eero client instance."""
        if self._eero is None:
            self._eero = Eero()

            # If we have a stored session, restore it
            session_token = self.auth_manager.get_session_token()
            if session_token:
                self._eero.session.cookie = session_token
                logger.info("Restored Eero session from stored token")

        return self._eero

    def is_authenticated(self) -> bool:
        """Check if we have valid authentication."""
        return self.auth_manager.is_authenticated()

    def login_phone(self, phone: str) -> Dict[str, Any]:
        """
        Initiate login with phone number.

        Returns:
            Dict with status and message
        """
        try:
            eero = self._get_client()
            user_token = eero.login(phone)

            if user_token:
                self.auth_manager.save_user_token(user_token)
                logger.info(f"SMS verification code sent to {phone}")
                return {
                    "success": True,
                    "message": "Verification code sent via SMS",
                    "user_token": user_token,
                }
            else:
                return {"success": False, "message": "Failed to send verification code"}

        except Exception as e:
            logger.error(f"Login error: {e}")
            return {"success": False, "message": str(e)}

    def login_verify(self, verification_code: str) -> Dict[str, Any]:
        """
        Verify SMS code and complete login.

        Returns:
            Dict with status and message
        """
        try:
            eero = self._get_client()
            user_token = self.auth_manager.get_user_token()

            if not user_token:
                return {
                    "success": False,
                    "message": "No pending verification. Please request code first.",
                }

            # Verify the code
            eero.login_verify(verification_code, user_token)

            # Save the session cookie
            if eero.session.cookie:
                self.auth_manager.save_session_token(eero.session.cookie)
                logger.info("Successfully authenticated with Eero")
                return {"success": True, "message": "Authentication successful"}
            else:
                return {
                    "success": False,
                    "message": "Verification failed - invalid code",
                }

        except Exception as e:
            logger.error(f"Verification error: {e}")
            return {"success": False, "message": str(e)}

    def get_account(self) -> Optional[Dict[str, Any]]:
        """Get account information."""
        try:
            eero = self._get_client()
            if not self.is_authenticated():
                logger.warning("Not authenticated - cannot get account")
                return None

            account = eero.account
            return account

        except Exception as e:
            logger.error(f"Error getting account: {e}")
            return None

    def get_networks(self) -> Optional[list]:
        """Get list of networks."""
        try:
            account = self.get_account()
            if not account:
                return None

            networks = account.get("networks", {}).get("data", [])
            return networks

        except Exception as e:
            logger.error(f"Error getting networks: {e}")
            return None

    def get_eeros(self, network_id: Optional[str] = None) -> Optional[list]:
        """
        Get list of eero devices (nodes).

        Args:
            network_id: Optional network ID. If None, uses first network.
        """
        try:
            eero = self._get_client()
            if not self.is_authenticated():
                return None

            if network_id is None:
                # Get first network
                networks = self.get_networks()
                if not networks:
                    return None
                network_id = networks[0]["url"]

            # Get eeros for network
            eeros_data = eero.get(network_id + "/eeros")
            return eeros_data.get("data", [])

        except Exception as e:
            logger.error(f"Error getting eeros: {e}")
            return None

    def get_devices(self, network_id: Optional[str] = None) -> Optional[list]:
        """
        Get list of connected devices.

        Args:
            network_id: Optional network ID. If None, uses first network.
        """
        try:
            eero = self._get_client()
            if not self.is_authenticated():
                return None

            if network_id is None:
                # Get first network
                networks = self.get_networks()
                if not networks:
                    return None
                network_id = networks[0]["url"]

            # Get devices for network
            devices_data = eero.get(network_id + "/devices")
            return devices_data.get("data", [])

        except Exception as e:
            logger.error(f"Error getting devices: {e}")
            return None

    def refresh_session(self) -> bool:
        """Attempt to refresh the session."""
        try:
            # Try to get account to test session
            account = self.get_account()
            return account is not None

        except Exception as e:
            logger.error(f"Session refresh failed: {e}")
            return False
