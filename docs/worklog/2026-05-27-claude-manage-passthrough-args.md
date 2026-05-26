# 2026-05-27 · claude-manage passthrough for `claude` flags

**Author**: Claude Code
**Session trigger**: "야 claude-manage 실행할 때 claude --dangerously-skip permissions 같이 인자 전달해서 쓰는 거 똑같이 쓸 수 있게 할 수 있어?"
**Related docs**: `packages/llm_tracker_agent/src/llm_tracker_agent/cli.py`

## Interpretation

User wants `claude-manage --dangerously-skip-permissions ...` (and any
other `claude` flag) to behave exactly like `claude --dangerously-skip-permissions ...`:
flags must be forwarded to the spawned `claude` subprocess transparently.

The `_run` path was already designed to forward `extra_args` through
`subprocess.run(["claude", *extra_args], ...)`, but a runtime probe
confirmed it failed at the Typer / Click layer: with `setup` registered
as a subcommand, Click's group parser tried to resolve the first
`--`-prefixed token as a subcommand name and exited with
`UsageError: No such command '--dangerously-skip-permissions'`,
even though `context_settings` had `allow_extra_args=True` +
`ignore_unknown_options=True`. So this was a CLI dispatch bug, not a
new-feature request.

## What was done

- Modified `packages/llm_tracker_agent/src/llm_tracker_agent/cli.py` —
  collapsed the Typer group into a single-purpose `_setup_cli`
  (handles `setup` only) and replaced the entry point with a plain
  `app()` function that inspects `sys.argv` itself: `setup` → Typer;
  anything else (including no args) → `_run(argv)` directly. Catches
  `click.exceptions.Exit` raised by `_run` / `_wait_ready` and
  re-raises as `SystemExit` so exit codes still propagate. (commit `ded0215`)
- Modified `packages/llm_tracker_agent/tests/test_cli.py` — added four
  regression tests: pass-through of `--`-prefixed flags, empty argv,
  `setup` dispatch (verifying the literal `setup` token is stripped
  before Typer sees argv), and `click.exceptions.Exit` → `SystemExit`
  translation. (commit `ded0215`)

`project.scripts` entry stays `llm_tracker_agent.cli:app` — `app` is now
a function rather than a Typer instance, both are callable so the
generated entry script doesn't need to change.

## Decisions

- **Argv preprocessing instead of `--` separator or new entrypoint.**
  Three options were on the table:
  1. argv-preprocessing dispatch in `app()` (chosen);
  2. document `claude-manage -- --dangerously-skip-permissions`;
  3. split `setup` into a separate `claude-manage-setup` entry point.
  (1) preserves the user's mental model ("same as `claude`") with a
  one-file change; (2) breaks the "exactly like claude" expectation;
  (3) is a public-interface change (CLAUDE.md §9) and would need an ADR.
- **Catch `click.exceptions.Exit` in `app()`.** `_run` and `_wait_ready`
  still raise `typer.Exit(code=...)` (which subclasses
  `click.exceptions.Exit`). Inside a Typer-managed call this gets
  translated to `sys.exit`; once we call `_run` outside Typer, nothing
  catches it. Translating in the wrapper keeps `_run` untouched and
  preserves the existing exit-code contract.
- **Strip `setup` from `sys.argv` before invoking `_setup_cli`.** With
  only one command registered, Typer auto-promotes `_setup_cli` to a
  no-name CLI, so the literal `setup` token would otherwise be parsed
  as the first positional argument (the org token). Slicing keeps the
  user-facing UX (`claude-manage setup lts_…`) while letting Typer parse
  cleanly internally.

## Verification

```
$ .venv/bin/python3 -m pytest packages/llm_tracker_agent/tests/ -q
..............                                                           [100%]
14 passed in 0.13s

$ .venv/bin/python3 -m ruff check packages/llm_tracker_agent/
All checks passed!
```

Pre-fix runtime probe (reproduces the original failure):

```
$ .venv/bin/python3 -c "from typer.testing import CliRunner; ..."
# Before:
#   UsageError: No such command '--dangerously-skip-permissions'.
#   exit_code: 2
# After (this commit):
#   captured: {'argv': ['--dangerously-skip-permissions', '-p', 'hi']}
```

End-to-end run against a real `claude` install was *not* exercised in
this session — the unit tests stub `_run`. The forwarding contract
itself (`subprocess.run(["claude", *extra_args], ...)`) was unchanged,
so the test coverage targets the new dispatch boundary specifically.

## Release: v0.1.2

`claude-manage` is distributed as a GitHub-Releases wheel
(ADR-0034/ADR-0035), so the fix only reaches participants once a new
tagged release is published. Bumped together in one release commit
mirroring the v0.1.1 pattern (commit `4ad1d04`):

- `packages/llm_tracker_agent/pyproject.toml`: `0.1.1` → `0.1.2`.
- `packages/llm_tracker_signup/.../templates/success.html`:
  install-step wheel URL bumped to `agent/v0.1.2/llm_tracker_agent-0.1.2-...`.
- `packages/llm_tracker_signup/tests/test_app.py`: locked-in URL
  assertion bumped in lockstep so a regression to the old URL fails
  fast.
- `docs/deploy.md`: example wheel URL bumped.

`release-agent.yml` is tag-driven and builds whatever `pyproject` says,
so no workflow change.

Local tag `agent/v0.1.2` (annotated) created on the release commit.

`agent/v0.1.1` was confirmed already on the remote (release ran
2026-05-26 17:30 KST → wheel + tarball attached), so STATUS.md's
"Other pending push — agent/v0.1.1" was stale; that section is
rewritten to reference v0.1.2 instead.

```
$ .venv/bin/python3 -m pytest \
    packages/llm_tracker_signup/tests/ packages/llm_tracker_agent/tests/ -q
...sss...ss..............                                                [100%]
20 passed, 5 skipped in 0.45s

$ .venv/bin/python3 -m ruff check \
    packages/llm_tracker_agent/ packages/llm_tracker_signup/
All checks passed!
```

## Hotfix: v0.1.3 (typer.Exit catch)

Live smoke of v0.1.2 (operator reinstalled the wheel and ran
`claude-manage --dangerously-skip-permissions`) confirmed flag
pass-through itself worked — Claude Code entered normally — but after
Claude exited cleanly, `claude-manage` printed a traceback ending in

```
File ".../llm_tracker_agent/cli.py", line 127, in _run
    raise typer.Exit(code=completed.returncode)
typer._click.exceptions.Exit
```

and propagated exit code 1 instead of Claude's actual return code.

**Root cause.** `app()` caught `click.exceptions.Exit`, but `typer.Exit`
inherits from typer's *vendored* click fork
(`typer._click.exceptions.Exit`), not upstream `click.exceptions.Exit`.
Two distinct class hierarchies. The except clause silently failed to
match, the exception escaped, Python printed the trace, and Python's
default `SystemExit` from an uncaught exception is code 1.

The original v0.1.2 unit test `test_app_translates_run_exit_to_systemexit`
passed because it stubbed `_run` to raise `click.exceptions.Exit`
directly — same name, wrong class for production. False confidence.

**Fix** (commit `53715ad`):

- `packages/llm_tracker_agent/src/llm_tracker_agent/cli.py`: drop the
  `import click`; catch `typer.Exit` directly. Most semantically
  correct since that's the type `_run` / `_wait_ready` actually raise.
- `packages/llm_tracker_agent/tests/test_cli.py`:
  - `test_app_translates_run_exit_to_systemexit` now raises the real
    `typer.Exit` instead of `click.exceptions.Exit`.
  - New `test_app_translates_real_run_subprocess_returncode` drives
    the real `_run` with `subprocess.run` + `uvicorn.Server` /
    `uvicorn.Config` / `_wait_ready` / `load_config` /
    `_pick_port` / `make_proxy_app` stubbed, asserts the subprocess
    returncode (42) propagates to `SystemExit(42)` AND that the
    forwarded subprocess argv is `["claude", "--dangerously-skip-permissions"]`.
    This is the test the v0.1.2 ship lacked.

**Release v0.1.3** (commit `496e517`):

- `packages/llm_tracker_agent/pyproject.toml`: `0.1.2` → `0.1.3`.
- `packages/llm_tracker_signup/.../templates/success.html`,
  `packages/llm_tracker_signup/tests/test_app.py`,
  `docs/deploy.md`: wheel URLs bumped to v0.1.3 in lockstep.

Local annotated tag `agent/v0.1.3` created on the release commit.

```
$ .venv/bin/python3 -m pytest \
    packages/llm_tracker_agent/tests/ packages/llm_tracker_signup/tests/ -q
..................sss...ss                                               [100%]
21 passed, 5 skipped in 0.39s

$ .venv/bin/python3 -m ruff check packages/llm_tracker_agent/
All checks passed!
```

`v0.1.2` is left published as-is (broken on exit). After v0.1.3 ships
the v0.1.2 wheel is effectively superseded; no recall needed since no
operator besides this dev box ever installed it.

## What's left / known limits

- **Operator must push** — `git push origin main && git push origin agent/v0.1.3`.
  The release workflow only fires on tag push.
- After reinstall, exercise the same smoke that surfaced the bug:
  `claude-manage --dangerously-skip-permissions` → `/quit` → confirm
  no traceback and exit code 0.
- `_setup_cli` no_args_is_help: invoking `claude-manage setup` with no
  token now shows Typer's help instead of an exit-2 error. Acceptable
  trade-off; mention if the user prefers strict.

## Handoff

Code + tests + release commit + local tag are ready. Single next step:

```
git push origin main
git push origin agent/v0.1.3
# wait for release-agent.yml to attach the wheel, then on operator machines:
uv tool install --reinstall \
  https://github.com/seopseop77/Userfriendly/releases/download/agent/v0.1.3/llm_tracker_agent-0.1.3-py3-none-any.whl
# restart Claude Code, run the traceback smoke check above
```

After that, the analytics_sink / ADR-0038 deploy track in
`docs/worklog/2026-05-26-vocab-and-collapse-refinement.md` is the
remaining work.

## Suggestions (untouched)

- None — surgical change.
