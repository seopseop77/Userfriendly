# 2026-05-07 · `claude-manage` wrapper

**Author**: Claude Code
**Session trigger**: User asked whether typing `claude-manage` could
auto-start the proxy in background, set `ANTHROPIC_BASE_URL`, then
launch `claude` transparently — and then explicitly redirected the
proxy lifecycle to be coupled to `claude` exit (with refcount support
for multiple concurrent `claude-manage` sessions).
**Related docs**: `CLAUDE.md` §10 (public interfaces), `docs/design.md`
(Mode L sidecar topology).

## Interpretation

Two design questions emerged during the conversation before any code
landed.

1. *Can the wrapper exist?* — Yes; standard pattern. Implemented as a
   second `[project.scripts]` entry rather than a subcommand of
   `llm-tracker`, because the user's mental model is
   "type `claude-manage` instead of `claude`" — a peer command, not a
   nested one. All argv after the wrapper name is forwarded to
   `claude`; the wrapper itself takes no flags. Configuration is via
   the same `LLMTRACK_*` env vars `llm-tracker start` already honours.
2. *Should the proxy outlive `claude`?* — Initial draft used
   `os.execvpe` (proxy detached, survives wrapper exit), but the user
   pushed back: lifecycle should be coupled. The resulting design
   keeps the wrapper alive across `claude`, uses an `fcntl.flock`
   shared lock on `var/proxy.lock` as a refcount, and only terminates
   the proxy when the *last* `claude-manage` exits. Manually started
   proxies (no `var/proxy.pid`) are spared.

This is a CLI surface addition, not a change to existing flags, so it
does not require an ADR per CLAUDE.md §10 — the existing
`llm-tracker ...` contract is untouched.

## What was done

### Checkpoint 1 — wrapper landed (commit d2e33d5)

- Created `packages/llm_tracker/src/llm_tracker/cli/manage.py` —
  the `claude-manage` entry point. Helpers: `_proxy_alive` (TCP probe),
  `_wait_for_proxy` (polling), `_spawn_proxy_daemon` (Popen with
  `start_new_session=True`, stdin /dev/null, stdout+stderr to
  `var/proxy.log`, PID to `var/proxy.pid`), `_build_child_env`,
  `_acquire_shared_lock` / `_try_become_last_user` / `_release_lock`
  (`fcntl.flock` refcount on `var/proxy.lock`), `_terminate_proxy`
  (SIGTERM → poll → SIGKILL escalation; no-op when pid file absent),
  `_reset_signals_in_child` (preexec_fn restoring SIG_DFL), and
  `main()` orchestrating the whole flow. (commit d2e33d5)
- Created `packages/llm_tracker/src/llm_tracker/__main__.py` — a
  one-liner re-export so `python -m llm_tracker ...` invokes the
  Typer CLI. Used by `_spawn_proxy_daemon` to launch the proxy in a
  way that's robust regardless of whether the `llm-tracker` console
  script is on PATH inside the user's environment. (commit d2e33d5)
- Modified `packages/llm_tracker/pyproject.toml` — added
  `claude-manage = "llm_tracker.cli.manage:main"` under
  `[project.scripts]`. After `uv sync`, both `llm-tracker` and
  `claude-manage` console scripts are present. (commit d2e33d5)
- Created `packages/llm_tracker/tests/test_cli_manage.py` — 22
  unit tests covering: TCP probe, env construction, daemon spawn flag
  shape (mocked Popen), shared-lock refcount semantics (real
  subprocess holder for the multi-process case), `_terminate_proxy`
  (no-op / invalid pid / dead pid / SIGTERM-then-poll / SIGKILL
  escalation), and `main()` happy + error paths (proxy already alive,
  proxy fails to start → return 1, claude not on PATH → return 127,
  last-user terminates / non-last-user does not, env var overrides).
  (commit d2e33d5)

### Checkpoint 2 — async cleanup so `/exit` is instant (commit 9aa8321)

User pointed out that `/exit` under `claude-manage` felt slower than
plain `claude`. Diagnosis: the wrapper's finally block was blocking
the user's shell prompt on uvicorn's graceful shutdown
(~100–400 ms typical, plus 50 ms polling granularity, capped at 5 s
before SIGKILL). Fixed by moving the kill loop off the user-facing
critical path:

- Added `_spawn_async_cleanup(var_dir)` to `manage.py`. `os.fork()`
  forks a detached cleanup child that calls `os.setsid()`, resets
  signal handlers to SIG_DFL, redirects stdio to `/dev/null`, and
  runs `_terminate_proxy(...)` (unchanged: SIGTERM → 50 ms poll →
  SIGKILL after 5 s). The parent returns immediately.
- Modified `main()` finally block. When `_try_become_last_user`
  returns True we now call `_spawn_async_cleanup` and deliberately
  *do not* call `_release_lock`. flock semantics keep the lock held
  on the open file description as long as any duplicate fd
  (parent's or child's) refers to it; we want the lock to outlive
  the parent so concurrent `claude-manage` invocations still block
  on `LOCK_SH` until the cleanup child finishes (preserving the
  "no traffic to a shutting-down proxy" invariant). The lock is
  released when the child's `os._exit(0)` closes its fd.
- Updated `tests/test_cli_manage.py`. Renamed the two main-flow
  tests to expect `_spawn_async_cleanup` instead of
  `_terminate_proxy` directly. Added
  `test_spawn_async_cleanup_returns_immediately_and_kills_proxy_in_child`
  — a real-fork integration test that spawns a stub long-sleep
  process, calls `_spawn_async_cleanup`, asserts the parent
  returns in under 500 ms, then waits up to 10 s for the detached
  child to actually kill the stub and unlink the pid file.
- Refreshed the module docstring's step 5 to describe the fork-based
  cleanup, the lock-fd inheritance trick, and the manual-proxy
  carve-out.

## Decisions

- **Async cleanup via `os.fork()` rather than `subprocess`.** A
  forked child inherits the parent's open file descriptions verbatim,
  including the flock lock — that's the whole point. A subprocess
  would need fd-passing gymnastics to inherit the lock. Caveat: fork
  in a multi-threaded process is deprecated in Python 3.12; pytest's
  asyncio plugin makes the test environment multi-threaded so the
  `_spawn_async_cleanup` test triggers a `DeprecationWarning`. The
  real `claude-manage` runtime is single-threaded at the fork point
  (just Popen + wait + fork), so the warning is a test-environment
  artefact and benign.
- **Refcount via `fcntl.flock` shared lock** rather than a marker
  directory or per-process tag files. Reason: kernel-managed locks
  release automatically on process death (including SIGKILL), so the
  refcount can never go stale. Cost: macOS/Linux-only; Windows would
  need a separate primitive — acceptable for a Mode-L dev sidecar.
- **`var/proxy.pid` is the "claude-manage spawned this proxy" marker.**
  When the last claude-manage exits, it terminates the proxy *only* if
  the pid file exists. A manually started `llm-tracker start ...`
  doesn't write the file, so it's never killed by claude-manage. This
  reuses an artefact we wanted anyway (for a future
  `llm-tracker stop`) instead of inventing a separate flag.
- **Wrapper ignores SIGINT/SIGQUIT, forwards SIGTERM/SIGHUP.** Ctrl-C
  goes straight to `claude` (which is the foreground TUI); the wrapper
  must outlive `claude` to run cleanup. `preexec_fn` restores SIG_DFL
  in the spawned child so claude itself isn't accidentally
  inherited-into-ignored-state.
- **Proxy daemon uses `start_new_session=True`.** Detaches it from the
  terminal's process group so terminal-delivered signals don't kill it
  mid-request. The wrapper terminates it explicitly during cleanup.
- **No new HTTP healthz endpoint on the proxy.** Health check is a
  TCP-connect probe. Adding `/.well-known/...` to the proxy would
  expand the public HTTP surface (CLAUDE.md §10) — defer until a
  future need justifies it.
- **CWD is whatever the user invoked `claude-manage` from**, matching
  `llm-tracker start`. So `var/` lands beside the user's project. The
  wider question of "where should llm-tracker state live by default"
  is deliberately out of scope for this checkpoint.

## Verification

Full suite (existing 150 + new 23) green after checkpoint 2:

```
$ .venv/bin/python3.12 -m pytest -q
........................................................................ [ 41%]
........................................................................ [ 83%]
.............................                                            [100%]
173 passed, 4 warnings in 1.18s
```

The 4 warnings are all the same `DeprecationWarning` about
multi-threaded fork (pytest test-env artefact, see Decisions).

Targeted run for the wrapper's tests after checkpoint 2:

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker/tests/test_cli_manage.py -v
... 23 passed in 0.67s
```

Lint clean on every file added/modified by this checkpoint:

```
$ .venv/bin/ruff check \
    packages/llm_tracker/src/llm_tracker/cli/manage.py \
    packages/llm_tracker/src/llm_tracker/__main__.py \
    packages/llm_tracker/tests/test_cli_manage.py
All checks passed!
```

Console script registration after `uv sync`:

```
$ ls .venv/bin/claude-manage .venv/bin/llm-tracker
.venv/bin/claude-manage
.venv/bin/llm-tracker

$ .venv/bin/python3.12 -m llm_tracker --help
... shows: init, start, audit, generate-key, sign-plugin
```

`cli/main.py` has a pre-existing `I001` import-sort warning that
predates this change (worklog 2026-05-06 only ran ruff on the
`packages/llm_tracker_plugin_*` directories). Not touched per
CLAUDE.md §2.3.

## What's left / known limits

- **Manual real-traffic e2e is still pending.** The unit tests mock
  `subprocess.Popen`, so they prove the wire-up and bookkeeping but
  not that a real `claude` session round-trips through a real proxy.
  A clean smoke test would be: in a fresh tmp dir, run
  `.venv/bin/llm-tracker init`, then `.venv/bin/claude-manage --print
  hello`, observe `var/proxy.log` and the `var/llm_tracker.db`
  audit/exchange rows, then verify the proxy terminates after
  claude exits.
- **No `llm-tracker stop` command yet.** `var/proxy.pid` is written
  for the future command, but if claude-manage's cleanup is bypassed
  (e.g. wrapper killed `-9`), there's no first-class way to stop a
  stuck proxy other than `kill $(cat var/proxy.pid)`.
- **Stale-pid race.** If `var/proxy.pid` outlives the process and the
  PID is reused by an unrelated process before next launch,
  `_terminate_proxy` could SIGTERM the wrong PID. Mitigations are all
  fragile cross-platform; documented and accepted.
- **Windows.** `fcntl.flock` is POSIX-only. A `msvcrt.locking`-based
  fallback (or skipping the refcount and degrading to "always orphan")
  would be needed for Windows support — out of scope.

## Handoff

`claude-manage` is wired up, lint-clean, and unit-tested. STATUS now
points the next session at this worklog and offers two parallel paths:

1. **Manual real-traffic e2e** for `claude-manage` (in addition to the
   pre-existing manual e2e for the bare proxy + test plugins) — this
   is the one outstanding verification on the wrapper itself.
2. **Open Phase 1c — `scope_guard` plugin.** Same starting point as
   before this side-quest; the wrapper doesn't change Phase 1c's
   shape.

When Phase 1c lands and ships an actual `llm-tracker stop` command,
revisit the "no auto-stop on `kill -9`" gap — that's the natural
place to also harden against stale pid files (e.g. validate the pid
points at a real `llm_tracker` process before signalling).

## Suggestions (untouched)

- The CWD-relative `var/` story is wobbly: each working directory the
  user runs `claude-manage` from gets its own `var/`. Likely worth
  switching to an XDG-style `~/.llm-tracker/` (or `LLMTRACK_HOME`)
  default in a future ADR, with current-dir fallback for project-local
  workflows. Not done here because it changes the data location for
  every existing CLI command, not just the wrapper.
- A `claude-manage status` / `claude-manage logs` subcommand pair
  would be cheap given the current `var/proxy.{pid,log,lock}` layout.
  Defer until the wrapper has actual users asking for it.
