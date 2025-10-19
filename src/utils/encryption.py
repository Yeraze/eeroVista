"""Encryption utilities for storing sensitive data."""

import base64
import os
from typing import Optional

from cryptography.fernet import Fernet

from src.config import get_settings

# Global cache for generated encryption key (persists during app lifetime)
_cached_encryption_key: Optional[bytes] = None


def get_encryption_key() -> bytes:
    """Get or generate encryption key."""
    global _cached_encryption_key

    settings = get_settings()

    if settings.encryption_key:
        # Use provided key from environment
        key = settings.encryption_key.encode()
    elif _cached_encryption_key is not None:
        # Use cached generated key
        key = _cached_encryption_key
    else:
        # Generate a new key and cache it
        # This persists for the lifetime of the application
        key = Fernet.generate_key()
        _cached_encryption_key = key

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
    import logging
    logger = logging.getLogger(__name__)

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
