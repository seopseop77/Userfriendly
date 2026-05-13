"""Read/write the agent config at ``~/.llm-tracker/config.toml``."""

from __future__ import annotations

import os
import stat
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomli_w

CONFIG_DIR = Path.home() / ".llm-tracker"
CONFIG_PATH = CONFIG_DIR / "config.toml"


@dataclass(frozen=True)
class Config:
    server_url: str
    token: str
    local_port: int


def load_config(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        sys.exit(
            f"llm-tracker config not found at {path}. Run `claude-manage setup <token>` first."
        )
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
        server = data["server"]
        return Config(
            server_url=str(server["url"]),
            token=str(server["token"]),
            local_port=int(server["local_port"]),
        )
    except (KeyError, ValueError, tomllib.TOMLDecodeError) as exc:
        sys.exit(f"llm-tracker config at {path} is malformed: {exc}")


def save_config(
    url: str,
    token: str,
    local_port: int,
    *,
    path: Path = CONFIG_PATH,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"server": {"url": url, "token": token, "local_port": local_port}}
    with path.open("wb") as f:
        tomli_w.dump(payload, f)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
