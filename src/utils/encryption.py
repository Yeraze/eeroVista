"""Encryption utilities for storing sensitive data."""

import base64
import logging
import os
import sys
from typing import Optional

from cryptography.fernet import Fernet

from src.config import get_settings

logger = logging.getLogger(__name__)

# Global cache for generated encryption key (persists during app lifetime)
_cached_encryption_key: Optional[bytes] = None


def validate_encryption_key(key: bytes) -> bool:
    """Validate that a key is a valid Fernet key.

    Args:
        key: The key to validate

    Returns:
        True if valid, False otherwise
    """
    try:
        # Try to create a Fernet instance with the key
        Fernet(key)
        return True
    except Exception:
        return False


def get_encryption_key() -> bytes:
    """Get or generate encryption key."""
    global _cached_encryption_key

    settings = get_settings()

    if settings.encryption_key:
        # Use provided key from environment
        key = settings.encryption_key.encode()

        # Validate the provided key
        if not validate_encryption_key(key):
            logger.error("=" * 80)
            logger.error("INVALID ENCRYPTION_KEY DETECTED")
            logger.error("=" * 80)
            logger.error("")
            logger.error("The ENCRYPTION_KEY environment variable is set but is not a valid Fernet key.")
            logger.error("A Fernet key must be 32 url-safe base64-encoded bytes.")
            logger.error("")
            logger.error("To fix this issue, choose one of these options:")
            logger.error("")
            logger.error("Option 1 (Recommended): Remove ENCRYPTION_KEY and let it auto-generate")
            logger.error("  - Remove the ENCRYPTION_KEY from your docker-compose.yml or .env file")
            logger.error("  - Restart the container")
            logger.error("")
            logger.error("Option 2: Generate a valid Fernet key")
            logger.error("  - Run: python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
            logger.error("  - Set ENCRYPTION_KEY to the generated value")
            logger.error("")
            logger.error("=" * 80)
            sys.exit(1)

    elif _cached_encryption_key is not None:
        # Use cached generated key
        key = _cached_encryption_key
    else:
        # Generate a new key and cache it
        # This persists for the lifetime of the application
        key = Fernet.generate_key()
        _cached_encryption_key = key
        logger.info("Generated new encryption key (will persist for application lifetime)")

    return key


def encrypt_value(value: str) -> str:
    """Encrypt a string value."""
    if not value:
        return ""

    key = get_encryption_key()
    f = Fernet(key)
    encrypted = f.encrypt(value.encode())
    return base64.b64encode(encrypted).decode()


def decrypt_value(encrypted_value: str) -> Optional[str]:
    """Decrypt a string value."""
    if not encrypted_value:
        return None

    try:
        key = get_encryption_key()
        f = Fernet(key)
        encrypted_bytes = base64.b64decode(encrypted_value.encode())
        decrypted = f.decrypt(encrypted_bytes)
        return decrypted.decode()
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        return None
