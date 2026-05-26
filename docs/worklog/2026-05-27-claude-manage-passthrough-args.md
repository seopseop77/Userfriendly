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

## What's left / known limits

- No live `claude-manage --dangerously-skip-permissions` smoke run in
  this session. The user can sanity-check by invoking it once after the
  worktree is reinstalled (`pip install -e packages/llm_tracker_agent`
  or equivalent).
- `_setup_cli` no_args_is_help: invoking `claude-manage setup` with no
  token now shows Typer's help instead of an exit-2 error. Acceptable
  trade-off; mention if the user prefers strict.

## Handoff

claude-manage flag pass-through is fixed and covered by unit tests; no
follow-up work required for this fix. Next session can return to the
analytics_sink / ADR-0038 tracks tracked in
`docs/worklog/2026-05-26-vocab-and-collapse-refinement.md`.

## Suggestions (untouched)

- None — surgical change.
