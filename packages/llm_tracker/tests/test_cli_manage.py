"""Tests for the `claude-manage` wrapper.

Coverage:
  * TCP probe (`_proxy_alive`, `_wait_for_proxy`)
  * Daemon spawn argument shape (`_spawn_proxy_daemon`)
  * Child env construction (`_build_child_env`)
  * Shared-lock refcount behaviour (`_acquire_shared_lock`,
    `_try_become_last_user`, `_release_lock`)
  * Proxy termination via pid file (`_terminate_proxy`)
  * Top-level `main()` happy / error paths

Real `claude` exec is never attempted; tests mock `subprocess.Popen`
so claude-manage's wait/cleanup logic is exercised in isolation.
"""

from __future__ import annotations

import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from llm_tracker.cli.manage import (
    _acquire_shared_lock,
    _build_child_env,
    _proxy_alive,
    _release_lock,
    _spawn_proxy_daemon,
    _terminate_proxy,
    _try_become_last_user,
    _wait_for_proxy,
    main,
)

# ---------------------------------------------------------------------------
# TCP probe
# ---------------------------------------------------------------------------


def test_proxy_alive_returns_false_when_nothing_listening() -> None:
    assert _proxy_alive("127.0.0.1", 1, timeout=0.05) is False


def test_proxy_alive_returns_true_when_port_open() -> None:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    _, port = sock.getsockname()
    try:
        assert _proxy_alive("127.0.0.1", port, timeout=0.5) is True
    finally:
        sock.close()


def test_wait_for_proxy_times_out_when_unreachable() -> None:
    start = time.monotonic()
    result = _wait_for_proxy("127.0.0.1", 1, timeout=0.3)
    elapsed = time.monotonic() - start
    assert result is False
    assert 0.25 <= elapsed <= 1.5


def test_wait_for_proxy_returns_true_when_already_open() -> None:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    _, port = sock.getsockname()
    try:
        assert _wait_for_proxy("127.0.0.1", port, timeout=1.0) is True
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# Child env
# ---------------------------------------------------------------------------


def test_build_child_env_sets_base_url() -> None:
    env = _build_child_env("127.0.0.1", 8787, {"PATH": "/usr/bin"})
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8787"
    assert env["PATH"] == "/usr/bin"


def test_build_child_env_overrides_existing_base_url() -> None:
    env = _build_child_env(
        "127.0.0.1",
        9999,
        {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"},
    )
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9999"


def test_build_child_env_does_not_mutate_input() -> None:
    parent = {"PATH": "/usr/bin"}
    _build_child_env("127.0.0.1", 8787, parent)
    assert "ANTHROPIC_BASE_URL" not in parent


# ---------------------------------------------------------------------------
# Daemon spawn
# ---------------------------------------------------------------------------


def test_spawn_proxy_daemon_uses_detached_flags(tmp_path: Path) -> None:
    with patch("llm_tracker.cli.manage.subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        result = _spawn_proxy_daemon("127.0.0.1", 8787, "L", tmp_path)

        assert result is mock_proc
        call = mock_popen.call_args
        cmd = call.args[0]
        assert cmd[:4] == [sys.executable, "-m", "llm_tracker", "start"]
        assert "--host" in cmd and "127.0.0.1" in cmd
        assert "--port" in cmd and "8787" in cmd
        assert "--mode" in cmd and "L" in cmd
        assert call.kwargs["start_new_session"] is True
        assert call.kwargs["stdin"] == subprocess.DEVNULL
        assert call.kwargs["close_fds"] is True
        assert (tmp_path / "proxy.pid").read_text().strip() == "12345"
        assert (tmp_path / "proxy.log").exists()


# ---------------------------------------------------------------------------
# Shared-lock refcount
# ---------------------------------------------------------------------------


def test_acquire_shared_lock_creates_lockfile(tmp_path: Path) -> None:
    fh = _acquire_shared_lock(tmp_path)
    try:
        assert (tmp_path / "proxy.lock").is_file()
    finally:
        _release_lock(fh)


def test_try_become_last_user_returns_true_when_alone(tmp_path: Path) -> None:
    fh = _acquire_shared_lock(tmp_path)
    try:
        assert _try_become_last_user(fh) is True
    finally:
        _release_lock(fh)


def test_try_become_last_user_returns_false_when_others_hold_shared(
    tmp_path: Path,
) -> None:
    """A sibling process holding the shared lock must block our exclusive upgrade."""
    lock_path = tmp_path / "proxy.lock"
    holder_script = (
        "import fcntl, sys, time;"
        f"fh=open(r'{lock_path}','ab+');"
        "fcntl.flock(fh, fcntl.LOCK_SH);"
        "sys.stdout.write('ready\\n'); sys.stdout.flush();"
        "time.sleep(10)"
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_script],
        stdout=subprocess.PIPE,
    )
    try:
        assert holder.stdout is not None
        line = holder.stdout.readline()
        assert line.strip() == b"ready"

        my_fh = _acquire_shared_lock(tmp_path)
        try:
            assert _try_become_last_user(my_fh) is False
        finally:
            _release_lock(my_fh)
    finally:
        holder.kill()
        holder.wait(timeout=5)


# ---------------------------------------------------------------------------
# Proxy termination
# ---------------------------------------------------------------------------


def test_terminate_proxy_no_op_when_pid_file_missing(tmp_path: Path) -> None:
    # Should not raise, should not call os.kill.
    with patch("llm_tracker.cli.manage.os.kill") as mock_kill:
        _terminate_proxy(tmp_path)
        mock_kill.assert_not_called()


def test_terminate_proxy_no_op_when_pid_file_invalid(tmp_path: Path) -> None:
    (tmp_path / "proxy.pid").write_text("not-a-number")
    with patch("llm_tracker.cli.manage.os.kill") as mock_kill:
        _terminate_proxy(tmp_path)
        mock_kill.assert_not_called()
    assert not (tmp_path / "proxy.pid").exists()


def test_terminate_proxy_handles_already_dead_process(tmp_path: Path) -> None:
    (tmp_path / "proxy.pid").write_text("99999\n")
    with patch("llm_tracker.cli.manage.os.kill") as mock_kill:
        mock_kill.side_effect = ProcessLookupError()
        _terminate_proxy(tmp_path)
        mock_kill.assert_called_once()
    assert not (tmp_path / "proxy.pid").exists()


def test_terminate_proxy_sigterms_then_polls_for_exit(tmp_path: Path) -> None:
    (tmp_path / "proxy.pid").write_text("12345\n")
    call_log: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        call_log.append((pid, sig))
        # Second poll (sig=0) reports dead.
        if sig == 0 and len(call_log) >= 2:
            raise ProcessLookupError()

    with patch("llm_tracker.cli.manage.os.kill", side_effect=fake_kill):
        _terminate_proxy(tmp_path, timeout=1.0)

    assert call_log[0] == (12345, signal.SIGTERM)
    assert call_log[1] == (12345, 0)
    assert not (tmp_path / "proxy.pid").exists()


def test_terminate_proxy_escalates_to_sigkill_after_timeout(tmp_path: Path) -> None:
    (tmp_path / "proxy.pid").write_text("12345\n")
    sigs_seen: list[int] = []

    def fake_kill(pid: int, sig: int) -> None:
        sigs_seen.append(sig)
        # Process never dies during polling: keep returning success on sig=0.
        if sig == signal.SIGKILL:
            raise ProcessLookupError()

    with patch("llm_tracker.cli.manage.os.kill", side_effect=fake_kill):
        _terminate_proxy(tmp_path, timeout=0.2)

    assert sigs_seen[0] == signal.SIGTERM
    assert signal.SIGKILL in sigs_seen
    assert not (tmp_path / "proxy.pid").exists()


# ---------------------------------------------------------------------------
# main() top-level
# ---------------------------------------------------------------------------


@pytest.fixture
def chdir_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_main_skips_spawn_when_proxy_already_alive(
    chdir_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("llm_tracker.cli.manage._proxy_alive", lambda *a, **kw: True)
    spawn_mock = MagicMock()
    monkeypatch.setattr("llm_tracker.cli.manage._spawn_proxy_daemon", spawn_mock)

    fake_proc = MagicMock()
    fake_proc.wait.return_value = 0
    popen_mock = MagicMock(return_value=fake_proc)
    monkeypatch.setattr("llm_tracker.cli.manage.subprocess.Popen", popen_mock)

    rc = main(["--version"])

    assert rc == 0
    spawn_mock.assert_not_called()
    popen_call = popen_mock.call_args
    assert popen_call.args[0] == ["claude", "--version"]
    env = popen_call.kwargs["env"]
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8787"


def test_main_returns_127_when_claude_not_installed(
    chdir_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("llm_tracker.cli.manage._proxy_alive", lambda *a, **kw: True)
    monkeypatch.setattr(
        "llm_tracker.cli.manage.subprocess.Popen",
        MagicMock(side_effect=FileNotFoundError("claude")),
    )

    rc = main(["--version"])
    assert rc == 127


def test_main_returns_1_when_proxy_fails_to_start(
    chdir_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("llm_tracker.cli.manage._proxy_alive", lambda *a, **kw: False)
    monkeypatch.setattr("llm_tracker.cli.manage._spawn_proxy_daemon", MagicMock())
    monkeypatch.setattr("llm_tracker.cli.manage._wait_for_proxy", lambda *a, **kw: False)

    rc = main([])
    assert rc == 1


def test_main_terminates_proxy_when_last_user(
    chdir_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("llm_tracker.cli.manage._proxy_alive", lambda *a, **kw: True)

    fake_proc = MagicMock()
    fake_proc.wait.return_value = 42
    monkeypatch.setattr(
        "llm_tracker.cli.manage.subprocess.Popen",
        MagicMock(return_value=fake_proc),
    )

    terminate_mock = MagicMock()
    monkeypatch.setattr("llm_tracker.cli.manage._terminate_proxy", terminate_mock)

    rc = main([])

    assert rc == 42
    terminate_mock.assert_called_once()


def test_main_does_not_terminate_proxy_when_others_active(
    chdir_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("llm_tracker.cli.manage._proxy_alive", lambda *a, **kw: True)

    fake_proc = MagicMock()
    fake_proc.wait.return_value = 0
    monkeypatch.setattr(
        "llm_tracker.cli.manage.subprocess.Popen",
        MagicMock(return_value=fake_proc),
    )

    monkeypatch.setattr("llm_tracker.cli.manage._try_become_last_user", lambda fh: False)
    terminate_mock = MagicMock()
    monkeypatch.setattr("llm_tracker.cli.manage._terminate_proxy", terminate_mock)

    rc = main([])

    assert rc == 0
    terminate_mock.assert_not_called()


def test_main_uses_env_var_overrides(chdir_tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLMTRACK_PROXY_HOST", "0.0.0.0")
    monkeypatch.setenv("LLMTRACK_PROXY_PORT", "9090")
    monkeypatch.setattr("llm_tracker.cli.manage._proxy_alive", lambda *a, **kw: True)

    fake_proc = MagicMock()
    fake_proc.wait.return_value = 0
    popen_mock = MagicMock(return_value=fake_proc)
    monkeypatch.setattr("llm_tracker.cli.manage.subprocess.Popen", popen_mock)

    rc = main([])

    assert rc == 0
    env = popen_mock.call_args.kwargs["env"]
    assert env["ANTHROPIC_BASE_URL"] == "http://0.0.0.0:9090"
