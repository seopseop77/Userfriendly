"""Runtime configuration via pydantic-settings (env prefix: LLMTRACK_)."""

from enum import StrEnum

from pydantic_settings import BaseSettings


class Mode(StrEnum):
    L = "L"
    A = "A"
    R = "R"


class Settings(BaseSettings):
    mode: Mode = Mode.L
    proxy_host: str = "127.0.0.1"
    proxy_port: int = 8787
    db_url: str = "sqlite+aiosqlite:///./var/llm_tracker.db"

    model_config = {"env_prefix": "LLMTRACK_"}
