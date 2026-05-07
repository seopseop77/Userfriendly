"""`claude-manage`: launch `claude` under the local llm-tracker proxy.

Behaviour:
  1. Probe whether the configured proxy port already accepts TCP. If
     not, spawn `python -m llm_tracker start ...` as a detached daemon
     (own session, stdin /dev/null, stdout+stderr appended to
     `var/proxy.log`, PID written to `var/proxy.pid`).
  2. Acquire a shared lock on `var/proxy.lock` — used as a refcount
     across concurrent `claude-manage` processes.
  3. Spawn `claude <argv>` as a foreground child with
     `ANTHROPIC_BASE_URL` pointed at the proxy. The wrapper ignores
     SIGINT/SIGQUIT so Ctrl-C goes to claude; SIGTERM/SIGHUP to the
     wrapper are forwarded to claude.
  4. Wait for claude to exit.
  5. Try to upgrade the shared lock to exclusive (non-blocking). If
     successful, no other `claude-manage` is alive — terminate the
     proxy (SIGTERM, then SIGKILL after a grace period). Manually
     started proxies are spared because only `claude-manage` writes
     `var/proxy.pid`; missing pid file means "not ours".

Configuration via `LLMTRACK_PROXY_HOST` / `LLMTRACK_PROXY_PORT` /
`LLMTRACK_MODE` (same env vars as `llm-tracker start`). The wrapper
itself takes no flags — every argv after `claude-manage` goes to
`claude`.

Known limits:
  * SIGKILL to the wrapper bypasses cleanup; claude (now reparented)
    and the detached proxy keep running.
  * PID reuse on a stale `var/proxy.pid` could in theory target an
    unrelated process. Acceptable for a local dev sidecar.
  * `fcntl.flock` is used for the refcount, so this is macOS/Linux
    only. Windows support would need a separate locking primitive.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import IO

PROXY_HOST_DEFAULT = "127.0.0.1"
PROXY_PORT_DEFAULT = 8787
PROXY_MODE_DEFAULT = "L"
PROXY_STARTUP_TIMEOUT = 10.0
PROXY_SHUTDOWN_TIMEOUT = 5.0
PROXY_PROBE_INTERVAL = 0.1
PROXY_PROBE_TIMEOUT = 0.2


def _proxy_alive(host: str, port: int, timeout: float = PROXY_PROBE_TIMEOUT) -> bool:
    """Return True if a TCP connection to host:port succeeds within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_for_proxy(host: str, port: int, timeout: float) -> bool:
    """Poll until the proxy port accepts connections or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _proxy_alive(host, port):
            return True
        time.sleep(PROXY_PROBE_INTERVAL)
    return False


def _spawn_proxy_daemon(
    host: str,
    port: int,
    mode: str,
    var_dir: Path,
) -> subprocess.Popen[bytes]:
    """Spawn `python -m llm_tracker start ...` as a detached daemon.

    The daemon is started in its own session via `start_new_session=True`
    so terminal SIGINT/SIGQUIT don't reach it (in-flight requests are
    protected). The wrapper terminates it explicitly during cleanup.
    """
    var_dir.mkdir(exist_ok=True)
    log_path = var_dir / "proxy.log"
    pid_path = var_dir / "proxy.pid"

    with open(log_path, "ab") as log_fh:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "llm_tracker",
                "start",
                "--host",
                host,
                "--port",
                str(port),
                "--mode",
                mode,
            ],
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=log_fh,
            start_new_session=True,
            close_fds=True,
        )
    pid_path.write_text(f"{proc.pid}\n")
    return proc


def _build_child_env(host: str, port: int, parent_env: dict[str, str]) -> dict[str, str]:
    """Return a copy of parent_env with ANTHROPIC_BASE_URL pointed at the proxy.

    Other env vars (including ANTHROPIC_API_KEY) pass through untouched —
    the proxy forwards them verbatim to upstream.
    """
    env = dict(parent_env)
    env["ANTHROPIC_BASE_URL"] = f"http://{host}:{port}"
    return env


def _acquire_shared_lock(var_dir: Path) -> IO[bytes]:
    """Acquire a shared (read) lock on `var/proxy.lock`.

    Multiple `claude-manage` processes hold this concurrently; the
    process that successfully upgrades to exclusive on exit knows it's
    the last one out and is responsible for terminating the proxy.
    """
    var_dir.mkdir(exist_ok=True)
    lock_path = var_dir / "proxy.lock"
    fh = open(lock_path, "ab+")  # noqa: SIM115 — handle must outlive this function
    try:
        fcntl.flock(fh, fcntl.LOCK_SH)
    except OSError:
        fh.close()
        raise
    return fh


def _try_become_last_user(lock_fh: IO[bytes]) -> bool:
    """Attempt to upgrade the shared lock to exclusive without blocking.

    Returns True iff no other `claude-manage` process holds a shared
    lock on the same file.
    """
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def _release_lock(lock_fh: IO[bytes]) -> None:
    with contextlib.suppress(OSError):
        fcntl.flock(lock_fh, fcntl.LOCK_UN)
    with contextlib.suppress(OSError):
        lock_fh.close()


def _terminate_proxy(var_dir: Path, timeout: float = PROXY_SHUTDOWN_TIMEOUT) -> None:
    """SIGTERM the PID in `var/proxy.pid`, escalating to SIGKILL if needed.

    No-op if the pid file is missing — that signals the proxy was
    started outside `claude-manage` (e.g. a manual `llm-tracker start`)
    and is therefore not ours to kill.
    """
    pid_path = var_dir / "proxy.pid"
    if not pid_path.is_file():
        return
    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError):
        pid_path.unlink(missing_ok=True)
        return

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pid_path.unlink(missing_ok=True)
        return
    except PermissionError:
        return

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pid_path.unlink(missing_ok=True)
            return
        time.sleep(0.05)

    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)
    pid_path.unlink(missing_ok=True)


def _reset_signals_in_child() -> None:
    """preexec_fn: restore default signal disposition in the spawned child."""
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGQUIT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGHUP, signal.SIG_DFL)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the `claude-manage` console script.

    Returns claude's exit code on normal completion, or:
      * 1   — proxy did not become reachable in time
      * 127 — `claude` binary not found on PATH
    """
    if argv is None:
        argv = sys.argv[1:]

    host = os.environ.get("LLMTRACK_PROXY_HOST", PROXY_HOST_DEFAULT)
    port = int(os.environ.get("LLMTRACK_PROXY_PORT", str(PROXY_PORT_DEFAULT)))
    mode = os.environ.get("LLMTRACK_MODE", PROXY_MODE_DEFAULT)
    var_dir = Path("var")

    if not _proxy_alive(host, port):
        _spawn_proxy_daemon(host, port, mode, var_dir)
        if not _wait_for_proxy(host, port, PROXY_STARTUP_TIMEOUT):
            print(
                f"claude-manage: proxy did not become reachable on "
                f"{host}:{port} within {PROXY_STARTUP_TIMEOUT:.0f}s. "
                f"Check {var_dir / 'proxy.log'} for details.",
                file=sys.stderr,
            )
            return 1

    env = _build_child_env(host, port, dict(os.environ))
    lock_fh = _acquire_shared_lock(var_dir)

    old_sigint = signal.signal(signal.SIGINT, signal.SIG_IGN)
    old_sigquit = signal.signal(signal.SIGQUIT, signal.SIG_IGN)
    old_sigterm = signal.getsignal(signal.SIGTERM)
    old_sighup = signal.getsignal(signal.SIGHUP)

    claude_proc: subprocess.Popen[bytes] | None = None

    def _forward(signum: int, _frame: object) -> None:
        if claude_proc is not None and claude_proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                claude_proc.send_signal(signum)

    try:
        try:
            claude_proc = subprocess.Popen(
                ["claude", *argv],
                env=env,
                preexec_fn=_reset_signals_in_child,
            )
        except FileNotFoundError:
            print(
                "claude-manage: `claude` binary not found on PATH. "
                "Install Claude Code first (https://claude.com/claude-code).",
                file=sys.stderr,
            )
            return 127

        signal.signal(signal.SIGTERM, _forward)
        signal.signal(signal.SIGHUP, _forward)

        rc = claude_proc.wait()
    finally:
        signal.signal(signal.SIGINT, old_sigint)
        signal.signal(signal.SIGQUIT, old_sigquit)
        signal.signal(signal.SIGTERM, old_sigterm)
        signal.signal(signal.SIGHUP, old_sighup)
        if _try_become_last_user(lock_fh):
            _terminate_proxy(var_dir)
        _release_lock(lock_fh)

    return rc
