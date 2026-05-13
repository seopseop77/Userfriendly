"""Alembic env for llm_tracker_server (PostgreSQL, asyncpg).

`sqlalchemy.url` in `alembic.ini` is documentation only. The runtime URL
is read from `LLMTRACK_DATABASE_URL` (matches the server's pydantic
Settings) so a single env var drives both the app and the migration
runner. Online-mode uses an async engine via asyncpg; offline-mode emits
SQL against the URL as given.
"""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

env_url = os.environ.get("LLMTRACK_DATABASE_URL")
if env_url:
    config.set_main_option("sqlalchemy.url", env_url)

from llm_tracker_server.storage.models import Base  # noqa: E402

target_metadata = Base.metadata


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url")
    # `statement_cache_size=0` disables asyncpg's prepared-statement cache for
    # pgbouncer transaction-mode pooling (Supabase). No-op on direct PG.
    engine = create_async_engine(
        url,
        connect_args={"statement_cache_size": 0},
    )
    async with engine.connect() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
