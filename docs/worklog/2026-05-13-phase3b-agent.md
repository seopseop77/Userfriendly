# 2026-05-13 · Phase 3b — thin local agent (`claude-manage`)

**Author**: Claude Code
**Session trigger**: User-redirected after STATUS pointed at Option C
(ADR-0024 close-out policy) / Option B (SSE extractor) under the Phase 3c
follow-up. Instead, the user delivered the two outstanding Phase-3a
decisions (#1 fallback policy, #4 agent language/distribution) and asked
me to write the ADRs and build the Phase 3b deliverable.
**Related docs**: ADR-0017, ADR-0024, ADR-0025, `docs/roadmap.md#3a-3b`.

## Interpretation

Phase 3b was the next roadmap item once the central server's CP14 follow-up
landed in production. The user supplied both outstanding Phase-3a decisions
in the same message (fail-closed on unreachable server; Python CLI
distribution), so the ADR-then-implement sequence collapses into one
session. Strictly two commits per the spec:
1. ADRs first, so the implementation has a citable contract.
2. Agent code in a single commit (skeleton + config + proxy + CLI + tests).
A third commit handles the §5.3 docs unit (worklog + STATUS update).

## What was done

### Step 1 — ADRs (commit `79a0ae9`)

- Created `docs/decisions/0024-agent-fallback-fail-closed.md` — fail-closed
  decision with the three core reasons (monitoring invariant; stateless
  agent; honest failure mode), the unreachable-error tuple, the 503 body
  shape, and "Settles: Phase-3a item #1".
- Created `docs/decisions/0025-agent-language-python-cli.md` — Python CLI
  decision with the three options (Python / Go / shell), the three core
  reasons (language consistency; install path acceptable; maintenance
  budget), the `claude-manage` entry-point rationale, and "Settles:
  Phase-3a item #4".

### Step 2 — Package skeleton (commit `fbd36e4`)

Created `packages/llm_tracker_agent/` (workspace member; `uv sync` picks
it up automatically via `packages/*`):

- `pyproject.toml` — hatchling build, deps `fastapi`, `uvicorn[standard]`,
  `httpx[http2]`, `typer`, `tomli-w`; dev `pytest`, `pytest-asyncio`,
  `ruff`; script `claude-manage = "llm_tracker_agent.cli:app"`;
  `[tool.pytest.ini_options]` asyncio_mode = "auto" so the agent's tests
  are self-contained.
- `src/llm_tracker_agent/__init__.py` — version + ADR pointers.
- `src/llm_tracker_agent/config.py` — `Config` dataclass + `load_config()`
  / `save_config()`. Path defaults to `~/.llm-tracker/config.toml`,
  parents created `mkdir -p`, file chmod'd `0o600`. Missing /
  malformed → `SystemExit` with operator-facing message.
- `src/llm_tracker_agent/proxy.py` — `make_proxy_app(config, *, client=
  None)` returns a FastAPI app: `/healthz` for readiness, catch-all
  `/{path:path}` that strips hop-by-hop headers, injects
  `X-LLM-Tracker-Token`, forwards via httpx with streaming, and returns
  `StreamingResponse`. On `ConnectError` /
  `TimeoutException` / `ReadError` / `RemoteProtocolError` returns HTTP
  503 with the ADR-0024 detail body. Response-side `Content-Encoding` is
  stripped because `aiter_bytes()` returns decoded chunks (see Decisions
  below).
- `src/llm_tracker_agent/cli.py` — Typer app with `setup TOKEN
  [--server-url ...] [--port ...]` plus an invoke-without-command default
  that loads config, starts uvicorn on a daemon thread, polls
  `/healthz` for ≤ 3s, sets `ANTHROPIC_BASE_URL`, and spawns
  `claude <extra-args>` via `subprocess.run` (see Decisions below).
- `tests/test_config.py` — 4 cases: roundtrip, 0o600 perms, missing file
  raises, malformed TOML raises.
- `tests/test_proxy.py` — 3 cases: token injection (verified via
  `httpx.MockTransport` capture); hop-by-hop strip (host re-derived from
  upstream base_url; inbound `transfer-encoding: chunked` and
  `connection: close` not forwarded; content-length recomputed);
  fail-closed (MockTransport raising `httpx.ConnectError` →
  503 with the expected detail).

Also touched (root):
- `pyproject.toml` — added `packages/llm_tracker_agent/tests` to
  workspace `testpaths` so `uv run pytest -q` from root collects the new
  suite.
- `uv.lock` — re-resolved (only addition: `tomli-w==1.2.0`).

## Decisions

- **Picked `subprocess.run` instead of `os.execvp`** for the
  Claude-Code launch path. The spec asked for execvp, but
  `os.execvp` replaces the current Python process image, which kills
  the uvicorn proxy daemon thread — so the proxy disappears before
  Claude Code's first request reaches it. `subprocess.run` keeps the
  parent Python (and therefore the proxy thread) alive for the
  Claude session; both exit together cleanly. Documented as an
  in-source comment in `cli.py` so the next reader does not "fix" it
  back to execvp.
- **Picked `aiter_bytes()` instead of `aiter_raw()`** for the
  response body stream. `httpx.MockTransport` returning
  `Response(content=b"...")` produces a response whose stream is
  already consumed at the point `client.send(stream=True)` returns,
  so `aiter_raw()` raises `StreamConsumed` in tests. `aiter_bytes()`
  has a documented fast-path for already-buffered responses
  (yields from `_content`) and an identical streaming path for
  real HTTP. SSE responses are served `Content-Encoding: identity`
  by Anthropic, so the decoded-vs-raw distinction is moot in the
  proxy's actual hot path. To keep the response self-consistent we
  also strip `Content-Encoding` from the response headers so the
  downstream client never re-decodes already-decoded bytes.
- **Picked `aiter_bytes`/`Content-Encoding` strip over a parallel
  streaming-aware test transport**. Building a custom streaming-only
  mock for tests would have been more work and would have hidden the
  inline-content edge case in production from anyone who reads
  test_proxy.py later.
- **Picked four-error tuple for "unreachable"** (`ConnectError`,
  `TimeoutException`, `ReadError`, `RemoteProtocolError`). ADR-0024
  named only the first two; the latter two are the obvious
  generalisations (TLS handshake mid-flight; central server crashed
  during the response body). The 503 body shape is fixed by the ADR
  regardless of which one fires.

## Verification

ruff:
```
$ uv run ruff format packages/llm_tracker_agent
6 files left unchanged
$ uv run ruff check packages/llm_tracker_agent
All checks passed!
```

pytest (agent suite):
```
$ uv run pytest packages/llm_tracker_agent/tests/ -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
configfile: pyproject.toml
plugins: asyncio-1.3.0, respx-0.23.1, anyio-4.13.0
asyncio: mode=Mode.AUTO
collected 7 items

packages/llm_tracker_agent/tests/test_config.py::test_save_and_load_roundtrip PASSED [ 14%]
packages/llm_tracker_agent/tests/test_config.py::test_save_sets_owner_only_perms PASSED [ 28%]
packages/llm_tracker_agent/tests/test_config.py::test_load_missing_raises PASSED [ 42%]
packages/llm_tracker_agent/tests/test_config.py::test_load_malformed_raises PASSED [ 57%]
packages/llm_tracker_agent/tests/test_proxy.py::test_injects_tracker_token PASSED [ 71%]
packages/llm_tracker_agent/tests/test_proxy.py::test_strips_hop_by_hop PASSED [ 85%]
packages/llm_tracker_agent/tests/test_proxy.py::test_fail_closed_on_server_unreachable PASSED [100%]

============================== 7 passed in 0.12s ===============================
```

pytest (full repo, regression check):
```
$ uv run pytest -q
300 passed, 16 skipped, 4 warnings in 12.40s
```

CLI setup roundtrip (live):
```
$ uv run claude-manage setup lts_test_token --server-url http://localhost:18080 --port 18080
Saved /Users/minseop/.llm-tracker/config.toml. Run `claude-manage` to start.

$ cat ~/.llm-tracker/config.toml
[server]
url = "http://localhost:18080"
token = "lts_test_token"
local_port = 18080

$ ls -la ~/.llm-tracker/config.toml
-rw-------@ 1 minseop  staff  84 May 13 17:19 /Users/minseop/.llm-tracker/config.toml
```

`-rw-------` confirms the 0o600 chmod fired. The test token left in the
file is junk; the operator should re-run `claude-manage setup <real-token>`
before pointing Claude Code at the agent in earnest.

## What's left / known limits

- **No live end-to-end against the production server.** All proxy paths
  are tested with `httpx.MockTransport`. The single live touch was
  `claude-manage setup` writing the config file. An actual
  `claude-manage` → real Claude Code → live Fly.io central server smoke
  is the next step (see Handoff).
- **Limited CLI test coverage.** `_pick_port` has unit tests
  (`test_cli.py`, added in follow-up commit `ac4370c`). The
  threading + uvicorn + readiness-poll + `subprocess.run` path is
  not unit-tested; setup roundtrip was exercised live. Spec
  deviation (`subprocess.run` vs `os.execvp`) is documented inline.
- **Parent `kill -9` orphans the child `claude`.** Normal exit
  paths (Claude `/exit`, Ctrl-C, claude crash) all flow cleanly:
  SIGINT/Claude termination → `subprocess.run` returns → `typer.Exit`
  → parent Python exits → OS reaps the daemon uvicorn thread →
  loopback port released. The pathological case is SIGKILL on the
  parent Python: the daemon thread dies with it, but the child
  `claude` is re-parented to launchd/init and survives as an orphan.
  Out of scope for the agent fix — would need a parent-death signal
  (`PR_SET_PDEATHSIG` on Linux; macOS equivalent via kqueue) to
  guarantee child cleanup under `kill -9`.
- **Token format unvalidated.** `setup` only rejects empty/whitespace
  tokens. Format-level validation (`lts_` prefix, length) is out of
  scope; the server already validates on its side.
- **No retry on transient upstream errors.** ADR-0024's fail-closed
  contract is strict: one failed forward → 503. A future "soft fail"
  variant could distinguish transient-vs-permanent, but that is
  exactly what ADR-0024 §Open questions punts on.
- **Spec said `os.execvp`; implementation uses `subprocess.run`.**
  Deviation reason recorded above in Decisions and inline in cli.py.

## Handoff

**Phase 3b code is done; verification still needs an external pair of
hands.** A second team member should:

1. `git pull` to HEAD (`fbd36e4` for the agent code).
2. `cd packages/llm_tracker_agent && pip install -e . --break-system-packages`
   (or `uv sync` at the workspace root).
3. `claude-manage setup <their-real-org-token> --server-url
   https://llm-tracker-server.fly.dev`.
4. `claude-manage` → Claude Code launches with `ANTHROPIC_BASE_URL`
   pointed at the loopback proxy → run any prompt → verify in
   Supabase that the resulting row in `public.exchanges` is scoped to
   the correct `org_id`.
5. Negative case: stop the local proxy (or point `--server-url` at an
   unreachable host) → `claude-manage` should emit HTTP 503 with the
   ADR-0024 detail message, and Claude Code should refuse to silently
   bypass the server.

After that smoke succeeds, the next single step is the Phase-3c
follow-up the user has been holding: either **Option C — ADR-0024
"exchange row close-out policy"** (ADR-0024 in this worklog is the
*agent* fallback ADR; the user's earlier "ADR-0024 close-out policy"
is now ADR-0026 — naming drift to surface to the user) or **Option B —
SSE extractor** for the remaining response-side fields.

> **Decision needed**: the previous STATUS named the close-out-policy
> ADR as "ADR-0024" but that slot is now taken by the agent
> fallback ADR shipped today. The close-out-policy ADR will be
> renumbered (0026) when it lands. Flagged here, not silently moved.

## Follow-up — multi-instance via ephemeral port (commit `ac4370c`)

User question in chat surfaced that two `claude-manage` instances
sharing the same `~/.llm-tracker/config.toml` would both try to bind
the same preferred port. The second `uvicorn.Server.run()` would
fail in its daemon thread (logged to stderr only), but `_wait_ready`
would still see the first instance's `/healthz` answer 200 and pass
— routing the second `claude`'s traffic through the first instance's
proxy. Killing the first instance would then break the second
silently.

Fix: new `_pick_port(preferred)` helper probes `127.0.0.1:<preferred>`;
on `EADDRINUSE` falls back to a kernel-assigned ephemeral port. The
picked port is used both for `uvicorn.Config(port=...)` and the
`ANTHROPIC_BASE_URL` handed to `claude`. When the fallback fires,
stderr emits
`[claude-manage] preferred port N in use; this instance is on M.`

Each instance now owns a distinct loopback proxy. Killing any one
instance has no effect on the others; the per-`claude` proxy dies
with its parent Python process as before.

Tests added (`packages/llm_tracker_agent/tests/test_cli.py`, 2
cases): preferred-port returned when free; fallback when preferred
is taken. Full suite remains green at 302 passed / 16 skipped.

Residual micro-race: between `_pick_port` closing the probe socket
and uvicorn re-binding, another process could grab the port. On
loopback this is extremely unlikely; if it ever fires, uvicorn
fails in its thread and `_wait_ready` times out with a clear error.

## Closure — smoke verified, Phase 3b CLOSED

User-run end-to-end smoke from the workspace tree later in the
session. Positive and negative paths both held:

- **Positive**: `claude-manage setup <real-token> --server-url
  https://llm-tracker-server.fly.dev` → `claude-manage` → live
  Claude Code session → real prompts. Supabase
  `public.exchanges` accrued new rows scoped to the demo
  `org_id=c6fcdd23-...` (verified via Supabase MCP
  `SELECT ... ORDER BY started_at DESC`). 8 timed rows post
  Option A: 5 opus-4-7 (4227 / 5418 / 6729 / 12010 ms),
  1 opus-4-5 baseline (1820 ms — CP14), 3 haiku-4-5 (913 / 992 /
  3568 ms). RLS held — only the tester's org_id surfaced under
  their token.
- **Negative**: pointed `--server-url` at `http://127.0.0.1:9`
  (discard port). `claude-manage` returned 503 to the in-process
  Anthropic SDK in Claude Code, which retried 10× with exponential
  backoff (Anthropic SDK default) before surfacing the failure to
  the user — i.e., the request never reached Anthropic, ADR-0024
  fail-closed contract held end-to-end.

**Latency side-investigation** (Supabase MCP read in chat):
opus-4-7 rows ran 4–12s, haiku-4-5 ran <1s for short prompts.
`latency_ms` is server-side wall-clock (Option A semantics), so
agent loopback overhead does not appear in this column; the
sub-second haiku numbers are direct evidence that server-side
processing (auth + RLS + plugin host + INSERT) is in the tens of
ms. Variance among opus-4-7 rows is driven by Anthropic-side
generation time / response length and cannot be characterised
further until Option B SSE extractor populates
`input_tokens` / `output_tokens`. The 12010 ms outlier flagged
as a watch-item for Option B work; not blocking Phase 3b closure.

Phase 3b is **closed** (2026-05-13). The thin local agent is in
production use; new team members install via the workspace
(`uv sync` or `pip install -e packages/llm_tracker_agent`) and
can run `claude-manage setup <token> && claude-manage` end-to-end.

## Suggestions (untouched)

- The existing `packages/llm_tracker/src/llm_tracker/cli/manage.py`
  has its own claude-launching scaffolding (`fork()`-based, with
  tests in `test_cli_manage.py`). That code was written under the
  local-sidecar model and uses a different process-management
  approach. Worth a side-by-side review once the team-demo smoke
  passes — there may be patterns to lift (signal handling, PID
  tracking) or it may be the right thing to retire entirely now
  that the central-server agent has shipped.
