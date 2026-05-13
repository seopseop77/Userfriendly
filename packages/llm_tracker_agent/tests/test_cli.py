"""CLI helpers: port selection for multi-instance coexistence."""

from __future__ import annotations

import socket

from llm_tracker_agent.cli import _pick_port


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_pick_port_returns_preferred_when_free() -> None:
    # Kernel just handed us this port; reopening the same number is
    # almost always still free in the next instant.
    candidate = _free_loopback_port()
    assert _pick_port(candidate) == candidate


def test_pick_port_falls_back_when_preferred_taken() -> None:
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        holder.bind(("127.0.0.1", 0))
        taken = holder.getsockname()[1]
        chosen = _pick_port(taken)
        assert chosen != taken
        assert 1024 <= chosen <= 65535
    finally:
        holder.close()
