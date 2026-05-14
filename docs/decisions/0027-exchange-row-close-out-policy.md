# ADR-0027 · Exchange row close-out policy

- **Status**: Accepted
- **Date**: 2026-05-14
- **Author**: Claude Cowork (decision) / Claude Code (drafting)
- **Related**: ADR-0017 (central server deployment), ADR-0018 (RLS multi-tenancy),
  ADR-0026 (HookContext response accessors), STATUS.md "Next single step",
  `docs/worklog/2026-05-13-cp14-response-side-followup.md`,
  `docs/worklog/2026-05-14-plugin-ecosystem.md`

## Context

The `public.exchanges` table is the single row-per-request fact table. Today the
forwarder writes it from three call sites with three different sets of populated
columns:

1. **Happy SSE path** (`record_exchange_timing` in `storage/exchanges.py`).
   After CP14 follow-up Option A, the close-out columns `ended_at`,
   `status_code`, `model_requested`, `latency_ms` are filled. Five response-side
   columns remain uniformly `NULL`: `model_served`, `input_tokens`,
   `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `stop_reason`.
   Option B (SSE Extractor) is about to fill them.
2. **Blocked path** (`record_exchange_blocked`). Lands when a plugin's
   `on_request_received` / `before_forward` returns `Block`, or
   `on_upstream_response_start` returns `Abort`. Today writes only
   `started_at`, `t_request_received_ms`, `blocked_by`. `ended_at`,
   `latency_ms`, and `model_requested` are `NULL` even though all three are
   trivially knowable at block time.
3. **Pre-SSE upstream failure path** — does not exist. If Anthropic returns
   non-2xx before the SSE generator's `for` loop's `else` clause runs (or if
   the upstream connection drops before first byte), no row is written at all.
   The request is silently absent from `exchanges`; `fly logs` is the only
   trace.

Option B is about to extend `record_exchange_timing`'s signature with six new
keyword-only params. Doing that without first committing to a NULL policy and
to the error/blocked paths' parity creates a moving target: every future column
addition becomes a re-negotiation of "is this required or optional?", and the
operator looking at a NULL today cannot distinguish "extractor didn't run" from
"the column was never populated on this code path."

This ADR fixes the close-out policy *before* Option B's signature extension
lands so the same contract covers both.

## Options considered (per axis)

### Axis 1 — Response-side NULL policy on happy SSE path

1a. **Best-effort NULL** — extractor never raises; on parse failure or missing
field the column stays NULL. Operator interpretation: "NULL means we didn't
observe it on this request" (network truncation, schema drift, etc).
1b. **Strict happy-path** — happy 200 SSE must have `model_served`, both token
counts, and `stop_reason` non-NULL; missing fields escalate to a server
error. `cache_*` allowed NULL because not all requests use prompt caching.

### Axis 2 — Pre-SSE upstream failure path

2a. **Write a row anyway** — populate `status_code`, `ended_at`,
`model_requested`, `latency_ms`; leave response-side columns NULL. Operator
gets a row per request even on upstream failure; the row's `status_code`
distinguishes it from happy SSE (200 vs 4xx/5xx).
2b. **Stay silent** — codify the current behaviour as policy. `fly logs` is
the only trace. Operator must cross-reference logs with the absence of a
row.

### Axis 3 — Blocked-path field parity

3a. **Pull the cheap fields into the helper** — `record_exchange_blocked` also
fills `ended_at`/`latency_ms`/`model_requested` because all three are
knowable at block time. Result: blocked rows are queryable on the same axes
as happy rows (`SELECT model_requested, count(*) FROM exchanges
WHERE blocked_by IS NOT NULL GROUP BY model_requested`).
3b. **Per-path divergence as policy** — blocked rows have a deliberately
different shape because the request never reached upstream. The operator
must `WHERE blocked_by IS NULL` before touching the close-out columns.

## Decision

- **Axis 1: option 1a (best-effort NULL).** The extractor's contract (per
  ADR-0026) is "never raise; missing fields default to None." Strict
  happy-path validation would either require the extractor to raise (breaking
  the contract that protects the request pipeline from parse bugs) or require
  a post-parse validator we would have to keep in sync with Anthropic schema
  changes. Best-effort means "NULL is data" — it tells the operator that the
  observation failed without escalating to a 500.
- **Axis 2: option 2a (write a row anyway).** Silence under failure is the
  exact pattern the central server exists to prevent (ADR-0017). All four
  cheap fields are knowable on this path; writing them gives the operator a
  per-request audit row that distinguishes "upstream returned 5xx" from "the
  request was never received." The `status_code` column is the discriminator
  — happy SSE writes 200, this path writes 4xx/5xx (or a sentinel like 599
  for connection-error cases where Anthropic gave us nothing).
- **Axis 3: option 3a (pull the cheap fields into the blocked helper).** The
  three fields are free at block time (forwarder already knows them).
  Declining to populate them is a per-path divergence the operator has to
  remember every time they write a query. Pulling them in costs three lines
  in `record_exchange_blocked`.

## Population matrix (post-decision)

| Column | Happy SSE 2xx | Pre-SSE failure | Blocked | Why |
|---|---|---|---|---|
| `id` | required | required | required | Always set by forwarder. |
| `org_id` | required | required | required | ADR-0018 tenancy invariant. |
| `started_at`, `t_request_received_ms` | required | required | required | Known on every code path. |
| `provider`, `endpoint`, `content_level` | required | required | required | Constant per code path. |
| `session_id` | required | required | required | `"server"`, set by helpers. |
| `model_requested` | populated when parseable | populated when parseable | **populated when parseable** (new) | Best-effort JSON read of request body — same logic on all three paths. |
| `status_code` | required (upstream's) | required (upstream's or 599 sentinel) | NULL | "599 = no response from upstream" is a documented sentinel; blocked rows never touched upstream. |
| `ended_at`, `latency_ms` | required | required | **required** (new) | Monotonic-anchor close-out is cheap on every path. |
| `t_upstream_first_byte_ms`, `t_client_first_byte_ms` | required | NULL | NULL | Only meaningful when SSE actually started. |
| `model_served`, `input_tokens`, `output_tokens` | best-effort | NULL | NULL | Extractor output. NULL on this row is data. |
| `cache_read_tokens`, `cache_write_tokens` | best-effort (NULL when no caching used) | NULL | NULL | As above. |
| `stop_reason` | best-effort | NULL | NULL | As above. |
| `tool_call_count` | 0 (placeholder until tool extraction lands) | 0 | 0 | Field already there from CP9. |
| `blocked_by` | NULL | NULL | required | The blocked-row discriminator. |

The pre-SSE failure path is **not implemented in this commit**; it is the
contract this ADR settles for a follow-up checkpoint. The current scope of
ADR-0027 covers axes 1 and 3 in code (Option B + blocked-path parity); axis 2
is documented here as the next agreed shape so the next session can implement
it without re-litigating.

## Consequences

- **Enables**:
  - Option B's six new keyword-only params on `record_exchange_timing` land
    under a stable NULL contract.
  - Blocked rows are queryable on the same close-out axes as happy rows.
  - Operator SQL like `WHERE status_code BETWEEN 500 AND 599` works once the
    pre-SSE failure path lands.
- **Forecloses**: the "NULL means we never tried to populate this on this
  code path" interpretation. Going forward NULL on a response-side column
  means "the extractor did not produce a value for this request" only.
- **Reversibility**:
  - Axis 1 — high. Tightening to strict is one validator function.
  - Axis 2 — high. The pre-SSE failure path is additive; landing the row
    write is a single helper call site.
  - Axis 3 — high. The three new args on `record_exchange_blocked` are
    optional in the helper but always supplied by the forwarder; reverting
    means dropping the keyword args and the columns stay NULL again.

## Open questions

- **`status_code` sentinel for connection-error case.** This ADR proposes 599
  for "upstream gave us nothing" (httpx `ConnectError` / `TimeoutException`).
  A non-standard HTTP status reserves a query-time grep. If the convention
  collides with anything we surface to clients later, this becomes an
  amendment.
- **`tool_call_count` populator**. Stays 0 until tool extraction is added to
  `extractors/anthropic.py` (Option B currently parses text content only).
  Out of scope for ADR-0027.

## Settles

STATUS.md "Next single step" ("Draft ADR-NNNN — exchange row close-out
policy") for axes 1 and 3. Axis 2 lands as a follow-up checkpoint under this
ADR's banner.
