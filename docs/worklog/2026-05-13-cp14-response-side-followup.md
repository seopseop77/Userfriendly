# 2026-05-13 · CP14 follow-up — response-side NULL columns: root cause + options

**Author**: Claude Code
**Session trigger**: STATUS.md "Next single step" — investigate the
response-side NULL columns on the CP14 exchange row.
**Related docs**: `docs/worklog/2026-05-13-cp14-operator-smoke.md`
(upstream context — CP14 closure), ADR-0017 (server pivot), ADR-0018
(per-org RLS), CP8/CP9 plan-of-record at
`docs/worklog/2026-05-11-phase3c-plan.md`.

## Interpretation

The CP14 closure flagged that the successful 200-OK exchange row had
`ended_at`, `model_requested`, `model_served`, `status_code`,
`input_tokens`, `output_tokens`, `latency_ms`, `stop_reason` all NULL.
STATUS.md's hypothesis: a two-step INSERT-at-open / UPDATE-at-close
contract where the close-out UPDATE was failing silently (suspect:
`on_persisted` hook dispatch lost in CP8's plugin host port, or the
follow-up UPDATE failing under RLS-context drift on a fresh post-stream
session). Verify the hypothesis before fixing.

## What was done

**Investigation half** (read-only, finding-only commit `f37c95f`):

- Read `packages/llm_tracker_server/src/llm_tracker_server/proxy/forwarder.py`
  (the full pre-stream + streaming-generator path), the storage helpers
  in `storage/exchanges.py`, the storage ORM model in `storage/models.py`,
  and the CP8 plugin host in `plugin_host/host.py`.
- Grep'd the server source for every `Exchange(` constructor call,
  every `UPDATE exchanges` / `update(Exchange` site, and every
  response-side column reference (`model_served`, `input_tokens`,
  `output_tokens`, `stop_reason`, `ended_at`). Results:
  - Two `Exchange(` constructors total —
    `record_exchange_timing` (happy path) and `record_exchange_blocked`
    (Block/Abort short-circuit). Both in `storage/exchanges.py`.
  - **Zero** `UPDATE exchanges` / `update(Exchange ...)` statements
    anywhere in the server source.
  - The response-side columns appear only in `models.py` (column
    definitions) and `proxy/sse.py` (synthetic-block SSE constants).
    They have **no producer site** in the server code.

**Implementation half — Option A landed** (commit `237d842`):

- Modified `packages/llm_tracker_server/src/llm_tracker_server/storage/exchanges.py` —
  extended `record_exchange_timing` signature with four new required
  kwargs: `ended_at_ms`, `status_code`, `model_requested`,
  `latency_ms`. Helper sets them on the `Exchange` ORM object alongside
  the existing started/timing fields. Module docstring rewritten to
  describe the new column set + carve-out for Option B's SSE-extractor
  fields.
- Modified `packages/llm_tracker_server/src/llm_tracker_server/proxy/forwarder.py` —
  added `import json`; added `_parse_model_requested(body)` helper
  (returns `None` on empty / non-JSON / non-dict / non-str-`model`
  bodies — observability gravy, never escalates); in the post-stream
  success block, derives `t_end_mono` from `time.monotonic()`,
  computes `ended_at_ms` from the same monotonic anchor as the
  existing `t_*_ms` marks (consistent under clock-jump), and passes
  `upstream.status_code` + `_parse_model_requested(body)` +
  `latency_ms = ended_at_ms - t0_epoch_ms` through.
- Modified `packages/llm_tracker_server/tests/test_two_org_e2e_isolation.py` —
  extended the org-A row assertions to verify `status_code == 200`,
  `model_requested == "claude-x"` (matching the request body in the
  test), `ended_at is not None and >= started_at`,
  `latency_ms is not None and >= 0`. The Option-B-bound columns
  (`model_served`, `*_tokens`, `stop_reason`) stay NULL and are
  intentionally not asserted.

## Findings — hypothesis falsified

The "INSERT-at-open + UPDATE-at-close two-step" architecture that STATUS
hypothesised **does not exist**.

The actual happy-path shape, traced end-to-end:

1. Forwarder enters its outer block. **No INSERT yet** —
   `t0_epoch_ms` is captured but nothing hits the DB.
2. Plugin hooks fire (`on_request_received`, `before_forward`,
   `on_upstream_response_start`). On `Block` / `Abort`, the
   short-circuit calls `record_exchange_blocked` and returns. On
   `Pass`, the upstream stream opens with no DB write so far.
3. Streaming generator iterates `upstream.aiter_bytes()`, tee'ing
   chunks to the internal queue + the client. **Still no INSERT.**
4. When the stream ends naturally (`async for ... else` runs the
   `else` clause → `completed = True`), the generator opens its
   fresh session (post-stream), and **only here** issues the single
   INSERT via `record_exchange_timing`. Then dispatches
   `on_persisted` to plugins.

So the live demo row was written by `record_exchange_timing`. Look at
what that helper actually inserts (`storage/exchanges.py:48–62`):

```python
session.add(
    Exchange(
        id=exchange_id,
        org_id=org_id,
        session_id="server",
        started_at=t_request_received_ms,   # = t0_epoch_ms
        provider="anthropic",
        endpoint=endpoint,
        content_level="L3",
        tool_call_count=0,
        t_request_received_ms=t_request_received_ms,
        t_upstream_first_byte_ms=t_upstream_first_byte_ms,
        t_client_first_byte_ms=t_client_first_byte_ms,
    )
)
```

Eight columns are intentionally omitted: `ended_at`, `model_requested`,
`model_served`, `status_code`, `input_tokens`, `output_tokens`,
`latency_ms`, `stop_reason` (also `cache_read_tokens`,
`cache_write_tokens`, `blocked_by` — the latter being NULL on a happy
row is correct).

So the NULLs on CP14's row are **not a silent failure**. They are
"never written by code" — a known unfinished piece of CP8/CP9 that
shipped as a stub. The `_drain` docstring in `forwarder.py:113–122`
flags exactly this: *"Phase-2 will replace this with the Extractor
(parse SSE events into the structured `events` / `tool_calls` records).
For CP8/CP9 the queue exists so the plumbing is in place; the consumer
side is empty."*

The CP9 closed-checkpoint note about `model_served=null` for HTTP-error
bodies described this same hole partially — the actual hole is wider:
**all eight response-side columns are NULL on every exchange row**,
both error and SSE-200, because there is no producer site for them.

## Decisions

**User picked Option A** (quick wins only) from the three options
below. Rationale (user-side, paraphrased): land the no-parser-needed
fields first so the next demo curl produces a populated-looking row;
defer the SSE extractor (Option B) and the policy ADR (Option C) to
separate tracks so each can be sized + scheduled on its own merits.
Recommendation in this worklog was C → A → B; user override accepted.

Implementation followed Option A's preview chip verbatim — same four
columns, same signature shape, same call site. No scope creep.

### Original option enumeration (kept for the next track's sizing)

Per CLAUDE.md §4 + §10, changing storage write behavior + extending the
helper's signature + (for option B/C) parsing SSE events into structured
fields is architecture territory. Surfacing options before implementing.
The CP14 worklog's "Suggestions" section already lined this up:

> Worth folding both [HTTP-error + SSE-200 close-out gaps] into a
> single ADR on "exchange row close-out policy" rather than patching
> ad hoc — the same code path determines both behaviors.

The same code path is `record_exchange_timing` + the forwarder's
post-stream block at `forwarder.py:305–325`.

### Option A — quick wins from data the forwarder already has

Populate just the fields available without touching the SSE stream
content:

| Column | Source | Cost |
|---|---|---|
| `ended_at` | `int(time.time() * 1000)` at the end of `generate()` | trivial |
| `status_code` | `upstream.status_code` | trivial |
| `latency_ms` | `t_client_first_byte_ms - t_request_received_ms`, or `ended_at - started_at` | trivial |
| `model_requested` | parse the `model` field from the request JSON body | small — needs body inspection in the post-stream block, or capture during pre-stream |

Out of scope under A: `model_served`, `input_tokens`, `output_tokens`,
`cache_*`, `stop_reason` (these all need SSE event parsing — Phase-2
Extractor work).

Roughly a 30–60 line surgical patch to `record_exchange_timing` +
forwarder. Tests pin the new columns. No new module, no schema change.

### Option B — wire a thin SSE extractor for `message_start` + `message_delta` + `message_stop`

Re-use the existing tee queue (`internal: asyncio.Queue[bytes]`).
Replace `_drain` with a parser that reads SSE events and extracts:

- `message_start` → `model_served`, baseline `input_tokens`
- `message_delta` → `stop_reason`, incremental `output_tokens`
- `message_stop` → final `output_tokens`, `cache_read_tokens`,
  `cache_write_tokens`

Yields a complete picture for the happy SSE path. Still doesn't help
the HTTP-error case (no SSE body), so error-row population also needs
some thought (status_code + ended_at land in option A territory).

Estimated 150–300 lines (parser + integration + tests). Lives under
`llm_tracker_server.extractors.anthropic` or similar. Brings forward
the Phase-2 Extractor that was originally scheduled later.

### Option C — write the ADR first, then implement

An ADR named "exchange row close-out policy" that:

1. Decides the contract — what fields are *guaranteed* populated on
   every closed row, and what is allowed to be NULL (and why).
2. Decides the producer split — request-side (`model_requested`,
   `started_at`) vs. response-side (`model_served`, `*_tokens`,
   `stop_reason`) vs. forwarder-internal (`status_code`, `latency_ms`,
   `ended_at`).
3. Decides how the error path is supposed to land — there's currently
   no INSERT at all if the upstream fails before SSE starts; the row
   is only persisted when the `else` clause of the streaming `for`
   loop runs.

Then implement under that contract. Slower-up-front but lines up the
SSE-200 hole + the CP9 HTTP-error hole + the silent "no row at all
on upstream non-SSE failure" hole all under one design.

### Original recommendation (overridden)

**Option C → Option A → Option B**, in that order, but with overlap
allowed. Rationale: C first (~30 min ADR draft) is small but
load-bearing for everything downstream; doing A or B without C risks
re-architecting the helper signature twice.

User chose **A only** (override accepted). The ADR (Option C) is
re-queued as a separate track — see "What's left" below.

## Verification

```
$ .venv/bin/python3.12 -m ruff check \
    packages/llm_tracker_server/src/llm_tracker_server/storage/exchanges.py \
    packages/llm_tracker_server/src/llm_tracker_server/proxy/forwarder.py \
    packages/llm_tracker_server/tests/test_two_org_e2e_isolation.py
All checks passed!

$ LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test \
    .venv/bin/python3.12 -m pytest packages/llm_tracker_server/tests -q
.............................................................   [100%]
61 passed in 23.79s
```

61/61 — same count as the post-CP14 baseline; the extended e2e
assertions reuse the existing test, no new test method.

Manual production verification (next demo curl) is **not** wrapped
into this checkpoint — the live Fly deploy still runs the pre-Option-A
build until the next `fly deploy`. Once redeployed, the next happy-
path curl should land an `exchanges` row with `ended_at`,
`status_code`, `model_requested`, `latency_ms` all populated; the
remaining columns (`model_served`, `*_tokens`, `stop_reason`) stay
NULL until Option B's extractor lands.

## What's left / known limits

- **Option B (SSE extractor)** still owed for the remaining five
  response-side fields. Touches: a new
  `llm_tracker_server.extractors.anthropic` module, replacement of
  the existing `_drain` stub in `proxy/forwarder.py` with a real
  consumer, integration into `record_exchange_timing`'s kwargs
  surface (extend signature again at that point). Estimated
  150–300 lines + tests; doubles as the Phase-2 Extractor entry
  point per `docs/roadmap.md`.
- **Option C (ADR-0024 "exchange row close-out policy")** still
  owed. Now that Option A has landed the forwarder-known fields, the
  ADR's surface area shrinks slightly (the request-side / forwarder-
  internal split is already concrete in code) but the open questions
  remain: contract for the error path (today: no row at all if
  upstream fails pre-SSE), parity for the blocked-path row, and the
  policy for "guaranteed populated vs. allowed NULL". Recommend
  drafting before Option B lands so B's signature change is
  contract-stable.
- **Blocked-path row parity**. `record_exchange_blocked` still writes
  rows with `ended_at`, `latency_ms`, `model_requested` NULL on
  Block / Abort short-circuits. Three of the four Option A fields
  are trivially available on that path too (the fourth,
  `status_code`, is debatable — no upstream call happened, the
  client sees a synthetic 200 from `block_response`). Out of scope
  for this checkpoint; flag for either Option C ADR or a follow-up
  surgical patch.
- **Migration 0006 stamp** on live Supabase is still un-aligned
  (live `alembic_version = 0005_rls_policies`; code head is
  `0006_grant_app_role_set`). Next `fly deploy` resolves via
  idempotent `alembic upgrade head`. Independent track from this
  worklog's scope.
- **CP9 closed-checkpoint observation rewording**. The framing
  ("by-design observability hole for HTTP-error responses") was
  always too narrow — the actual hole covered all SSE-200 happy
  paths too. After Option A: the hole shrinks but doesn't close. A
  re-write should wait until Option B / C lands and the picture
  stabilises.

## Handoff

Option A is **closed**. The CP14 row's NULLs that triggered this
investigation are now reduced from 8 columns to 5; the remaining 5
all need SSE event parsing (Option B). The natural next checkpoint is
either:

1. **Deploy + verify**: `fly deploy` the Option A build, run an
   operator curl, confirm a fresh exchange row carries the four new
   columns populated. Roughly 10–15 minutes.
2. **ADR-0024 draft** (Option C): write the close-out policy ADR
   *before* sizing Option B, so B's signature change lands under a
   stable contract.
3. **Option B implementation**: the SSE Extractor — replace `_drain`
   with `extractors/anthropic.py` parsing `message_start` /
   `message_delta` / `message_stop` events.

Continuation prompt for the next session, paste verbatim:

> Resume. Read STATUS.md → the worklog it points to → `git log -5`.
> Announce the next single step in one line, then execute it. Update
> per §5.3 along the way.

## Suggestions (untouched)

- `_drain` in `proxy/forwarder.py:112–122` is the natural seam for
  Option B's SSE event parser — it already owns the tee queue and the
  CP8/CP9 docstring explicitly flagged it as the Phase-2 hook point.
  No refactor needed before it.
- The forwarder's pre-stream block doesn't even attempt an INSERT.
  If a future contract wants an INSERT-at-open for crash-resilience
  (observability of requests that died mid-stream), that's a
  separate ADR — distinct from the close-out write being missing.
