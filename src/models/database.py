"""SQLAlchemy database models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class EeroNode(Base):
    """Eero mesh network node (eero device)."""

    __tablename__ = "eero_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    eero_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String)
    model: Mapped[Optional[str]] = mapped_column(String)
    mac_address: Mapped[Optional[str]] = mapped_column(String)
    is_gateway: Mapped[Optional[bool]] = mapped_column(Boolean)
    os_version: Mapped[Optional[str]] = mapped_column(String)
    update_available: Mapped[Optional[bool]] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Relationships
    metrics: Mapped[list["EeroNodeMetric"]] = relationship(back_populates="eero_node")
    device_connections: Mapped[list["DeviceConnection"]] = relationship(
        back_populates="eero_node"
    )


class Device(Base):
    """Connected client device."""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mac_address: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    hostname: Mapped[Optional[str]] = mapped_column(String)
    nickname: Mapped[Optional[str]] = mapped_column(String)
    device_type: Mapped[Optional[str]] = mapped_column(String)
    aliases: Mapped[Optional[str]] = mapped_column(Text)  # JSON array of alias strings
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Relationships
    connections: Mapped[list["DeviceConnection"]] = relationship(back_populates="device")


class DeviceConnection(Base):
    """Time-series device connection metrics."""

    __tablename__ = "device_connections"
    __table_args__ = (
        # Indexes for efficient querying
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("devices.id"), nullable=False
    )
    eero_node_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("eero_nodes.id")
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )
    is_connected: Mapped[Optional[bool]] = mapped_column(Boolean)
    connection_type: Mapped[Optional[str]] = mapped_column(String)  # wireless/wired
    signal_strength: Mapped[Optional[int]] = mapped_column(Integer)
    ip_address: Mapped[Optional[str]] = mapped_column(String)
    bandwidth_down_mbps: Mapped[Optional[float]] = mapped_column(Float)
    bandwidth_up_mbps: Mapped[Optional[float]] = mapped_column(Float)

    # Relationships
    device: Mapped["Device"] = relationship(back_populates="connections")
    eero_node: Mapped[Optional["EeroNode"]] = relationship(
        back_populates="device_connections"
    )


class NetworkMetric(Base):
    """Network-wide time-series metrics."""

    __tablename__ = "network_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )
    total_devices: Mapped[Optional[int]] = mapped_column(Integer)
    total_devices_online: Mapped[Optional[int]] = mapped_column(Integer)
    guest_network_enabled: Mapped[Optional[bool]] = mapped_column(Boolean)
    wan_status: Mapped[Optional[str]] = mapped_column(String)


class Speedtest(Base):
    """Historical speedtest results."""

    __tablename__ = "speedtests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )
    download_mbps: Mapped[Optional[float]] = mapped_column(Float)
    upload_mbps: Mapped[Optional[float]] = mapped_column(Float)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float)
    jitter_ms: Mapped[Optional[float]] = mapped_column(Float)
    server_location: Mapped[Optional[str]] = mapped_column(String)
    isp: Mapped[Optional[str]] = mapped_column(String)


class EeroNodeMetric(Base):
    """Per-node time-series metrics."""

    __tablename__ = "eero_node_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    eero_node_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("eero_nodes.id"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )
    status: Mapped[Optional[str]] = mapped_column(String)  # online/offline
    connected_device_count: Mapped[Optional[int]] = mapped_column(Integer)
    connected_wired_count: Mapped[Optional[int]] = mapped_column(Integer)
    connected_wireless_count: Mapped[Optional[int]] = mapped_column(Integer)
    uptime_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    mesh_quality_bars: Mapped[Optional[int]] = mapped_column(Integer)  # 1-5 bars

    # Relationships
    eero_node: Mapped["EeroNode"] = relationship(back_populates="metrics")


class DailyBandwidth(Base):
    """Daily accumulated bandwidth statistics per device."""

    __tablename__ = "daily_bandwidth"
    __table_args__ = (
        UniqueConstraint('device_id', 'date', name='uix_device_date'),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("devices.id")
    )  # NULL = network-wide totals
    date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)

    # Accumulated totals in MB for this day
    download_mb: Mapped[float] = mapped_column(Float, default=0.0)
    upload_mb: Mapped[float] = mapped_column(Float, default=0.0)

    # Track last collection time to calculate deltas
    last_collection_time: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    device: Mapped[Optional["Device"]] = relationship()


class Config(Base):
    """Application configuration key-value store."""

    __tablename__ = "config"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


def create_tables(database_url: str) -> None:
    """Create all database tables."""
    engine = create_engine(database_url, echo=False)
    Base.metadata.create_all(engine)


if __name__ == "__main__":
    # Allow running this module to initialize database
    from src.config import get_settings

    settings = get_settings()
    db_url = f"sqlite:///{settings.database_path}"
    print(f"Creating tables in {settings.database_path}")
    create_tables(db_url)
    print("Database tables created successfully")
