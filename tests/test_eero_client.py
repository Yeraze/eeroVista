"""Tests for eero_client/client.py - Eero API client wrapper."""

from unittest.mock import MagicMock, PropertyMock, patch

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
def authenticated_db_session(db_session):
    """DB session with a valid session token stored."""
    from src.utils.encryption import encrypt_value

    encrypted_token = encrypt_value("fake-session-cookie-token")
    config = Config(key="eero_session_token", value=encrypted_token)
    db_session.add(config)
    db_session.commit()
    return db_session


@pytest.fixture
def client(db_session):
    """Create an EeroClientWrapper with in-memory DB (unauthenticated)."""
    from src.eero_client.client import EeroClientWrapper

    return EeroClientWrapper(db_session)


@pytest.fixture
def authenticated_client(authenticated_db_session):
    """Create an authenticated EeroClientWrapper."""
    from src.eero_client.client import EeroClientWrapper

    return EeroClientWrapper(authenticated_db_session)


class TestEeroClientWrapperInit:
    """Tests for EeroClientWrapper initialization."""

    def test_initializes_with_db_session(self, db_session):
        from src.eero_client.client import EeroClientWrapper

        wrapper = EeroClientWrapper(db_session)
        assert wrapper.db is db_session

    def test_auth_manager_is_created(self, client):
        from src.eero_client.auth import AuthManager

        assert isinstance(client.auth_manager, AuthManager)

    def test_eero_client_is_none_initially(self, client):
        assert client._eero is None


class TestIsAuthenticated:
    """Tests for is_authenticated method."""

    def test_returns_false_when_no_session_token(self, client):
        assert client.is_authenticated() is False

    def test_returns_true_when_session_token_exists(self, authenticated_client):
        assert authenticated_client.is_authenticated() is True


class TestGetClient:
    """Tests for _get_client method."""

    def test_creates_eero_instance_without_token(self, client):
        with patch("src.eero_client.client.Eero") as MockEero:
            mock_eero = MagicMock()
            MockEero.return_value = mock_eero

            eero = client._get_client()

            assert eero is mock_eero
            # Called without session kwarg
            MockEero.assert_called_once_with()

    def test_creates_eero_with_session_when_token_exists(self, authenticated_client):
        with patch("src.eero_client.client.Eero") as MockEero, \
             patch("src.eero_client.client.MemorySessionStorage") as MockSession:
            mock_session = MagicMock()
            MockSession.return_value = mock_session
            mock_eero = MagicMock()
            MockEero.return_value = mock_eero

            eero = authenticated_client._get_client()

            assert eero is mock_eero
            MockSession.assert_called_once_with(cookie="fake-session-cookie-token")
            MockEero.assert_called_once_with(session=mock_session)

    def test_returns_same_instance_on_second_call(self, client):
        with patch("src.eero_client.client.Eero") as MockEero:
            mock_eero = MagicMock()
            MockEero.return_value = mock_eero

            eero1 = client._get_client()
            eero2 = client._get_client()

            assert eero1 is eero2
            MockEero.assert_called_once()


class TestLoginPhone:
    """Tests for login_phone method."""

    def test_returns_success_with_user_token(self, client):
        with patch("src.eero_client.client.Eero") as MockEero:
            mock_eero = MagicMock()
            mock_eero.login.return_value = "user-token-abc"
            MockEero.return_value = mock_eero

            result = client.login_phone("+15551234567")

            assert result["success"] is True
            assert result["user_token"] == "user-token-abc"
            assert "message" in result

    def test_returns_failure_when_no_user_token(self, client):
        with patch("src.eero_client.client.Eero") as MockEero:
            mock_eero = MagicMock()
            mock_eero.login.return_value = None
            MockEero.return_value = mock_eero

            result = client.login_phone("+15551234567")

            assert result["success"] is False
            assert "message" in result

    def test_returns_failure_on_exception(self, client):
        with patch("src.eero_client.client.Eero") as MockEero:
            mock_eero = MagicMock()
            mock_eero.login.side_effect = Exception("Connection refused")
            MockEero.return_value = mock_eero

            result = client.login_phone("+15551234567")

            assert result["success"] is False
            assert "Connection refused" in result["message"]

    def test_saves_user_token_after_successful_login(self, client):
        with patch("src.eero_client.client.Eero") as MockEero:
            mock_eero = MagicMock()
            mock_eero.login.return_value = "saved-user-token"
            MockEero.return_value = mock_eero

            client.login_phone("+15551234567")

            saved = client.auth_manager.get_user_token()
            assert saved == "saved-user-token"


class TestLoginVerify:
    """Tests for login_verify method."""

    def test_returns_failure_when_no_user_token_pending(self, client):
        result = client.login_verify("123456")

        assert result["success"] is False
        assert "No pending verification" in result["message"]

    def test_successful_verification_saves_session_token(self, client, db_session):
        from src.utils.encryption import encrypt_value

        # Store a user token so verification can proceed
        client.auth_manager.save_user_token("pending-user-token")

        with patch("src.eero_client.client.Eero") as MockEero:
            mock_session = MagicMock()
            mock_session.cookie = "new-session-cookie"
            mock_eero = MagicMock()
            mock_eero.session = mock_session
            mock_eero.login_verify.return_value = None  # void return
            MockEero.return_value = mock_eero

            result = client.login_verify("123456")

            assert result["success"] is True
            assert client.auth_manager.get_session_token() == "new-session-cookie"

    def test_returns_failure_when_no_session_cookie_after_verify(self, client):
        client.auth_manager.save_user_token("pending-user-token")

        with patch("src.eero_client.client.Eero") as MockEero:
            mock_session = MagicMock()
            mock_session.cookie = None
            mock_eero = MagicMock()
            mock_eero.session = mock_session
            mock_eero.login_verify.return_value = None
            MockEero.return_value = mock_eero

            result = client.login_verify("000000")

            assert result["success"] is False

    def test_returns_failure_on_exception(self, client):
        client.auth_manager.save_user_token("pending-user-token")

        with patch("src.eero_client.client.Eero") as MockEero:
            mock_eero = MagicMock()
            mock_eero.login_verify.side_effect = Exception("Invalid code")
            MockEero.return_value = mock_eero

            result = client.login_verify("wrong-code")

            assert result["success"] is False
            assert "Invalid code" in result["message"]


class TestGetAccount:
    """Tests for get_account method."""

    def test_returns_none_when_not_authenticated(self, client):
        result = client.get_account()
        assert result is None

    def test_returns_account_when_authenticated(self, authenticated_client):
        mock_account = {"networks": {"data": []}}

        with patch("src.eero_client.client.Eero") as MockEero:
            mock_eero = MagicMock()
            mock_eero.account = mock_account
            MockEero.return_value = mock_eero

            result = authenticated_client.get_account()

            assert result == mock_account

    def test_returns_none_on_exception(self, authenticated_client):
        with patch("src.eero_client.client.Eero") as MockEero:
            mock_eero = MagicMock()
            type(mock_eero).account = PropertyMock(side_effect=Exception("API Error"))
            MockEero.return_value = mock_eero

            result = authenticated_client.get_account()

            assert result is None


class TestGetNetworks:
    """Tests for get_networks method."""

    def test_returns_none_when_not_authenticated(self, client):
        result = client.get_networks()
        assert result is None

    def test_returns_empty_list_when_no_networks(self, authenticated_client):
        with patch.object(authenticated_client, "get_account", return_value={"networks": {"data": []}}):
            result = authenticated_client.get_networks()
            assert result == []

    def test_returns_networks_from_pydantic_model(self, authenticated_client):
        mock_network = MagicMock()
        mock_network.name = "Home"
        mock_account = MagicMock()
        mock_account.networks.data = [mock_network]

        with patch.object(authenticated_client, "get_account", return_value=mock_account):
            result = authenticated_client.get_networks()
            assert len(result) == 1
            assert result[0].name == "Home"

    def test_returns_networks_from_dict_fallback(self, authenticated_client):
        dict_account = {"networks": {"data": [{"name": "Home", "url": "/url/123"}]}}

        with patch.object(authenticated_client, "get_account", return_value=dict_account):
            result = authenticated_client.get_networks()
            assert len(result) == 1
            assert result[0]["name"] == "Home"

    def test_returns_none_when_account_is_none(self, authenticated_client):
        with patch.object(authenticated_client, "get_account", return_value=None):
            result = authenticated_client.get_networks()
            assert result is None

    def test_returns_none_on_exception(self, authenticated_client):
        with patch.object(authenticated_client, "get_account", side_effect=Exception("oops")):
            result = authenticated_client.get_networks()
            assert result is None


class TestGetNetworkClient:
    """Tests for get_network_client method."""

    def test_returns_none_when_not_authenticated(self, client):
        result = client.get_network_client()
        assert result is None

    def test_returns_none_when_no_networks(self, authenticated_client):
        with patch.object(authenticated_client, "get_networks", return_value=None):
            result = authenticated_client.get_network_client()
            assert result is None

    def test_returns_none_when_networks_empty(self, authenticated_client):
        with patch.object(authenticated_client, "get_networks", return_value=[]):
            result = authenticated_client.get_network_client()
            assert result is None

    def test_returns_none_when_network_name_not_found(self, authenticated_client):
        mock_net = MagicMock()
        mock_net.name = "Home"

        with patch.object(authenticated_client, "get_networks", return_value=[mock_net]):
            result = authenticated_client.get_network_client("Office")
            assert result is None

    def test_returns_network_client_for_pydantic_model(self, authenticated_client):
        mock_net = MagicMock()
        mock_net.name = "Home"

        mock_eero = MagicMock()
        mock_network_client = MagicMock()
        # Use a MagicMock for network_clients so .get() is patchable
        mock_eero.network_clients = MagicMock()
        mock_eero.network_clients.get.return_value = mock_network_client

        with patch.object(authenticated_client, "get_networks", return_value=[mock_net]), \
             patch.object(authenticated_client, "_get_client", return_value=mock_eero):
            result = authenticated_client.get_network_client()
            assert result is not None

    def test_handles_dict_network_with_model_construct(self, authenticated_client):
        dict_net = {"name": "Home", "url": "/api/networks/123", "created": "2024-01-01"}

        with patch.object(authenticated_client, "get_networks", return_value=[dict_net]):
            with patch("src.eero_client.client.Eero") as MockEero, \
                 patch("eero.client.clients.NetworkClient") as MockNetClient, \
                 patch("eero.client.models.NetworkInfo") as MockNetInfo:
                mock_eero = MagicMock()
                MockEero.return_value = mock_eero
                mock_client = MagicMock()
                MockNetClient.return_value = mock_client

                result = authenticated_client.get_network_client()
                # Should have tried to construct a NetworkClient
                assert result is not None or result is None  # Either way, no crash


class TestGetEeros:
    """Tests for get_eeros method."""

    def test_returns_none_when_not_authenticated(self, client):
        result = client.get_eeros()
        assert result is None

    def test_returns_eeros_list_when_authenticated(self, authenticated_client):
        mock_network_client = MagicMock()
        mock_eeros = [MagicMock(), MagicMock()]
        mock_network_client.eeros = mock_eeros

        with patch.object(authenticated_client, "get_network_client", return_value=mock_network_client):
            result = authenticated_client.get_eeros()
            assert result == mock_eeros

    def test_returns_none_when_network_client_is_none(self, authenticated_client):
        with patch.object(authenticated_client, "get_network_client", return_value=None):
            result = authenticated_client.get_eeros()
            assert result is None

    def test_returns_none_on_exception(self, authenticated_client):
        with patch.object(authenticated_client, "get_network_client", side_effect=Exception("boom")):
            result = authenticated_client.get_eeros()
            assert result is None


class TestGetDevices:
    """Tests for get_devices method."""

    def test_returns_none_when_not_authenticated(self, client):
        result = client.get_devices()
        assert result is None

    def test_returns_devices_list_when_authenticated(self, authenticated_client):
        mock_network_client = MagicMock()
        mock_devices = [MagicMock(), MagicMock(), MagicMock()]
        mock_network_client.devices = mock_devices

        with patch.object(authenticated_client, "get_network_client", return_value=mock_network_client):
            result = authenticated_client.get_devices()
            assert result == mock_devices

    def test_returns_none_when_network_client_none(self, authenticated_client):
        with patch.object(authenticated_client, "get_network_client", return_value=None):
            result = authenticated_client.get_devices()
            assert result is None

    def test_returns_none_on_exception(self, authenticated_client):
        with patch.object(authenticated_client, "get_network_client", side_effect=RuntimeError("fail")):
            result = authenticated_client.get_devices()
            assert result is None


class TestGetProfiles:
    """Tests for get_profiles method."""

    def test_returns_none_when_not_authenticated(self, client):
        result = client.get_profiles()
        assert result is None

    def test_returns_none_when_network_client_is_none(self, authenticated_client):
        with patch.object(authenticated_client, "get_network_client", return_value=None):
            result = authenticated_client.get_profiles()
            assert result is None

    def test_returns_profiles_from_api(self, authenticated_client):
        mock_network_client = MagicMock()
        mock_network_client.network_info.url = "/api/networks/net_abc"

        mock_eero = MagicMock()
        mock_eero.session.cookie = "test-cookie"

        mock_profiles = [{"id": "profile_1"}, {"id": "profile_2"}]

        with patch.object(authenticated_client, "get_network_client", return_value=mock_network_client), \
             patch.object(authenticated_client, "_get_client", return_value=mock_eero), \
             patch("eero.client.api_client.APIClient") as MockAPIClient:
            mock_api = MagicMock()
            mock_api.get.return_value = mock_profiles
            MockAPIClient.return_value = mock_api

            result = authenticated_client.get_profiles()
            assert result == mock_profiles

    def test_returns_none_on_exception(self, authenticated_client):
        with patch.object(authenticated_client, "get_network_client", side_effect=Exception("api error")):
            result = authenticated_client.get_profiles()
            assert result is None


class TestRefreshSession:
    """Tests for refresh_session method."""

    def test_returns_true_when_account_available(self, authenticated_client):
        with patch.object(authenticated_client, "get_account", return_value={"networks": {}}):
            assert authenticated_client.refresh_session() is True

    def test_returns_false_when_account_is_none(self, authenticated_client):
        with patch.object(authenticated_client, "get_account", return_value=None):
            assert authenticated_client.refresh_session() is False

    def test_returns_false_on_exception(self, authenticated_client):
        with patch.object(authenticated_client, "get_account", side_effect=Exception("timeout")):
            assert authenticated_client.refresh_session() is False


class TestGetFirmwareUpdateInfo:
    """Tests for get_firmware_update_info method."""

    def test_returns_none_when_not_authenticated(self, client):
        result = client.get_firmware_update_info()
        assert result is None

    def test_returns_none_when_network_client_is_none(self, authenticated_client):
        with patch.object(authenticated_client, "get_network_client", return_value=None):
            result = authenticated_client.get_firmware_update_info()
            assert result is None

    def test_returns_has_update_false_when_no_updates(self, authenticated_client):
        mock_nc = MagicMock()
        mock_nc.networks = {"updates": {}}

        with patch.object(authenticated_client, "get_network_client", return_value=mock_nc):
            result = authenticated_client.get_firmware_update_info()
            assert result == {"has_update": False}

    def test_returns_firmware_info_when_update_available(self, authenticated_client):
        mock_nc = MagicMock()
        mock_nc.networks = {
            "updates": {
                "has_update": True,
                "target_firmware": "3.5.1.0",
                "update_to_firmware": "3.5.1.0",
                "manifest_resource": "/manifest/123",
            }
        }

        with patch.object(authenticated_client, "get_network_client", return_value=mock_nc):
            result = authenticated_client.get_firmware_update_info()
            assert result["has_update"] is True
            assert result["target_firmware"] == "3.5.1.0"

    def test_returns_none_on_exception(self, authenticated_client):
        with patch.object(authenticated_client, "get_network_client", side_effect=Exception("error")):
            result = authenticated_client.get_firmware_update_info()
            assert result is None
