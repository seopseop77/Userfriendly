"""Async SQLAlchemy engine + session factory (PostgreSQL via asyncpg)."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(database_url: str) -> AsyncEngine:
    if not database_url:
        raise ValueError("database_url is required (set LLMTRACK_DATABASE_URL)")
    return create_async_engine(database_url, echo=False, future=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
