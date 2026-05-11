"""Process-wide settings (pydantic-settings, env prefix LLMTRACK_)."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    log_level: str = "INFO"
    # PostgreSQL connection URL consumed by SQLAlchemy + Alembic.
    # Format: postgresql+asyncpg://user:pass@host:port/dbname
    # Required in any environment that touches the storage layer;
    # the bare /healthz path keeps booting without it.
    database_url: str = ""

    model_config = {"env_prefix": "LLMTRACK_"}
