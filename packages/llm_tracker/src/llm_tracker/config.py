"""Runtime configuration via pydantic-settings (env prefix: LLMTRACK_)."""

from enum import StrEnum
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode


class Mode(StrEnum):
    L = "L"
    A = "A"
    R = "R"


class Settings(BaseSettings):
    mode: Mode = Mode.L
    proxy_host: str = "127.0.0.1"
    proxy_port: int = 8787
    db_url: str = "sqlite+aiosqlite:///./var/llm_tracker.db"
    # Comma-separated list of plugin manifest names to skip at load time
    # (ADR-0013). `NoDecode` keeps pydantic-settings from JSON-decoding
    # the env var; the validator below splits the raw CSV string.
    plugins_disabled: Annotated[list[str], NoDecode] = []
    # Process-wide user opt-in flag (ADR-0016). Default False keeps
    # ADR-0006's "off by default" axiom intact — Mode R's content
    # ceiling stays at L1 until the operator sets this. The real
    # per-task consent UX is Phase-2 stretch.
    user_opted_in: bool = False

    model_config = {"env_prefix": "LLMTRACK_"}

    @field_validator("plugins_disabled", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        # Env vars arrive as strings; accept "a,b , c" → ["a", "b", "c"].
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v
