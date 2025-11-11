"""Tests for encryption utilities."""

import os
import pytest
from unittest.mock import patch, MagicMock
from cryptography.fernet import Fernet

from src.utils.encryption import (
    validate_encryption_key,
    get_encryption_key,
    encrypt_value,
    decrypt_value,
)


class TestEncryptionKeyValidation:
    """Test encryption key validation."""

    def test_validate_encryption_key_valid(self):
        """Test that a valid Fernet key passes validation."""
        valid_key = Fernet.generate_key()
        assert validate_encryption_key(valid_key) is True

    def test_validate_encryption_key_invalid(self):
        """Test that an invalid key fails validation."""
        invalid_keys = [
            b"too_short",
            b"this_is_not_a_valid_fernet_key_format",
            b"",
            b"123456789012345678901234567890XX",  # Wrong length/format
        ]
        for invalid_key in invalid_keys:
            assert validate_encryption_key(invalid_key) is False

    @patch("src.utils.encryption.get_settings")
    def test_get_encryption_key_with_invalid_env_var(self, mock_get_settings):
        """Test that an invalid ENCRYPTION_KEY environment variable causes exit."""
        # Mock settings to return an invalid key
        mock_settings = MagicMock()
        mock_settings.encryption_key = "invalid_key_format"
        mock_get_settings.return_value = mock_settings

        # Should exit with code 1
        with pytest.raises(SystemExit) as exc_info:
            # Clear the cache first
            import src.utils.encryption
            src.utils.encryption._cached_encryption_key = None
            get_encryption_key()

        assert exc_info.value.code == 1

    @patch("src.utils.encryption.get_settings")
    def test_get_encryption_key_with_valid_env_var(self, mock_get_settings):
        """Test that a valid ENCRYPTION_KEY environment variable is accepted."""
        # Mock settings to return a valid key
        valid_key = Fernet.generate_key().decode()
        mock_settings = MagicMock()
        mock_settings.encryption_key = valid_key
        mock_get_settings.return_value = mock_settings

        # Clear the cache first
        import src.utils.encryption
        src.utils.encryption._cached_encryption_key = None

        # Should not raise an exception
        key = get_encryption_key()
        assert key == valid_key.encode()

    @patch("src.utils.encryption.get_settings")
    def test_get_encryption_key_auto_generate(self, mock_get_settings):
        """Test that encryption key is auto-generated when not provided."""
        # Mock settings with no encryption key
        mock_settings = MagicMock()
        mock_settings.encryption_key = None
        mock_get_settings.return_value = mock_settings

        # Clear the cache first
        import src.utils.encryption
        src.utils.encryption._cached_encryption_key = None

        # Should auto-generate a valid key
        key = get_encryption_key()
        assert key is not None
        assert validate_encryption_key(key) is True


class TestEncryptDecrypt:
    """Test encryption and decryption functions."""

    @patch("src.utils.encryption.get_settings")
    def test_encrypt_decrypt_roundtrip(self, mock_get_settings):
        """Test that values can be encrypted and decrypted."""
        # Mock settings with no encryption key (will auto-generate)
        mock_settings = MagicMock()
        mock_settings.encryption_key = None
        mock_get_settings.return_value = mock_settings

        # Clear the cache first
        import src.utils.encryption
        src.utils.encryption._cached_encryption_key = None

        test_value = "secret_session_token_12345"
        encrypted = encrypt_value(test_value)
        assert encrypted != test_value
        assert len(encrypted) > 0

        decrypted = decrypt_value(encrypted)
        assert decrypted == test_value

    @patch("src.utils.encryption.get_settings")
    def test_encrypt_empty_string(self, mock_get_settings):
        """Test encrypting empty string."""
        mock_settings = MagicMock()
        mock_settings.encryption_key = None
        mock_get_settings.return_value = mock_settings

        result = encrypt_value("")
        assert result == ""

    @patch("src.utils.encryption.get_settings")
    def test_decrypt_empty_string(self, mock_get_settings):
        """Test decrypting empty string."""
        mock_settings = MagicMock()
        mock_settings.encryption_key = None
        mock_get_settings.return_value = mock_settings

        result = decrypt_value("")
        assert result is None

    @patch("src.utils.encryption.get_settings")
    def test_decrypt_invalid_value(self, mock_get_settings):
        """Test decrypting invalid encrypted value."""
        mock_settings = MagicMock()
        mock_settings.encryption_key = None
        mock_get_settings.return_value = mock_settings

        # Clear the cache first
        import src.utils.encryption
        src.utils.encryption._cached_encryption_key = None

        result = decrypt_value("not_a_valid_encrypted_value")
        assert result is None
