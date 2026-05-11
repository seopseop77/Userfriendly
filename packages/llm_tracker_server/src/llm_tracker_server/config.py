"""Process-wide settings (pydantic-settings, env prefix LLMTRACK_)."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    log_level: str = "INFO"

    model_config = {"env_prefix": "LLMTRACK_"}
