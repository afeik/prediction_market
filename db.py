"""Database layer (SQLAlchemy 2.0).

Portable across SQLite (local dev) and PostgreSQL (Supabase / Neon in
production). Set the DATABASE_URL env var to point at Postgres; otherwise a
local market.db SQLite file is used.
"""
from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    sessionmaker,
)

def _database_url() -> str:
    """Resolve the database URL from, in order of priority:

    1. The DATABASE_URL environment variable (used by smoke_test and local runs).
    2. Streamlit Cloud secrets (when running inside a deployed Streamlit app).
    3. A local SQLite file for development.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        try:  # only available when running under Streamlit
            import streamlit as st

            url = st.secrets.get("DATABASE_URL")
        except Exception:
            url = None
    if not url:
        url = "sqlite:///market.db"
    # Some hosts hand out postgres:// URLs; SQLAlchemy wants postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


DATABASE_URL = _database_url()

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL, connect_args={"check_same_thread": False}, future=True
    )
else:
    # Postgres (Supabase / Neon): pool_pre_ping recovers from idle connections
    # that the serverless database closes between trades; pool_recycle keeps
    # connections fresh so reruns stay snappy.
    engine = create_engine(
        DATABASE_URL, pool_pre_ping=True, pool_recycle=300, future=True
    )

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    balance: Mapped[float] = mapped_column(Float, default=1000.0)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Market(Base):
    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(String(1000), default="")
    category: Mapped[str] = mapped_column(String(50), default="Other")
    b: Mapped[float] = mapped_column(Float, default=100.0)
    q_yes: Mapped[float] = mapped_column(Float, default=0.0)
    q_no: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | resolved
    outcome: Mapped[str | None] = mapped_column(String(10), nullable=True)  # yes | no
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    close_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # trading deadline (UTC)


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("user_id", "market_id", name="uq_user_market"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    yes_shares: Mapped[float] = mapped_column(Float, default=0.0)
    no_shares: Mapped[float] = mapped_column(Float, default=0.0)


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    side: Mapped[str] = mapped_column(String(10))  # yes | no
    action: Mapped[str] = mapped_column(String(10))  # buy | sell
    shares: Mapped[float] = mapped_column(Float)
    cost: Mapped[float] = mapped_column(Float)  # +paid / -received
    prob_after: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    question: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(String(1000), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | approved | rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


def init_db() -> None:
    """Create all tables if they do not exist yet."""
    Base.metadata.create_all(engine)


def reset_db() -> None:
    """Drop every table and recreate them — destroys ALL data. Used to wipe the
    database when starting a fresh game from scratch."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
