"""Process-wide settings (pydantic-settings, env prefix LLMTRACK_)."""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    log_level: str = "INFO"
    # PostgreSQL connection URL consumed by SQLAlchemy + Alembic.
    # Format: postgresql+asyncpg://user:pass@host:port/dbname
    # Required in any environment that touches the storage layer;
    # the bare /healthz path keeps booting without it.
    database_url: str = ""
    # `exchanges.content_level` value written by every forwarder
    # storage helper. The four levels are defined in design.md §7.1:
    # L0 metadata-only, L1 + hashes, L2 + scrubbed body, L3 raw.
    # `Literal` rejects typos at Settings() instantiation so a bad
    # env value fails the server boot rather than silently
    # mis-labelling rows.
    content_level: Literal["L0", "L1", "L2", "L3"] = "L3"

    model_config = {"env_prefix": "LLMTRACK_"}
