"""Config roundtrip + missing-file behaviour."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from llm_tracker_agent.config import Config, load_config, save_config


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    save_config(
        url="https://central.test",
        token="lts_test_token",
        local_port=12345,
        path=cfg_path,
    )
    loaded = load_config(cfg_path)
    assert loaded == Config(
        server_url="https://central.test",
        token="lts_test_token",
        local_port=12345,
    )


def test_save_sets_owner_only_perms(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    save_config(
        url="https://central.test",
        token="lts_secret",
        local_port=18080,
        path=cfg_path,
    )
    mode = stat.S_IMODE(cfg_path.stat().st_mode)
    assert mode == 0o600


def test_load_missing_raises(tmp_path: Path) -> None:
    missing = tmp_path / "nope.toml"
    with pytest.raises(SystemExit):
        load_config(missing)


def test_load_malformed_raises(tmp_path: Path) -> None:
    bad = tmp_path / "config.toml"
    bad.write_text("this is not toml = = =\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        load_config(bad)
