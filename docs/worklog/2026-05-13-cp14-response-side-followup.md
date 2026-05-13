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

## Decisions needed (escalate — architecture / public-interface touching)

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

### Recommendation

**Option C → Option A → Option B**, in that order, but they can
overlap. Specifically:

1. **C first** (ADR draft) — 30 minutes. The decisions are small but
   load-bearing for everything downstream. Doing A or B without C
   risks re-architecting the helper signature twice.
2. **A under the ADR's contract** — small, immediate-value, lands all
   the no-parser-needed fields, gives the operator something to
   `SELECT *` on the next demo curl.
3. **B as proper Phase-2 entry point** — the SSE extractor is wanted
   anyway for `events` / `tool_calls` population (per the Phase-2 plan
   in `docs/roadmap.md`). Landing it here gives it a real consumer
   immediately.

Awaiting user pick before touching code.

## Verification

(Read-only investigation. No code or tests changed.)

```
$ grep -rn "Exchange(" packages/llm_tracker_server/src/
storage/models.py:45:class Exchange(Base):
storage/exchanges.py:49:        Exchange(   # record_exchange_timing
storage/exchanges.py:77:        Exchange(   # record_exchange_blocked

$ grep -rn "UPDATE.*exchanges\|update(Exchange\|.update(\s*Exchange" \
    packages/llm_tracker_server/src/
(no matches)

$ grep -rn "model_served\|input_tokens\|output_tokens\|stop_reason\|ended_at" \
    packages/llm_tracker_server/src/
storage/models.py:56,60,62,63,67   (column defs)
proxy/sse.py:16,55,57,82,83        (synthetic-block SSE constants only)
(no producer site)
```

## What's left / known limits

- This worklog is purely a finding + options write-up. Awaiting user
  decision on Option A / B / C. No code shipped under this slug yet.
- The CP9 closed-checkpoint observation about `model_served=null`
  needs to be reworded once the ADR / fix lands — the framing
  ("by-design observability hole for non-SSE responses") was already
  too narrow.
- Migration 0006 is still un-stamped on live Supabase
  (`alembic_version = 0005_rls_policies`). Not blocking this
  investigation; carries over.

## Handoff

Three options on the table for the user (Option C → A → B
recommended). All three converge on populating eight currently-NULL
columns on the `exchanges` row close-out path; they differ on
how-much-design-up-front vs. ship-now. Once the user picks a lane,
the next session starts from this worklog and either:

- Drafts ADR-0024 ("exchange row close-out policy") under Option C, or
- Lands the surgical patch under Option A as a single small commit, or
- Stands up `extractors/anthropic.py` under Option B as a Phase-2 entry.

## Suggestions (untouched)

- `_drain` in `proxy/forwarder.py:112–122` is the natural seam for
  Option B's SSE event parser — it already owns the tee queue and the
  CP8/CP9 docstring explicitly flagged it as the Phase-2 hook point.
  No refactor needed before it.
- The forwarder's pre-stream block doesn't even attempt an INSERT.
  If a future contract wants an INSERT-at-open for crash-resilience
  (observability of requests that died mid-stream), that's a
  separate ADR — distinct from the close-out write being missing.
