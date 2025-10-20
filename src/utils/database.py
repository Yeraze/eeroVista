"""Database utility functions."""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.config import get_settings

# Global engine and session factory
_engine = None
_SessionLocal = None


def get_engine():
    """Get or create database engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        database_url = f"sqlite:///{settings.database_path}"
        _engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},  # Required for SQLite
            echo=settings.debug,
        )
    return _engine


def get_session_factory():
    """Get or create session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=get_engine()
        )
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """Get database session for FastAPI dependency injection."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """Get database session context manager for direct use (e.g., CLI scripts)."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_database() -> None:
    """Initialize database tables."""
    from src.models.database import Base

    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    # Run migrations
    _run_migrations(engine)


def _run_migrations(engine) -> None:
    """Run database migrations."""
    import logging
    from sqlalchemy import inspect, text

    logger = logging.getLogger(__name__)
    inspector = inspect(engine)

    # Migration: Add aliases column to devices table if it doesn't exist
    if "devices" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("devices")]
        if "aliases" not in columns:
            logger.info("Running migration: Adding 'aliases' column to devices table")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE devices ADD COLUMN aliases TEXT"))
                conn.commit()
            logger.info("Migration complete: 'aliases' column added")

    # Migration: Add mesh quality and client count breakdown columns to eero_node_metrics table
    if "eero_node_metrics" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("eero_node_metrics")]

        if "mesh_quality_bars" not in columns:
            logger.info("Running migration: Adding 'mesh_quality_bars' column to eero_node_metrics table")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE eero_node_metrics ADD COLUMN mesh_quality_bars INTEGER"))
                conn.commit()
            logger.info("Migration complete: 'mesh_quality_bars' column added")

        if "connected_wired_count" not in columns:
            logger.info("Running migration: Adding 'connected_wired_count' column to eero_node_metrics table")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE eero_node_metrics ADD COLUMN connected_wired_count INTEGER"))
                conn.commit()
            logger.info("Migration complete: 'connected_wired_count' column added")

        if "connected_wireless_count" not in columns:
            logger.info("Running migration: Adding 'connected_wireless_count' column to eero_node_metrics table")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE eero_node_metrics ADD COLUMN connected_wireless_count INTEGER"))
                conn.commit()
            logger.info("Migration complete: 'connected_wireless_count' column added")
