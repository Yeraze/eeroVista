"""Authentication management for Eero API."""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from src.models.database import Config
from src.utils.encryption import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)


class AuthManager:
    """Manages Eero authentication and session tokens."""

    SESSION_TOKEN_KEY = "eero_session_token"
    USER_TOKEN_KEY = "eero_user_token"

    def __init__(self, db: Session):
        """Initialize auth manager with database session."""
        self.db = db

    def is_authenticated(self) -> bool:
        """Check if we have a valid session token."""
        token = self.get_session_token()
        return token is not None and len(token) > 0

    def get_session_token(self) -> Optional[str]:
        """Get stored session token (decrypted)."""
        config = (
            self.db.query(Config).filter(Config.key == self.SESSION_TOKEN_KEY).first()
        )
        if config and config.value:
            return decrypt_value(config.value)
        return None

    def get_user_token(self) -> Optional[str]:
        """Get stored user token (decrypted)."""
        config = (
            self.db.query(Config).filter(Config.key == self.USER_TOKEN_KEY).first()
        )
        if config and config.value:
            return decrypt_value(config.value)
        return None

    def save_session_token(self, session_token: str) -> None:
        """Save session token (encrypted)."""
        encrypted = encrypt_value(session_token)

        config = (
            self.db.query(Config).filter(Config.key == self.SESSION_TOKEN_KEY).first()
        )
        if config:
            config.value = encrypted
        else:
            config = Config(key=self.SESSION_TOKEN_KEY, value=encrypted)
            self.db.add(config)

        self.db.commit()
        logger.info("Session token saved")

    def save_user_token(self, user_token: str) -> None:
        """Save user token (encrypted)."""
        encrypted = encrypt_value(user_token)

        config = (
            self.db.query(Config).filter(Config.key == self.USER_TOKEN_KEY).first()
        )
        if config:
            config.value = encrypted
        else:
            config = Config(key=self.USER_TOKEN_KEY, value=encrypted)
            self.db.add(config)

        self.db.commit()
        logger.info("User token saved")

    def clear_tokens(self) -> None:
        """Clear all stored tokens."""
        self.db.query(Config).filter(
            Config.key.in_([self.SESSION_TOKEN_KEY, self.USER_TOKEN_KEY])
        ).delete(synchronize_session=False)
        self.db.commit()
        logger.info("All tokens cleared")

    def save_config(self, key: str, value: str, encrypted: bool = False) -> None:
        """Save arbitrary configuration value."""
        stored_value = encrypt_value(value) if encrypted else value

        config = self.db.query(Config).filter(Config.key == key).first()
        if config:
            config.value = stored_value
        else:
            config = Config(key=key, value=stored_value)
            self.db.add(config)

        self.db.commit()

    def get_config(self, key: str, encrypted: bool = False) -> Optional[str]:
        """Get configuration value."""
        config = self.db.query(Config).filter(Config.key == key).first()
        if config and config.value:
            return decrypt_value(config.value) if encrypted else config.value
        return None
