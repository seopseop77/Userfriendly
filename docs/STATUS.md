# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-18 (Claude Code; **scope_guard provider swap — ADR-0031 accepted; embedding/judge moved from OpenAI to Gemini in one commit.** Operator was Gemini-only on API procurement so the OpenAI-pinned ADR-0030 §D3/§D4 needed superseding; ADR-0031 records the swap, migration 0012 collapses `scope_chunks.embedding vector(1536) → vector(768)` (drop-and-add; safe on the empty table — STATUS-confirmed pre-swap), `embeddings.py` retargets `https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent` with `x-goog-api-key`, `judge.py` retargets `…/gemini-2.5-flash:generateContent` with `systemInstruction` + `generationConfig.responseMimeType=application/json` + temp 0, env var `OPENAI_API_KEY` → `GEMINI_API_KEY`, log key `scope_guard.openai_failure` → `scope_guard.gemini_failure`, `plugin.toml` egress allowlist swapped exact-URL, `.env.example`/`docs/deploy.md` §"Data collection & privacy"/`docs/plugins.md` §11 retargeted at Google + Gemini API additional-terms link. ADR-0030 §Q4 frozen prompt template **carried over unchanged** — the swap is transport / shape, not contract. Tests rewritten: 38 offline scope_guard tests pass (was 38; structure unchanged), full repo suite still 213 passed + 26 DB-skipped, ruff clean. Earlier same session: scope_guard CP8 of 8 done — commit `39595da` (server: migration 0011 scope_alerts retention).** Migration `0011_scope_alerts_retention` ships one daily `pg_cron` job `llm-tracker-retention-scope-alerts` at 03:00 UTC running `DELETE FROM public.scope_alerts WHERE created_at < now() - INTERVAL '6 months'` — `timestamptz` cutoff is direct (same shape as 0009's plugin_analytics job, unlike `exchanges.started_at` which is unix-ms). `scope_documents` + `scope_chunks` are operator-curated baseline content (ADR-0030 §D8) and intentionally NOT retention-managed; the module docstring spells this out so a future "why isn't this cleaned" doesn't have to re-derive. Same pg_cron-gated `DO $$ … $$` pattern as 0009 keeps alembic upgrade green on environments without the extension. Downgrade unschedules by name (idempotent EXISTS-checked) without dropping pg_cron — same blast-radius stance as 0009/0010. `docs/deploy.md` §"Data collection & privacy" retention bullet bumped from "two pg_cron jobs" to "three" with the new job name + an explicit sentence on the `scope_documents`/`scope_chunks` exemption + the `process-scope-document` CLI re-registration path. Verified: ruff clean, alembic upgrade/downgrade --sql round-trip emits clean BEGIN/SQL/COMMIT blocks, 239 tests pass under DB fixture (unchanged from CP7 — cron job appears in `cron.job` table; no test surface change). ADR-0030 open-question ledger now ZERO outstanding (Q1 resolved at CP3, Q3 resolved at CP8 per the CP1 pre-pin, Q4 resolved at CP4; Q2 ANN index stays MVP-deferred per the ADR — revisit when any org's scope_chunks count approaches ~10k). **Next active step is operational, not implementation: operator-side live smoke against a real OPENAI_API_KEY to exercise the actual `text-embedding-3-small` + `gpt-4o-mini` round-trips on production traffic.** Phase 1c scope_guard shipped end-to-end: migration + package + chunker + OpenAI clients + pipeline + storage + plugin wiring + operator CLI + disclosure docs + retention cron. CP7 closed earlier same session by commit `8e18892`; CP6 by `c0c000f`; CP5 by `f0042f6`; CP4 by `80ca424`; CP3 by `44cd664`; CP2 by `2fe84e6`; CP1 by `2511c3a` + `b6cdf5f`.)
**Updated by**: Claude Code (scope_guard provider swap; ADR-0031 accepted + applied)

## Current phase

- **Phase**: **Phase 3b — CLOSED (2026-05-13).** Thin local agent
  `claude-manage` (`packages/llm_tracker_agent/`) shipped over
  three commits (`79a0ae9` ADRs / `fbd36e4` agent code /
  `ac4370c` multi-instance fallback) and live-verified by the
  user against `https://llm-tracker-server.fly.dev`. Surface area
  in production:
  - `claude-manage setup <token> [--server-url ...] [--port ...]`
    writes `~/.llm-tracker/config.toml` (`0o600`).
  - `claude-manage` (default) picks a free loopback port —
    preferred from config, else kernel-assigned ephemeral so
    multiple instances coexist — runs the FastAPI proxy that
    injects `X-LLM-Tracker-Token` + strips hop-by-hop, polls
    `/healthz` for ≤ 3s readiness, sets `ANTHROPIC_BASE_URL`, and
    spawns `claude <extra-args>`.
  - Fail-closed per ADR-0024 confirmed end-to-end in negative
    smoke: 503 propagates to Anthropic SDK → 10 retries with
    backoff → user-facing failure, no Anthropic bypass.
- **Active task**: **scope_guard implementation against
  ADR-0030 (Accepted 2026-05-18). ALL 8 CPs DONE — Phase 1c
  scope_guard shipped end-to-end.** Migration `0010_scope_guard_tables`
  (commit `2511c3a`) lands the three tables + RLS + GRANTs
  per ADR §D8; package skeleton
  `packages/llm_tracker_plugin_scope_guard/` (commit
  `2fe84e6`) lands the manifest + 6 module stubs per ADR §D9
  + new `pgvector` dep with transitive `numpy`; `chunker.py`
  (commit `44cd664`) lands the full ADR §D5 pipeline + 22
  unit tests + Q1 parameters pinned; `embeddings.py` +
  `judge.py` (commit `80ca424`) land the OpenAI clients over
  `EgressClient`, pin **§Q4** as a module-top frozen prompt
  template, and add 18 offline unit tests
  (`EgressClient.fetch` stubbed); `pipeline.py` +
  `storage.py` + `plugin.py` (commit `f0042f6`) wire the
  two-stage routing + pgvector max-cosine lookup +
  scope_alerts insert + the `on_persisted` §D6
  message-extraction + fail-closed `on_init` wiring
  (`OPENAI_API_KEY` / `LLMTRACK_DATABASE_URL` / `egress`)
  with 26 new tests including a 5-case DB-fixture integration
  test (stage1_in, stage1_out, stage2, per-org RLS isolation,
  no-corpus); `process_scope_document.py` (commit `c0c000f`)
  ships the operator CLI as both a library
  (`register_document(...)`) and a console-script
  (`process-scope-document <org_id> <file>` after `uv sync`,
  plus `python -m` fallback) with idempotent delete-then-insert
  per `(org_id, title)` using migration-0010
  `ON DELETE CASCADE`, fail-closed env checks, and 9 new tests
  (6 arg-validation + 3 DB-fixture); CP7 (commit `8e18892`) is
  docs-only — `.env.example` gains the 6 plugin env knobs with
  ADR-section pointers, `docs/deploy.md` §"Data collection &
  privacy" gains a new Privacy posture bullet carrying the
  ADR-0030 §Consequences — Disclosure paragraph verbatim plus
  a closing CLI pointer, and `docs/plugins.md` §11 gains a
  refined scope_guard table row + a `process-scope-document`
  CLI invocation paragraph; CP8 (commit `39595da`) ships
  migration `0011_scope_alerts_retention` — one daily
  `pg_cron` job `llm-tracker-retention-scope-alerts` at 03:00
  UTC deleting `scope_alerts` rows older than 6 months
  (`scope_documents` + `scope_chunks` deliberately not
  retention-managed per ADR-0030 §D8 — operator-curated
  baseline content), pg_cron-gated, reversible downgrade
  unschedules-by-name without dropping the extension, plus a
  `docs/deploy.md` retention-bullet refresh naming the third
  job alongside the existing two. Full suite 239 passed under
  the `pgvector/pgvector:pg15` DB fixture; alembic
  upgrade/downgrade `--sql` round-trip clean. **ADR-0030
  open-question ledger: zero outstanding** (Q1 resolved at
  CP3, Q3 resolved at CP8 per the CP1 pre-pin, Q4 resolved at
  CP4; Q2 ANN index stays MVP-deferred per the ADR — revisit
  when any org's `scope_chunks` count approaches ~10k).
  **Next active step is operational, not implementation:
  operator-side live smoke against a real `OPENAI_API_KEY` to
  exercise the actual `text-embedding-3-small` +
  `gpt-4o-mini` round-trips on production traffic.** Per-CP
  work board lives in
  `docs/worklog/2026-05-18-scope-guard-impl.md` §"Checkpoint
  plan".
- **Queued follow-ups** (none gating; pick one to continue):
  - **`plugin_analytics` RLS axis — ADR-level revisit.** 0007's
    docstring chose "no RLS on this table" deliberately ("Analytics
    is internal — the plugin queries this directly from operator
    tooling"). Either elevate that choice to an ADR or reconsider
    with an explicit policy on operator-tooling access shape.
  - **Task hierarchy (session/task/exchange).** Deferred track to
    introduce a `task_id` layer between `session_id` and
    `exchange_id` so multi-exchange Claude-Code sessions map to
    operator-visible task units rather than only the per-turn
    exchange row. Not gated on anything; design-first.
  - **Real `session_id` populator + deletion endpoint** (ADR-0029
    Axis 4 + Phase 3b agent identity).
  - **i18n email scrubbing** (ADR-0029 §"Open questions").
  - ~~**Block/Abort ctx-cleanup latent gap**~~ **Closed 2026-05-17**
    by commit `4fef915`.
  - ~~**DB-fixture integration tests for `record_exchange_failure`**~~
    **Closed 2026-05-17** by commit `3fe0caa`.
  - ~~**6-month automated retention deletion job**~~ **Closed
    2026-05-17** by migration `0009_retention_deletion_job`.
  - ~~**ADR-#2 consent + data-handling**~~ **Closed 2026-05-17** by
    ADR-0029, production-validated same day.

## Active worklog

`docs/worklog/2026-05-18-gemini-provider-swap.md` — scope_guard
provider swap to Gemini per ADR-0031 (Accepted 2026-05-18 same
session). Single-commit change spanning ADR-0031, migration 0012
(`scope_chunks.embedding` 1536 → 768; safe drop-and-add on empty
table), `embeddings.py` + `judge.py` rewritten against
`generativelanguage.googleapis.com` endpoints, `plugin.py` env-var
rename `OPENAI_API_KEY` → `GEMINI_API_KEY` + log key
`scope_guard.openai_failure` → `scope_guard.gemini_failure`,
`plugin.toml` egress allowlist swapped, all five test files
updated (Gemini URL/shape + 768d), and `.env.example` /
`docs/deploy.md` §"Data collection & privacy" / `docs/plugins.md`
§11 retargeted at Google + Gemini API additional-terms link. The
ADR-0030 §Q4 frozen prompt template is unchanged across the swap.
Verified: 38 offline scope_guard tests pass; full repo suite still
213 passed + 26 DB-skipped; ruff clean. **Next single step is
operational: operator-side live smoke against a real
`GEMINI_API_KEY` to exercise the `text-embedding-004` +
`gemini-2.5-flash` round-trips on production traffic.**

Prior worklog (kept as the OpenAI-era implementation history):
`docs/worklog/2026-05-18-scope-guard-impl.md` — scope_guard
implementation against ADR-0030 (Accepted). **ALL 8 CPs DONE
— Phase 1c scope_guard complete.** Migration
`0010_scope_guard_tables` (commit `2511c3a`), package
skeleton + manifest (commit `2fe84e6`), the full ADR §D5
chunker (commit `44cd664`) with Q1 pinned to
`window=3, drop=0.15`, the OpenAI clients (commit `80ca424`)
with **ADR-0030 §Q4 pinned** as a module-top frozen prompt
template, the pipeline + storage + plugin wiring (commit
`f0042f6`) — `pipeline.evaluate(...)` pure two-stage routing
+ `storage.select_top_chunks_by_cosine(...)` +
`storage.insert_alert(...)` over pgvector text literals + the
RLS-off `scope_alerts` table + `plugin.ScopeGuard.on_init`
fail-closed wiring + `on_persisted` §D6 message-extraction —
the operator CLI (commit `c0c000f`):
`process_scope_document.register_document(session_factory,
embed_client, *, org_id, title, text)` library +
`process-scope-document <org_id> <file>` console script with
idempotent delete-then-insert per `(org_id, title)`
(`ON DELETE CASCADE` cleans prior chunks),
`_ToolEgressClient` httpx adapter for out-of-host egress,
fail-closed env checks mirroring plugin's `on_init`, and an
async port of `chunker.chunk_document` reusing the chunker's
pure helpers — and the CP7 docs (commit `8e18892`):
`.env.example` adds the 6 `LLMTRACK_PLUGIN_SCOPE_GUARD_*`
knobs + `OPENAI_API_KEY` section, `docs/deploy.md` §"Data
collection & privacy" gains the ADR-0030 §Consequences —
Disclosure bullet (OpenAI `text-embedding-3-small` +
`gpt-4o-mini`, assistant + tool-result content not sent,
zero-data-retention pointer), `docs/plugins.md` §11 refines
the scope_guard table row + adds a
`process-scope-document` CLI invocation paragraph. 75
scope_guard tests (22 chunker + 7 embeddings + 11 judge + 8
pipeline + 13 plugin + 5 DB-fixture integration + 9
process-scope-document); CP8 (commit `39595da`) ships
migration `0011_scope_alerts_retention` — daily `pg_cron`
job `llm-tracker-retention-scope-alerts` at 03:00 UTC
deleting `scope_alerts` rows older than 6 months
(`scope_documents`/`scope_chunks` intentionally not
retention-managed per ADR-0030 §D8) plus a `docs/deploy.md`
retention-bullet refresh naming the third job. Full suite
239 passed under the `pgvector/pgvector:pg15` DB fixture
without regression; alembic upgrade/downgrade `--sql`
round-trip clean. **ADR-0030 open-question ledger is zero
outstanding** (Q1/Q3/Q4 resolved during implementation, Q2
stays MVP-deferred per the ADR). Next active step is
operational, not implementation: operator-side live smoke
against a real `OPENAI_API_KEY`.

Prior worklog (same day, earlier session):
`docs/worklog/2026-05-18-adr-0030-scope-guard.md` — ADR-0030
(scope_guard plugin design) drafted as Proposed; nine pre-decided
axes from the user interview + four Cowork-surfaced ambiguities
resolved to Cowork defaults. Superseded by the acceptance + CP1
landed in this session's worklog above.

Earlier worklogs preserved:
`docs/worklog/2026-05-17-followup-batch-2.md` — queued follow-up
batch round 2 (three items: Block/Abort `end_exchange` cleanup at
the short-circuit return sites; DB-fixture integration test for
`record_exchange_failure` pinning the row-write half of ADR-0027
axis 2; migration `0009_retention_deletion_job` with two
`pg_cron`-gated daily jobs at 03:00 UTC plus the deploy.md retention
bullet update). Prior worklogs from earlier:
`docs/worklog/2026-05-17-followup-batch.md` — round 1 of the queued
follow-ups (deploy.md PG16+ paragraph, tool_call_count drop
migration 0008, ADR-0027 axis 2 impl, empty-shells cleanup; one
returned to queue: `plugin_analytics` RLS as ADR-level).
`docs/worklog/2026-05-17-adr-0029-production-smoke.md` — production
smoke verification of ADR-0029 scrubber after Fly `v11` deploy, plus
doc reconciliation against falsified `messages_json` canonical
assumption;
`docs/worklog/2026-05-17-archive-sidecar-housekeeping.md` — two-task
housekeeping pass (ADR archive + sidecar removal);
`docs/worklog/2026-05-17-adr-0029-consent.md` — ADR-0029 (Accepted)
records the six-axis policy; code commit `a4c08b3` lands the SDK
scrubber + HookContext wiring + deploy/plugins disclosure paragraphs;
production-validated 2026-05-17 by the smoke worklog. Earlier
worklogs preserved:
`docs/worklog/2026-05-16-extractor-faithful-response.md` (ADR-0028 +
operator smoke closure),
`docs/worklog/2026-05-14-plugin-ecosystem.md` (Option B SSE
extractor + analytics_sink + keyword_block multi-checkpoint
session; ADR-0026 + ADR-0027 land in checkpoint α),
`docs/worklog/2026-05-13-phase3b-agent.md` (Phase 3b — ADRs
0024 / 0025 + `packages/llm_tracker_agent/` shipped),
`docs/worklog/2026-05-13-cp14-response-side-followup.md` (CP14
response-side investigation — now Option B execution), and
`docs/worklog/2026-05-13-cp14-operator-smoke.md` (closes Phase 3c
CP14 proper).

## Recent commits

```
<finalize>   docs: STATUS + worklog — scope_guard CP8 (COMPLETE)
39595da   server: migration 0011 scope_alerts retention (ADR-0030 §Q3)
b8a9f37   docs: STATUS + worklog — scope_guard CP7
8e18892   docs: scope_guard disclosure + env knobs + plugins.md CLI entry (CP7)
cd5c706   docs: STATUS + worklog — scope_guard CP6
c0c000f   scope-guard: process_scope_document CLI (ADR-0030 §D5)
```

## Where we paused

**scope_guard implementation ALL 8 CPs DONE — Phase 1c
complete (2026-05-18, commits `2511c3a` + `b6cdf5f` +
`2fe84e6` + `0fcb2c4` + `44cd664` + `6840281` + `80ca424` +
`c7ec9bd` + `f0042f6` + `5472463` + `c0c000f` + `cd5c706` +
`8e18892` + `b8a9f37` + `39595da` + docs-finalize).**

CP8 ships migration `0011_scope_alerts_retention` — the
last CP. Mirrors the 0009 retention pattern: one `DO $$ …
$$` block gated on `pg_available_extensions WHERE name =
'pg_cron'`, with the `RAISE NOTICE` skip-path for
environments without the extension. Schedules one daily job
`llm-tracker-retention-scope-alerts` at `0 3 * * *` running
`DELETE FROM public.scope_alerts WHERE created_at < now()
- INTERVAL '6 months'` — the `timestamptz` cutoff is direct
(same shape as 0009's plugin_analytics job, unlike
`exchanges.started_at` which is bigint unix-ms).

`scope_documents` + `scope_chunks` are **not** retention-
managed (ADR-0030 §D8: operator-curated baseline content,
retained indefinitely). The module docstring spells this out
so a future "why isn't this table being cleaned" doesn't
have to re-derive — the answer is in ADR-0030 §D8 + the
docstring + the CP8 migration's deliberate omission.

Downgrade unschedules the job by name (idempotent EXISTS-
checked); does **not** drop `pg_cron`. Matches the
migration-0009 stance on blast radius (and migration-0010's
on `vector`).

`docs/deploy.md` §"Data collection & privacy" retention
bullet bumped from "two `pg_cron` jobs" to "three", named
the two migrations that ship them
(`0009_retention_deletion_job` + `0011_scope_alerts_retention`),
and added an explicit sentence that `scope_documents` /
`scope_chunks` are operator-curated and intentionally not
retention-managed — directing the operator to the CP6
`process-scope-document` CLI for re-registration or manual
SQL.

Verified end to end:

```
$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_server/alembic/versions/0011_scope_alerts_retention.py
All checks passed!
$ LLMTRACK_DATABASE_URL=postgresql://localhost/dummy \
    .venv/bin/python3.12 -m alembic upgrade \
    0010_scope_guard_tables:0011_scope_alerts_retention --sql
... emits BEGIN; <DO $$ … END$$;>; UPDATE alembic_version …; COMMIT;
$ LLMTRACK_DATABASE_URL=postgresql://localhost/dummy \
    .venv/bin/python3.12 -m alembic downgrade \
    0011_scope_alerts_retention:0010_scope_guard_tables --sql
... emits BEGIN; <DO $$ … unschedule … END$$;>; UPDATE alembic_version …; COMMIT;
$ LLMTRACK_TEST_DATABASE_URL=... .venv/bin/python3.12 -m pytest -q
239 passed in 35.43s
```

Test suite unchanged at 239 passed — the new migration adds
one row to `cron.job` when `pg_cron` is present; no
behavioural change to the test fixtures. Scope_guard package
suite still 75 tests across 8 files.

Operational consequences after the next `fly deploy`:

1. `alembic upgrade head` advances stamp from
   `0010_scope_guard_tables` to
   `0011_scope_alerts_retention`. `cron.job` gains one
   `llm-tracker-retention-scope-alerts` row alongside the
   `…-exchanges` and `…-plugin-analytics` rows from 0009;
   no data deletion at migration time.
2. First scheduled `scope_alerts` deletion fires at the next
   03:00 UTC tick; the recurring job deletes alert rows
   older than 6 months on each tick. `scope_documents` and
   `scope_chunks` continue to grow until the operator
   deletes them manually or re-registers via the
   `process-scope-document` CLI.

ADR-0030 open-question ledger after CP8: **zero outstanding
questions.** Q1 resolved at CP3 (chunker boundary
parameters), Q3 resolved here at CP8 time per the CP1
pre-pin (new migration over amending 0009), Q4 resolved at
CP4 (judge prompt template frozen in `judge.py`). Q2
(pgvector ANN index) stays MVP-deferred per the ADR — revisit
when any org's `scope_chunks` count approaches ~10k.

scope_guard implementation closes here. Phase 1c shipped
end-to-end against ADR-0030: migration + plugin package +
chunker + OpenAI clients + pipeline + storage + plugin
wiring + operator CLI + disclosure docs + retention cron.
Next active step for a future session is **operational, not
implementation**: operator-side live smoke against a real
`OPENAI_API_KEY` to confirm the `text-embedding-3-small` +
`gpt-4o-mini` round-trips write expected `scope_alerts`
rows on production traffic. The DB-fixture suite uses stubs
by design (ADR-0029-aligned, no third-party calls in CI),
so the first live call needs an operator on a real key.

CP7 narrative preserved below for cold-start sessions:

**scope_guard implementation CP1 + CP2 + CP3 + CP4 + CP5 +
CP6 + CP7 of 8 done (2026-05-18).**

CP7 is docs-only — lands the three operator-facing surfaces
ADR-0030 §Consequences — Disclosure obliged us to update:

- `.env.example` gains a new
  `# -- scope_guard plugin (ADR-0030)` section between the
  Local PG test loop and the Per-request headers info-block.
  Lists `OPENAI_API_KEY` (framed as "needed when the plugin
  is enabled" since the plugin's `on_init` already fail-closes
  when it's missing) and the five
  `LLMTRACK_PLUGIN_SCOPE_GUARD_*` knobs: `THRESHOLD` (0.6),
  `AMBIGUOUS_BAND` (0.1), `WINDOW` (5), `JUDGE_MODEL`
  (`gpt-4o-mini`), `JUDGE_TOP_K` (3). Each variable carries an
  ADR-section pointer + behaviour note so the operator
  doesn't need to flip to the ADR.
- `docs/deploy.md` §"Data collection & privacy" gains one
  new bullet on the existing Privacy posture list carrying
  the ADR-0030 §Consequences — Disclosure paragraph verbatim
  ("the most recent user-initiated turns from each exchange
  are sent to OpenAI's embedding API (`text-embedding-3-small`);
  ambiguous-band requests additionally trigger a `gpt-4o-mini`
  Chat Completions call.…") plus a closing pointer to the
  `process-scope-document` CLI for the per-org corpus that
  scope_alerts are scored against. The existing
  `LLMTRACK_PLUGINS_DISABLED` bullet now names both
  `analytics_sink` and `scope_guard` as valid off-switch
  targets (comma-separate to disable both).
- `docs/plugins.md` §11 Reference plugins: the scope_guard
  table row's Purpose column updated to "Server-side scope
  monitor on `on_persisted` (ADR-0030, Phase 1c). Two-stage
  embedding + judge pipeline; observe-only; writes
  `public.scope_alerts`." A new paragraph after the
  install-via-git-URL snippet documents the
  `process-scope-document` CLI — both invocations
  (`process-scope-document <org_id> <file.md>` and the
  `python -m` fallback), accepted formats (`.txt` / `.md`),
  idempotency contract, and env requirements
  (`OPENAI_API_KEY` + `LLMTRACK_DATABASE_URL`).

`git diff --stat` for CP7 shows 71 lines added / 2 lines
removed across the three files (the only deletion is the old
scope_guard row in plugins.md being expanded inline). Test
suite unchanged at 239 passed under the DB fixture — CP7
ships no code paths.

Implementation notes worth carrying forward to CP8:

- **`docs/plugins.md` §11 table drift surfaced.** The
  Reference plugins table still lists
  `llm-tracker-plugin-supabase-sink` but the package directory
  was removed in 2026-05-17 (commit `8ef166d`'s sidecar
  archive). It also doesn't list `analytics_sink`,
  `keyword_block`, or `token_counter`, all of which exist as
  workspace packages. CP7 deliberately scoped to scope_guard
  per CLAUDE.md §2.3 surgical changes; the table drift is
  queued for a future docs sweep (see worklog §Suggestions).
- **Disclosure-paragraph wording is pinned in ADR-0030.** The
  bullet in `docs/deploy.md` matches the ADR §Consequences
  — Disclosure block verbatim plus the closing CLI pointer.
  If the ADR wording ever changes, `docs/deploy.md` follows
  in the same PR — the canonical source is the ADR, the
  deploy doc is the operator-facing surface.
- **`LLMTRACK_PLUGINS_DISABLED` is the unified off-switch
  for both plugins.** Comma-separated CSV semantics (the
  host's plugin-host already parses it this way for
  analytics_sink). Documented in the extended deploy.md
  bullet so the operator can disable scope_guard standalone,
  analytics_sink standalone, or both.

CP6 narrative preserved below for cold-start sessions:

CP6 ships the operator CLI that fills the
ADR-0030 §D5 + §D9 registration UX. New module
`packages/llm_tracker_plugin_scope_guard/src/llm_tracker_plugin_scope_guard/process_scope_document.py`
exposes both a library function (`register_document(...)`,
imported by the DB-fixture test) and an argparse-driven
`main()`. After `uv sync` both
`process-scope-document <org_id> <file>` (console script
registered in pyproject) and
`python -m llm_tracker_plugin_scope_guard.process_scope_document
...` work. Validates UUID + file existence + suffix (`.txt`
or `.md` only — PDFs/DOCX queued under §Deferred §3) before
any DB or network call; refuses with exit code 2 when
`OPENAI_API_KEY` or `LLMTRACK_DATABASE_URL` is unset (mirrors
the plugin's `on_init` fail-closed). Idempotent
re-registration: `DELETE FROM scope_documents WHERE
(org_id, title)` runs first inside the same session, the
migration-0010 FK `ON DELETE CASCADE` on
`scope_chunks.document_id` drops the prior chunks in the same
statement, then fresh INSERTs land — single commit at the end
so a mid-run failure leaves no partial document. `_chunk_document_async`
inlined as an async port of `chunker.chunk_document`, reusing
the pure helpers (`_segment_sentences`, `_detect_boundaries`,
`_group_into_chunks`, `_enforce_size_bounds`, `_cosine`) and
awaiting the OpenAI embed call one sentence at a time —
sequential is fine for an operator one-shot. New
`_ToolEgressClient(EgressClient)` adapter wraps `httpx`
without `HostEgressClient`'s audit-log mediation (safe because
the script runs out-of-host and only hits OpenAI's
allowlisted embeddings endpoint). New direct dep
`httpx>=0.27` in scope_guard's pyproject.

Test coverage adds 9 tests: 6 arg-validation (non-UUID
`org_id`, missing file, unsupported suffix `.pdf`,
default-title-is-stem, explicit `--title` wins, `.md`
accepted) + 3 DB-fixture-gated (idempotency two-round
contract verifying chunk count matches round 2 only,
sequential `chunk_index` 0..N-1 with correct
`org_id`/`document_id`, per-title isolation under same org).
Smoke-tested both invocation paths post-`uv sync`:
`.venv/bin/process-scope-document --help` and the `-m`
form both render the same argparse help.

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

239 is +9 over CP5's 230 — exactly the CP6 test additions.
Scope_guard package suite now 66 → 75 tests.

Implementation notes worth carrying forward to CP7 / CP8:

- **CLI lives in-package, not under top-level `tools/`.**
  ADR-0030 "Implementation surface" suggested either a
  `tools/` script or a Typer subcommand under the server CLI.
  Both have downsides: a top-level `tools/` dir would carry
  one file; a server CLI subcommand creates a server → plugin
  import dependency that reverses the architecture (plugins
  depend on server/sdk, not vice versa). Putting the module
  inside the plugin package + a console-script entry-point
  sidesteps both — gives both
  `process-scope-document ...` and `python -m
  llm_tracker_plugin_scope_guard.process_scope_document ...`
  for free, keeps the testable library next to its DB-fixture
  test, and the operator's deploy artifact is whatever
  `uv sync` produces.
- **`ON DELETE CASCADE` does the chunk cleanup.** Migration
  0010 set `scope_chunks.document_id REFERENCES
  scope_documents(id) ON DELETE CASCADE`, so `DELETE FROM
  scope_documents WHERE org_id = :o AND title = :t` is
  sufficient — no explicit `DELETE FROM scope_chunks` needed
  first. The CP6 idempotency test exercises this implicitly
  (chunk count after re-registration matches round 2, not
  1+2).
- **`_ToolEgressClient` skips the audit log on purpose.** The
  plugin's `HostEgressClient` writes one
  `egress_blocked` / `egress_allowed` row per fetch through
  `EgressGuard.check(...)`. The CLI runs locally outside the
  host, so there's no audit table to write to. Documented in
  the class docstring so a future "why isn't this audited"
  doesn't have to re-derive.

CP5 narrative preserved below for cold-start sessions:

CP5 wires the three implementation modules end-to-end:
`pipeline.py` (pure two-stage routing), `storage.py` (pgvector
lookup + alert insert), and `plugin.py` (lifecycle + §D6 message
extraction). The `on_persisted` path now reads a real
`HookContext`, builds the user-initiated message string per
ADR-0030 §D6, runs `pipeline.evaluate(...)` against the org's
`scope_chunks`, and writes one row to `scope_alerts` — observe
only, no `Block` return.

`pipeline.evaluate(message_text, *, embed, judge,
max_cosine_lookup, thresholds)` is the pure entry point:
embeds the message, runs the cosine lookup, applies
`Thresholds(threshold=0.6, band=0.1, judge_top_k=3)` to route
to `stage1_in` / `stage1_out` (no judge call) or to the judge
for `stage2_in` / `stage2_out`. Empty corpus → `None` (the
plugin treats that as "no alert" per ADR-0030 §D9). The
`ScopeEvaluation` dataclass maps 1 : 1 to a `scope_alerts` row
minus the plugin-stamped id / exchange_id / org_id /
created_at.

`storage.select_top_chunks_by_cosine(session_factory, *,
org_id, vector, k)` issues `SELECT set_config('app.org_id',
:v, true)` on the session then runs the ADR-0030 §D7 query
(`ORDER BY embedding <=> CAST(:vec AS vector) ASC LIMIT :k`,
similarity reported as `1 - distance`). pgvector is bound via
a text-literal codec (`[v1,v2,...]::vector`) — no
`pgvector.sqlalchemy` adapter required at the engine layer.
`storage.insert_alert(session_factory, ...)` writes one row
with `id = ULID().to_uuid()` for time-ordered keys. The
`SessionFactory` Protocol is what both `async_sessionmaker`
and the conftest role-wrapper expose — production wiring and
the test fixture drop in without translation.

`plugin.ScopeGuard.on_init` reads `OPENAI_API_KEY`,
`LLMTRACK_DATABASE_URL`, and the four
`LLMTRACK_PLUGIN_SCOPE_GUARD_*` knobs. Missing key /
`self.egress` / DB URL → `structlog.warning("scope_guard.disabled",
...)` and the plugin no-ops on subsequent `on_persisted`
calls. Constructor injection (`session_factory`,
`embed_client`, `judge_client`, `thresholds`, `window`) is
the test path — anything not pre-injected is filled from env
by `on_init`. The module-level `_build_message_text(request_json,
window)` runs §D6 verbatim: first user turn's
`<system-reminder>` / `<system>` blocks captured once,
user-initiated text from each user turn whose blocks aren't
all `tool_result`, assistant text + top-level `system` field
excluded, most recent `window` turns retained, joined with
`\n\n`. OpenAI failures (`EmbeddingError` / `JudgeError` /
`EgressDenied`) degrade to "no alert this exchange" rather
than crash the host.

Test coverage adds 26 tests: 8 in
`tests/test_pipeline.py` (stage routing edges + `judge_top_k`
plumbing); 13 in `tests/test_plugin.py` (§D6 extraction —
including the "first-turn system-reminder survives outside
the window" and "tool_result-only turn skipped" cases —
plus three disabled-path tests); 5 in
`tests/test_integration.py` (DB-fixture-gated end-to-end:
stage1_in 1.0-similarity, stage1_out orthogonal-vector,
stage2 ambiguous-band judge call + verdict persistence,
per-org RLS isolation with identical embeddings in two
orgs, empty-corpus no-op). The conftest at
`packages/llm_tracker_plugin_scope_guard/tests/conftest.py`
is a copy-adapted version of the server's session_factory
fixture pointed at the workspace's
`packages/llm_tracker_server` for the alembic subprocess —
same role-wrap pattern so docker-default superuser doesn't
bypass RLS.

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

The 230 figure is +44 over CP4's 186 — 26 new scope_guard
tests plus the 18 DB-fixture-gated server tests that the
test DB unblocks (no behaviour change there, only the gate
that flips). Scope_guard alone goes 40 → 66 tests.

Implementation notes picked up at CP5 (recorded so
CP6 / CP7 / CP8 don't re-derive):

- **`HookContext` ceiling in tests.** Constructing a
  `HookContext` with `mode="R"` defaults to
  `user_opted_in=False`, which makes `request_text()` return
  `None` (effective ceiling drops below L2). The integration
  test ctx helper passes `user_opted_in=True`; the
  analytics_sink test pattern was the precedent. In
  production the host pins `_ceiling=L3` from the manifest's
  `min_content_level="L3"`, so this only bites tests that
  build their own ctx.
- **Pgvector text-literal codec.** Storage renders vectors
  as `[v1,v2,...]` and binds via `CAST(:vec AS vector)` so
  neither `pgvector.asyncpg` nor `pgvector.sqlalchemy` needs
  to register a codec at engine-creation time. The SELECT
  only returns floats (`1 - distance`), never the raw vector
  — no codec needed on reads either.
- **`session_factory` vs `engine` injection.** Storage
  helpers take a `SessionFactory` Protocol (zero-arg
  callable returning an async ctx-manager yielding
  `AsyncSession`) instead of an `AsyncEngine`. That shape
  is what both `async_sessionmaker(engine)` and the conftest
  fixture's role-wrapper expose — the production wiring and
  the test wiring drop in without a translation layer at the
  storage boundary.
- **Stage1_in writes a row (not "no alert").** ADR-0030
  §D2's parenthetical "(no alert)" reads ambiguously against
  §D8's "one row per `on_persisted` evaluation" docstring +
  the partial index `WHERE flagged`. We picked "always write
  a row, `flagged` is True iff terminal verdict is
  `out_of_scope`" so the operator gets the full similarity
  distribution for threshold tuning (the research-phase
  priority §D1 names) and the partial index does its actual
  job of separating cold rows from hot. Implementation-tier
  decision; ADR not changed.
- **IEEE-754 boundary fragility.** Default `threshold=0.6,
  band=0.1` gives a lower bound of `0.5499999999999999` in
  IEEE-754, so a similarity of exactly `0.55` lands inside
  the band. The boundary test uses `threshold=0.5, band=0.2`
  (lower=0.4, upper=0.6 — both exact) to pin the `>=` /
  `<=` inequality direction unambiguously.

CP1–CP4 recaps preserved below for cold-start sessions:

CP3 ships the chunker that registration-time CLI (CP6) calls
on each scope document. The implementation lives at
`packages/llm_tracker_plugin_scope_guard/src/llm_tracker_plugin_scope_guard/chunker.py`
and reads top-down as four stages mapping 1 : 1 to ADR-0030 §D5:

1. `_segment_sentences` — paragraph-split on `\n{2,}`, then
   sentence-split on terminal punctuation (Latin `.?!` + CJK
   `。？！`) followed by whitespace and an opener class (Latin
   capital, ASCII `"` / `(`, curly left double / single quote,
   CJK ideograph U+4E00..U+9FFF, Hangul syllable
   U+AC00..U+D7AF). MVP-regex limitations (abbreviations like
   "Mr." mis-split; decimals like "3.14" mis-split) are
   acknowledged in the docstring; library swap to `blingfire` /
   `pysbd` queued under ADR-0030 §Deferred §6.
2. `_detect_boundaries` — walks adjacent-sentence cosine
   similarities; flags sentence `i+1` as a chunk boundary when
   `similarities[i] < rolling_mean(prev WINDOW sims) - DROP`.
   **Q1 pinned at this checkpoint** to `WINDOW=3, DROP=0.15`
   with a benchmark test that rejects `window=5, drop=0.15`
   (under-splits — its 5-sim warm-up swallows the first
   inter-topic drop in a 15-sentence corpus) and
   `window=3, drop=0.10` (over-splits — fires a false boundary
   on a smooth-prose fixture with a single ~0.16 dip).
3. `_enforce_size_bounds` — two passes. Pass 1 merges
   below-min chunks into the next neighbour (or previous if
   last, or accepts as-is if the chunk is solo). Pass 2 splits
   above-max chunks recursively on the lowest internal adjacent
   similarity until every chunk is at or below `_MAX_TOKENS`.
4. `chunk_document(text, embed)` — orchestrates the above. The
   `embed` callable is injected so CP3 unit tests stub it
   without touching the network (CP4 wires it to the real
   OpenAI client). Each final chunk is **re-embedded as one
   string** so the returned vector represents the chunk's
   concatenated `content` exactly — not a sentence-vector
   average — matching the `scope_chunks.embedding`/`content`
   contract.

Token count is approximated by whitespace-split word count
rather than a tokenizer dependency: predictable, dep-free,
maps to ~65 / ~650 actual tokens at the 1.3 token/word ratio
typical of English. CJK-heavy corpora may want to retune;
flagged in the module comment.

Test coverage: 22 unit tests in
`packages/llm_tracker_plugin_scope_guard/tests/test_chunker.py`.
Sentence segmenter (simple punctuation, paragraph break, CJK
terminator, empty input); cosine helper (orthogonal, parallel,
zero-norm guard); `chunk_document` (empty / single-sentence /
3-topic boundary recovery, per-chunk re-embedding contract);
`_detect_boundaries` (warm-up quiet, short-input guard); **Q1
benchmark** (chosen tuple recovers 3-topic boundaries `[5, 10]`
and stays quiet on smooth prose; `window=5` misses
sentence-5 boundary; `drop=0.10` over-fires on the smooth
prose); `_enforce_size_bounds` (merge below-min, keep solo
below-min, split above-max on lowest seam, recursive split,
single-oversized-sentence kept as-is); `ChunkRecord` NamedTuple
contract.

Verified end to end:

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

The full-suite figure went from 146 → 168 passed without a DB
fixture (+22 chunker tests, no regression); the 18 skipped are
the unchanged DB-fixture-gated server tests. With the
`pgvector/pgvector:pg15` DB fixture active the baseline is 186
passed.

Implementation notes picked up at CP3 (recorded so CP4 / CP5
don't re-derive):

- **ruff RUF001 / RUF003 ambiguous-glyph lint on the CJK
  regex.** Pattern-intent CJK chars `？！。“‘` look like accidental
  Asian punctuation to ruff. Resolved with two per-string
  `# noqa: RUF001` lines on the segments where the ambiguous
  chars are pattern members. The EN-DASH `–` in module comments
  was the easy half — replaced with HYPHEN-MINUS.
- **pytest collection collision on `tests/__init__.py`.** Plain
  empty `tests/__init__.py` collides with every other plugin's
  `tests/` namespace (`ModuleNotFoundError: No module named
  'tests.test_chunker'` during collection). Matches the
  analytics_sink / keyword_block / token_counter pattern —
  none of them ship one either.
- **Above-max split recursion is correct; the test fixture had
  to grow into the bound.** A single split of three 300-word
  sentences leaves a 600-word half that the recursive splitter
  correctly splits again — so the fixture sentences are 250
  words each (split lands exactly at 500 words and accepts
  without recursion).

CP1 / CP2 recaps preserved below for cold-start sessions:

**scope_guard implementation CP1 + CP2 of 8 done (2026-05-18,
commits `2511c3a` + `b6cdf5f` + `2fe84e6` + docs-finalize).**

CP2 ships the workspace package at
`packages/llm_tracker_plugin_scope_guard/` per ADR-0030 §D9:
`pyproject.toml` with entry point
`scope_guard → llm_tracker_plugin_scope_guard.plugin:ScopeGuard`,
`plugin.toml` declaring `hooks=[on_persisted]` /
`capabilities=[egress_http]` / two OpenAI egress destinations /
`db_namespace="scope_guard"` / `min_content_level="L3"`, and six
module stubs (`plugin.py`, `embeddings.py`, `judge.py`,
`chunker.py`, `pipeline.py`, `storage.py`) whose docstrings
point to the CPs that fill them in. New direct dep
`pgvector>=0.2` for the `vector(1536)` SQLAlchemy / asyncpg
adapter; `numpy 2.4.5` arrives transitively and CP3 chunker
reuses it for adjacent-sentence cosine math. Verified end to
end: ruff clean, `uv sync` installs the workspace package +
`pgvector==0.4.2` + `numpy==2.4.5`,
`PluginManifest.from_path()` accepts §D9 verbatim,
`importlib.metadata` entry point loads + instantiates
`ScopeGuard` cleanly, 164 tests pass (zero new tests by design;
CP2 is skeleton-only).

CP1 ran earlier in the same session, recap below:

**scope_guard implementation CP1 of 8 done (2026-05-18, commits
`2511c3a` server-migration + `b6cdf5f` docs-finalize).** ADR-0030 Accepted
by operator at the start of this session; CP1 ships migration
`0010_scope_guard_tables` — three tables (`scope_documents`,
`scope_chunks`, `scope_alerts`), the `vector` extension, RLS on
the two corpus tables (migration 0005 `_org_isolation` +
`_admin_access` pattern), no-RLS on `scope_alerts` (migration
0007 `plugin_analytics` pattern), and `GRANT SELECT / INSERT /
UPDATE / DELETE` to `llm_tracker_app`.

Local test environment switched `postgres:15` →
`pgvector/pgvector:pg15` so `CREATE EXTENSION vector` works
unconditionally — Operator picked Option A (image bump) over
Option B (extension guard) at the start of the session;
reasoning is that `vector` is the plugin's core data type, not
an operational-only scheduler like 0009's `pg_cron`. STATUS.md
§"Local dev loop revival" updated in the same docs-finalize
commit.

Round-trip verified end-to-end:
`alembic upgrade head` → `downgrade -1` → `upgrade head`;
**164 tests pass under the DB fixture, 0 regression.** The 164
figure is this session's accurate baseline; the older
"354 passed" line in STATUS history is pre-archive (commit
`8ef166d` removed the local sidecar in 2026-05-17, rescuing
only SDK tests).

Implementation-axis surprises picked up during CP1, recorded
for the next CPs:

- **asyncpg multi-statement quirk.** First migration draft
  sent the schema block as one `op.execute(big_string)`;
  asyncpg rejects multi-statement prepared inputs ("cannot
  insert multiple commands into a prepared statement"). Fix:
  per-statement dispatch via `_UPGRADE_STATEMENTS` tuple
  iterated with one `op.execute` per item. Migration 0009
  sidesteps the same trap by wrapping its body in a single
  `DO $$ ... END$$;` block; 0010 picks the per-statement style
  because the bulk of its work is ordinary DDL, not procedural.
- **Q3 resolved early — new `0011_scope_alerts_retention`
  migration over amending 0009.** Decided at CP1 time so CP8
  has a single direction. Each retention concern owns its own
  reversible migration; mixing a third cron row with a
  different table / column / unit shape into 0009 muddies the
  downgrade.

The remaining three ADR-0030 open questions are pinned at:
Q1 chunker algo → CP3 (small benchmark + frozen choice);
Q2 ANN index → MVP linear scan, revisit when any org's chunk
count exceeds ~10k; Q4 judge prompt → CP4 (frozen module-top
string).

CP2 through CP8 work board lives in
`docs/worklog/2026-05-18-scope-guard-impl.md` §"Checkpoint plan".

### Prior workstream — ADR-0030 design + acceptance (2026-05-18, earlier today)

**ADR-0030 design workstream (2026-05-18, commit `27b6d92` +
finalize).** Documentation only — no code shipped. The Phase 1c
`scope_guard` plugin design captured into an ADR (Proposed) so the
implementation session has a fixed target. User had run a private
design pass on nine axes (execution model, pipeline shape,
embedding/judge providers, chunking, message-input construction,
similarity, schema, registration UX, packaging); Cowork surfaced four
ambiguities, the user resolved them with `"전부 default OK"`:

- **Q1** — Stage-2 judge through the same EgressGuard egress path as
  Stage-1 (OpenAI `gpt-4o-mini` instead of brief's "Anthropic SDK
  bypass"). One vendor, two destinations, one audit trail.
- **Q2** — Embedding input is **user-initiated turns only**. No
  assistant text. No top-level `system`. No `tool_result` blocks.
- **Q3** — `scope_alerts` gains four extra columns
  (`stage` / `stage2_verdict` / `stage2_reason` / `matched_chunk_id`)
  so threshold tuning has direct evidence on the table.
- **Q4** — OpenAI external-API disclosure binds to a follow-up
  `docs/deploy.md` edit that lands with the implementation
  checkpoint, not this ADR.

ADR-0030 **settles ADR-0002** in reframed form — Phase-1's
synchronous-block spec becomes async monitoring on `on_persisted`
with alerts on `scope_alerts`. The synthetic-SSE block path is
explicitly Deferred (real-time blocking returns once threshold
stability data accumulates over ≥ 30 days of alerts).

### Prior workstream — queued follow-up batch round 2 (2026-05-17)

User asked to clear three executable follow-ups from the prior
batch's queue. All three shipped:

- **`4fef915` (Block/Abort end_exchange cleanup).** Added an
  explicit `plugin_host.end_exchange(exchange_id)` immediately
  before each `return block_response(...)` short-circuit in
  `forwarder.py` (the three Block/Abort sites — `on_request_received`
  Block, `before_forward` Block, `on_upstream_response_start`
  Abort). Before this, cleanup of the per-exchange ctx ran only via
  `block_response.gen()`'s `finally`, which fires only when the
  ASGI server iterates the synthetic stream — leaving a leak window
  if the client disconnects before iterating. Matches the axis-2
  cleanup pattern. New test
  `test_block_short_circuit_cleans_ctx_without_iterating_response`
  pins the behaviour without relying on response-stream iteration.
- **`3fe0caa` (DB-fixture test for record_exchange_failure).** New
  `test_record_exchange_failure_db.py` alongside
  `test_storage_smoke.py`. Pins the row-write half of ADR-0027
  axis 2 against the DB fixture (the forwarder-level unit tests in
  `test_proxy_forwarder_hooks.py::test_axis2_*` exercise the
  forwarder branching and ctx cleanup but stop short of the actual
  INSERT). Two shapes covered: `status_code=599` (network-error
  sentinel) and `status_code=401` (upstream non-2xx). Each asserts
  the row exists with the correct `exchange_id` + `org_id`,
  close-out fields (`ended_at`, `latency_ms`) populated, and
  `blocked_by` NULL (failure is not a plugin decision). Skips
  under the same `LLMTRACK_TEST_DATABASE_URL` gate as the rest of
  the DB-fixture suite.
- **`cd21da3` (6-month retention cron migration 0009).** Migration
  `0009_retention_deletion_job` schedules two daily `pg_cron` jobs
  at 03:00 UTC:
  `llm-tracker-retention-exchanges` runs
  `DELETE FROM public.exchanges WHERE started_at <
  (EXTRACT(EPOCH FROM now() - INTERVAL '6 months') * 1000)::bigint`
  (the unix-ms representation is unavoidable — `started_at` is
  `BigInteger`); `llm-tracker-retention-plugin-analytics` runs
  `DELETE FROM public.plugin_analytics WHERE created_at <
  now() - INTERVAL '6 months'` (timestamptz, direct).
  The `DO $$ … $$` block is gated on
  `pg_available_extensions WHERE name='pg_cron'` so the alembic
  cycle stays green on stock Postgres dev environments (where the
  operator falls back to the manual DELETE in `docs/deploy.md`).
  Downgrade unschedules both jobs by name but does **not** drop
  the `pg_cron` extension (project-wide blast-radius rule).
  `docs/deploy.md` "Retention is 6 months" bullet updated to name
  the jobs, the gating posture, and the inspection query.

**Verification recap:**

```
$ .venv/bin/python3.12 -m ruff check <all modified files>
All checks passed!
$ .venv/bin/python3.12 -m ruff format --check \
    packages/llm_tracker_server/alembic/versions/0009_retention_deletion_job.py
1 file already formatted
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_server/tests -q
59 passed, 18 skipped in 5.71s
# Was 58 / 16 — +1 forwarder test (Block-without-iteration),
# +1 DB-fixture file (2 skipped tests under no-DB shape).
$ LLMTRACK_DATABASE_URL=postgresql://localhost/dummy \
    .venv/bin/python3.12 -m alembic upgrade \
    0008_drop_tool_call_count:0009_retention_deletion_job --sql
... emits BEGIN; <DO $$ … $$>; UPDATE alembic_version …; COMMIT;
$ LLMTRACK_DATABASE_URL=postgresql://localhost/dummy \
    .venv/bin/python3.12 -m alembic downgrade \
    0009_retention_deletion_job:0008_drop_tool_call_count --sql
... emits BEGIN; <unschedule loop>; UPDATE alembic_version …; COMMIT;
```

Operational consequences after the next `fly deploy`:

1. `alembic upgrade head` advances stamp from
   `0008_drop_tool_call_count` to `0009_retention_deletion_job`.
   `cron.job` gains two `llm-tracker-retention-*` rows; no data
   deletion at migration time.
2. First scheduled deletion fires at the next 03:00 UTC tick; the
   recurring job deletes rows older than 6 months on each tick.
3. The forwarder's Block/Abort short-circuits now clean up the
   per-exchange ctx immediately (no more reliance on synthetic
   stream iteration); behaviourally identical for clients that
   iterate the response, leak-tight for clients that disconnect
   before iterating.

---

### Prior workstream — Queued follow-up batch round 1 (closed 2026-05-17 earlier)

**Queued follow-up batch round 1 (2026-05-17, commits `1a886e6` +
`7b20125` + `0db0bac` + finalize).** User asked to clear the five
queued items in one batch, surfacing only the decisions that
actually needed input. Two decisions surfaced (`tool_call_count`
fate — drop; `plugin_analytics` RLS — defer + correct STATUS
framing). Three items shipped:

- **`1a886e6` (deploy.md PG16+ paragraph).** New § between the
  pgbouncer/asyncpg note and the "subsequent deploy" §. Names the
  PG16 split of role membership into (admin / inherit / set), the
  Supabase auto-grant-inherit-only pattern, the
  `InsufficientPrivilegeError` symptom, and the conditional fix in
  migration `0006_grant_app_role_set` (PG16+ uses `WITH SET TRUE`;
  PG15 uses plain GRANT). Closes the future-deploy gap for RDS /
  Cloud SQL / Neon.
- **`7b20125` (tool_call_count drop, migration 0008).** Column was
  seeded at 0 by CP9 and never populated; ADR-0028 §Non-goals had
  already stated the placeholder posture. Migration drops the
  column from `public.exchanges` (sibling
  `public.plugin_analytics.tool_call_count` left untouched);
  `storage.models.Exchange` and both INSERT helpers in
  `storage.exchanges` are updated; three test files have the
  placeholder removed from `Exchange()` constructors. Downgrade
  re-adds with the original `NOT NULL DEFAULT 0` shape.
- **`0db0bac` (ADR-0027 axis 2 impl — pre-SSE upstream-failure
  row write).** Before this an upstream failure before the first
  SSE event left no row in `public.exchanges` at all; the
  open-INSERT lives inside the streaming generator's `else`
  clause which never runs on this shape. Implementation: new
  `record_exchange_failure` helper (signature parallels
  `_blocked` plus `status_code`), `httpx.RequestError` `try /
  except` around `http_client.send` with `status_code=599`
  sentinel for network errors, and a `status_code != 200`
  short-circuit immediately after for upstream non-2xx. Both
  paths explicitly call `plugin_host.end_exchange(exchange_id)`
  because the streaming generator's `finally` is the normal
  ctx-cleanup site and never runs on short-circuit paths. Two
  forwarder-level tests added (401 forward + ConnectError → 503).

Cleanup (no commit; no git-tracked file changed): `rm -rf
packages/llm_tracker/ packages/llm_tracker_plugin_supabase_sink/`
removed the empty shells with their `__pycache__/*.pyc` stragglers
(the `git rm` earlier today left the directory shells behind).

**Decision that returned to the queue.** While inspecting
`packages/llm_tracker_server/alembic/versions/0007_plugin_analytics.py`
to write the RLS migration, the docstring revealed: 0007 explicitly
chose "no RLS on this table" with reasoning ("Analytics is internal
— the plugin queries this directly from operator tooling without
going through the request-scoped session"). The advisor's "newly
surfaced gap" framing previously in STATUS was factually wrong:
0007 made the deliberate choice, just not as an ADR. Reversing it
is ADR-level work, not a routine follow-up. Deferred + STATUS
side-quests entry corrected (see below).

**Latent gap surfaced for separate follow-up.** The Block/Abort
short-circuit returns in the forwarder also lacked explicit
`plugin_host.end_exchange()` — same shape as the axis 2 short-
circuit before that CP. Closed by round 2's `4fef915`.

---

### Prior workstream — ADR-0029 production smoke + doc reconciliation (closed 2026-05-17 earlier)

**ADR-0029 production smoke + doc reconciliation (2026-05-17, commit
`d7f17c0` + `d4a7891`).** Operator deployed `a4c08b3` to Fly
(release `v11`, completed ~16m before the smoke). Two threads in this
session: planned verification of the ADR-0029 scrubber on real
production traffic; unplanned `claude-manage` recovery + doc
reconciliation against a falsified assumption that the smoke
surfaced.

**Production smoke results.** Two `plugin_analytics` rows from the
live smoke (`01KRRS5S2VNPPCS5QNM4P2HG37` end_turn /
`01KRRS5PJGVDK4J6XND3JWKCEH` prior turn, both 2026-05-16 16:16 UTC,
under `model_served=claude-opus-4-7`). Injected `sk-deadbeef12345678`
lands as `[REDACTED:secret]` in `messages_json`; raw value absent.
`response_json` was not affected on this exchange because the model
did not echo the token. Scrubber is live on production traffic.

**Falsified assumption.** The prior ADR-0029 consent worklog +
ADR-0029 §Axis 6 + ADR-0028 §Open questions + `docs/plugins.md` §3.2
+ `hook_context.py` module docstring all claimed `analytics_sink`
parses the request body on its own path and writes the canonical body
to `plugin_analytics`. Inspection of
`packages/llm_tracker_plugin_analytics_sink/.../plugin.py:113` shows
the plugin actually reads through `ctx.request_text()` (and
`ctx.response_content_json()` in `_build_row`), and the SDK accessors
at `hook_context.py:120` + `hook_context.py:188` both run `scrub()`
before returning. So `plugin_analytics` rows inherit the scrubbed
shape from the accessor, not the canonical one — verified live by the
`sk-deadbeef12345678` injection. The descriptive paragraph in five
places was factually wrong.

**Resolution (user picked Option A).** Align docs to production; keep
privacy-first posture. No code change to plugins or accessors. Commit
`d7f17c0` reconciles all five locations:

- ADR-0029 §Axis 6 body + §Open questions (`messages_json` bullet
  rewritten as "Canonical-body retention for incident response";
  the prior bullet's premise was the load-bearing wrong claim).
- ADR-0028 §Open questions: 2026-05-17 update note clarifying that
  the scrubber landed at the SDK accessor — not a post-extractor
  pass — so faithful-reassembly governs the in-memory
  `_parsed_response` only, not the row written by the current
  plugin.
- `docs/plugins.md` §3.2: replaced the "storage layer reads
  canonical" paragraph with the actual split — server-core writes
  store metadata only; plugin-mediated writes carry the scrubbed
  shape.
- `hook_context.py` module docstring: same correction in SDK source
  so plugin authors reading the SDK have the right picture.
- Prior worklog `2026-05-17-adr-0029-consent.md`:
  `> Correction (2026-05-17, ...)` blockquote under the wrong bullet.
  Frozen-narrative rule from CLAUDE.md §2.3 preserved: the original
  bullet is untouched.

**Side-finding (env, not code).** `claude-manage` returned `command
not found` immediately after the deploy. The agent package was still
editable-installed (`uv pip list` showed `llm-tracker-agent`), but
the console_script in `.venv/bin/` had been skipped by yesterday's
housekeeping `uv sync` (which dropped three packages). Restored with
`uv sync --reinstall-package llm-tracker-agent`. Environment-only fix;
no commit. Documented in the new worklog §"What was done".

**Secondary discovery (queued, not blocking).** Supabase advisor
flagged `public.plugin_analytics` as RLS-off. CP13-b §Decisions 4
named only `orgs`, `api_tokens`, `alembic_version` as intentionally
RLS-off; `plugin_analytics` was added in migration 0007 *after* that
decision and needs its own RLS policy. Added to side-quests below.

**Verification recap:**

```
$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_sdk/src/llm_tracker_sdk/hook_context.py
All checks passed!
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_sdk/tests/test_hook_context.py -q
19 passed in 0.06s
$ fly releases -a llm-tracker-server | head -3
 v11     │ complete │ Release │ ... │ 16m24s ago      ← ADR-0029 image (a4c08b3)
 v10     │ complete │ Release │ ... │ 11h18m ago
```

External (non-team) testing of the central server is now fully ready
to proceed: the policy is set (ADR-0029), the scrubber is
operationally verified, and the descriptive docs match what the
database actually carries.

---

### Prior workstream — Housekeeping pass (closed 2026-05-17 earlier)

**Housekeeping pass — archive + sidecar removal (2026-05-17, commits
`8ef166d` + `3d76d1f`).** Two user-supplied tasks executed in
sequence:

- Task 1 — moved 7 superseded ADRs into `docs/decisions/archive/`
  (0001, 0004, 0006, 0007, 0008, 0016, 0021). `docs/decisions/README.md`
  now documents the archive directory as historical-only. The 22
  remaining top-level ADRs are the active set.
- Task 2 — deleted `packages/llm_tracker/` (the original local
  sidecar; superseded by `llm_tracker_server` + `llm_tracker_agent`
  per ADR-0017) and `packages/llm_tracker_plugin_supabase_sink/` (the
  closed Phase 2 reference plugin from 2026-05-08). Local branch
  `archive/local-sidecar` was created at the pre-deletion HEAD to
  preserve the full history; it is **not pushed** (per CLAUDE.md §10
  and the user's closing instruction).

Two correctness corrections came up during Task 2 and were resolved
via `AskUserQuestion`:

1. `supabase_sink/tests/test_e2e.py` imported from the sidecar's
   internals (`llm_tracker.plugin_host.host`,
   `llm_tracker.egress_guard.guard`,
   `llm_tracker.storage.models`). User chose to archive the whole
   supabase_sink package alongside the sidecar — its workstream is
   already closed, its runtime depends only on `llm_tracker_sdk +
   structlog`, and only the e2e test tied it to the sidecar.
2. Five test files under `packages/llm_tracker/tests/` were
   misplaced SDK tests, importing only from `llm_tracker_sdk` (the
   kept package). Including the freshly-added ADR-0029 scrubber +
   accessor-wiring tests from commit `a4c08b3` (~20 tests dated
   2026-05-17). User chose to rescue them into a new
   `packages/llm_tracker_sdk/tests/` directory (added to pytest
   testpaths). Git auto-detected them as renames in the commit.

The 12 other test files in `packages/llm_tracker/tests/` tied to
sidecar internals (`test_cli_manage`, `test_cli_plugins`,
`test_config`, `test_content_levels`, `test_audit_triggers`,
`test_egress_client`, `test_egress_guard`, `test_plugin_host`,
`test_policy`, and three under `proxy/`) died with their package as
intended.

Test count deltas (no-DB baseline):

```
pre-housekeeping (post-ADR-0029):  338 passed, 16 skipped
post-housekeeping:                 143 passed, 16 skipped
```

The 195-test drop = sidecar (~140) + supabase_sink (~55) tests dying
with their packages, partially offset by the 55 rescued SDK tests.
DB-fixture count not re-measured this session — rescued tests are
pure unit tests; deleted sidecar/proxy tests had been the DB-fixture
consumers, so the next DB-fixture run will drop by a similar margin
with no information loss (the deleted tests covered deleted code).

`uv sync` cleaned the lockfile by uninstalling `llm-tracker`,
`llm-tracker-plugin-supabase-sink`, and `respx` (the latter only used
by the now-deleted test suites). `[tool.uv.workspace].members` glob
(`packages/*`) needed no edit; the deleted packages disappear
automatically.

`grep` for inbound references to the moved ADR paths surfaced 11 hits
in historical worklog files. Left untouched per CLAUDE.md §2.3
(surgical changes; worklogs are frozen narratives of past sessions).

---

### Prior workstream — ADR-0029 consent + data-handling (closed earlier 2026-05-17)

**ADR-0029 — consent + data-handling — Accepted (2026-05-17).** The
six-axis decision packet the user supplied lands as policy + code in
one commit (`a4c08b3`):

- **Axis 1** — full L3 storage; `LLMTRACK_PLUGINS_DISABLED` stays the
  operator off-switch for `analytics_sink`.
- **Axis 2** — documentation-only disclosure (`docs/deploy.md` new
  "Data collection & privacy" section; `docs/plugins.md` §3.2). No
  per-task consent UI.
- **Axis 3** — 6-month retention policy stated; automated deletion
  deferred.
- **Axis 4** — operator-handled SQL deletion on `org_id` / `session_id`;
  typed endpoint deferred until `session_id` is real (currently
  hardcoded `"server"`).
- **Axis 5** — `sk-`/`lts_`/`Bearer <value>`/email regex redaction with
  kind-tagged replacements (`[REDACTED:secret|token|bearer|email]`).
  Privacy-tilted: `\bsk-` over-redacts after `-` (documented + pinned
  by test).
- **Axis 6** — scrubbing at the SDK accessor (`HookContext.request_text`,
  `HookContext.response_content_json`); raw `_raw_request_body` and
  `_parsed_response` left untouched so storage stays canonical per
  ADR-0028.

The pre-existing structlog log-side scrubber
(`llm_tracker_server.proxy.credential`) stays as defence-in-depth for
log event dicts; ADR-0029 explicitly does not unify the two layers
today.

Test deltas (verified with and without the DB fixture):

```
no-DB:  338 passed, 16 skipped, 4 warnings in 13.05s   (was 318 / +20)
DB:     354 passed, 4 warnings in 30.88s               (was 334 / +20)
```

The +20 splits into 16 new scrubber unit tests
(`packages/llm_tracker/tests/test_scrubbers.py`) + 4 new accessor-level
wiring tests in `packages/llm_tracker/tests/test_hook_context.py`.

Smoke from the 2026-05-16 closure remains the latest production
state — the central server is still on commit `8138d91` until the
operator runs `fly deploy` to pick up `a4c08b3`. No code-side
operator-smoke is owed for this CP because the scrubber is in the SDK
that `analytics_sink` already imports; the next routine deploy lands
it without plugin-side changes.

The verbatim `response_json` shape from production:

```json
{
  "model": "claude-opus-4-7",
  "content": [
    {"type": "thinking", "thinking": "", "signature": "EoEC..."},
    {"type": "tool_use",
     "id": "toolu_01HgwgDtcBKBChGSpUBQeLoj",
     "name": "Bash",
     "input": {"command": "date \"+%Y-%m-%d %H:%M:%S %Z\"",
               "description": "Print current date and time"}}
  ],
  "stop_reason": "tool_use",
  "usage": {"input_tokens": 6, "output_tokens": 152,
            "cache_read_input_tokens": 75512,
            "cache_creation_input_tokens": 133}
}
```

What this row independently proves:

- **ADR-0028 faithful reassembly is live.** `content` carries both
  the thinking block (with `signature_delta` preserved despite an
  empty `thinking_delta` stream) and the tool_use block, whose
  `input` is a *parsed dict* — `_finalize_input_json` parsed the
  `input_json_delta` buffer cleanly, no `_input_json_raw` fallback.
  Pre-`8138d91` this row would have been `content: []`.
- **Option B (2026-05-14) is live on the same image.** All five
  SSE-derived columns are populated: `model_served`, `input_tokens`,
  `output_tokens`, `cache_read_input_tokens`,
  `cache_creation_input_tokens`, and `stop_reason`. The 2026-05-14
  worklog's four-step recipe (deploy → `/admin/plugins` → real
  request → Supabase MCP check) is end-to-end satisfied.

`keyword_block` also exercised in production: operator set
`LLMTRACK_KEYWORD_BLOCK_LIST = "no_response"` in `fly.toml` (was the
empty default), redeployed, and confirmed the operator-configurable
block path. Kept as the live operator config post-smoke — see the
`infra:` commit in "Recent commits" below.

Both workstreams are **production-validated as of this CP**. Smoke
gate closed.

Auxiliary CP carry-overs (unchanged from 2026-05-16 worklog):

- **`exchanges.tool_call_count` stays at 0 placeholder.** Derive
  from `response_json.content` via `jsonb_path_query` at analysis
  time; column's fate (deprecate / drop / leave) queued.
- **Backfill posture**: pre-`8138d91` `plugin_analytics` rows
  under a tool_use `stop_reason` carry `content: []` irrecoverably.
  Operator queries on historical rows must filter
  `WHERE created_at >= <deploy_time_of_8138d91>`.

---

### Prior workstream — Phase 3b (closed 2026-05-13)

**Phase 3b — CLOSED (live smoke verified by user).** Three commits
in that session built the agent:

1. `c124458` — pre-step tightening of `CLAUDE.md` (central-server
   stack/structure correction; token trim). Not Phase 3b proper.
2. `79a0ae9` — ADR-0024 (agent fail-closed) + ADR-0025 (Python CLI
   distribution). Both Accepted. Settle Phase-3a items #1 and #4.
3. `fbd36e4` — agent package. Net +511 lines: `pyproject.toml` +
   `__init__.py` + `config.py` + `proxy.py` + `cli.py` + 4 config
   tests + 3 proxy tests + 1 line in root `pyproject.toml`
   testpaths + uv.lock churn.

Verification recap (full output in
`docs/worklog/2026-05-13-phase3b-agent.md` §Verification):

```
$ uv run ruff check packages/llm_tracker_agent
All checks passed!
$ uv run pytest packages/llm_tracker_agent/tests/ -v
7 passed in 0.12s
$ uv run pytest -q
300 passed, 16 skipped, 4 warnings in 12.40s
$ uv run claude-manage setup lts_test_token \
      --server-url http://localhost:18080 --port 18080
Saved /Users/minseop/.llm-tracker/config.toml. Run `claude-manage` to start.
$ ls -la ~/.llm-tracker/config.toml
-rw-------@ 1 minseop  staff  84 May 13 17:19 ...
```

`-rw-------` confirms the 0o600 chmod fired. The test token
(`lts_test_token`) left in the file is junk — the external smoke
tester needs to re-run `claude-manage setup <real-token>` before
launching Claude Code through the proxy in earnest.

**Spec deviations** (recorded for the next reader):

- Spec asked for `os.execvp("claude", ...)`; implementation uses
  `subprocess.run(["claude", ...])` because `os.execvp` replaces
  the Python process image and kills the in-thread uvicorn proxy
  before Claude's first request hits it. Inline comment in
  `cli.py._run` explains; the worklog §Decisions captures the
  reasoning.
- Proxy uses `aiter_bytes()` not `aiter_raw()` because
  `httpx.MockTransport(content=b"...")` returns a response with an
  already-consumed stream, breaking `aiter_raw()` in tests.
  `aiter_bytes()` has an explicit fast-path for buffered content
  and is production-equivalent on SSE (no gzip). Response-side
  `Content-Encoding` is therefore stripped to keep the downstream
  client from double-decoding.

**Follow-up after the main checkpoint** (commit `ac4370c`):
`_pick_port` helper added so two `claude-manage` instances no
longer collide on the preferred port. The first claims
`config.local_port`; subsequent instances fall back to a
kernel-assigned ephemeral port and announce on stderr. Each
instance owns its own proxy; killing one no longer breaks the
others. Two unit tests added; full suite now 302 passed / 16
skipped. Worklog §"Follow-up — multi-instance via ephemeral port"
captures the race-window note.

**Closure — live smoke verified by user** (later in this session):

- **Positive**: `claude-manage` → live Fly.io server →
  Anthropic → back. 8 new timed rows in `public.exchanges`
  scoped to demo `org_id=c6fcdd23-...` covering opus-4-7 (5),
  opus-4-5 (1, CP14 baseline), haiku-4-5 (3). `latency_ms`
  range: haiku 913–3568 ms, opus 1820–12010 ms. Sub-second
  haiku is direct evidence that server-side overhead (auth +
  RLS + plugin host + INSERT) is in the tens of ms; the rest
  is Anthropic generation time.
- **Negative**: pointed `--server-url` at `http://127.0.0.1:9`
  (discard port). `claude-manage` returned 503 with body
  `{"detail": "llm-tracker central server unreachable"}`; the
  in-process Anthropic SDK retried 10× before surfacing the
  failure. Request never reached Anthropic — ADR-0024
  fail-closed contract held end-to-end.
- **Latency outlier note** (not blocking): the 12010 ms
  opus-4-7 row stands out; full diagnosis is gated on Option B
  SSE extractor populating `output_tokens` so we can compute
  ms/token and identify whether it was a long response or a
  cold-path call. Flagged for Option B work.

Phase 3b is now in production use. New team members install via
`uv sync` (workspace) or
`pip install "git+<repo>.git#subdirectory=packages/llm_tracker_agent"`
(standalone), then `claude-manage setup <token> && claude-manage`.

---

### Prior workstream — Phase 3c CP14 follow-up Option A (closed 2026-05-13)

**Phase 3c CP14 — operator-only end-to-end smoke — CLOSED.** The
first real `/v1/messages` curl through the live server hit a P0
500 inside `AuthMiddleware.dispatch`. fly logs traceback:

```
asyncpg.exceptions.InsufficientPrivilegeError:
    permission denied to set role "llm_tracker_app"
[SQL: SET LOCAL ROLE llm_tracker_app]
File ".../llm_tracker_server/auth/middleware.py", line 83
```

Diagnosis via Supabase MCP `execute_sql` on `pg_auth_members`:
`postgres` was *already* a member of `llm_tracker_app` (Supabase
auto-grants `postgres` membership of newly created roles), but
with `admin_option=true, inherit_option=false, set_option=false`.
PG16 split role membership into three orthogonal options; the
pre-PG16 coupling of "membership implies SET ROLE" no longer
holds upstream. The auto-grant had INHERIT only — exactly the
combination that lets `current_user='postgres'` *see*
`llm_tracker_app`'s privileges (which is why CP5/CP6 passed
locally against `cp2` superuser-mode tests) but blocks
`SET LOCAL ROLE` (which is what RLS-enforcing auth middleware
actually needs).

Immediate unblock via Supabase MCP:

```sql
GRANT llm_tracker_app TO postgres WITH SET TRUE;
```

Post-grant `pg_auth_members` shows a second row with
`set_option=true, inherit_option=true` alongside the original
auto-grant row (Postgres ORs option rows; effective: all three
true). Cosmetic-only: the two rows could be collapsed via REVOKE
+ GRANT but behavior is unchanged.

Durable fix shipped as alembic migration `0006_grant_app_role_set`
(commit `458a4ba`):

- PG16+ branch: `GRANT llm_tracker_app TO CURRENT_USER WITH SET
  TRUE`
- PG15 branch: plain `GRANT llm_tracker_app TO CURRENT_USER`
  (the `WITH SET TRUE` qualifier is PG16+ only; would syntax-error
  on the local docker test fixture)
- Branch selector: `server_version_num >= 160000` inside a
  `DO $$ ... END $$` block; emit the right form per server.

`CURRENT_USER` (not hardcoded `postgres`) keeps the migration
portable across deploy environments where the connecting role
might be named differently. Live Supabase `alembic_version` is
still `0005` until the next `fly deploy` runs `alembic upgrade
head`; the migration is idempotent so the next deploy is a no-op
on the DB side and just advances the alembic stamp.

Verification:

```
$ # pre-fix (CP14 first attempt, operator-run curl)
HTTP/2 500 Internal Server Error

$ # post-fix invalid-token probe (no Anthropic key needed)
$ curl -X POST .../v1/messages -H "X-LLM-Tracker-Token: bogus" \
    -d '{"model":"claude-opus-4-5","max_tokens":1,"messages":[]}'
HTTP/2 403
{"detail":"unknown or revoked token"}

$ # post-fix real curl (operator-run, valid Anthropic key)
HTTP/2 200

$ # fly logs --since 5m (the 200 path)
proxy.forward (forwarded_credential: true)
HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"
INFO: "POST /v1/messages HTTP/1.1" 200 OK
(no traceback)

$ # Supabase MCP: SELECT FROM exchanges ORDER BY started_at DESC
[1 row: id=01KRFVTG1E7Q72QN7E5MP26JXY,
 org_id=c6fcdd23-... (org_name="demo"),
 started_at=2026-05-13 05:09:16.974+00,
 endpoint=v1/messages, provider=anthropic, content_level=L3]

$ .venv/bin/python3.12 -m ruff check \
    packages/llm_tracker_server/alembic/versions/0006_grant_app_role_set_membership.py
All checks passed!

$ .venv/bin/python3.12 -m pytest packages/llm_tracker_server/tests -q
61 passed in 25.70s
```

CP14's three success criteria from
`docs/worklog/2026-05-11-phase3c-plan.md`:

- ✅ Response stream returns to client unchanged (operator-confirmed
  200 + SSE bytes match Anthropic emit).
- ✅ Exactly one row lands in `public.exchanges` scoped to demo
  org. (Two demo-scoped rows total — the second is a 400-BadRequest
  debug row from the same session, also evidence that
  multi-tenancy isolation fires on every request regardless of
  upstream outcome.)
- ✅ `fly logs` since request timestamp shows no traceback.

**Secondary finding** (carved out per user direction as a separate
track): the successful row's response-side columns are all NULL —
`ended_at`, `model_requested`, `model_served`, `status_code`,
`input_tokens`, `output_tokens`, `latency_ms`, `stop_reason`. The
request-open INSERT works; the stream-close UPDATE that should
fill the response-side fields is silent on a 200-OK SSE. STATUS
CP9 had previously flagged `model_served=null` only for HTTP-error
(non-SSE) responses as a by-design observability hole; the current
finding extends that hole into the happy SSE path. Suspected
location: CP8's server-side plugin host port (`on_persisted` hook
dispatch) or CP9's storage UPDATE path. Owner of next CP / ADR
TBD — fresh worklog when picked up.

Phase 3c is **closed (operator smoke validated)**. The OAuth
Claude Code question that started this session is **not** yet
answerable in the affirmative — it remains gated on Phase 3b
(thin local agent or equivalent header-injection sidecar), which
itself is gated on Phase-3a items #1/#4. Operator-only smoke is
the proof-point for everything Phase-3c-rated, and that is now
in.

---

### Prior workstream — ADR-0023 server auth header rename (closed 2026-05-13)

**ADR-0023 — server auth header rename — landed (CP14 prep).** A
P0 blocker surfaced while preparing CP14: OAuth Claude Code users
(the majority) send their Anthropic credential in `Authorization:
Bearer <oauth-token>`. `AuthMiddleware` was reading the same slot
for our per-org token, eating the OAuth bearer and returning `403
unknown or revoked`. The local proxy never had this problem because
it was a transparent pass-through with no auth layer; the central
server is the first surface in this project that *consumes* a
header. ADR-0023 (commit `21e9fa5`) renames the server-auth header
to `X-LLM-Tracker-Token`; `Authorization` is now reserved for the
Anthropic credential pass-through (OAuth bearer, or absent for
`x-api-key` users) and flows through to upstream untouched.

Source change shipped in `af6bd8f`:

- `AuthMiddleware` reads `X-LLM-Tracker-Token` (was: `Authorization:
  Bearer ...`); the bearer-scheme parse is gone, the new header is
  a plain opaque value.
- `proxy.forwarder._LOCAL_ONLY = {"x-llm-tracker-token"}` (was:
  `{"authorization"}`). The strip set no longer touches
  `Authorization`, fixing the OAuth pass-through.
- Two new credential-passthrough tests pin the contract:
  `test_outbound_strips_x_llm_tracker_token` and
  `test_outbound_passes_authorization_bearer_through`.
- Module docstrings (`auth/__init__.py`, `auth/middleware.py`,
  `proxy/credential.py`, `proxy/forwarder.py`) updated; the
  Authorization-passthrough case is now explicit at every level.

Docs change in `21e9fa5`:

- ADR-0023 (Accepted) — amends ADR-0020 Axis 1 only; Axis 2
  (Anthropic credential pass-through) untouched.
- `docs/deploy.md` Step 5–6 curl + prose moved to
  `X-LLM-Tracker-Token`.
- `.env.example` Section 1 swapped; Section 2 extended to list
  `Authorization: Bearer <oauth-token>` as a third accepted form.

Verification (full transcript in worklog
`docs/worklog/2026-05-13-auth-header-rename.md` §Verification):

```
$ .venv/bin/python3.12 -m ruff check <7 modified files>
All checks passed!

$ .venv/bin/python3.12 -m pytest packages/llm_tracker_server/tests -q
............................................................. 61 passed in 23.04s
```

The "still on pre-rename build until next `fly deploy`" note that
sat here at finalize time turned out to be wrong: the rename build
was actually already live by the time CP14 started probing —
re-validated by the `missing X-LLM-Tracker-Token header` 401 body
in CP14's pre-flight probe.

---

### Prior workstream — Phase 3c CP13-b (closed 2026-05-13)

**Phase 3c CP13-b — first Fly.io + Supabase deploy — closed.**
The operator drove `docs/deploy.md` end-to-end. Two real-world
failures surfaced in flight and were fixed inside this session:

- **Failure 1: stale `public.exchanges` from the closed
  `supabase_sink` workstream.** The operator's Supabase project
  was the same one used by the Phase-2 `supabase_sink` plugin
  (closed 2026-05-08), which had created `public.exchanges` with
  an *incompatible* schema (`exchange_id` PK, `ts_started_ms`,
  `mode`, `source`, `request_text/response_text/raw_*`). The new
  server's `0001_initial_schema` collided
  (`DuplicateTableError: relation "exchanges" already exists`)
  on first `fly deploy`. Diagnosis confirmed via Supabase MCP
  `list_tables` (single stale table, 7 rows, no `alembic_version`
  yet, no trigger function) — i.e. nothing of the new schema had
  partially applied. Dropped the stale table via MCP
  `execute_sql DROP TABLE public.exchanges CASCADE` after
  confirming with the user that ADR-0007's plugin data is not
  load-bearing (ADR-0017 supersedes ADR-0007; the plugin's
  `schema.sql` is checked in so a future revival can rebuild a
  fresh sink target without depending on these rows). Second
  `fly deploy` ran `alembic upgrade head` cleanly through 0001
  → 0005; both `nrt` Machines passed `/healthz`.
- **Failure 2: asyncpg / pgbouncer transaction-mode prepared-
  statement clash.** After migrations applied, `alembic current`
  (and any DB-touching application route) failed with
  `asyncpg.exceptions.DuplicatePreparedStatementError: prepared
  statement "__asyncpg_stmt_1__" already exists`. Cause: Supabase's
  pooled URL (Transaction mode pgbouncer) does not preserve
  prepared statement names across pooled sessions, while asyncpg
  caches them by default. Fix shipped in commit `3050bcc`
  (`server: pgbouncer transaction-mode compat (CP13-b)`):
  `connect_args={"statement_cache_size": 0}` passed through both
  `make_engine()` and `alembic/env.py` `create_async_engine`.
  No-op against direct PG (the local Docker test fixture); the
  single-token-of-effect lives in `make_engine` so it covers the
  server, the `llm-tracker-server tokens issue` CLI, and the test
  fixtures uniformly. Initial false-start (also passing
  `prepared_statement_cache_size=0` as a top-level kwarg) was
  reverted — that is a URL-level dialect parameter, not an
  engine kwarg, and the root-cause error name (`__asyncpg_stmt_N__`)
  pointed at asyncpg's cache only.

Verification (post-deploy, full transcript in worklog
§Verification):

```
$ fly ssh console -C "alembic current"
0005_rls_policies (head)

$ curl -i https://llm-tracker-server.fly.dev/healthz
HTTP/2 200 ...
{"status":"ok","version":"0.0.1"}

$ for i in 1 2 3; do curl -s -o /dev/null -w "HTTP %{http_code}\n" \
   -X POST https://llm-tracker-server.fly.dev/v1/messages \
   -H "Content-Type: application/json" \
   -d '{"model":"claude-opus-4-5","max_tokens":1,"messages":[]}'; done
HTTP 401   HTTP 401   HTTP 401
```

Supabase schema state (via MCP `list_tables`, post-deploy):

```
public.alembic_version  (1 row, version_num = 0005_rls_policies)
public.exchanges        (RLS on,  0 rows)
public.events           (RLS on,  0 rows)
public.tool_calls       (RLS on,  0 rows)
public.audit_log        (RLS on,  0 rows)
public.orgs             (RLS off — substrate, by design 0005)
public.api_tokens       (RLS off — substrate, by design 0005)
```

CP13-b-specific decisions captured in the worklog
`docs/worklog/2026-05-13-cp13b-fly-deploy.md` §Decisions; the
load-bearing ones:

1. **Same Supabase project, drop the stale plugin table.** Plugin
   workstream is closed; rows are not load-bearing; spinning up
   a new Supabase project would have doubled secrets + budget for
   no benefit.
2. **Disable asyncpg's prepared-statement cache at the engine
   layer**, not via URL query parameter. Single point of effect
   across all callers; portable across deploy environments;
   `LLMTRACK_DATABASE_URL` secret stays untouched.
3. **Did not also disable SQLAlchemy's compiled prepared-statement
   cache.** The reproducible failure was asyncpg's
   `__asyncpg_stmt_N__` only; verified by three consecutive
   `/v1/messages` 401s post-fix.
4. **Did not auto-apply the Supabase RLS advisor remediation SQL.**
   Advisor flagged `alembic_version`, `orgs`, `api_tokens` as
   RLS-disabled. `alembic_version` is alembic-internal;
   `orgs`/`api_tokens` are *intentionally* RLS-disabled per the
   0005 docstring (tenancy substrate the auth path needs to read
   before any RLS context is set). The advisor's concern is
   PostgREST-anon exposure — not used by this server, but a
   defense-in-depth follow-up CP is owed (REVOKE anon/authenticated
   or RLS-with-`llm_tracker_app`-only policy). Surfaced; not
   acted on.

Source HEAD is now `3050bcc`. Documentation HEAD advances with
this §5.3 finalize commit.

### Prior workstream — Phase-3a decisions (closed 2026-05-11)

The Phase-3a decision interview (worklog
`docs/worklog/2026-05-11-phase-3a-decisions.md`) settled four of
the seven queued ADRs:

1. **ADR-0018 — Multi-tenancy: per-org + Postgres RLS only.**
   Every user-data table carries `org_id NOT NULL`; RLS policies
   are the sole enforcement; no service-role bypass; operator
   tooling runs through an `admin` role expressed inside RLS.
   Maps cleanly to enterprise self-hosted (single-org).
2. **ADR-0019 — L/A/R retired; L0–L3 kept as plugin capability.**
   The deployment-mode taxonomy disappears. The content-level
   ladder survives as a plugin-manifest `min_content_level`.
   Server-side storage is a **single uniform shape**; no per-user
   retention differentiation in the near term.
3. **ADR-0020 — Auth: per-org token (agent→server) + Anthropic
   credential pass-through (server→Anthropic).** Tokens align
   directly with ADR-0018's per-org RLS context. The server
   **never persists** the user's Anthropic API key — it forwards
   it transiently and discards it after each response stream.
   Zero KMS/Vault build-out; Anthropic-ToS posture is the safest
   available.
4. **ADR-0021 — Plugin manifest signing fully retired.** ADR-0008's
   threat model (user-side `plugin.toml` tampering) disappeared
   with the pivot to server-side plugin execution. The team
   decided not to repurpose signing as a deployment-time trust
   gate (YAGNI for a one-person contributor team). The trust root
   for plugin loading is now the deploy pipeline itself (git +
   CI + server filesystem permissions). Code-removal is a
   separate Phase-3c-prep checkpoint.

**ADRs touched in this workstream**:

- ADR-0018 (new, Accepted) — multi-tenancy boundary.
- ADR-0019 (new, Accepted) — mode-taxonomy fate.
- ADR-0020 (new, Accepted) — auth model.
- ADR-0021 (new, Accepted) — signing fate (supersedes ADR-0008).
- ADR-0008 — status changed to **Superseded by ADR-0021**.
- ADR-0006 — supersession note extended to point at ADR-0019 as
  the ADR that closes its "what survives of L/A/R" open question.

**Where my recommendation differed from the user's pick**: For
ADR-#7 I recommended Option B (repurpose signing as
deployment-time trust). The user picked Option A (full retirement)
on YAGNI grounds. Decision is final; rationale and counter-argument
preserved in `docs/worklog/2026-05-11-phase-3a-decisions.md`
§Decisions.

## Phase 3a — decision ADR queue (4 of 7 settled)

| # | Topic | Status | ADR |
|---|---|---|---|
| 1 | Fallback policy when server unreachable | **Pending** (defers Phase 3b; not on critical path under server-first reframe) | — |
| 2 | Consent + data-handling policy | **Settled 2026-05-17** | **ADR-0029** |
| 3 | Agent-to-server auth model | **Settled 2026-05-11** | **ADR-0020** |
| 4 | Local agent language/distribution | **Pending** (defers Phase 3b; not on critical path under server-first reframe) | — |
| 5 | Multi-tenancy boundary | **Settled 2026-05-11** | **ADR-0018** |
| 6 | What survives of ADR-0006 L/A/R modes | **Settled 2026-05-11** | **ADR-0019** |
| 7 | What survives of ADR-0008 signing | **Settled 2026-05-11** — fully retired | **ADR-0021** |

Items 1 and 4 do **not** block Phase 3c (server build-out): the
server can be built against ADR-0018/0019/0020 schemas and surfaces
without resolving them. Item #2 (consent + data-handling) is **now
settled** by ADR-0029, so external (non-team) testing is no longer
blocked on policy — operator-deploy of the new image is the
operational next step.

## Phase 3c kick-off — deployment platform (2026-05-11)

| Topic | Status | ADR |
|---|---|---|
| Server host + database vendor | **Settled 2026-05-11** | **ADR-0022** |

ADR-0022 commits the project to Fly.io (containerised FastAPI) +
Supabase (managed PostgreSQL with RLS), with `DATABASE_URL` as the
single DB knob and the app shipped as a Dockerfile so the
deployment is not Fly-locked. Reversibility is high — `DATABASE_URL`
swaps the DB, and `fly.toml` is replaced 1:1 by any other
orchestrator's manifest.

---

### Prior workstream — `supabase_sink` (closed 2026-05-08, CP9)

ADR-0007's reference Mode-R plugin is operational against the
operator's real Supabase project (7 rows in `public.exchanges` from
Path 1). All three safety paths verified against real traffic in CP9:

- **Path 1 — Happy** (`Mode R` + opted_in + correct manifest):
  7 rows landed; `request_text` / `response_text` / `usage`
  populated as expected; one row has `model_served=null` (HTTP
  error response from Anthropic — non-SSE body — by-design
  observability hole, see CP9 worklog "Observation").
- **Path 2 — Mode L safety**: `capability_denied` at proxy
  startup, plugin never loaded, 0 new rows, `claude` response
  flowed through the proxy normally. Production equivalent of
  `test_e2e_mode_l_rejects_plugin_at_load_time`.
- **Path 3 — Allowlist mismatch**: manifest's `egress_destinations`
  set to a bogus URL → plugin loaded but `EgressGuard` denied
  every fetch with `reason=destination_not_in_allowlist`; 0 new
  rows; 4 `egress_blocked` audit rows; manifest restored +
  re-signed (ed25519 deterministic → byte-identical to CP8).

> **Note (2026-05-11)**: ADR-0021 retires signing entirely. The
> manifest re-signing path used in CP9 will disappear when the
> code-removal checkpoint lands. The `supabase_sink` plugin itself
> stays valid as a server-side analytics output.

**Workstream artefacts** (per CLAUDE.md §10 public-interface
catalogue):

- ADR-0015 — `EgressClient` Protocol + `EgressResponse` +
  `EgressDenied`; `BasePlugin.egress` / `HookContext.egress`
  reference the *same* per-plugin instance bound at load time.
- ADR-0016 — `LLMTRACK_USER_OPTED_IN` env knob (interim consent
  surface; per-task UX still deferred per ADR-0006 §"Open
  questions").
- New SDK module: `llm_tracker_sdk.egress`.
- New core module: `llm_tracker.egress_guard.client` (`HostEgressClient`).
- New `PluginHost` constructor params: `http_client`,
  `user_opted_in`. New `SHUTDOWN_HOOK_TIMEOUT` = 30 s for sink
  drain.
- New plugin package: `packages/llm_tracker_plugin_supabase_sink/`
  (signed by `minseop`, 55 unit + 3 integration tests).
- Supabase: `public.exchanges` table + RLS enabled (CP4).
- Operator UX: proxy reads `.env` at lifespan; refreshed
  `.env.example` to match the current `Settings` surface.

Closed-checkpoint roll-up (cleanup pass A–G + stop gates +
side-quests):

- A (e2ee4f0): EgressGuard wired into proxy lifespan
- B (3010aae): signature verifier wired + signing CLI
- C (a2bc3d4): on_persisted ordering fix
- D (b1724fa): synthetic SSE block response
- E (2891e8f): audit_log append-only triggers
- F (6a08c9c): ADR-0008 housekeeping
- G (96305e1): session_factory property + ADR-0009
- 14 (654fbfb): ADR-0010 retroactive (Block/Abort.plugin)
- 15 (cfbbb8e): ADR-0011 Transform policy
- 16 (bbb33e7): Transform impl + 4 tests
- 17 (4606ed0): ADR-0012 hook payload routing
- 18 (75ff46a): HookContext impl + 14 tests
- pre-1c verification (2c28f68): TEST-ONLY token_counter + keyword_block
- side-quest #2 (d2e33d5, 9aa8321): `claude-manage` wrapper + async cleanup
- side-quest #3 (0a43502, 161505d): plugin disable config + `/admin/plugins`
- supabase_sink workstream (8712183, f75a841, dff7e3e, a3b5dff,
  9088825, 6ab979c, 4294d10, f420000, f2f53b7, + this CP9
  finalize commit): ADR-0015/0016 + `EgressClient` SDK +
  `LLMTRACK_USER_OPTED_IN` + Supabase schema + the plugin itself
  + `SHUTDOWN_HOOK_TIMEOUT` + signed manifest + `.env` lifespan
  loader + manual e2e

## Phase 1c prerequisites (reframed under ADR-0019)

These three items were Phase-1c carry-overs. **ADR-0019 (2026-05-11)
reframes them server-side**:

- **L2 scrubbed shape of `request_text`**. Scrubber primitives now
  run on the central server, not per user machine. Pinned by
  `test_hook_context.py::test_request_text_returns_body_at_l2_when_ceiling_allows`
  so the eventual change is test-visible. Lands in Phase 3c.
- **Manifest `min_content_level` field** (ADR-0012 §"Open
  questions"). ADR-0019 confirms this primitive survives the
  pivot. Add the schema field + validator + host enforcement
  during Phase 3c. Separate ADR if the host-side semantics surface
  anything non-obvious.
- **Response-side `ctx` accessors** (`response_text`,
  `tool_call_inputs`, etc.). ADR-0012 ships only the request-side
  accessors. Response-side data needs the Phase-2 Extractor to
  surface structured response records first; separate ADR if the
  semantics surface anything non-obvious (e.g. partial vs assembled).

## Next single step

**CP4 of 8 — `embeddings.py` + `judge.py` via `HostEgressClient`;
pin ADR-0030 §Q4 (Stage-2 prompt template).** Per ADR-0030 §D3
+ §D4:

1. `EmbeddingClient` wraps a `HostEgressClient` for
   `https://api.openai.com/v1/embeddings`. One method:
   `async def embed(text: str) -> list[float]` returning the
   1536-dim vector from `text-embedding-3-small`. Constructor
   takes the egress client and the `OPENAI_API_KEY` so the
   class stays testable in isolation; CP5 wires the actual
   `self.egress` injection at `on_init` time.
2. `JudgeClient` wraps a `HostEgressClient` for
   `https://api.openai.com/v1/chat/completions`. One method:
   `async def judge(message_text: str, chunks: list[str]) ->
   tuple[Verdict, str]` where `Verdict` is
   `"in_scope" | "out_of_scope"` and the string is a
   one-sentence reason. Top-K (default 3) chunks accompany the
   prompt (top-K is an env var read at CP5, not at CP4).
3. **Q4 — pin the Stage-2 prompt template** as a frozen
   module-top string in `judge.py`. The prompt asks
   `gpt-4o-mini` for a strict JSON shape
   `{"verdict": "...", "reason": "..."}`; parser tolerates
   leading whitespace + trailing newlines; falls back to a
   degraded `("out_of_scope", "parse_error: ...")` verdict on
   malformed JSON so a flaky upstream cannot crash the
   `on_persisted` path. Future tweaks become diff-visible.
4. Unit tests stub `HostEgressClient.fetch` so no network
   traffic. Pin: prompt-shape sentinels (system + user role
   text), JSON happy-path parse, malformed-JSON fallback.

Output of CP4 is two reusable clients + their tests; CP5 then
wires them into `pipeline.py` + `storage.py` + `plugin.py` and
ships the end-to-end DB-fixture integration test.

Remaining CP5 through CP8 work board (concise; full board in
the impl worklog):

- **CP5** — `pipeline.py` + `storage.py` + `plugin.py`;
  DB-fixture integration test with a fake OpenAI client.
- **CP6** — `tools/process_scope_document.py` CLI (`.txt` + `.md`,
  idempotent delete-then-insert on `(org_id, title)`).
- **CP7** — `.env.example` six `LLMTRACK_PLUGIN_SCOPE_GUARD_*`
  vars + `docs/deploy.md §"Data collection & privacy"` OpenAI
  disclosure paragraph + `docs/plugins.md §11` reference entry.
- **CP8** — `0011_scope_alerts_retention` migration mirroring
  0009's `pg_cron` guard pattern (Q3 already decided at CP1).

Operator's parallel operational step remains `fly deploy` to pick up
migration `0009_retention_deletion_job` on production (no data
deletion at apply time; first scheduled run is at the next 03:00 UTC
tick).

Queued follow-ups (pickable cold; none gate any next CP):

1. **`plugin_analytics` RLS axis — ADR-level revisit.** 0007's
   docstring chose "no RLS on this table" deliberately; either
   elevate that choice to an ADR or reconsider with an explicit
   policy on how operator tooling queries internal analytics tables
   under a session-bound RLS shape. Distinct axis from ADR-0018's
   user-data RLS guarantee.
2. **Task hierarchy (session/task/exchange).** Deferred track to
   introduce a `task_id` layer between `session_id` and
   `exchange_id` so multi-exchange Claude-Code sessions map to
   operator-visible task units rather than only the per-turn
   exchange row. Design-first; not gated on anything.
3. **Real `session_id` populator + deletion endpoint** (ADR-0029
   Axis 4 + Phase 3b agent identity).
4. **i18n email scrubbing** (ADR-0029 §"Open questions").

### Side-quests (do at any time, none blocking)

- ~~**Stamp migration 0006 on live Supabase.**~~ **Closed** by this
  checkpoint's `fly deploy` (release-command-run `alembic upgrade
  head` advanced `alembic_version` to `0006_grant_app_role_set`).
- ~~**ADR-#2 consent + data-handling.**~~ **Closed 2026-05-17** by
  ADR-0029 (six-axis policy + SDK accessor scrubber);
  **production-validated** the same day by Fly `v11` smoke. External
  testing is now fully unblocked.
- **`plugin_analytics` RLS axis — ADR-level revisit, not a missed
  gap.** Initially logged 2026-05-17 as a "newly surfaced" RLS-off
  table; closer reading of
  `packages/llm_tracker_server/alembic/versions/0007_plugin_analytics.py`
  showed 0007's docstring made a deliberate "no RLS on this table"
  choice with reasoning ("Analytics is internal — the plugin
  queries this directly from operator tooling without going through
  the request-scoped session"). The advisor warning is correct
  *given* that the choice was not elevated to an ADR; whether to
  enable RLS or to elevate the docstring decision to an ADR is the
  open question.
- ~~**`docs/deploy.md` paragraph on PG16+ `set_option` quirk.**~~
  **Closed 2026-05-17** by commit `1a886e6` — new § between the
  pgbouncer/asyncpg note and the "subsequent deploy" §.
- ~~**Empty package-directory shells cleanup.**~~ **Closed
  2026-05-17** by `rm -rf packages/llm_tracker/
  packages/llm_tracker_plugin_supabase_sink/` (no commit; no
  git-tracked file changed).

### Local dev loop revival (still current)

To revive the local dev loop in a new session (Postgres on the
host for the test-fixture suite; the Dockerised server +
Fly.io deployment are independent):

```
# Migration 0010 (scope_guard) requires pgvector; the
# pgvector/pgvector:pg15 image bundles it. Vanilla postgres:15 fails
# the `alembic upgrade head` round-trip in conftest.py.
docker run -d --name llm-tracker-pg \
  -e POSTGRES_USER=cp2 -e POSTGRES_PASSWORD=cp2 \
  -e POSTGRES_DB=llm_tracker_test \
  -p 55432:5432 pgvector/pgvector:pg15
export LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test
```

To rebuild + smoke the CP12 image locally:

```
docker build -t llm-tracker-server:local .
docker run -d --rm -p 18080:8080 --name lts-smoke llm-tracker-server:local
curl -sS http://localhost:18080/healthz
docker stop lts-smoke
```

The user-deferred items #1 (fallback) and #4 (agent language) are
**not on the critical path** under the current server-first
reframe; they re-enter the queue once Phase 3b (thin agent) is
ready to start.

## Blocking / decisions needed

- **#2 consent + data-handling**: **Settled 2026-05-17 by ADR-0029.**
  External (non-team) testing is no longer blocked on policy;
  operator-deploy of `a4c08b3` is the operational next step before
  routing external traffic.
- **#1 fallback** and **#4 agent language**: deferred to Phase 3b
  scoping; not blocking anything Phase 3a or 3c.

## Progress

- [x] Design v0.1 written
- [x] Framework pivot v0.2
- [x] English-only documentation pass
- [x] ADRs 0001–0008 sealed (0004 superseded by 0007)
- [x] Phase 0 — core skeleton (CLOSED 2026-05-04)
- [x] Phase 1a — plugin SDK (CLOSED 2026-05-05)
- [x] Phase 1b — security boundary hardening (CLOSED 2026-05-06)
- [x] Pre-Phase-1c verification — TEST-ONLY plugins (token_counter, keyword_block) (2026-05-06, commit 2c28f68)
- [x] `claude-manage` wrapper — auto-spawn proxy + lifecycle-coupled cleanup (2026-05-07, commits d2e33d5, 9aa8321)
- [x] Plugin disable config + `/admin/plugins` introspection (2026-05-07, commits 0a43502, 161505d)
- [x] **Phase 2 partial — `supabase_sink` reference plugin (CLOSED 2026-05-08, 9 commits 8712183 → CP9 finalize)**
- [x] **Phase 1b loose-ends (CLOSED 2026-05-09, commits 86acecd / 14b6f7a / 86caf03 / 8d4422b)**
- [x] **Architectural pivot to central server documented (2026-05-11, ADR-0017; commits f74710f / 87142f9 / 8a47b2f / fbf23a5)**
- [x] **Phase 3a decisions 4/7 settled (2026-05-11, ADR-0018/0019/0020/0021; commit 223f742)**
- [x] **ADR-0021 code-removal housekeeping (2026-05-11, commit b446c3f)**
- [x] **ADR-0022 deployment platform — Fly.io + Supabase (2026-05-11, commit 3211672)**
- [x] **Phase 3c build plan — 14 commit-sized checkpoints (2026-05-11, commit ec51a40)**
- [x] **Phase 3c CP1 — `llm_tracker_server` skeleton + /healthz (2026-05-11, commit 7d992ff)**
- [x] **Phase 3c CP2 — storage layer on PostgreSQL (2026-05-11, commit b7eed52)**
- [x] **Phase 3c CP3 — orgs + api_tokens substrate (2026-05-11, commit 373ed11)**
- [x] **Phase 3c CP4 — `org_id NOT NULL` on user-data tables (2026-05-11, commit 2da7438)**
- [x] **Phase 3c CP5 — RLS policies + `llm_tracker_app` role (2026-05-12, commit 0dec2f1)**
- [x] **Phase 3c CP6 — auth middleware + tokens CLI (2026-05-12, commit 1c0835a)**
- [x] **Phase 3c CP7 — Anthropic credential pass-through + log scrubbing (2026-05-12, commit e1d34bc)**
- [x] **Phase 3c CP8 — Port proxy + plugin host server-side (2026-05-12, commit 79227fe)**
- [x] **Phase 3c CP9 — Storage layer: org-aware INSERTs (2026-05-12, commit fe18e9a)**
- [x] **Phase 3c CP10 — `min_content_level` manifest field + per-plugin host clamp (2026-05-12, commit 6c3b7b8)**
- [x] **Phase 3c CP11 — `.env.example` + developer docs refresh (2026-05-12, commit a7e21c9)**
- [x] **Phase 3c CP12 — `Dockerfile` + `.dockerignore` (2026-05-12, commit 92ddff7)**
- [x] **Phase 3c CP13-a — `fly.toml` + `docs/deploy.md` (2026-05-13, commits ef59192 + 59dbae6)**
- [x] **Phase 3c CP13-b — first Fly.io + Supabase deploy (2026-05-13, commit 3050bcc; server live at `https://llm-tracker-server.fly.dev/`)**
- [x] **ADR-0023 — server auth header rename to `X-LLM-Tracker-Token` (2026-05-13, commits af6bd8f + 21e9fa5; CP14 prep, fixes OAuth Claude Code collision)**
- [x] **Phase 3c CP14 — operator-only end-to-end smoke (2026-05-13, commit 458a4ba; first 200-OK roundtrip with operator-minted demo token; demo-scoped row in `public.exchanges`; PG16+ deploy gap surfaced + fixed in migration 0006; response-side metadata NULL on the success row flagged as separate follow-up track)**
- [x] **CP14 follow-up Option A — close-out columns populated (`ended_at`/`status_code`/`model_requested`/`latency_ms`) (2026-05-13, commit 237d842; production-verified on row `01KRG14W5VNV78HN3P9PEF2Z9P` after `fly deploy` — same deploy stamped `alembic_version` to `0006_grant_app_role_set`; investigation falsified the prior "INSERT-at-open + UPDATE-at-close" hypothesis — there is no UPDATE path; 4 of 8 response-side NULLs closed; remaining 5 (`model_served`, `input_tokens`, `output_tokens`, `cache_*`, `stop_reason`) need Option B's SSE Extractor)**
- [x] **Option B + plugin-ecosystem workstream (2026-05-14, commits `f02f516` α / `61c8aeb` β / `49804f5` γ / `b3f9ed2` δ / `7741c13` ε / `854d4ee` ζ); ADR-0026 (HookContext response accessors) + ADR-0027 (exchange row close-out policy) Accepted; `extractors/anthropic.py` populates the five SSE-derived columns end-to-end on the happy path; migration 0007 adds `plugin_analytics`; `analytics_sink` writes one row per exchange; `keyword_block` polished from TEST-ONLY to operator-configurable; Docker image bundles both plugins. **Production-validated 2026-05-16 by operator smoke** (post-deploy `plugin_analytics` row carried all five columns populated with `usage.input_tokens=6 / output_tokens=152 / cache_read=75512 / cache_creation=133` under `stop_reason=tool_use`).**
- [x] **ADR-0028 follow-up — extractor faithful reassembly (2026-05-16, commit `8138d91`); `response_json` now captures tool_use, thinking, signature, and unknown future block types instead of text-only; surfaced by a live `plugin_analytics` row whose `content: []` had silently dropped a 112-token tool_use payload. Full repo test suite 334 passed under the DB fixture (+5 new tests). **Production-validated 2026-05-16 in the same operator-smoke window** — verbatim row carried both a thinking block (signature preserved) and a tool_use block with `input` as a parsed dict (no `_input_json_raw` fallback). `keyword_block` also exercised live via `LLMTRACK_KEYWORD_BLOCK_LIST = "no_response"` in `fly.toml`.**
- [x] **ADR-0029 — consent + data-handling policy + HookContext accessor-level scrubber (2026-05-17, commit `a4c08b3`); six-axis decision packet (full L3 storage / docs-only disclosure / 6-month retention / operator-handled deletion / `sk-`+`lts_`+`Bearer`+email scrubbing / SDK-accessor location) lands as Accepted ADR plus `llm_tracker_sdk.scrubbers` + HookContext wiring + `docs/deploy.md` "Data collection & privacy" section + `docs/plugins.md` §3.2. Test suite 354 passed under DB fixture (+20 new). External (non-team) testing no longer blocked on policy — operator-deploy of the new image is the operational step that brings the scrubber to production.**
- [x] **Housekeeping — archive superseded ADRs + remove local sidecar (2026-05-17, commits `8ef166d` + `3d76d1f`); 7 superseded ADRs moved into `docs/decisions/archive/`, `packages/llm_tracker/` (local sidecar) and `packages/llm_tracker_plugin_supabase_sink/` (closed workstream) deleted, 5 SDK-only test files rescued into new `packages/llm_tracker_sdk/tests/`; local branch `archive/local-sidecar` preserves full pre-deletion history (not pushed); no-DB test count 143 passed / 16 skipped.**
- [x] **ADR-0029 production smoke + doc reconciliation (2026-05-17, commit `d7f17c0` + finalize commit); Fly release `v11` (ADR-0029 image, deploy of `a4c08b3`) verified live by injecting `sk-deadbeef12345678` through `claude-manage` — two `plugin_analytics` rows carry `[REDACTED:secret]` in `messages_json` with no raw value. Smoke surfaced that `analytics_sink` reads through `ctx.request_text()` / `ctx.response_content_json()` (not raw body parsing as docs claimed), so plugin-mediated rows inherit the scrubber's privacy floor. User picked "align docs to production"; commit `d7f17c0` reconciles ADR-0029 §Axis 6 + §Open questions, ADR-0028 §Open questions, `docs/plugins.md` §3.2, `hook_context.py` module docstring, and adds a Correction blockquote to the prior ADR-0029 worklog. Side-finding: `claude-manage` console_script was missing from `.venv/bin/` after yesterday's `uv sync`; restored via `uv sync --reinstall-package llm-tracker-agent`. Secondary discovery queued: `public.plugin_analytics` is RLS-off (not on the CP13-b intentional list).**
- [x] **Queued follow-up batch (2026-05-17, commits `1a886e6` + `7b20125` + `0db0bac` + finalize). Four of five queued items shipped in one session: (a) `docs/deploy.md` PG16+ `WITH SET TRUE` paragraph alongside the pgbouncer/asyncpg note; (b) `exchanges.tool_call_count` drop via migration 0008 + storage/test cleanup (ADR-0028 §Non-goals had already documented the placeholder posture); (c) ADR-0027 axis 2 impl — new `record_exchange_failure` helper + `httpx.RequestError` short-circuit + `status_code != 200` short-circuit, with `599` sentinel for network errors and explicit `plugin_host.end_exchange()` cleanup on both paths; (d) empty package-directory shells `rm -rf` (no commit). Fifth item — `plugin_analytics` RLS — returned to queue as ADR-level after finding 0007's docstring made a deliberate "no RLS on this table" choice. Tests 58 / 16 (was 56 / 16; +2 axis 2 forwarder tests). Surfaced a latent Block/Abort ctx-cleanup gap for a separate small follow-up.**
- [ ] **Phase 3a — remaining 2 decision ADRs** (#1 fallback / #4 agent language)
- [ ] Phase 3b — thin local agent (gated on #1 + #4)
- [x] **Phase 3c — server build-out (14 of 14 plan-checkpoints done; closed 2026-05-13 with operator smoke validated. Plan at `docs/worklog/2026-05-11-phase3c-plan.md`, anchored on ADR-0017/0018/0019/0020/0022/0023)**
- [ ] **Phase 1c — `scope_guard`** (**in progress 2026-05-18**; ADR-0030 Accepted; CP1 + CP2 of 8 done — commits `2511c3a` (migration 0010) + `2fe84e6` (package skeleton); CP3–CP8 pending per `docs/worklog/2026-05-18-scope-guard-impl.md`)
- [ ] Phase 3d — carry-overs: OpenAI/Gemini adapters, analytics interface, response-side policy plugins

---

## Update rules (for Claude Code)

At every checkpoint, do these three as one atomic unit (CLAUDE.md §5.3):

1. `git commit` the code change (CLAUDE.md §11).
2. Append the new commit hash to the active worklog's "What was done"
   section, and rewrite the "What's left / Handoff" section as of *now*.
3. Refresh this STATUS.md:
   - Last-updated timestamp (YYYY-MM-DD).
   - Active worklog path.
   - Last 3–5 commits.
   - "Where we paused".
   - "Next single step".

If you don't bundle these three, the next session won't know where to pick
up.
