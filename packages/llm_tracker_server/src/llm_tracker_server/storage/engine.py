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
    # `statement_cache_size=0` disables asyncpg's prepared-statement cache,
    # required under pgbouncer transaction-mode pooling (Supabase) which does
    # not preserve statement names across pooled sessions. No-op on direct PG.
    return create_async_engine(
        database_url,
        echo=False,
        future=True,
        connect_args={"statement_cache_size": 0},
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
