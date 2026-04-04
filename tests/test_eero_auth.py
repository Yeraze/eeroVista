"""Tests for eero_client/auth.py - Eero authentication manager."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Base, Config


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def auth_manager(db_session):
    """Create an AuthManager instance with in-memory DB."""
    from src.eero_client.auth import AuthManager

    return AuthManager(db_session)


class TestAuthManagerInitialization:
    """Tests for AuthManager initialization."""

    def test_creates_with_db_session(self, db_session):
        from src.eero_client.auth import AuthManager

        manager = AuthManager(db_session)
        assert manager.db is db_session

    def test_has_session_token_key_constant(self):
        from src.eero_client.auth import AuthManager

        assert hasattr(AuthManager, "SESSION_TOKEN_KEY")
        assert isinstance(AuthManager.SESSION_TOKEN_KEY, str)

    def test_has_user_token_key_constant(self):
        from src.eero_client.auth import AuthManager

        assert hasattr(AuthManager, "USER_TOKEN_KEY")
        assert isinstance(AuthManager.USER_TOKEN_KEY, str)


class TestIsAuthenticated:
    """Tests for is_authenticated method."""

    def test_returns_false_when_no_token_stored(self, auth_manager):
        assert auth_manager.is_authenticated() is False

    def test_returns_true_after_session_token_saved(self, auth_manager):
        auth_manager.save_session_token("test-session-token-abc123")
        assert auth_manager.is_authenticated() is True

    def test_returns_false_after_tokens_cleared(self, auth_manager):
        auth_manager.save_session_token("test-session-token-abc123")
        auth_manager.clear_tokens()
        assert auth_manager.is_authenticated() is False


class TestGetSessionToken:
    """Tests for get_session_token method."""

    def test_returns_none_when_no_token(self, auth_manager):
        assert auth_manager.get_session_token() is None

    def test_returns_stored_token(self, auth_manager):
        auth_manager.save_session_token("my-secret-session-token")
        token = auth_manager.get_session_token()
        assert token == "my-secret-session-token"

    def test_returns_decrypted_token(self, auth_manager, db_session):
        from src.utils.encryption import encrypt_value

        # Manually insert encrypted token
        encrypted = encrypt_value("raw-session-token")
        config = Config(key=auth_manager.SESSION_TOKEN_KEY, value=encrypted)
        db_session.add(config)
        db_session.commit()

        token = auth_manager.get_session_token()
        assert token == "raw-session-token"

    def test_returns_none_when_config_value_is_none(self, auth_manager, db_session):
        config = Config(key=auth_manager.SESSION_TOKEN_KEY, value=None)
        db_session.add(config)
        db_session.commit()

        token = auth_manager.get_session_token()
        assert token is None


class TestGetUserToken:
    """Tests for get_user_token method."""

    def test_returns_none_when_no_token(self, auth_manager):
        assert auth_manager.get_user_token() is None

    def test_returns_stored_user_token(self, auth_manager):
        auth_manager.save_user_token("user-token-xyz")
        token = auth_manager.get_user_token()
        assert token == "user-token-xyz"

    def test_decrypts_user_token(self, auth_manager, db_session):
        from src.utils.encryption import encrypt_value

        encrypted = encrypt_value("plain-user-token")
        config = Config(key=auth_manager.USER_TOKEN_KEY, value=encrypted)
        db_session.add(config)
        db_session.commit()

        token = auth_manager.get_user_token()
        assert token == "plain-user-token"


class TestSaveSessionToken:
    """Tests for save_session_token method."""

    def test_saves_new_session_token(self, auth_manager, db_session):
        auth_manager.save_session_token("new-token")

        config = db_session.query(Config).filter_by(key=auth_manager.SESSION_TOKEN_KEY).first()
        assert config is not None
        assert config.value is not None  # Should be encrypted

    def test_updates_existing_session_token(self, auth_manager, db_session):
        auth_manager.save_session_token("first-token")
        auth_manager.save_session_token("second-token")

        configs = db_session.query(Config).filter_by(key=auth_manager.SESSION_TOKEN_KEY).all()
        assert len(configs) == 1  # Only one record

        token = auth_manager.get_session_token()
        assert token == "second-token"

    def test_token_is_encrypted_in_db(self, auth_manager, db_session):
        plaintext = "super-secret-token"
        auth_manager.save_session_token(plaintext)

        config = db_session.query(Config).filter_by(key=auth_manager.SESSION_TOKEN_KEY).first()
        # The stored value should NOT equal the plaintext
        assert config.value != plaintext


class TestSaveUserToken:
    """Tests for save_user_token method."""

    def test_saves_new_user_token(self, auth_manager, db_session):
        auth_manager.save_user_token("user-token-abc")

        config = db_session.query(Config).filter_by(key=auth_manager.USER_TOKEN_KEY).first()
        assert config is not None

    def test_updates_existing_user_token(self, auth_manager):
        auth_manager.save_user_token("first-user-token")
        auth_manager.save_user_token("second-user-token")

        token = auth_manager.get_user_token()
        assert token == "second-user-token"

    def test_token_is_encrypted_in_db(self, auth_manager, db_session):
        plaintext = "plain-user-token-value"
        auth_manager.save_user_token(plaintext)

        config = db_session.query(Config).filter_by(key=auth_manager.USER_TOKEN_KEY).first()
        assert config.value != plaintext


class TestClearTokens:
    """Tests for clear_tokens method."""

    def test_clears_session_token(self, auth_manager, db_session):
        auth_manager.save_session_token("session-token")
        auth_manager.clear_tokens()

        config = db_session.query(Config).filter_by(key=auth_manager.SESSION_TOKEN_KEY).first()
        assert config is None

    def test_clears_user_token(self, auth_manager, db_session):
        auth_manager.save_user_token("user-token")
        auth_manager.clear_tokens()

        config = db_session.query(Config).filter_by(key=auth_manager.USER_TOKEN_KEY).first()
        assert config is None

    def test_clears_both_tokens(self, auth_manager, db_session):
        auth_manager.save_session_token("session-token")
        auth_manager.save_user_token("user-token")
        auth_manager.clear_tokens()

        count = db_session.query(Config).filter(
            Config.key.in_([auth_manager.SESSION_TOKEN_KEY, auth_manager.USER_TOKEN_KEY])
        ).count()
        assert count == 0

    def test_clear_tokens_when_none_exist(self, auth_manager):
        # Should not raise even when no tokens exist
        auth_manager.clear_tokens()
        assert auth_manager.is_authenticated() is False


class TestSaveConfig:
    """Tests for save_config method."""

    def test_saves_plain_config_value(self, auth_manager, db_session):
        auth_manager.save_config("my_key", "my_value")

        config = db_session.query(Config).filter_by(key="my_key").first()
        assert config is not None
        assert config.value == "my_value"

    def test_saves_encrypted_config_value(self, auth_manager, db_session):
        auth_manager.save_config("my_secret_key", "my_secret_value", encrypted=True)

        config = db_session.query(Config).filter_by(key="my_secret_key").first()
        assert config is not None
        # Stored value should differ from plaintext when encrypted=True
        assert config.value != "my_secret_value"

    def test_updates_existing_config(self, auth_manager, db_session):
        auth_manager.save_config("update_key", "value_v1")
        auth_manager.save_config("update_key", "value_v2")

        configs = db_session.query(Config).filter_by(key="update_key").all()
        assert len(configs) == 1
        assert configs[0].value == "value_v2"


class TestGetConfig:
    """Tests for get_config method."""

    def test_returns_none_for_nonexistent_key(self, auth_manager):
        result = auth_manager.get_config("nonexistent_key")
        assert result is None

    def test_returns_plain_config_value(self, auth_manager):
        auth_manager.save_config("test_key", "test_value")
        result = auth_manager.get_config("test_key")
        assert result == "test_value"

    def test_returns_decrypted_config_when_encrypted_flag_set(self, auth_manager):
        auth_manager.save_config("enc_key", "encrypted_value", encrypted=True)
        result = auth_manager.get_config("enc_key", encrypted=True)
        assert result == "encrypted_value"

    def test_returns_raw_encrypted_bytes_without_encrypted_flag(self, auth_manager):
        from src.utils.encryption import encrypt_value

        plaintext = "secret_value"
        encrypted = encrypt_value(plaintext)
        auth_manager.save_config("raw_key", encrypted)

        # Without encrypted=True, returns raw stored value (still encrypted)
        result = auth_manager.get_config("raw_key", encrypted=False)
        assert result == encrypted
        assert result != plaintext

    def test_returns_none_when_config_has_no_value(self, auth_manager, db_session):
        config = Config(key="null_value_key", value=None)
        db_session.add(config)
        db_session.commit()

        result = auth_manager.get_config("null_value_key")
        assert result is None
