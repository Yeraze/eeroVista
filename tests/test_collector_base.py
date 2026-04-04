"""Tests for src/collectors/base.py - BaseCollector."""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Base, Config
from src.collectors.base import BaseCollector


# ---------------------------------------------------------------------------
# Concrete subclass for testing the abstract base
# ---------------------------------------------------------------------------

class ConcreteCollector(BaseCollector):
    """Minimal concrete implementation of BaseCollector for testing."""

    def __init__(self, db, eero_client, collect_result=None, collect_raises=None):
        super().__init__(db, eero_client)
        self._collect_result = collect_result or {"items_collected": 5}
        self._collect_raises = collect_raises

    def collect(self) -> dict:
        if self._collect_raises:
            raise self._collect_raises
        return self._collect_result


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def mock_client():
    client = Mock()
    client.is_authenticated.return_value = True
    client.refresh_session.return_value = True
    return client


# ---------------------------------------------------------------------------
# __init__ tests
# ---------------------------------------------------------------------------

class TestBaseCollectorInit:
    def test_name_derived_from_class(self, db_session, mock_client):
        collector = ConcreteCollector(db_session, mock_client)
        assert collector.name == "ConcreteCollector"

    def test_db_and_client_stored(self, db_session, mock_client):
        collector = ConcreteCollector(db_session, mock_client)
        assert collector.db is db_session
        assert collector.eero_client is mock_client


# ---------------------------------------------------------------------------
# update_last_collection / get_last_collection tests
# ---------------------------------------------------------------------------

class TestLastCollection:
    def test_update_creates_config_row(self, db_session, mock_client):
        collector = ConcreteCollector(db_session, mock_client)
        collector.update_last_collection("devices")

        row = db_session.query(Config).filter(Config.key == "last_collection_devices").first()
        assert row is not None
        assert row.value is not None

    def test_update_overwrites_existing_row(self, db_session, mock_client):
        collector = ConcreteCollector(db_session, mock_client)
        collector.update_last_collection("devices")
        first_value = (
            db_session.query(Config)
            .filter(Config.key == "last_collection_devices")
            .first()
            .value
        )

        collector.update_last_collection("devices")
        second_value = (
            db_session.query(Config)
            .filter(Config.key == "last_collection_devices")
            .first()
            .value
        )

        # Both are ISO strings; second should be >= first
        assert second_value >= first_value

    def test_get_returns_none_when_missing(self, db_session, mock_client):
        collector = ConcreteCollector(db_session, mock_client)
        result = collector.get_last_collection("nonexistent")
        assert result is None

    def test_get_returns_datetime_after_update(self, db_session, mock_client):
        collector = ConcreteCollector(db_session, mock_client)
        collector.update_last_collection("network")
        result = collector.get_last_collection("network")
        assert isinstance(result, datetime)

    def test_update_handles_db_error_gracefully(self, db_session, mock_client):
        collector = ConcreteCollector(db_session, mock_client)
        # Simulate a DB error during commit
        collector.db = Mock()
        collector.db.query.return_value.filter.return_value.first.return_value = None
        collector.db.commit.side_effect = Exception("DB error")
        # Should not raise
        collector.update_last_collection("devices")
        collector.db.rollback.assert_called_once()

    def test_get_handles_db_error_gracefully(self, db_session, mock_client):
        collector = ConcreteCollector(db_session, mock_client)
        collector.db = Mock()
        collector.db.query.return_value.filter.return_value.first.side_effect = Exception("DB error")
        result = collector.get_last_collection("devices")
        assert result is None


# ---------------------------------------------------------------------------
# run() tests
# ---------------------------------------------------------------------------

class TestBaseCollectorRun:
    def test_run_returns_success_true_on_collect(self, db_session, mock_client):
        collector = ConcreteCollector(db_session, mock_client, collect_result={"items_collected": 3})
        result = collector.run()
        assert result["success"] is True
        assert result["items_collected"] == 3
        assert "duration_seconds" in result

    def test_run_skips_when_not_authenticated(self, db_session, mock_client):
        mock_client.is_authenticated.return_value = False
        collector = ConcreteCollector(db_session, mock_client)
        result = collector.run()
        assert result["success"] is False
        assert "Not authenticated" in result["error"]
        assert result["duration_seconds"] == 0

    def test_run_updates_last_collection_timestamp(self, db_session, mock_client):
        collector = ConcreteCollector(db_session, mock_client, collect_result={"items_collected": 1})
        collector.run()

        # ConcreteCollector -> "concrete" after stripping "Collector"
        row = (
            db_session.query(Config)
            .filter(Config.key == "last_collection_concrete")
            .first()
        )
        assert row is not None

    def test_run_returns_failure_on_exception(self, db_session, mock_client):
        collector = ConcreteCollector(
            db_session, mock_client, collect_raises=ValueError("boom")
        )
        result = collector.run()
        assert result["success"] is False
        assert "boom" in result["error"]
        assert result["duration_seconds"] >= 0

    def test_run_attempts_session_refresh_on_connection_error(self, db_session, mock_client):
        collector = ConcreteCollector(
            db_session,
            mock_client,
            collect_raises=RuntimeError("connection refused"),
        )
        collector.run()
        mock_client.refresh_session.assert_called_once()

    def test_run_attempts_session_refresh_on_401_error(self, db_session, mock_client):
        collector = ConcreteCollector(
            db_session,
            mock_client,
            collect_raises=RuntimeError("401 unauthorized"),
        )
        collector.run()
        mock_client.refresh_session.assert_called_once()

    def test_run_does_not_refresh_on_value_error(self, db_session, mock_client):
        collector = ConcreteCollector(
            db_session,
            mock_client,
            collect_raises=ValueError("bad value"),
        )
        collector.run()
        mock_client.refresh_session.assert_not_called()

    def test_run_handles_refresh_exception_gracefully(self, db_session, mock_client):
        mock_client.refresh_session.side_effect = RuntimeError("refresh failed")
        collector = ConcreteCollector(
            db_session,
            mock_client,
            collect_raises=RuntimeError("timeout"),
        )
        result = collector.run()
        assert result["success"] is False


# ---------------------------------------------------------------------------
# _should_refresh_session tests
# ---------------------------------------------------------------------------

class TestShouldRefreshSession:
    @pytest.fixture()
    def collector(self, db_session, mock_client):
        return ConcreteCollector(db_session, mock_client)

    @pytest.mark.parametrize("msg", [
        "connection refused",
        "timeout exceeded",
        "401 error",
        "403 forbidden",
        "unauthorized access",
        "network unreachable",
        "connection refused by server",
    ])
    def test_returns_true_for_api_errors(self, collector, msg):
        assert collector._should_refresh_session(RuntimeError(msg)) is True

    @pytest.mark.parametrize("msg", [
        "key error",
        "value is wrong",
        "attribute missing",
        "type mismatch",
    ])
    def test_returns_false_for_non_api_errors(self, collector, msg):
        assert collector._should_refresh_session(RuntimeError(msg)) is False
