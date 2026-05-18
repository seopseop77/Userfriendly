# 2026-05-18 · scope_guard plugin implementation (ADR-0030)

**Author**: Claude Code
**Session trigger**: User accepted ADR-0030 (Proposed → Accepted) and
asked Claude Code to plan + execute the implementation. User picked
Option A (`pgvector/pgvector:pg15` for the local test DB so ADR-0030
§D8's `CREATE EXTENSION vector` runs unconditionally — same as
Supabase) over Option B (gate the migration on `pg_available_extensions`
and skip locally).
**Related docs**: ADR-0030 (now Accepted), ADR-0017 (server pivot),
ADR-0018 (RLS), ADR-0026 (HookContext response accessors), ADR-0029
(consent + accessor scrubber), ADR-0015 (EgressClient SDK). Prior
worklog: `docs/worklog/2026-05-18-adr-0030-scope-guard.md` (ADR drafting).

## Interpretation

User asked: "Accept할게. 그럼 scope_guard 구현에 대한 계획을 짜고
실행할 수 있는거야?" then approved an 8-checkpoint plan and chose
Option A for the pgvector axis.

The ADR has 9 user-axes + 4 Cowork-axes all locked, so this is a
straight implementation session — no architectural decisions to make
beyond the four open questions ADR-0030 explicitly delegated to the
implementing session:

- **Q1** — chunker semantic-boundary algorithm. Picked at CP3 via
  small benchmark; pin in `chunker.py` with a comment.
- **Q2** — pgvector ANN index. ADR defers until org chunk count
  exceeds ~10k. MVP keeps linear scan; this session does not add an
  index.
- **Q3** — retention job split. Default this session picked: new
  `0011_scope_alerts_retention` migration mirroring 0009's
  `pg_cron` guard pattern, rather than amending 0009. Reason: each
  retention concern owns its own reversible migration; 0009 already
  has two cron rows and adding a third with a different table /
  column / time-unit shape muddies the downgrade.
- **Q4** — Stage-2 prompt template. Pinned as a frozen module-top
  string in `judge.py` at CP4; future tweaks become diff-visible.

Pre-flight sanity check (before CP1) found everything else in the
ADR matches the current codebase:

- `ctx.org_id` exists at `llm_tracker_sdk/hook_context.py:71` and is
  populated by the forwarder's `begin_exchange` from
  `request.state.org_id` (ADR-0026).
- `analytics_sink` is a 1:1 reference for the plugin shape:
  `on_init` builds an `AsyncEngine`, `on_persisted` inserts one
  row, `_engine_owned` flag controls dispose on `on_shutdown`.
- `HostEgressClient.fetch(url, *, method, headers, body, timeout)`
  returns `EgressResponse(status_code, headers, body)`; one client
  is constructed per loaded plugin at host-load time, baking in the
  plugin name. `self.egress` on `BasePlugin` is the access point.
- Workspace registration is glob-based (`[tool.uv.workspace]
  members = ["packages/*"]`); only `testpaths` needs a one-line
  edit when adding a new plugin package.
- Migration 0005 RLS pattern: `ENABLE` + `FORCE` RLS, two
  PERMISSIVE policies (`_org_isolation` + `_admin_access`) with
  `NULLIF(current_setting(...), '')::uuid` to handle Postgres GUC
  '' quirk. The plugin's tables follow this exactly for
  `scope_documents` + `scope_chunks`; `scope_alerts` follows the
  RLS-off `plugin_analytics` shape from migration 0007.

Local test DB was previously `postgres:15`; the same commit that
ships migration 0010 bumps STATUS.md §"Local dev loop revival" to
`pgvector/pgvector:pg15`.

## Checkpoint plan

| CP | Scope | Status |
|---|---|---|
| **CP1** | Migration `0010_scope_guard_tables` + STATUS.md docker image bump | **done** (commits `2511c3a` + `b6cdf5f`) |
| **CP2** | `packages/llm_tracker_plugin_scope_guard/` skeleton + manifest + workspace registration | **done** (commit `2fe84e6` + docs finalize) |
| **CP3** | `chunker.py` + unit tests; resolve Q1 | **done** (commit `44cd664` + docs finalize) |
| **CP4** | `embeddings.py` + `judge.py` via `HostEgressClient`; pin Q4 prompt | **done** (commit `80ca424` + this docs finalize) |
| **CP5** | `pipeline.py` + `storage.py` + `plugin.py`; DB-fixture integration test | **done** (commit `f0042f6` + this docs finalize) |
| **CP6** | operator CLI (`.txt` + `.md`, idempotent) — `process_scope_document.py` + console script | **done** (commit `c0c000f` + this docs finalize) |
| **CP7** | `.env.example` + `docs/deploy.md` §"Data collection & privacy" + `docs/plugins.md` §11 | **done** (commit `8e18892` + this docs finalize) |
| CP8 | `0011_scope_alerts_retention` migration (Q3 default: new migration, not amend 0009) | queued |

Each CP = 1 commit + worklog "What was done" append + STATUS.md
refresh (CLAUDE.md §5.3).

## What was done

### CP1 — migration 0010 + STATUS.md docker image (done; commit `2511c3a` server + docs finalize)

- Created `packages/llm_tracker_server/alembic/versions/0010_scope_guard_tables.py` (commit `2511c3a`):
  - `CREATE EXTENSION IF NOT EXISTS vector`.
  - Three tables (`scope_documents`, `scope_chunks`,
    `scope_alerts`) with column shapes from ADR-0030 §D8 verbatim,
    btree indexes per §D8, no pgvector ANN index (Q2 deferred).
  - RLS on `scope_documents` + `scope_chunks` (migration 0005
    pattern: ENABLE + FORCE + `_org_isolation` +
    `_admin_access`); no RLS on `scope_alerts` (migration 0007
    `plugin_analytics` pattern).
  - GRANT SELECT/INSERT/UPDATE/DELETE on all three tables to
    `llm_tracker_app`.
  - Reversible downgrade in reverse order. `vector` extension is
    left in place (same blast-radius reasoning as 0009 keeps
    `pg_cron`).
- Modified `docs/STATUS.md` — "Local dev loop revival" §:
  `postgres:15` → `pgvector/pgvector:pg15`, with a comment
  explaining why (migration 0010 requires the extension; vanilla
  image fails `alembic upgrade head` in `conftest.py`).
- Modified `docs/decisions/0030-scope-guard-plugin.md`:
  Status `Proposed` → `Accepted` with the user's acceptance date
  + pgvector Option A pre-decision noted.

### CP2 — scope_guard package skeleton + manifest (done; commit `2fe84e6` + this docs finalize)

- Created `packages/llm_tracker_plugin_scope_guard/pyproject.toml`
  (commit `2fe84e6`):
  - Hatchling build target, entry point `scope_guard` →
    `llm_tracker_plugin_scope_guard.plugin:ScopeGuard`.
  - Deps: `llm-tracker-sdk` (workspace), `sqlalchemy[asyncio]`,
    `asyncpg`, `pgvector>=0.2`, `python-ulid`, `structlog`. Matches
    the `analytics_sink` reference for the SQLAlchemy / asyncpg /
    ulid / structlog set; `pgvector` is new for the
    `vector(1536)` column adapter.
- Created
  `packages/llm_tracker_plugin_scope_guard/src/llm_tracker_plugin_scope_guard/plugin.toml`
  per ADR-0030 §D9 verbatim: `hooks = ["on_persisted"]`,
  `capabilities = ["egress_http"]`, `egress_destinations` for both
  OpenAI endpoints, `allowed_modes = ["R"]`,
  `min_content_level = "L3"`, `db_namespace = "scope_guard"`.
- Created `__init__.py` exporting `ScopeGuard`; `plugin.py` with
  the `ScopeGuard(BasePlugin)` skeleton (`on_persisted` no-op so
  the host's load + audit path can be exercised before the
  pipeline lands).
- Created five module stubs (`chunker.py`, `embeddings.py`,
  `judge.py`, `pipeline.py`, `storage.py`), each with a docstring
  pointing to the CP that fills it in (CP3..CP6).
- Modified `uv.lock` — `pgvector==0.4.2` + transitive `numpy==2.4.5`
  installed alongside the new workspace package.

### CP3 — chunker.py + Q1 parameters pinned (done; commit `44cd664` + this docs finalize)

- Replaced
  `packages/llm_tracker_plugin_scope_guard/src/llm_tracker_plugin_scope_guard/chunker.py`
  (commit `44cd664`) with the full ADR-0030 §D5 implementation:
  - `_segment_sentences` — paragraph-split on blank lines
    (`\n{2,}`), then sentence-split on terminal punctuation
    (Latin `.?!` + CJK `。？！`) followed by whitespace and an
    opener class (Latin capital, ASCII `"` / `(`, curly left
    double / single quote, or any CJK ideograph / Hangul
    syllable). Library swap to `blingfire` / `pysbd` queued
    under ADR-0030 §Deferred §6.
  - `_detect_boundaries` — walks adjacent-sentence cosine
    similarities. Flags sentence `i+1` as a boundary when
    `similarities[i] < rolling_mean(prev WINDOW sims) - DROP`.
    Window-size warm-up: the first WINDOW similarities cannot
    themselves trigger a boundary.
  - `_enforce_size_bounds` — two passes. Pass 1 merges
    below-min chunks into the next neighbour (or previous, if
    last). Pass 2 splits above-max chunks on the lowest internal
    adjacent similarity, recursively, until every chunk is at or
    below the max bound.
  - `chunk_document(text, embed)` — orchestrates the above.
    `embed` is dependency-injected (CP4 wires it to the real
    OpenAI client). Each final chunk is **re-embedded** as one
    string so the returned vector matches the chunk's stored
    `scope_chunks.content` column exactly (not a sentence
    average — explicit contract pinned by the
    `embedding_is_chunk_content_not_sentence_average` test).
- Pinned **ADR-0030 §Q1** to `_BOUNDARY_WINDOW = 3`,
  `_BOUNDARY_DROP_THRESHOLD = 0.15`. Module docstring carries
  the benchmark vs. `window=5` (under-splits short docs) and
  `drop=0.10` (over-splits on smooth prose).
- Created
  `packages/llm_tracker_plugin_scope_guard/tests/test_chunker.py`
  (22 tests). Coverage:
  - Sentence segmenter: simple Latin punctuation, paragraph
    breaks, CJK terminator, empty input.
  - Cosine helper: orthogonal / parallel / zero-norm guard.
  - `chunk_document` empty input / single-sentence / 3-topic
    boundary recovery / per-chunk re-embedding contract.
  - `_detect_boundaries` warm-up quiet behaviour, short-input
    guard.
  - **Q1 benchmark** — chosen tuple recovers the 3-topic
    fixture boundaries `[5, 10]` and stays quiet on the smooth
    prose fixture; `window=5` misses sentence-5 boundary;
    `drop=0.10` fires a false positive on the same fixture.
  - `_enforce_size_bounds` — below-min merge with neighbour,
    below-min-with-no-neighbour kept as-is, above-max split on
    lowest seam, recursive split for very long chunks,
    single-oversized-sentence kept as-is (cannot split a single
    sentence).
  - `ChunkRecord` NamedTuple contract.
- Modified root `pyproject.toml` — added
  `packages/llm_tracker_plugin_scope_guard/tests` to `testpaths`.
  Initially also added a `tests/__init__.py` but removed it
  after `pytest` collection conflicted with the other plugin
  packages' top-level `tests` namespace
  (`ModuleNotFoundError: No module named 'tests.test_chunker'`);
  the other plugin packages don't ship a `tests/__init__.py`,
  so this package matches.

### CP4 — embeddings.py + judge.py + Q4 prompt pinned (done; commit `80ca424` + this docs finalize)

- Replaced `embeddings.py` with the `EmbeddingClient` per ADR-0030 §D3
  (commit `80ca424`):
  - Constructor takes `api_key`, `egress: EgressClient`, optional
    `timeout`. The `egress` is injected (host populates
    `self.egress` at plugin load time per ADR-0015) so unit tests
    substitute a stub without touching the network.
  - `async embed(text) -> list[float]` posts to
    `https://api.openai.com/v1/embeddings` with model
    `text-embedding-3-small`; bearer-token auth.
  - Raises `EmbeddingError` on non-2xx, malformed body, or vector
    dim ≠ 1536 (catches model swap / API drift before the bad row
    reaches storage). `EgressDenied` from the guard is allowed to
    propagate so the plugin can log + skip in-band.
- Replaced `judge.py` with the `JudgeClient` per ADR-0030 §D4 + §Q4
  (commit `80ca424`):
  - **ADR-0030 §Q4 pinned** — `_SYSTEM_PROMPT` and
    `_USER_PROMPT_TEMPLATE` are module-top frozen strings. The
    system prompt instructs `gpt-4o-mini` to emit strict JSON
    `{"verdict": "in_scope" | "out_of_scope", "reason": "<one sentence>"}`.
    `response_format = {"type": "json_object"}` + `temperature = 0.0`
    on the request side reinforce the contract. The user prompt
    numbers the supplied chunks and wraps the message text with
    `<<<` / `>>>` sentinels.
  - `async judge(message_text, chunks) -> tuple[Verdict, str]`
    posts to `https://api.openai.com/v1/chat/completions`. 2xx +
    malformed JSON (missing field, unknown verdict literal, non-JSON
    content) falls back to
    `("in_scope", "stage2_malformed_response")` rather than crashing
    — ADR-0030 §D1 is observe-only, so recording a degraded alert
    beats taking the host down.
  - Non-2xx responses raise `JudgeError`; `EgressDenied` propagates.
- Created `tests/test_embeddings.py` (7 tests). Pins URL / model /
  bearer / body shape; covers dim mismatch, malformed payload,
  non-2xx, `EgressDenied`, and timeout pass-through via a stub
  `EgressClient` that records every call.
- Created `tests/test_judge.py` (11 tests). Coverage:
  - **Q4 freeze test** — asserts six sentinel substrings in
    `_SYSTEM_PROMPT` (scope-monitoring judge / strict JSON only /
    verdict literals / `"reason":` / in_scope-when / out_of_scope-when).
    Future tweaks to the wording must bump this test, making them
    diff-visible.
  - Request shape — model `gpt-4o-mini`, `response_format`
    `json_object`, temperature 0.0, system content equals the
    frozen string, user content embeds the message and the
    numbered chunks.
  - Happy-path verdict + reason round-trip.
  - Empty-chunks branch ("(no scope chunks supplied)" sentinel).
  - Whitespace-tolerant content parse (leading / trailing
    whitespace around the JSON object).
  - Malformed-JSON content fallback.
  - Out-of-vocab verdict fallback (rejects `"maybe"` so
    `scope_alerts.verdict` only stores known literals).
  - Missing-`choices` field fallback (transport returned 2xx, body
    not OpenAI-shaped — log a degraded alert, don't raise).
  - Non-2xx → `JudgeError`.
  - `EgressDenied` propagation.

### CP5 — pipeline.py + storage.py + plugin.py wired end-to-end (done; commit `f0042f6` + this docs finalize)

- Replaced
  `packages/llm_tracker_plugin_scope_guard/src/llm_tracker_plugin_scope_guard/pipeline.py`
  with the pure two-stage routing function
  `evaluate(message_text, *, embed, judge, max_cosine_lookup, thresholds)`.
  Module exports `Thresholds(threshold=0.6, band=0.1, judge_top_k=3)`,
  `ChunkCandidate(id, content, similarity)`, and
  `ScopeEvaluation(stage, flagged, max_similarity, matched_chunk_id,
  stage2_verdict, stage2_reason)`. Stage routing per ADR-0030 §D2:
  `>= threshold + band/2` → `stage1_in` / `flagged=False`;
  `<= threshold - band/2` → `stage1_out` / `flagged=True`; in-band
  → judge call → `stage2_in` / `stage2_out` mirroring the verdict
  literal. Empty candidate list → `None` (caller treats as "no
  corpus, no alert" per ADR-0030 §D9).
- Replaced
  `packages/llm_tracker_plugin_scope_guard/src/llm_tracker_plugin_scope_guard/storage.py`
  with the pgvector read + insert helpers:
  - `select_top_chunks_by_cosine(session_factory, *, org_id, vector, k)`
    issues `SELECT set_config('app.org_id', :v, true)` on the same
    session then runs the ADR-0030 §D7 query
    (`ORDER BY embedding <=> CAST(:vec AS vector) ASC LIMIT :k`,
    similarity reported as `1 - distance`). Filters explicitly by
    `org_id = :org_id` so the WHERE clause is correct even when the
    session bypasses RLS (e.g. a local superuser DB).
  - `insert_alert(session_factory, *, exchange_id, org_id, stage, ...)`
    INSERTs one `scope_alerts` row with `id = ULID().to_uuid()` for
    time-ordered primary keys. Calls `session.commit()` because the
    RLS-off table is fine to write under any role.
  - `_vector_literal(vec)` renders the pgvector text literal
    (`[v1,v2,...]`) with `.18g` formatting for lossless float
    round-trip. `SessionFactory` is the `Protocol` that both the
    plain `async_sessionmaker` and the conftest role-wrapped factory
    satisfy — same call signature, same yield type.
- Replaced
  `packages/llm_tracker_plugin_scope_guard/src/llm_tracker_plugin_scope_guard/plugin.py`
  with the full `ScopeGuard(BasePlugin)` wiring:
  - Constructor accepts `session_factory`, `embed_client`,
    `judge_client`, `thresholds`, `window` — any non-`None` value
    pre-seeds the field; `on_init` fills in remaining `None` fields
    from env (`OPENAI_API_KEY`, `LLMTRACK_DATABASE_URL`, the four
    `LLMTRACK_PLUGIN_SCOPE_GUARD_*` knobs). Tests pre-inject
    everything; production wires through `on_init`.
  - `on_init` fail-closed posture per ADR-0030 §D9 — missing API
    key, missing `self.egress`, or missing `LLMTRACK_DATABASE_URL`
    → `structlog.warning("scope_guard.disabled", ...)` + the plugin
    no-ops on subsequent `on_persisted` calls. ADR-0030 §D1 is
    observe-only so "do nothing" is the right degraded state.
  - `on_persisted` builds the message text per ADR-0030 §D6 via the
    module-level `_build_message_text(request_json, window)` helper
    (first-turn `<system-reminder>` / `<system>` block captured
    once; user-initiated text from every user turn whose blocks are
    not entirely `tool_result`; assistant text + top-level `system`
    field excluded; most recent `window` user turns retained,
    joined with `\n\n`). Then calls `pipeline.evaluate(...)` and on
    a non-`None` result calls `storage.insert_alert(...)`. OpenAI
    failures (`EmbeddingError` / `JudgeError` / `EgressDenied`)
    degrade to "no alert this exchange" — never re-raise.
  - `on_shutdown` disposes the engine iff `on_init` constructed it
    (matches `analytics_sink`'s `_engine_owned` flag).
- Added 26 new tests across three files:
  - `tests/test_pipeline.py` (8 tests) — pure-function routing:
    empty corpus → `None`; high similarity → `stage1_in` and judge
    not called; low similarity → `stage1_out` and judge not called;
    clean-threshold boundary check (`0.5 / 0.2` pair so IEEE-754
    edge math is unambiguous); ambiguous → `stage2_in` and
    `stage2_out`; `judge_top_k` plumbed through to the lookup
    callable.
  - `tests/test_plugin.py` (13 tests) — §D6 extraction + disabled
    paths: single-turn extraction; assistant text excluded; first-turn
    `<system-reminder>` captured (and only once); `<system>` tag
    variant; `tool_result`-only turn skipped; top-level `system` field
    excluded; window truncation (`window=2` retains the last two
    user turns); first-turn `<system-reminder>` survives even when
    the first turn falls outside the window; no-user-text → `None`;
    malformed JSON → `None`; missing `messages` key → `None`. Plus
    three disabled-path tests: no `OPENAI_API_KEY` → `_ready()=False`
    and `on_persisted` no-ops; missing `egress` → disabled; missing
    `LLMTRACK_DATABASE_URL` → disabled.
  - `tests/test_integration.py` (5 tests, DB-fixture-gated) — full
    `on_persisted` against pgvector: high similarity (1.0) →
    `stage1_in` row with correct `matched_chunk_id`; low similarity
    (0.0 — orthogonal unit vectors) → `stage1_out`; ambiguous (0.6
    similarity via a `[0.6, 0.8, 0, ...]` two-axis vector) → judge
    called with the top-K chunk content and verdict + reason
    persisted; RLS isolation — two orgs seed identical chunks at
    the same embedding, org A's evaluation matches org A's chunk
    and org B's matches org B's; org with zero chunks → no alert
    row written.
- Added `packages/llm_tracker_plugin_scope_guard/tests/conftest.py`
  — a copy-adapted version of the server's session_factory fixture
  with `SERVER_ROOT` pointed at the workspace's
  `packages/llm_tracker_server` so the alembic subprocess runs in
  the right cwd. Identical role-wrap pattern
  (`SET LOCAL ROLE llm_tracker_app`) so docker-default superuser
  doesn't bypass RLS in the local test loop.

Verified end to end:

```
$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_plugin_scope_guard/
All checks passed!
$ .venv/bin/python3.12 -m ruff format --check packages/llm_tracker_plugin_scope_guard/
14 files already formatted
$ LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test \
    .venv/bin/python3.12 -m pytest packages/llm_tracker_plugin_scope_guard/tests -q
66 passed in 5.81s
$ LLMTRACK_TEST_DATABASE_URL=... .venv/bin/python3.12 -m pytest -q
230 passed in 31.53s
```

The 230 figure is +44 over CP4's 186 — 26 new scope_guard tests plus
the 18 DB-fixture-gated server tests that the test DB unblocks (no
behaviour change there, only the gate). Scope_guard alone goes
40 → 66 tests.

Implementation notes worth carrying forward (so CP6 / CP7 / CP8
don't re-derive):

- **`HookContext` ceiling in tests.** Constructing a `HookContext`
  with `mode="R"` defaults to `user_opted_in=False`, which makes
  `request_text()` return `None` (effective ceiling drops below
  L2). The integration test ctx helper passes
  `user_opted_in=True`; the analytics_sink test pattern was the
  precedent. In production the host pins `_ceiling=L3` from the
  manifest's `min_content_level="L3"`, so this only bites tests
  that build their own ctx.
- **Pgvector text-literal codec.** Storage renders vectors as
  `[v1,v2,...]` and binds via `CAST(:vec AS vector)` so neither
  `pgvector.asyncpg` nor `pgvector.sqlalchemy` needs to register a
  codec at engine-creation time. The SELECT only returns floats
  (`1 - distance`), never the raw vector — no codec needed on
  reads either.
- **`session_factory` vs `engine` injection.** Storage helpers
  take a `SessionFactory` Protocol (zero-arg callable returning an
  async ctx-manager yielding `AsyncSession`) instead of an
  `AsyncEngine`. That shape is what both
  `async_sessionmaker(engine)` and the conftest fixture's
  role-wrapper expose — the production wiring and the test
  wiring drop in without a translation layer at the storage
  boundary.
- **Boundary tests use a binary-clean threshold pair.** The
  default `threshold=0.6, band=0.1` gives a lower bound of
  `0.5499999999999999` in IEEE-754, so a similarity of exactly
  `0.55` lands inside the band. The boundary test uses
  `threshold=0.5, band=0.2` (lower=0.4, upper=0.6 — both exact)
  to pin the `>=` / `<=` inequality direction unambiguously. The
  high-similarity / low-similarity tests use clean margins so
  they don't depend on the boundary edge at all.
- **Stage1_in writes a row (not "no alert").** ADR-0030 §D2's
  parenthetical "(no alert)" reads ambiguously against §D8's
  "one row per `on_persisted` evaluation" docstring + the
  partial index `WHERE flagged`. We picked "always write a row,
  `flagged` is True iff terminal verdict is `out_of_scope`" so
  the operator gets the full similarity distribution for
  threshold tuning (the research-phase priority §D1 names) and
  the partial index does its actual job of separating cold rows
  from hot. Implementation-tier decision; ADR not changed.

### CP6 — process_scope_document CLI (done; commit `c0c000f` + this docs finalize)

- Created
  `packages/llm_tracker_plugin_scope_guard/src/llm_tracker_plugin_scope_guard/process_scope_document.py`
  with two surfaces:
  - **Library** `register_document(session_factory, embed_client, *,
    org_id, title, text) -> (document_id, chunk_count)` — pure async
    function that does the chunk-and-store. Imported by the
    integration test; the CLI's `main()` is a thin wrapper.
  - **CLI** `main()` / `_amain()` — argparse over `org_id` (UUID),
    `file` (Path), `--title` (default = file stem). Validates the
    UUID + file existence + suffix in `_validate_args` (raises
    `SystemExit` so the operator sees a clean message); refuses to
    run when `OPENAI_API_KEY` or `LLMTRACK_DATABASE_URL` is unset
    (exit 2 — mirrors plugin's `on_init` fail-closed).
- Async port of `chunker.chunk_document` inlined as
  `_chunk_document_async`: reuses the chunker's pure helpers
  (`_segment_sentences`, `_detect_boundaries`, `_group_into_chunks`,
  `_enforce_size_bounds`, `_cosine`) and awaits the OpenAI embedding
  call one sentence at a time. Sequential is acceptable for a
  one-shot operator script and avoids a churn on chunker's sync
  embed contract (which has its own 22-test suite).
- Idempotent re-registration shape: `DELETE FROM scope_documents
  WHERE org_id = :o AND title = :t` runs first inside the same
  session — the migration-0010 FK `ON DELETE CASCADE` on
  `scope_chunks.document_id` drops the prior chunks in the same
  statement. Then `INSERT scope_documents` with a fresh
  `ULID().to_uuid()` PK, then `INSERT scope_chunks` per record.
  Single commit at the end so a mid-run failure leaves no partial
  document in place.
- New `_ToolEgressClient(EgressClient)` adapter — standalone httpx
  wrapper that conforms to the SDK's `EgressClient` Protocol but
  skips the audit-log mediation `HostEgressClient` performs.
  Safe because the script runs out-of-host (no `PluginHost`, no
  audit log) and the only egress destination is OpenAI's
  embeddings endpoint, which is the same allowlisted URL the
  plugin uses.
- Registered as a console script in `pyproject.toml` so
  `process-scope-document <org_id> <file>` works after `uv sync`;
  `python -m llm_tracker_plugin_scope_guard.process_scope_document
  ...` is the fallback for environments where `.venv/bin/` isn't
  on PATH. Added `httpx>=0.27` as a direct dep (the runtime
  plugin path gets httpx through the host; the CLI doesn't).
- 9 new tests in `tests/test_process_scope_document.py`:
  - 6 arg-validation (no DB needed): non-UUID `org_id`, missing
    file, unsupported suffix, default-title-is-stem, explicit
    `--title` wins, `.md` accepted.
  - 3 DB-fixture (gated on `LLMTRACK_TEST_DATABASE_URL`):
    re-registration drops to 1 doc + round-2 chunks only (the
    ADR-mandated idempotency contract); chunk_index runs
    contiguously 0..N-1 with the right `org_id`/`document_id`;
    two distinct titles under the same org → two doc rows (no
    collapse).
- Smoke-tested both invocation paths after `uv sync`:
  `.venv/bin/process-scope-document --help` and
  `.venv/bin/python3.12 -m llm_tracker_plugin_scope_guard.process_scope_document --help`
  both render the same argparse help.

Verified end to end:

```
$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_plugin_scope_guard/
All checks passed!
$ .venv/bin/python3.12 -m ruff format --check packages/llm_tracker_plugin_scope_guard/
16 files already formatted
$ LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test \
    .venv/bin/python3.12 -m pytest packages/llm_tracker_plugin_scope_guard/tests/test_process_scope_document.py -q
9 passed in 3.61s
$ LLMTRACK_TEST_DATABASE_URL=... .venv/bin/python3.12 -m pytest -q
239 passed in 35.62s
```

239 is +9 over CP5's 230 — exactly the CP6 test additions. Scope_guard
package suite now 66 → 75 tests.

Implementation notes worth carrying forward to CP7 / CP8:

- **CLI lives in-package, not under top-level `tools/`.** ADR-0030
  "Implementation surface" suggested either a `tools/` script or a
  Typer subcommand under the server CLI. Both have downsides: a
  top-level `tools/` dir would carry one file; a server CLI
  subcommand creates a server → plugin import dependency that
  reverses the architecture (plugins depend on server/sdk, not
  vice versa). Putting the module inside the plugin package + a
  console-script entry-point sidesteps both — gives both
  `process-scope-document ...` and `python -m
  llm_tracker_plugin_scope_guard.process_scope_document ...` for
  free, keeps the testable library next to its DB-fixture test,
  and the operator's deploy artifact is whatever `uv sync`
  produces. Documented in the module docstring + this worklog so a
  future "why isn't there a tools/ dir" doesn't have to re-derive.
- **`_chunk_document_async` mirrors `chunker.chunk_document` but
  awaits.** Two embed call sites stay sequential (per sentence →
  similarity baseline + per final chunk). Batching would require a
  rewrite of the algorithm — boundary detection needs sentence
  vectors before similarities, and chunk vectors after size
  enforcement. The N+M serial round-trips are fine for an
  operator one-shot; if registration time becomes a UX issue,
  batching the *sentence* embeds is the cheaper half (single
  batched call replaces N round-trips).
- **`ON DELETE CASCADE` does the cleanup.** Migration 0010 set
  `scope_chunks.document_id REFERENCES scope_documents(id) ON
  DELETE CASCADE`, so `DELETE FROM scope_documents WHERE org_id
  = :o AND title = :t` is sufficient — no explicit
  `DELETE FROM scope_chunks` needed first. The CP6 idempotency
  test covers this implicitly (chunk count after re-registration
  matches round 2, not 1+2).
- **`_ToolEgressClient` skips the audit log on purpose.** The
  plugin's `HostEgressClient` writes one `egress_blocked` /
  `egress_allowed` row per fetch through `EgressGuard.check(...)`.
  The CLI runs locally outside the host, so there's no audit
  table to write to. Documented in the class docstring so a
  future "why isn't this audited" doesn't have to re-derive.

### CP7 — disclosure + env knobs + plugins.md entry (done; commit `8e18892` + this docs finalize)

Docs-only commit landing the three operator-facing surfaces
ADR-0030 §Consequences — Disclosure obliged us to update:

- Modified `.env.example`: new
  `# -- scope_guard plugin (ADR-0030)` section between the
  Local PG test loop and the Per-request headers info-block.
  Lists `OPENAI_API_KEY` (with the "needed when the plugin is
  enabled" framing — not a hard "required", since the plugin's
  `on_init` already fail-closes when the key is missing) and
  the five `LLMTRACK_PLUGIN_SCOPE_GUARD_*` knobs: `THRESHOLD`
  (default 0.6), `AMBIGUOUS_BAND` (0.1), `WINDOW` (5),
  `JUDGE_MODEL` (`gpt-4o-mini`), `JUDGE_TOP_K` (3). Each
  variable carries an ADR-section pointer + behaviour note so
  the operator doesn't need to flip to the ADR to understand
  the knob.
- Modified `docs/deploy.md` §"Data collection & privacy":
  appended one new bullet to the existing Privacy posture list
  carrying the ADR-0030 §Consequences — Disclosure paragraph
  verbatim ("the most recent user-initiated turns from each
  exchange are sent to OpenAI's embedding API
  (`text-embedding-3-small`); ambiguous-band requests
  additionally trigger a `gpt-4o-mini` Chat Completions
  call.…"), plus a closing sentence pointing the operator to
  the `process-scope-document` CLI for the per-org corpus that
  scope_alerts are scored against. Extended the
  `LLMTRACK_PLUGINS_DISABLED` bullet so it names both
  `analytics_sink` and `scope_guard` as valid off-switch
  targets (comma-separate for both).
- Modified `docs/plugins.md` §11 Reference plugins:
  - Updated the scope_guard table row's Purpose column from
    "Task-scope enforcement (Phase 1c)" to the post-impl
    shape: "Server-side scope monitor on `on_persisted`
    (ADR-0030, Phase 1c). Two-stage embedding + judge
    pipeline; observe-only; writes `public.scope_alerts`."
  - Added a new paragraph after the install-via-git-URL
    snippet covering the `process-scope-document` CLI — both
    invocations (`process-scope-document <org_id> <file.md>`
    and the `python -m` fallback), accepted formats (`.txt` +
    `.md`), idempotency contract, and the env requirements
    (`OPENAI_API_KEY` + `LLMTRACK_DATABASE_URL`).

Verified end to end: docs-only; no code paths touched, no
test changes. `git diff --stat` shows 71 lines added / 2 lines
removed across the three files (the only deletion is the
short scope_guard row in plugins.md being expanded inline).

Implementation notes worth carrying forward to CP8:

- **`docs/plugins.md` §11 table drift surfaced.** The Reference
  plugins table lists `llm-tracker-plugin-supabase-sink` but
  the package directory was removed in 2026-05-17 (commit
  `8ef166d`'s sidecar archive). The table also doesn't list
  `analytics_sink`, `keyword_block`, or `token_counter`, all of
  which exist as workspace packages. CP7 didn't fix this —
  scoped to scope_guard per CLAUDE.md §2.3. Flagged in
  §Suggestions below for a future docs sweep.
- **Disclosure-paragraph wording is pinned in ADR-0030.** The
  bullet in `docs/deploy.md` matches the ADR-0030
  §Consequences — Disclosure block verbatim plus the
  closing CLI pointer. If the ADR wording ever changes,
  `docs/deploy.md` follows in the same PR — the canonical
  source is the ADR, the deploy doc is the operator-facing
  surface.
- **`LLMTRACK_PLUGINS_DISABLED` is the unified off-switch for
  both plugins.** Comma-separated CSV semantics (the host's
  plugin-host already parses it this way for analytics_sink).
  Documented in the extended deploy.md bullet so the operator
  can disable scope_guard standalone, analytics_sink
  standalone, or both.

## Decisions

- **Q3 default — new `0011_scope_alerts_retention` migration,
  not amend 0009.** Reason: each retention concern owns its own
  reversible migration; mixing a third cron row with different
  table/column/unit shape into 0009 muddies the downgrade. Not
  high-stakes either way — easy to reverse.
- **pgvector — Option A (image bump) over Option B (extension
  guard).** Reason: ADR-0030 §D8 explicitly assumes the extension
  is present ("already present on Supabase"). The 0009 guard
  precedent applies to `pg_cron` (operational-only) but does not
  carry over to `vector` (plugin-core data type). Surfaced this as
  a user-facing decision; user picked Option A.
- **No ANN index in MVP (Q2).** ADR-0030 defers until any org's
  chunk count exceeds ~10k. btree indexes on `org_id` +
  `document_id` cover the basic paths; the cosine-distance
  `ORDER BY` does a linear scan within an org's chunks.
- **CP2 deps: `pgvector>=0.2` added; `numpy` arrives transitively.**
  `pgvector` is the SQLAlchemy / asyncpg adapter for the
  `vector(1536)` column — required for CP5's `scope_chunks` write
  + max-cosine query path. `numpy` is a pgvector transitive that
  CP3's chunker can reuse for adjacent-sentence cosine
  similarity (avoids re-implementing the math in pure Python).
  `httpx` is intentionally **not** a direct dep — CP4 reaches
  OpenAI via `HostEgressClient`, which the host injects on
  `self.egress`. ADR-0030 §D3/§D4 are silent on Python packages;
  these are implementation-tier choices.
- **Q1 pinned — `window=3`, `drop=0.15`.** Rolling-mean cosine
  drop algorithm chosen over percentile-based (Greg Kamradt
  style) and absolute-threshold variants — rolling-mean is
  scale-robust to the embedding model's baseline cosine
  distribution and works on short documents without needing a
  global distance histogram. Benchmarked three candidate tuples
  on synthetic fixtures: chosen tuple recovers all expected
  boundaries on a 3-topic 15-sentence corpus while staying quiet
  on a smooth-prose fixture with a single ~0.16 dip;
  `window=5, drop=0.15` swallows the first boundary into its
  warm-up region; `window=3, drop=0.10` over-fires on the
  smooth-prose dip. The benchmark lives in the test module so
  regressions on the picked parameters are CI-caught.
- **Token count = whitespace word count.** ADR-0030 §D5 §4 says
  "min 50 / max 500 tokens" without pinning the tokenizer.
  Whitespace-split is cheap, predictable, and avoids pulling
  `tiktoken` as a direct dep just to enforce a soft size bound.
  English token : word ratio is ~1.3 : 1 so the bounds map to
  ~65 / ~650 actual tokens — comfortably inside the 8191-token
  embedding-input ceiling. CJK-heavy corpora may want to retune
  at follow-up time (acknowledged in module comment); not
  blocking MVP.
- **Per-chunk re-embedding over sentence-vector averaging.**
  ADR-0030 §D5 §5 says "each chunk gets one embedding stored in
  `scope_chunks.embedding`". The chunker re-embeds the
  concatenated chunk string so the stored vector represents the
  string that goes into `content` — averaging the per-sentence
  vectors would drift from that (especially under the
  topic-tagged stub embedder used in tests). Costs one extra
  embed call per chunk at registration time; chunks are written
  once and queried many times, so the cost is amortised
  immediately.
- **`tests/__init__.py` not shipped.** pytest's rootdir-based
  collection treats every `tests/` directory as a top-level
  package named `tests`. With an `__init__.py` present, all
  packages' `tests/` collide on the same module name and only
  one gets collected. Mirrors the analytics_sink / keyword_block
  / token_counter pattern — none of them ship a `tests/__init__.py`
  either.
- **Q4 pinned — frozen module-top prompt string + `json_object`
  response format.** Two layers reinforce the contract: (a) the
  system prompt's first sentence instructs strict-JSON output with
  the exact shape; (b) the request carries
  `response_format = {"type": "json_object"}` + `temperature = 0.0`
  so the OpenAI API itself rejects free-form text. The prompt's
  exact wording is asserted in `test_q4_prompt_template_is_frozen`
  (six sentinel substrings) so future edits are diff-visible in
  review — ADR-0030 §Q4 commits the implementation to "pinned as a
  module-top frozen string" and the test pins what "frozen" means.
- **Malformed-JSON fallback over raising in `JudgeClient`.**
  ADR-0030 §D1 is observe-only — the plugin's job is to record an
  alert. A 2xx response with the body shape OpenAI documents but
  with a malformed `content` field (e.g. wrong verdict literal,
  non-JSON content) is recoverable: store
  `verdict="in_scope"` + `reason="stage2_malformed_response"` so
  operators see the degradation in the alerts table. The opposite
  choice — raise — would skip the alert row entirely, which is
  worse for the observability story. Non-2xx still raises
  `JudgeError` because transport failures are real bugs the host
  log should surface.
- **Strict verdict-vocabulary check before pass-through.** The
  parser rejects any verdict that isn't exactly `"in_scope"` or
  `"out_of_scope"` and routes to the fallback. Reason:
  `scope_alerts.verdict` is a free-text column today (no DB CHECK
  constraint per ADR-0030 §D8), but operator dashboards filter on
  the two known values. Letting a stray `"maybe"` slip through
  would break those filters silently.
- **Embedding dim sanity check at the client boundary.** Returning
  a non-1536 vector means the model swapped under us or OpenAI
  changed the API. The vector column is `vector(1536)` (migration
  0010) so the bad row would fail at the DB anyway, but failing
  early at the client gives a more useful exception message + an
  unambiguous audit-log entry tied to the egress call.
- **`Authorization` header constructed per-call from
  constructor-injected key.** ADR-0030 §D4 keeps the OPENAI_API_KEY
  read at `on_init` time (CP5); both clients accept the key by
  constructor injection, not env-read, so they remain pure +
  testable in isolation. Matches the analytics_sink pattern
  (engine injected, not constructed inside the plugin).

## Verification

CP1 verified end-to-end against the new pgvector image:

```
$ docker rm -f llm-tracker-pg && docker run -d --name llm-tracker-pg \
    -e POSTGRES_USER=cp2 -e POSTGRES_PASSWORD=cp2 \
    -e POSTGRES_DB=llm_tracker_test \
    -p 55432:5432 pgvector/pgvector:pg15
# (image pulled, container up)

$ export LLMTRACK_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test
$ cd packages/llm_tracker_server && .venv/bin/python -m alembic upgrade head
# 0001 → 0002 → ... → 0010_scope_guard_tables; version stamped 0010

$ psql -c "\dt" -c "SELECT extname FROM pg_extension WHERE extname='vector'"
# scope_documents, scope_chunks, scope_alerts present; vector extension installed

$ .venv/bin/python -m alembic downgrade -1
# scope_* tables dropped; alembic_version → 0009

$ .venv/bin/python -m alembic upgrade head
# scope_* tables recreated; alembic_version → 0010 (round-trip clean)

$ export LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test
$ cd /Users/minseop/Desktop/MyProjects/Userfriendly && .venv/bin/python -m pytest -q
164 passed in 25.14s
```

The `164 passed` baseline is lower than STATUS.md's pre-archive
"354 passed under DB fixture" because the 2026-05-17 archive
session removed the local `llm_tracker` sidecar (`8ef166d`) and
rescued only the SDK tests into `packages/llm_tracker_sdk/tests/`.
The current sum across the six testpath entries is 164 — CP1 added
zero new tests and broke zero existing ones (regression-free).

Found and fixed during verification:

- **Multi-statement asyncpg issue.** Initial draft sent the whole
  schema block as one `op.execute(big_string)`; asyncpg rejected it
  with `cannot insert multiple commands into a prepared statement`.
  Migration `0009_retention_deletion_job` sidesteps the same trap by
  wrapping its body in a single `DO $$ ... END$$;` block. For 0010
  the cleaner fix is per-statement dispatch — a `_UPGRADE_STATEMENTS`
  tuple iterated with one `op.execute` per item. Same transactional
  guarantees (alembic wraps `upgrade()` in one DDL transaction),
  driver-friendly.

- **Stale `.git/HEAD.lock`.** A 0-byte HEAD.lock from earlier in the
  day (Cursor gitWorker, likely crashed) blocked the first commit
  attempt. Confirmed stale (>2h old, no active git mutating
  processes), removed manually. Standard git recovery, not
  destructive.

CP2 verified after the package skeleton landed:

```
$ .venv/bin/python -m ruff format packages/llm_tracker_plugin_scope_guard/
7 files left unchanged
$ .venv/bin/python -m ruff check packages/llm_tracker_plugin_scope_guard/
All checks passed!

$ uv sync
Resolved 63 packages in 307ms
   Building llm-tracker-plugin-scope-guard @ file:///...
Downloaded numpy
      Built llm-tracker-plugin-scope-guard @ file:///...
Installed 3 packages
 + llm-tracker-plugin-scope-guard==0.1.0
 + numpy==2.4.5
 + pgvector==0.4.2

$ .venv/bin/python -c "..."
manifest OK: scope_guard 0.1.0 hooks=['on_persisted']
  caps=['egress_http'] level=L3
egress: ['https://api.openai.com/v1/embeddings',
         'https://api.openai.com/v1/chat/completions']
db_namespace: scope_guard
entry points found: [EntryPoint(name='scope_guard',
   value='llm_tracker_plugin_scope_guard.plugin:ScopeGuard', ...)]
class loaded: ScopeGuard name attr = scope_guard
instance OK: scope_guard

$ .venv/bin/python -m pytest -q
164 passed in 25.03s
```

Four checks all green: ruff clean; `uv sync` installs the new
workspace package with `pgvector==0.4.2` (and transitive
`numpy==2.4.5`); `PluginManifest.from_path()` accepts the
ADR §D9 manifest verbatim; the `llm_tracker.plugins` entry point
group exposes `scope_guard` → `ScopeGuard`, which loads and
instantiates cleanly; full test suite stays at 164 (CP2 added zero
tests as designed — skeleton-only).

CP3 verified after the chunker landed:

```
$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_plugin_scope_guard/
All checks passed!
$ .venv/bin/python3.12 -m ruff format --check packages/llm_tracker_plugin_scope_guard/
9 files already formatted

$ .venv/bin/python3.12 -m pytest packages/llm_tracker_plugin_scope_guard/tests -q
22 passed in 0.17s

$ .venv/bin/python3.12 -m pytest -q
168 passed, 18 skipped in 5.89s
```

Three checks green: ruff clean across the package; scope_guard's
own 22 chunker tests pass; the full suite picks up +22 tests
(146 → 168 passed without the DB fixture; the 18 skipped are
the DB-gated server tests, unchanged from before) with zero
regression.

Found and fixed during CP3:

- **`RUF001` / `RUF003` ambiguous-glyph lint on the CJK regex.**
  The sentence-segmenter character class legitimately contains
  CJK fullwidth `？` `！` `。` and the curly left double / single
  quotation marks `“ ‘` — ruff cannot tell pattern-intent CJK
  from accidental Asian punctuation. Resolved with two
  per-string `# noqa: RUF001` lines on the segments where the
  ambiguous chars are pattern members. The EN-DASH `–` in the
  module comment was the easy half: replaced with HYPHEN-MINUS.
- **pytest collection collision on `tests/__init__.py`.** Initial
  draft shipped an empty `tests/__init__.py` (mirroring the
  server package). pytest's rootdir-based collection then treated
  every plugin's `tests/` as a top-level `tests` package and they
  fought over the same name (`ModuleNotFoundError: No module
  named 'tests.test_chunker'` while collecting). Removed the
  `__init__.py` to match the analytics_sink / keyword_block /
  token_counter pattern — they don't ship one either.
- **`SIM300` Yoda condition on `pytest.approx`.** Flipped to
  `pytest.approx(0.15) == _BOUNDARY_DROP_THRESHOLD` per ruff
  preference. `pytest.approx` is symmetric so the assertion is
  equivalent.
- **Above-max split test fixture math.** Initial draft used
  three 300-word sentences (900 words total) and asserted a
  single split at the lowest seam. The recursive splitter
  correctly re-splits the 600-word half (still above the
  500-word max), producing three groups rather than the
  expected two. Adjusted the fixture to 250-word sentences
  (750 total → splits to `[[0,1], [2]]` where `[0,1]` is exactly
  at the bound) so the test pins one-pass split behaviour
  precisely.

CP4 verified after the egress clients landed:

```
$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_plugin_scope_guard/
All checks passed!
$ .venv/bin/python3.12 -m ruff format --check packages/llm_tracker_plugin_scope_guard/
10 files already formatted

$ .venv/bin/python3.12 -m pytest packages/llm_tracker_plugin_scope_guard/tests -q
40 passed in 0.26s

$ .venv/bin/python3.12 -m pytest -q
186 passed, 18 skipped in 5.89s
```

Three checks green: ruff clean across the package; scope_guard's
own tests rose 22 → 40 (7 embeddings + 11 judge new); the full
suite picks up +18 tests (168 → 186 passed without the DB fixture;
the 18 skipped are DB-gated server tests, unchanged from CP3) with
zero regression.

Found and fixed during CP4:

- **`E501` 101-char line in `embeddings.py`'s dim-mismatch error
  message.** Initial draft wedged the conditional length expression
  inside the f-string, pushing past the 100-col limit. Split into a
  named `actual_dim` local + a shorter error message. Mechanical
  cleanup, no behaviour change.
- **ruff format collapsed the multi-line `_USER_PROMPT_TEMPLATE`
  string concat onto a single 92-col line.** Confirmed the template
  still emits the expected `\n` separators (the Q4 freeze test +
  the request-shape test both pass against the collapsed form), so
  the collapsed shape is the canonical one going forward. No
  hand-edit fight against the formatter.

## What's left / known limits

- CP8 not started. CP8 is the next active step (the last CP).
- ADR-0030's open questions reduce to one: Q1 **resolved at
  CP3**, Q4 **resolved at CP4**, Q3 resolved at CP1 time (new
  0011 migration over amending 0009). Q2 stays MVP-deferred
  (linear scan acceptable until any org's chunk count
  approaches ~10k). CP8 ships the Q3 migration and closes the
  ADR's open-question ledger.
- Test baseline after CP7: still **239 passed** under the DB
  fixture (CP7 is docs-only; no test changes). Scope_guard
  package suite still 75 tests.
- No real OpenAI call has fired yet — operator-side smoke
  against a real key (`process-scope-document <org_id> <scope.md>`
  followed by a normal Claude Code request) is unblocked now
  that the `.env.example` + deploy.md disclosure are in place.
  Smoke is a separate follow-up; CP8 doesn't gate on it.
- pgvector ANN index not present (ADR-0030 §Q2 defers it). When
  any org's `scope_chunks` count starts approaching ~10k,
  revisit and add an `HNSW` or `IVFFlat` index on `embedding`.
- Chunker token-count proxy is whitespace word count, not a
  real tokenizer. English token : word ratio is ~1.3 : 1 so the
  50/500 word bounds map to ~65/~650 actual tokens. CJK-heavy
  corpora may want to retune; flagged in the module comment.
- Sentence segmenter is MVP regex — abbreviations like "Mr." or
  decimal numbers like "3.14" can mis-split. Library swap to
  `blingfire` / `pysbd` queued under ADR-0030 §Deferred §6.
- `tests/__init__.py` omitted in scope_guard's `tests/` (CP3
  decision retained for CP5). The conftest at
  `packages/llm_tracker_plugin_scope_guard/tests/conftest.py`
  is a copy-adapted version of
  `packages/llm_tracker_server/tests/conftest.py` — once a third
  plugin needs the same DB fixture, hoist to a workspace-root
  `tests/conftest.py` (queued as a §Suggestion-tier follow-up,
  not blocking).

## Handoff

CP1–CP7 closed by commits `2511c3a` + `b6cdf5f` + `2fe84e6` +
`44cd664` + `80ca424` + `f0042f6` + `c0c000f` + `8e18892` +
this docs finalize. The active work board is the "Checkpoint
plan" table above: CP1 + CP2 + CP3 + CP4 + CP5 + CP6 + CP7
done, CP8 pending (last CP).

**Next active step — CP8: migration `0011_scope_alerts_retention`.**
Resolves ADR-0030 §Q3 (decided at CP1 time: new migration
over amending 0009 — each retention concern owns its own
reversible migration; mixing a third cron row with a
different table/column/unit shape into 0009 muddies the
downgrade). Concrete spec:

1. New migration file
   `packages/llm_tracker_server/alembic/versions/0011_scope_alerts_retention.py`,
   `down_revision = "0010_scope_guard_tables"`.
2. Inside a `DO $$ … $$` block gated on `pg_cron`
   availability (same pattern as
   `0009_retention_deletion_job`), schedule one daily job at
   03:00 UTC: `llm-tracker-retention-scope-alerts` runs
   `DELETE FROM public.scope_alerts WHERE created_at < now()
   - INTERVAL '6 months'` (timestamptz column → direct,
   unlike `exchanges.started_at` which is bigint unix-ms).
3. `scope_documents` + `scope_chunks` are **explicitly not
   retention-managed** — operator-curated baseline content,
   not user-generated data (ADR-0030 §D8). Don't include
   them in the cron job.
4. Downgrade unschedules the job by name; does NOT drop the
   `pg_cron` extension (matches the migration-0009 stance on
   blast radius).
5. Extend `docs/deploy.md` §"Data collection & privacy"
   bullet on retention to name the third job alongside the
   existing two (`llm-tracker-retention-exchanges` +
   `llm-tracker-retention-plugin-analytics` →
   `…-scope-alerts`).
6. Round-trip verification: `alembic upgrade
   0010_scope_guard_tables:0011_scope_alerts_retention --sql`
   then the reverse `--sql` invocation; no actual DB writes
   needed, the cycle just emits the BEGIN/SQL/COMMIT block.

The CP8 commit closes the implementation phase; ADR-0030's
open-question ledger drops to zero (Q1/Q3/Q4 resolved during
implementation, Q2 stays MVP-deferred per the ADR).

The Decisions section above carries every ADR-0030
open-question commitment + the implementation-tier choices
(the `session_factory` Protocol, the pgvector text-literal
codec, the always-write-a-row stage1_in interpretation, the
`HookContext` ceiling quirk in tests, the in-package CLI path
vs. ADR's `tools/` suggestion, the `_ToolEgressClient`
audit-skip, the CP7 docs split across three files) so CP8
doesn't re-derive them. Read STATUS.md → this worklog → last
5 commits (`80ca424` + `f0042f6` + `5472463` + `c0c000f` +
`cd5c706` + `8e18892` + finalize).

## Suggestions (untouched)

- `CLAUDE.md §1` still lists "Mode-aware" as a core principle even
  though ADR-0019 retired L/A/R modes; `min_content_level` is what
  ADR-0030 binds against. Flagged here so a future CLAUDE.md touch
  can drop it.
- `docs/design.md` still describes the local-sidecar architecture in
  places; ADR-0017 + ADR-0019 + ADR-0030 together are owed a v0.3
  pass once scope_guard ships.
- `docs/plugins.md §11 Reference plugins` table is stale (surfaced
  during CP7): lists `llm-tracker-plugin-supabase-sink` which was
  archived in commit `8ef166d` (2026-05-17) and omits the workspace
  packages `analytics_sink`, `keyword_block`, and `token_counter`.
  CP7 only updated the scope_guard row + added the CLI paragraph
  (CLAUDE.md §2.3 surgical changes). A future docs sweep should
  drop the supabase_sink row and add the three missing plugins.
