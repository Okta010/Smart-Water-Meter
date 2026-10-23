"""Database tables and session factory for the local development backend."""
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"
    customer_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    meter_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[str] = mapped_column(String(300), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    readings: Mapped[list["Reading"]] = relationship(back_populates="customer")


class Officer(Base):
    __tablename__ = "officers"
    officer_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)


class SessionToken(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(40), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Reading(Base):
    __tablename__ = "readings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"), nullable=False, index=True)
    measured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    meter_value: Mapped[float] = mapped_column(Float, nullable=False)
    daily_usage: Mapped[float] = mapped_column(Float, nullable=False)
    customer: Mapped[Customer] = relationship(back_populates="readings")
    __table_args__ = (UniqueConstraint("customer_id", "measured_at", name="uq_customer_reading_time"),)


def build_db(database_url: str | None = None):
    db_file = Path(__file__).resolve().parents[1] / "smart_water_meter.db"
    url = database_url or os.environ.get("SWM_DATABASE_URL") or f"sqlite:///{db_file.as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {}, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)
