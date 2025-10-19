"""Encryption utilities for storing sensitive data."""

import base64
import os
from typing import Optional

from cryptography.fernet import Fernet

from src.config import get_settings


def get_encryption_key() -> bytes:
    """Get or generate encryption key."""
    settings = get_settings()

    if settings.encryption_key:
        # Use provided key
        key = settings.encryption_key.encode()
    else:
        # Generate a new key (note: this will change on restart if not persisted)
        # In production, you'd want to store this persistently
        key = Fernet.generate_key()

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
    except Exception:
        return None
