"""
Database plumbing — async SQLAlchemy 2.0 engine, session factory, declarative Base.

The engine is created from `db_settings.url`, which resolves to either the parts
(local container) or a full `DATABASE_URL` (remote DB "by link"). Both the API
(`get_db` dependency) and the worker (its own session factory) build on this.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.settings.config import db_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models (SQLAlchemy 2.0 typed style)."""


engine = create_async_engine(
    db_settings.url,
    echo=False,  # flip to True locally if you need to see raw SQL; noisy in every log otherwise
    future=True,
    pool_pre_ping=True,  # survive stale connections to remote DBs
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a session and guarantees close."""
    async with AsyncSessionLocal() as session:
        yield session
