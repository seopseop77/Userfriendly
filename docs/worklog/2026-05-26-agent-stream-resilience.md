# 2026-05-26 · llm_tracker_agent — swallow mid-stream upstream close

**Author**: Claude Code
**Session trigger**: Operator (verbatim): "그냥 /context 명령어를 치면 계속
같은 에러가 발생해. 이건 해결을 해줘야 할 거 같은데"
**Related docs**: ADR-0024 (fail-closed agent), prior worklog
`2026-05-25-uv-tool-install.md` (ADR-0035, install layout).

## Interpretation

Operator was running Claude Code through the locally-installed
`llm-tracker-agent` (uv tool). Every few requests — reliably around
`/context` and other Claude Code background calls — uvicorn printed
a long traceback ending in:

```
httpcore.RemoteProtocolError: peer closed connection without sending
complete message body (incomplete chunked read)

  File ".../llm_tracker_agent/proxy.py", line 85, in body_iter
    async for chunk in upstream_response.aiter_bytes():
```

`/context` itself is a local Claude Code command and does not call
the LLM, but other background requests (title generation, model
probes, in-flight tool calls being cancelled when the user types a
new slash command) hit the proxy concurrently, and one of those
chunked streams was being closed by the upstream
(`llm-tracker-server` on fly) before the body terminator.

Read of `proxy.py` confirmed: `_UNREACHABLE_ERRORS` (which already
includes `httpx.RemoteProtocolError`, `ReadError`, `TimeoutException`,
`ConnectError`) was caught **only at the initial `send()`**. The
`body_iter()` async generator wrapped `aiter_bytes()` in
`try/finally` with no `except`, so any mid-stream upstream error
propagated to Starlette → ASGI 500 → uvicorn traceback.

## What was done

- Modified
  `packages/llm_tracker_agent/src/llm_tracker_agent/proxy.py` —
  added `except _UNREACHABLE_ERRORS: return` inside `body_iter`'s
  `try` block (before the existing `finally: aclose()`). Status +
  headers have already shipped by the time the generator runs, so
  503 is no longer a valid response; the generator just terminates
  cleanly, the downstream client receives whatever partial bytes
  arrived, and uvicorn no longer prints the traceback. (commit
  afa3d59)
- Extended
  `packages/llm_tracker_agent/tests/test_proxy.py` — added
  `_MidStreamFailStream` (an `httpx.AsyncByteStream` that yields
  one chunk then raises `RemoteProtocolError`) and
  `_MidStreamFailTransport`, plus
  `test_swallows_midstream_upstream_close` asserting the proxy
  returns 200 with `b"partial"` rather than crashing. The custom
  transport (instead of `httpx.MockTransport`) is necessary because
  MockTransport pre-reads the response body, which would surface
  the error at `send()` time rather than during `aiter_bytes()`.
  (commit &lt;pending&gt;)

## Decisions

- **Swallow the mid-stream error rather than re-raise.** Functional
  outcome to the downstream client is identical either way (200
  status, truncated body — the bytes already on the wire stay on
  the wire). Re-raising buys nothing observable and produces a
  spurious uvicorn traceback for what is a normal upstream-close
  condition. The agent's fail-closed posture (ADR-0024) targets
  *unreachability before forwarding starts*, not mid-stream upstream
  drops, so swallowing here does not soften ADR-0024.
- **Reused `_UNREACHABLE_ERRORS` rather than narrowing to
  `RemoteProtocolError`.** All four members (`ConnectError`,
  `TimeoutException`, `ReadError`, `RemoteProtocolError`) can fire
  mid-stream and have the same "stream cut, nothing we can do"
  shape. Using the same tuple keeps the two arms (initial send /
  mid-stream) symmetric.
- **No logging added.** `proxy.py` currently has zero logging
  imports; mixing in `structlog` for one event-class would expand
  scope beyond the bug. Observability can land as a separate
  change if production noise warrants it.

## Verification

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_agent/tests/ -q
.......... 10 passed in 0.34s

$ .venv/bin/python3.12 -m pytest -q
285 passed, 31 skipped in 6.38s

$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_agent/
All checks passed!

$ .venv/bin/python3.12 -m ruff format --check packages/llm_tracker_agent/
7 files already formatted
```

The new test exercises the exact failure mode from the operator's
traceback (`aiter_bytes()` raising `RemoteProtocolError` mid-iter)
end-to-end through `httpx.ASGITransport`, so a regression in the
`body_iter` exception handling would fail the test.

## What's left / known limits

- **The installed uv tool still runs the old wheel.** The traceback
  shows the error originating at
  `/Users/minseop/.local/share/uv/tools/llm-tracker-agent/.../proxy.py`.
  That is a separate copy from the workspace source — `uv tool
  install` builds a wheel and pins it. Source patches do not take
  effect until the operator runs `uv tool install --reinstall
  ./packages/llm_tracker_agent` (or the equivalent from the
  install worklog) and restarts Claude Code so the new agent
  process loads.
- **Root upstream cause untouched.** We made the agent resilient to
  mid-stream closes; we did not investigate *why* `llm-tracker-server`
  on fly is closing chunked streams short. Likely candidates: fly's
  proxy idle/connection limits, the server's plugin pipeline raising
  during streaming, or Anthropic-side cuts being faithfully relayed.
  Worth a separate look once the operator confirms the traceback
  spam stops after the reinstall.
- **STATUS.md's pre-existing "Next single step"** (operator deploys
  updated `llm-tracker-server` plugin code to fly to align with
  ADR-0038's schema) remains pending; this bug fix is a separate
  track and does not unblock it.

## Handoff

Code change is committed and tests green. The fix only takes effect
once the operator:

1. `uv tool install --reinstall ./packages/llm_tracker_agent` (or
   whichever invocation matches the install worklog).
2. Restarts Claude Code so the new agent process loads.

After that, run `/context` (or any other previously-failing call)
and confirm the uvicorn traceback no longer appears. If it still
does, the new traceback's filename will tell us whether the
installed copy was actually refreshed — that is the first
diagnostic.

## Follow-up · Release v0.1.1

**Trigger**: Operator pointed out (verbatim) "uv tool install
https://github.com/.../agent/v0.1.0/llm_tracker_agent-0.1.0-py3-none-any.whl
원래 이걸로 설치해야 하는데, release도 변경해야 하는거 아니야?"

Correct: the install URL is a fixed GitHub Release asset, and the
local agent process is loaded from that wheel — not from the
workspace source. A source patch with the same pyproject version
would either be ignored (uv tool sees the same version, refuses to
reinstall cleanly) or, worse, silently install a 0.1.0 wheel built
from post-fix code, leaving the version string lying. The right
move is semver patch bump and a new tag.

### Decisions

- **Patch bump (0.1.0 → 0.1.1).** Behavior change is a defensive
  resilience fix in `body_iter` exception handling — no public
  interface shift (CLI flags, env vars, hook lifecycle, etc. per
  CLAUDE.md §9 untouched), no API surface change. Operator-
  confirmed patch over minor.
- **Bump the signup-app success-page wheel URL in the same
  commit.** New participants installing via the live success page
  would otherwise receive a now-stale URL pointing at the buggy
  wheel. The signup app still needs a fly redeploy for the
  template change to land in production (separate operator step,
  same redeploy command as the ADR-0035 follow-up worklog).
- **No CI / workflow change.** `.github/workflows/release-agent.yml`
  is tag-driven (`agent/v*`) and version-agnostic; the build step
  (`uv build --out-dir dist`) consumes `pyproject.toml`'s `version`
  field at build time, so the tag + pyproject bump is sufficient.

### What was done

- Modified `packages/llm_tracker_agent/pyproject.toml` —
  `version = "0.1.0"` → `"0.1.1"`. (commit &lt;pending&gt;)
- Modified
  `packages/llm_tracker_signup/src/llm_tracker_signup/templates/success.html` —
  Step 1b's `step-1-code` `<code>` URL bumped to
  `agent/v0.1.1/llm_tracker_agent-0.1.1-py3-none-any.whl`. (commit
  9dee369)
- Modified `packages/llm_tracker_signup/tests/test_app.py` —
  `test_get_success_renders_token`'s wheel-URL assertion bumped in
  lockstep so a regression to the old URL fails fast. (commit
  9dee369)
- Modified `docs/deploy.md` — the example URL under "Participant
  Installation → Install" bumped from `0.1.0` to `0.1.1`. (commit
  9dee369)

### Verification

```
$ .venv/bin/python3.12 -m pytest \
    packages/llm_tracker_agent/tests/ \
    packages/llm_tracker_signup/tests/ -q
16 passed, 5 skipped in 0.83s

$ .venv/bin/python3.12 -m ruff check \
    packages/llm_tracker_agent/ packages/llm_tracker_signup/
All checks passed!
```

The 5 skipped signup tests are the DB-touching ones that need
`LLMTRACK_TEST_DATABASE_URL` — same baseline as the ADR-0035
worklog, not a regression.

### Handoff (release v0.1.1)

A local tag `agent/v0.1.1` will be created on the release commit.
The release workflow only fires on **pushed** tags, so the operator
needs to:

```
git push origin main          # publish the two release commits
git push origin agent/v0.1.1  # publish the tag → triggers
                              # .github/workflows/release-agent.yml
```

The workflow checks out the tagged commit, runs `uv build` from
`packages/llm_tracker_agent`, and attaches
`llm_tracker_agent-0.1.1-py3-none-any.whl` (and the matching
sdist) to the auto-created GitHub Release. The asset URL becomes:

```
https://github.com/seopseop77/Userfriendly/releases/download/agent/v0.1.1/llm_tracker_agent-0.1.1-py3-none-any.whl
```

Then on the operator machine (or any participant machine):

```
uv tool install --reinstall \
  https://github.com/seopseop77/Userfriendly/releases/download/agent/v0.1.1/llm_tracker_agent-0.1.1-py3-none-any.whl
# restart Claude Code so the new agent process loads
```

`--reinstall` is required because uv sees `claude-manage` already
installed; without the flag uv keeps the 0.1.0 wheel even if the
URL is new.

For the signup app, the live success page still hands out the
0.1.0 URL until fly redeploys; same redeploy command as before:

```
fly deploy -c packages/llm_tracker_signup/fly.toml
# or push to main and let .github/workflows/deploy-signup.yml run
```

If the new wheel fails to attach to the Release, check the
Actions tab for the `Release llm-tracker-agent` run — the most
common failure mode is the workflow not triggering at all (tag
prefix mismatch), which would show no run rather than a failed
one.
