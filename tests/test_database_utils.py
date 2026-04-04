"""Tests for utils/database.py - database utility functions."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from src.models.database import Base


@pytest.fixture(autouse=True)
def reset_database_globals():
    """Reset global engine and session factory between tests."""
    import src.utils.database as db_mod
    original_engine = db_mod._engine
    original_session = db_mod._SessionLocal
    yield
    db_mod._engine = original_engine
    db_mod._SessionLocal = original_session


@pytest.fixture
def mock_settings():
    """Mock settings to use in-memory database."""
    settings = MagicMock()
    settings.database_path = ":memory:"
    settings.debug = False
    return settings


class TestGetEngine:
    def test_returns_engine_instance(self, mock_settings):
        import src.utils.database as db_mod
        with patch("src.utils.database.get_settings", return_value=mock_settings):
            db_mod._engine = None
            engine = db_mod.get_engine()
            assert engine is not None

    def test_returns_same_engine_on_second_call(self, mock_settings):
        import src.utils.database as db_mod
        with patch("src.utils.database.get_settings", return_value=mock_settings):
            db_mod._engine = None
            engine1 = db_mod.get_engine()
            engine2 = db_mod.get_engine()
            assert engine1 is engine2

    def test_creates_new_engine_after_reset(self, mock_settings):
        import src.utils.database as db_mod
        with patch("src.utils.database.get_settings", return_value=mock_settings):
            db_mod._engine = None
            engine = db_mod.get_engine()
            assert engine is not None


class TestGetSessionFactory:
    def test_returns_session_factory(self, mock_settings):
        import src.utils.database as db_mod
        with patch("src.utils.database.get_settings", return_value=mock_settings):
            db_mod._engine = None
            db_mod._SessionLocal = None
            factory = db_mod.get_session_factory()
            assert factory is not None

    def test_returns_same_factory_on_second_call(self, mock_settings):
        import src.utils.database as db_mod
        with patch("src.utils.database.get_settings", return_value=mock_settings):
            db_mod._engine = None
            db_mod._SessionLocal = None
            factory1 = db_mod.get_session_factory()
            factory2 = db_mod.get_session_factory()
            assert factory1 is factory2


class TestGetDb:
    def test_yields_a_session(self, mock_settings):
        import src.utils.database as db_mod
        with patch("src.utils.database.get_settings", return_value=mock_settings):
            db_mod._engine = None
            db_mod._SessionLocal = None
            gen = db_mod.get_db()
            session = next(gen)
            assert session is not None
            try:
                next(gen)
            except StopIteration:
                pass

    def test_rollback_on_exception(self, mock_settings):
        import src.utils.database as db_mod
        with patch("src.utils.database.get_settings", return_value=mock_settings):
            db_mod._engine = None
            db_mod._SessionLocal = None
            gen = db_mod.get_db()
            session = next(gen)
            try:
                gen.throw(RuntimeError("Test error"))
            except RuntimeError:
                pass


class TestGetDbContext:
    def test_yields_a_session(self, mock_settings):
        import src.utils.database as db_mod
        with patch("src.utils.database.get_settings", return_value=mock_settings):
            db_mod._engine = None
            db_mod._SessionLocal = None
            with db_mod.get_db_context() as session:
                assert session is not None

    def test_rollback_on_exception(self, mock_settings):
        import src.utils.database as db_mod
        with patch("src.utils.database.get_settings", return_value=mock_settings):
            db_mod._engine = None
            db_mod._SessionLocal = None
            try:
                with db_mod.get_db_context() as session:
                    raise RuntimeError("Force rollback")
            except RuntimeError:
                pass


class TestInitDatabase:
    def test_creates_database_tables(self, tmp_path):
        import src.utils.database as db_mod
        settings = MagicMock()
        settings.database_path = str(tmp_path / "test.db")
        settings.debug = False
        with patch("src.utils.database.get_settings", return_value=settings):
            db_mod._engine = None
            db_mod._SessionLocal = None
            with patch("src.utils.database._run_structured_migrations"):
                db_mod.init_database()
                engine = db_mod.get_engine()
                inspector = inspect(engine)
                table_names = inspector.get_table_names()
                assert "devices" in table_names
                assert "device_connections" in table_names

    def test_can_be_called_multiple_times(self, tmp_path):
        import src.utils.database as db_mod
        settings = MagicMock()
        settings.database_path = str(tmp_path / "test.db")
        settings.debug = False
        with patch("src.utils.database.get_settings", return_value=settings):
            db_mod._engine = None
            db_mod._SessionLocal = None
            with patch("src.utils.database._run_structured_migrations"):
                db_mod.init_database()
                db_mod.init_database()


class TestRunMigrations:
    """Tests for _run_migrations function (ad-hoc migration logic)."""

    def test_adds_aliases_column_if_missing(self):
        from src.utils.database import _run_migrations

        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE devices ("
                "id INTEGER PRIMARY KEY, "
                "network_name TEXT, "
                "mac_address TEXT, "
                "hostname TEXT, "
                "nickname TEXT, "
                "device_type TEXT, "
                "first_seen DATETIME, "
                "last_seen DATETIME, "
                "manufacturer VARCHAR"
                ")"
            ))
            conn.commit()

        _run_migrations(engine)

        inspector = inspect(engine)
        columns = [col["name"] for col in inspector.get_columns("devices")]
        assert "aliases" in columns

    def test_adds_manufacturer_column_if_missing(self):
        from src.utils.database import _run_migrations

        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE devices ("
                "id INTEGER PRIMARY KEY, "
                "network_name TEXT, "
                "mac_address TEXT, "
                "aliases TEXT"
                ")"
            ))
            conn.commit()

        _run_migrations(engine)

        inspector = inspect(engine)
        columns = [col["name"] for col in inspector.get_columns("devices")]
        assert "manufacturer" in columns

    def test_adds_mesh_quality_bars_if_missing(self):
        from src.utils.database import _run_migrations

        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE eero_node_metrics ("
                "id INTEGER PRIMARY KEY, "
                "eero_node_id INTEGER, "
                "timestamp DATETIME, "
                "status TEXT, "
                "connected_device_count INTEGER, "
                "connected_wired_count INTEGER, "
                "connected_wireless_count INTEGER, "
                "uptime_seconds INTEGER"
                ")"
            ))
            conn.commit()

        _run_migrations(engine)

        inspector = inspect(engine)
        columns = [col["name"] for col in inspector.get_columns("eero_node_metrics")]
        assert "mesh_quality_bars" in columns

    def test_adds_is_guest_column_if_missing(self):
        from src.utils.database import _run_migrations

        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE device_connections ("
                "id INTEGER PRIMARY KEY, "
                "network_name TEXT, "
                "device_id INTEGER, "
                "timestamp DATETIME, "
                "is_connected BOOLEAN"
                ")"
            ))
            conn.commit()

        _run_migrations(engine)

        inspector = inspect(engine)
        columns = [col["name"] for col in inspector.get_columns("device_connections")]
        assert "is_guest" in columns

    def test_migration_skipped_when_columns_exist(self):
        from src.utils.database import _run_migrations

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        _run_migrations(engine)


class TestRunStructuredMigrations:
    def test_handles_exception_gracefully(self, mock_settings):
        import src.utils.database as db_mod
        with patch("src.utils.database.get_settings", return_value=mock_settings):
            db_mod._engine = None
            db_mod._SessionLocal = None
            with patch("src.utils.database.get_db_context", side_effect=Exception("fail")):
                db_mod._run_structured_migrations()  # Should not raise
