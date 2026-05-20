# ADR-0030 · scope_guard plugin design

- **Status**: Accepted (2026-05-18 by operator; implementation begins in
  `docs/worklog/2026-05-18-scope-guard-impl.md`. Pre-decision on the only
  unresolved infra axis surfaced during sanity-checking: local test DB
  uses `pgvector/pgvector:pg15` so the §D8 `CREATE EXTENSION vector`
  applies unconditionally — Option A from the worklog's "Pre-flight
  sanity check" section.)
- **Date**: 2026-05-18
- **Author**: Claude Cowork (decisions captured in 2026-05-18 user
  interview) / Claude Code (drafting)
- **Related**: ADR-0002 (Task-scope enforcement spec — *settled* by this
  ADR in reframed async form), ADR-0019 (content level / plugin model),
  ADR-0026 (HookContext response accessors), ADR-0027 (exchange row
  close-out policy), ADR-0029 (consent + data handling), ADR-0018 (RLS
  multi-tenancy — schema pattern), ADR-0015 (EgressClient SDK), ADR-0013
  (plugin disable config — operator off-switch)
- **Settles**: ADR-0002 — that ADR was a *spec* for Phase-1 sidecar-era
  task-scope enforcement. This ADR is its implementation in reframed
  form (async monitoring on the central server instead of synchronous
  block on the local sidecar).

## Context

ADR-0002 sketched a task-scope enforcement plugin in 2026-05-01. The
spec assumed:

- Plugins ran on the user's machine (the sidecar era).
- The enforcement was *synchronous* — a Stage-2 LLM judge could block
  before forwarding via a synthetic SSE response.
- The trust boundary was the user's own machine; consent + retention
  were per-user opt-in choices (ADR-0006).

The 2026-05-11 pivot to a central server (ADR-0017) and its
consequences (ADR-0019: L/A/R modes retired, L0–L3 content-level
ladder kept; ADR-0029: full L3 storage, 6-month retention, scrubber
on `request_text()` / `response_content_json()`) invalidated those
assumptions. scope_guard now runs server-side, sees the same L3 view
analytics_sink does, and operates against a 6-month-retained corpus
of exchanges.

Phase 1c was the user-deferred slot for scope_guard since
2026-05-08. With the server-side runtime, the egress client SDK
(ADR-0015), and the HookContext response accessors (ADR-0026) all
shipped, the infrastructure is ready. This ADR records the design
decisions made in the user interview so a follow-up implementation
session can build against a fixed target.

The plugin's research-phase priority is **data collection and
threshold tuning over real-time enforcement**. Real-time blocking
remains an explicit follow-up (Deferred §1) once thresholds are
validated against real traffic.

## Options considered (per axis)

### Axis 1 — Execution model

- **A. Synchronous Block on `on_request_received`.** Matches the
  ADR-0002 spec. Forces every request to pay the
  embedding + (occasionally) LLM-judge latency before forwarding.
- **B. Asynchronous monitor on `on_persisted`** *(chosen)*. Runs after
  the response is already written; records a per-exchange alert row.
  Loses the ability to block in real time; gains zero per-request
  latency impact.

### Axis 2 — Pipeline shape

- **A. Embedding-only.** Cheap but accuracy drops on long / complex
  documents (single-vector compression).
- **B. LLM-only.** Highest accuracy; cost-prohibitive at full traffic.
- **C. Two-stage (cheap pre-filter → LLM judge on ambiguous only)**
  *(chosen)*. Bounds cost while preserving accuracy on the boundary.

### Axis 3 — Embedding provider

- **A. OpenAI `text-embedding-3-small` via API** *(chosen for MVP)*.
- **B. Local model (e.g. `intfloat/multilingual-e5-small`)** *(deferred
  — Fly.io 256 MB VM cannot host)*.

### Axis 4 — Stage-2 judge provider

- **A. Anthropic Claude Haiku via SDK** *(brief's initial preference)*.
  Bypasses EgressGuard because the SDK uses its own httpx client.
- **B. OpenAI `gpt-4o-mini` via the same EgressGuard path used for
  Stage 1** *(chosen)*. One egress vendor, two destinations under the
  same allowlist; EgressGuard's audit trail covers every external
  call.
- **C. Skip Stage 2 in MVP.** Embedding-only; threshold tuning data
  later motivates adding the judge.

### Axis 5 — Embedding input scope

- **A. User-initiated text only** *(chosen)*. Measures user intent;
  smallest data set leaves the box; aligns with the original ADR-0002
  intent.
- **B. User + assistant text.** Catches Claude-driven topic drift;
  doubles token count; sends Claude's output to the third-party
  embedding API.

### Axis 6 — Stage-2 storage shape on `scope_alerts`

- **A. Brief's minimal shape** — `max_similarity float, flagged bool`.
  Loses the Stage-2 verdict + reason + which chunk matched.
- **B. Expanded shape with four extra columns** *(chosen)* — `stage`,
  `stage2_verdict`, `stage2_reason`, `matched_chunk_id`. Lets the
  operator review false positives and tune thresholds from the alerts
  table directly.

### Axis 7 — Document chunking strategy

- **A. Fixed-size chunks.** Simple; splits mid-paragraph; loses
  semantic units.
- **B. Semantic chunking via sentence-similarity boundaries** *(chosen
  for `scope_documents`)*. Research plans have clear section
  structure; single-vector compression of the whole document would
  flatten sub-topic granularity.

### Axis 8 — Message-input shape at evaluation time

- **A. Single-vector embed of the constructed user input** *(chosen)*.
  Asymmetric vs. the chunked scope-document corpus — but messages are
  short (≤ 5 turns under default config) and a single vector is
  cheaper.
- **B. Chunk the message input too.** Higher fidelity; doubles
  per-request embedding cost; complicates the max-similarity query.

### Axis 9 — Scope-document registration UX

- **A. CLI script** *(chosen for MVP)* —
  `tools/process_scope_document.py <org_id> <file>`.
- **B. HTTP API + onboarding UI.** Deferred to Phase 3d.

## Decision

### D1 — Execution model: async monitoring via `on_persisted`

scope_guard binds `on_persisted` only — never `on_request_received` or
`before_forward`. The hook is observe-only (no `Pass`/`Block` return),
so the plugin's output is a row in `scope_alerts`, not a decision in
the request pipeline. Research-phase priority is data collection;
real-time blocking is Deferred §1.

This deliberately reframes ADR-0002's "synthetic SSE block on
out-of-scope" — that synthetic-block path no longer exists in this
ADR. Re-introducing it later means binding `on_request_received` and
returning `Block(reason=...)`, which is additive: the plugin contract
already supports it.

### D2 — Two-stage pipeline with stage boundaries pinned in env

Both stages classify the same `max_similarity` score against the
operator-tunable threshold:

```
similarity >= threshold + band/2      → "stage1_in"     (no alert)
similarity <= threshold - band/2      → "stage1_out"    (alert; no Stage 2)
otherwise                             → routes to Stage 2
```

Stage 2 calls the LLM judge with the constructed message input plus
the top-K (default K=3) most-similar scope chunks; the judge returns a
binary verdict (`in_scope` / `out_of_scope`) and a one-sentence
reason. Both are persisted on the same `scope_alerts` row.

Frequency of Stage-2 dispatch is *empirical* — brief's "10–20% of
requests" is a starting estimate, not a contract. Operator validates
against the first 30-day window before treating any number as a
constraint.

### D3 — Embedding provider: OpenAI `text-embedding-3-small` (MVP)

Vector dim 1536, token limit 8191. Egress through the
`HostEgressClient` (ADR-0015) to
`https://api.openai.com/v1/embeddings`. The plugin declares
`egress_http` capability and that destination in its manifest;
EgressGuard's audit trail covers every call.

Local model migration is Deferred §2 — interface is
`EmbeddingClient.embed(text) -> list[float]` so the swap is one
construction site.

### D4 — Stage-2 judge provider: OpenAI `gpt-4o-mini` via the same egress path

Brief's "Anthropic Claude Haiku via SDK, not egress_guard" is rejected
because the SDK's self-owned httpx client bypasses the audit trail
EgressGuard provides; the project has no other plugin doing that and
the precedent would weaken the security model. Switching to
`gpt-4o-mini` keeps a single egress vendor, two destinations under the
same allowlist:

```toml
egress_destinations = [
  "https://api.openai.com/v1/embeddings",
  "https://api.openai.com/v1/chat/completions",
]
```

Cost ballpark per request: `text-embedding-3-small` ≈ $0.02 / 1M
tokens; `gpt-4o-mini` ≈ $0.15 / 1M input + $0.60 / 1M output. At the
10–20% Stage-2-routing estimate the per-request marginal cost stays
below $0.001 for the modal exchange.

### D5 — Document chunking: semantic boundary detection

`scope_documents` are chunked once at registration time:

1. Sentence-segment the document (MVP: regex on `[.?!。？！]` +
   whitespace + capital / line-break heuristic; library swap to
   `blingfire` or `pysbd` queued under Deferred §6 if quality is
   insufficient).
2. Embed each sentence individually.
3. Walk adjacent-sentence cosine similarities; insert a chunk
   boundary where similarity drops below the rolling-mean baseline
   (specific algorithm TBD in implementation — Open question Q1).
4. Enforce chunk size bounds: **min 50 tokens, max 500 tokens**.
   Below-min chunks merge with the next neighbour; above-max chunks
   split on the longest gap.
5. Each chunk gets one embedding stored in `scope_chunks.embedding`.

Re-registration of the same `(org_id, title)` is **idempotent
delete-then-insert**: drop all existing `scope_chunks` for that
document row, regenerate. No versioning in MVP — operator gets the
behaviour of "re-run the CLI, get a fresh corpus."

Supported input formats for MVP: **plain text (`.txt`) and Markdown
(`.md`) only**. PDFs, DOCX, etc. queued under Deferred §3.

### D6 — Message-input construction: user-initiated text only

Per ADR-0026, scope_guard runs `on_persisted`, so `ctx.request_text()`
returns the *scrubbed* parsed messages array (ADR-0029) at L3
(scope_guard declares `min_content_level = "L3"`). The plugin
extracts:

1. **system-reminder content** from the first user turn's content
   blocks where the text starts with `<system-reminder>` or
   `<system>`. Extracted once; subsequent turns' system-reminders are
   skipped (typically identical Claude Code project context).
2. **User-initiated text** from user turns where any content block has
   `type="text"` and *does not* start with `<system-reminder>` or
   `<system>`. Turns whose user message contains only `tool_result`
   blocks are skipped — those represent Claude Code's internal
   tool-use cycles, not user intent.
3. **No assistant text.** This is a deliberate change from the brief.
   Rationale:
   - Measures user intent, not conversation drift (ADR-0002's
     original framing).
   - Halves embedding tokens.
   - Halves the data sent to the third-party embedding API — narrower
     external-disclosure surface for ADR-0029's
     `docs/deploy.md §"Data collection & privacy"` paragraph (see
     ADR-0030 §Consequences — Disclosure).
4. **Top-level Anthropic `system` field** is *excluded* — it carries
   the same Claude Code boilerplate every request and contributes no
   signal.
5. **Turn window**: most recent N user-initiated turns concatenated
   in time order (default N=5; configurable via
   `LLMTRACK_PLUGIN_SCOPE_GUARD_WINDOW`). Bounds the input within
   `text-embedding-3-small`'s 8191-token limit.
6. **Concatenation order**: time-ordered as the turns appear in
   `messages[]`, joined with `\n\n`.

The constructed string is a *single embedding input* — message input
is **not** chunked. Asymmetric vs. the chunked scope corpus, but
messages are short.

### D7 — Similarity calculation: max-cosine over org's chunks

At evaluation time:

```sql
SELECT id, 1 - (embedding <=> :msg_embedding) AS similarity
  FROM scope_chunks
 WHERE org_id = :org_id
 ORDER BY similarity DESC
 LIMIT 1
```

Use pgvector's `<=>` cosine distance operator. The plugin runs the
query under the same async engine pattern `analytics_sink` already
uses. Multiple `scope_documents` per org all contribute to the
candidate pool — `scope_chunks.org_id` does not distinguish documents
at query time. The matched chunk's `id` is persisted on the alert
row so the operator can attribute the score to a specific chunk
during threshold tuning.

### D8 — DB schema (Alembic migration `0010_scope_guard_tables`)

Four new tables. Index list pinned in the migration.

```sql
CREATE EXTENSION IF NOT EXISTS vector;  -- already present on Supabase

CREATE TABLE scope_documents (
  id          uuid PRIMARY KEY,
  org_id      uuid NOT NULL REFERENCES orgs(id),
  title       text NOT NULL,
  content     text NOT NULL,            -- original source for re-chunking
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, title)                -- idempotent re-registration key
);
CREATE INDEX idx_scope_documents_org ON scope_documents(org_id);

CREATE TABLE scope_chunks (
  id           uuid PRIMARY KEY,
  document_id  uuid NOT NULL REFERENCES scope_documents(id) ON DELETE CASCADE,
  org_id       uuid NOT NULL REFERENCES orgs(id),       -- denormalised
  chunk_index  int  NOT NULL,
  content      text NOT NULL,
  embedding    vector(1536) NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_scope_chunks_org      ON scope_chunks(org_id);
CREATE INDEX idx_scope_chunks_document ON scope_chunks(document_id);
-- Cosine-distance ANN index is deferred (small corpora — brute force
-- linear scan over a few hundred chunks per org outperforms HNSW
-- build cost at MVP scale). Queued under Open question Q2.

CREATE TABLE scope_alerts (
  id                uuid PRIMARY KEY,
  exchange_id       text NOT NULL,                          -- no FK; analytics_sink pattern
  org_id            uuid NOT NULL REFERENCES orgs(id),
  stage             text NOT NULL,                          -- "stage1_in" | "stage1_out" | "stage2_in" | "stage2_out"
  flagged           bool NOT NULL,                          -- true iff terminal verdict is out_of_scope
  max_similarity    float NOT NULL,
  matched_chunk_id  uuid NULL REFERENCES scope_chunks(id),  -- nullable: chunk may be deleted later
  stage2_verdict    text NULL,                              -- null iff Stage 2 did not run
  stage2_reason     text NULL,
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_scope_alerts_org     ON scope_alerts(org_id);
CREATE INDEX idx_scope_alerts_flagged ON scope_alerts(org_id, flagged) WHERE flagged;
CREATE INDEX idx_scope_alerts_created ON scope_alerts(created_at);
```

RLS policy:

- `scope_documents` and `scope_chunks` follow the `exchanges` RLS
  pattern (ADR-0018) — org-scoped row visibility via the
  `current_setting('app.org_id')` guard. The plugin reads these under
  the request-scoped session that already carries `org_id` from the
  AuthMiddleware.
- `scope_alerts` follows the `plugin_analytics` pattern — no RLS.
  Reads from operator tooling; writes from plugin code that knows the
  correct `org_id` from `ctx.org_id` (ADR-0026 SDK extension).

Retention (inheriting ADR-0029 §Axis 3):

- `scope_alerts` retained 6 months; the operator's `pg_cron` deletion
  job in migration `0009` gains a third matching row in a follow-up
  migration (or the existing migration is extended in a follow-up
  commit — Open question Q3 picks the cleanest path).
- `scope_documents` and `scope_chunks` retained **indefinitely** —
  they are operator-curated baseline content, not user-generated
  data. The operator deletes via `tools/delete_scope_document.py
  <org_id> <title>` (Deferred §5) or by `DELETE` SQL.

### D9 — Plugin packaging

```
packages/llm_tracker_plugin_scope_guard/
├── pyproject.toml
└── src/llm_tracker_plugin_scope_guard/
    ├── __init__.py
    ├── plugin.py
    ├── embeddings.py        # OpenAI EmbeddingClient
    ├── judge.py             # Stage-2 LLM judge
    ├── chunker.py           # semantic boundary detector
    ├── pipeline.py          # two-stage decision logic
    ├── storage.py           # scope_chunks read + scope_alerts write
    └── plugin.toml
```

`plugin.toml` shape:

```toml
name = "scope_guard"
version = "0.1.0"
description = "Server-side task-scope monitor. Async on_persisted: embed the user-initiated turns, compare against the org's scope_chunks, and record a per-exchange alert. Two-stage pipeline (embedding pre-filter; LLM judge on ambiguous band). Records alerts; never blocks. Settles ADR-0002 in reframed form."
hooks = ["on_persisted"]
capabilities = ["egress_http"]
egress_destinations = [
  "https://api.openai.com/v1/embeddings",
  "https://api.openai.com/v1/chat/completions",
]
allowed_modes = ["R"]   # documentation only — ADR-0019 retired runtime enforcement
min_content_level = "L3"
db_namespace = "scope_guard"
```

Env vars (prefix `LLMTRACK_PLUGIN_SCOPE_GUARD_*`):

| Var | Default | Meaning |
|---|---|---|
| `THRESHOLD` | `0.6` | Cosine-similarity decision boundary. |
| `AMBIGUOUS_BAND` | `0.1` | Width of the ambiguous zone routed to Stage 2. |
| `WINDOW` | `5` | Recent user-initiated turn count to embed. |
| `JUDGE_MODEL` | `gpt-4o-mini` | OpenAI Chat Completions model name. |
| `JUDGE_TOP_K` | `3` | How many top-similarity chunks accompany the judge prompt. |
| `OPENAI_API_KEY` | *(required)* | OpenAI API key for both stages. No silent fallback. |

The plugin gracefully no-ops if `OPENAI_API_KEY` is unset *or* the
org has zero `scope_chunks` rows — in either case `on_persisted`
returns without writing to `scope_alerts`. Audit log records the
no-op for visibility.

## Consequences

### What this enables

- The first plugin that performs real *judgement* on user content,
  not just observation (analytics_sink) or text-match (keyword_block).
- Operator-visible scope monitoring at zero per-request latency cost.
- A working baseline for the broader research goal (drift /
  scope-creep detection) once a 30-day alert corpus accumulates.
- Pgvector usage validated for the project — future similarity-based
  plugins reuse the same pattern.

### What it forecloses (until lifted by a follow-up ADR)

- **Real-time blocking** of out-of-scope requests. Reaches the user as
  a normal Claude Code response; only the alert row reflects
  scope_guard's view. ADR-0002's synthetic-SSE block is reframed away.
- **Cross-org pattern detection.** Each org's `scope_chunks` are
  isolated by RLS; no aggregate view in MVP.
- **Provider diversity.** OpenAI is the single egress vendor for both
  stages. A future ADR introducing Anthropic / local-model judges is
  additive (pipeline.py picks the client).

### Disclosure (binds to ADR-0029)

scope_guard introduces a new external-disclosure axis:
**user-initiated message text is embedded by OpenAI's
text-embedding-3-small, and ambiguous-band requests additionally
trigger a gpt-4o-mini call.** ADR-0029 §Axis 5
(`docs/deploy.md §"Data collection & privacy"`) currently only
discloses storage on the central server and `analytics_sink`'s
internal table. **Accepting this ADR obliges a follow-up commit that
extends that paragraph** with:

> When `scope_guard` is enabled, the most recent user-initiated turns
> from each exchange are sent to OpenAI's embedding API
> (`text-embedding-3-small`); ambiguous-band requests additionally
> trigger a `gpt-4o-mini` Chat Completions call. Assistant responses
> and tool-result contents are not sent. OpenAI's standard API ToS
> applies; the operator should configure
> [zero data retention](https://platform.openai.com/docs/guides/your-data)
> on the API key used.

The deploy.md edit lands as its own commit alongside the
implementation checkpoint, not in this ADR's commit.

### Reversibility

- **Pipeline shape (two-stage)**: High. `pipeline.py` could drop to
  embedding-only by skipping the judge branch; reversing back later
  is one PR.
- **Embedding provider**: High. `EmbeddingClient` is a one-method
  interface.
- **Async monitoring → synchronous block**: Medium. Adding
  `on_request_received` binding is additive; the plugin's existing
  `on_persisted` path stays untouched.
- **Schema additions**: Low — once `scope_alerts` accumulates rows,
  removing or renaming the four extra columns means a migration that
  copies-then-drops. Add them generously now.

## Open questions

These are explicitly *not* settled by this ADR and will surface in the
implementation session as `decision needed` checkpoints if they
become blocking.

- **Q1 — Semantic-boundary detection algorithm.** Decision §D5
  specifies "sentence-similarity drop below rolling-mean baseline"
  but does not pin the exact threshold or window size. The
  implementing session benchmarks two or three variants against a
  hand-curated corpus before locking in.
- **Q2 — pgvector ANN index.** MVP uses linear scan
  (`ORDER BY embedding <=> :v LIMIT 1`); HNSW / IVFFlat indexes
  trade build cost for query cost. Revisit when an org's chunk count
  exceeds ~10k.
- **Q3 — Retention job extension.** Whether to extend the existing
  `0009_retention_deletion_job` migration with a third `pg_cron` row
  for `scope_alerts`, or to add a new `0011_scope_alerts_retention`
  migration. Cleanest if the implementing session picks at impl
  time — both work.
- **Q4 — Stage-2 prompt template.** The exact wording sent to
  `gpt-4o-mini` (instructions, JSON-shape constraints, chunk
  injection format) is implementation-tier; pin a frozen template
  in `judge.py` as the source of truth so future tweaks are
  diff-visible.

## Deferred

Items intentionally left for later phases. Each becomes its own ADR
or follow-up checkpoint when prioritised:

1. **Real-time blocking mode.** Bind `on_request_received` and
   return `Block(reason=...)` when Stage 2 verdicts `out_of_scope`.
   Reframes scope_guard from monitor to gate. Requires threshold
   stability data (≥ 30 days of `scope_alerts`).
2. **Local embedding model.** Drop the OpenAI dependency by hosting
   `intfloat/multilingual-e5-small` or `BAAI/bge-m3` on the server.
   Requires a VM with ≥ 1 GB RAM headroom.
3. **Onboarding UI + API registration.** Replace
   `tools/process_scope_document.py` with an authenticated HTTP
   endpoint and an operator-facing form.
4. **Prompt-injection defense.** Mitigates the tool-result bypass
   noted under Known limitations §1. Requires a dedicated layer
   outside scope_guard's purview.
5. **Conversation-level alert aggregation.** Aggregate scope_alerts
   above `exchange_id` by grouping on `plugin_analytics.conversation_id`
   (added by ADR-0032 / Candidate-1 dedup, 2026-05-19). The earlier
   plan referenced a deferred `task_id` layer; that layer was closed
   2026-05-21 as won't-do — `conversation_id` covers the aggregation
   need without a new schema axis.
6. **Embedding cache for repeated user messages.** Dedup identical
   inputs at the embedding-API boundary; saves API calls on
   keyboard-bashing or replay traffic.
7. **Operator review dashboard.** A web view over
   `scope_alerts` so the operator triages flagged exchanges without
   raw SQL.

## Known limitations

1. **Prompt injection via `tool_results`.** If a user instructs Claude
   to read a file whose content directs Claude off-scope, that
   off-scope content arrives as `tool_result` and is excluded from
   scope_guard's evaluation by design (D6 §2). Full mitigation
   belongs to a separate prompt-injection defense layer (Deferred §4).
2. **First-turn detection is heuristic.** Distinguishing user-initiated
   turns from internal tool-use cycles depends on Claude Code's
   message-block shape — `text` blocks not starting with
   `<system-reminder>` mean "user typed something." If Claude Code
   changes its message format, this heuristic may break silently;
   the implementing session adds a metrics counter for "skipped due
   to heuristic" so silent breakage becomes operator-visible.
3. **Threshold tuning is empirical.** Default `THRESHOLD=0.6` /
   `AMBIGUOUS_BAND=0.1` are starting points. Operators **must
   review the first 100 `scope_alerts` rows manually** before
   treating `flagged=true` as a violation signal; a too-tight
   threshold floods the alert table, a too-loose threshold misses
   real drift. The plugin's research-phase priority (D1) is exactly
   the data collection that supports this tuning.
4. **OpenAI as single external vendor.** ADR-0030 ties scope_guard
   to OpenAI for both stages. The Open question Q4 about prompt
   template, and Deferred §2 about local models, are the two
   forward paths that diversify this dependency.

## Implementation surface (informational — not part of the ADR contract)

For the implementing session, the file touchpoints are:

- `packages/llm_tracker_plugin_scope_guard/` (new package, structure
  in D9).
- `packages/llm_tracker_server/alembic/versions/0010_scope_guard_tables.py`
  (new migration).
- `tools/process_scope_document.py` (new CLI; or
  `packages/llm_tracker_server/src/llm_tracker_server/cli/scope_document.py`
  if the implementing session prefers Typer subcommand parity with
  `llm-tracker-server tokens issue`).
- `pyproject.toml` (workspace root) — add new plugin package to
  `testpaths`.
- `.env.example` — add the six `LLMTRACK_PLUGIN_SCOPE_GUARD_*` vars
  under a new section.
- `docs/deploy.md` — extend the "Data collection & privacy"
  paragraph per §Consequences — Disclosure.
- `docs/plugins.md` — add `scope_guard` to §11 Reference plugins.
- Tests (per CLAUDE.md §7): unit tests for `chunker.py` boundary
  detection, `pipeline.py` stage-routing, `judge.py` prompt-shape;
  DB-fixture integration test for the full `on_persisted` path with
  a fake OpenAI client.
