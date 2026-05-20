# 2026-05-21 · Follow-up cleanup — drop exchanges.session_id + ADR-0033

**Author**: Claude Code
**Session trigger**: User instruction listing three tasks: (1) drop
`exchanges.session_id` as migration 0017 + the ORM / helper / test
cleanup, (2) write the `plugin_analytics` no-RLS ADR, (3) update the
worklog + STATUS.md to absorb both the prior-session Candidate-1
implementation and this session's two tasks.
**Related docs**:
- ADR-0027 (exchange row close-out policy — names `session_id` in its
  population matrix; superseded for that column by this track)
- ADR-0029 (consent + data-handling — has open follow-up "real
  `session_id` populator + deletion endpoint" that this track retires)
- ADR-0033 (created this session — no-RLS for `plugin_analytics`)
- Prior worklogs: `docs/worklog/2026-05-19-candidate-1-implementation.md`
  (Candidate-1 dedup track; closed 2026-05-19; this session absorbs
  its post-deploy closure into STATUS / worklog only)

## Interpretation

Two pickable items from the §"Queued follow-ups" menu landed in one
session:

- **Drop `exchanges.session_id`.** The user confirmed
  `conversation_id` + `first_msg_hash` on `plugin_analytics` cover
  every use case the column was intended for (per-conversation
  grouping, dedup of retries, operator deletion scope). Column has
  zero non-`"server"` values in production and no query consumers in
  code. This retires the queued "real `session_id` populator +
  deletion endpoint" item — the populator was the prerequisite for
  the column being useful, and the analytics_sink plugin's
  `conversation_id` shipped that capability under a different name.
- **No-RLS ADR for `plugin_analytics`.** Elevates migration 0007's
  docstring choice to an ADR, naming the AsyncEngine / GUC
  propagation reason that makes RLS impractical for the analytics
  write path today.

Worklog rule §5.2 — one file per (date, topic). This is a separate
topic from the Candidate-1 implementation track (closed 2026-05-19),
so it gets its own file.

## What was done

- Created `packages/llm_tracker_server/alembic/versions/0017_drop_exchanges_session_id.py`
  — `ALTER TABLE exchanges DROP COLUMN session_id` on upgrade;
  downgrade re-adds the column `NOT NULL DEFAULT 'server'`
  (commit `21c5552`).
- Modified `packages/llm_tracker_server/src/llm_tracker_server/storage/models.py`
  — removed `session_id` from the `Exchange` ORM class (commit
  `21c5552`).
- Modified `packages/llm_tracker_server/src/llm_tracker_server/storage/exchanges.py`
  — removed the `session_id="server"` kwarg from
  `record_exchange_timing`, `record_exchange_blocked`, and
  `record_exchange_failure` (commit `21c5552`).
- Modified `packages/llm_tracker_server/tests/test_storage_smoke.py`,
  `packages/llm_tracker_server/tests/test_rls_two_org_isolation.py`,
  `packages/llm_tracker_server/tests/test_org_id_constraint.py` —
  removed the column from the Exchange constructor / `_make_exchange`
  helper / assertion (commit `21c5552`).
- Created `docs/decisions/0033-plugin-analytics-no-rls.md` — ADR
  accepting "no RLS on `plugin_analytics`" with the three reasons
  (GUC connection-scoping, operator-only access pattern, app-layer
  isolation), plus revisit trigger if the table is ever exposed via a
  request-scoped session path (commit `257caee`).

## Decisions

- **`session_id` removal is full-drop, not soft-deprecation.** The
  column has only the literal `"server"` value in production, zero
  query consumers in the code, and the queued "real populator" item
  was effectively retired the moment the analytics_sink plugin's
  `conversation_id` shipped. Soft-deprecation (NULL-allow) would
  carry a vestigial column forever.
- **HookContext.session_id stays.** This is an SDK-level identifier
  for the request slot (`packages/llm_tracker_sdk/src/llm_tracker_sdk/hook_context.py`),
  not the Exchange row column. Different concept; pre-existing
  infrastructure; out of scope for this track.
- **ADR-0033 captures the AsyncEngine reason explicitly.** The
  docstring on migration 0007 was thin ("Analytics is internal");
  the ADR pins the actual mechanical reason — the GUC binding
  (`set_config('app.org_id', ...)`) is session-scoped and does not
  propagate to the plugin's separate `AsyncEngine`. This is the part
  that makes adding RLS later non-trivial in practice, not a stylistic
  preference.

## Verification

```
$ .venv/bin/python3.12 -m pytest \
    packages/llm_tracker_sdk \
    packages/llm_tracker_plugin_analytics_sink \
    packages/llm_tracker_server -q
157 passed, 18 skipped in 5.78s

$ .venv/bin/python3.12 -m ruff check packages/
All checks passed!

$ cd packages/llm_tracker_server && ../../.venv/bin/python3.12 \
    -m alembic upgrade --sql 0016_drop_messages_json:0017_drop_exchanges_session_id
# Clean BEGIN ... COMMIT block:
#   ALTER TABLE exchanges DROP COLUMN session_id;
#   UPDATE alembic_version SET version_num='0017_drop_exchanges_session_id';

$ ../../.venv/bin/python3.12 -m alembic downgrade \
    --sql 0017_drop_exchanges_session_id:0016_drop_messages_json
# Clean reverse:
#   ALTER TABLE exchanges ADD COLUMN session_id TEXT DEFAULT 'server' NOT NULL;
```

Whole-repo grep `grep -rn "session_id" --include="*.py" packages/`
after the commit confirms zero references to the dropped Exchange
column. The remaining matches are all `HookContext.session_id` (SDK)
or unrelated test contexts — pre-existing and intentional.

**Live apply is operator-driven**: migration 0017 has not been
applied to Supabase; `fly deploy` is gated behind that. The previous
image's helpers will keep writing `"server"` to the column until both
land — which is safe because the column still exists in the live DB.
After migration apply + `fly deploy`, the new image's helpers stop
writing the column and the dropped column has no readers.

## Live apply timeline (same session continuation)

Operator authorised the Supabase live apply ("supabase 적용은 너가
해야지"). Migration 0017 applied via Supabase MCP `execute_sql`
as one atomic `BEGIN ... COMMIT` block, matching the
0013 / 0014 / 0015 / 0016 precedent.

Pre-state (`alembic_version` + `information_schema.columns`):

| field | value |
|---|---|
| alembic_at | `0016_drop_messages_json` |
| session_id column present | `true` |
| non-`"server"` rows | `0` (zero data to lose) |
| total `exchanges` rows | 182 |

Apply (one transaction):

```sql
BEGIN;
ALTER TABLE exchanges DROP COLUMN session_id;
UPDATE alembic_version SET version_num='0017_drop_exchanges_session_id'
  WHERE version_num='0016_drop_messages_json';
COMMIT;
```

Post-state:

| field | value |
|---|---|
| alembic_at | `0017_drop_exchanges_session_id` |
| session_id column present | `false` |
| total `exchanges` rows | 182 (no row loss) |

The 182-row count is preserved across the column drop — PostgreSQL
`ALTER TABLE DROP COLUMN` is a metadata-only operation on a single
NOT NULL column with no FK / index references, so no data is
rewritten.

## Post-Candidate-1 absorption (prior-session work in context)

Worklog rule §5.3 — checkpoint absorbs prior unrecorded work.
Candidate-1 (`conversation_messages` dedup) shipped end-to-end on
2026-05-19 across five commits:

- `54ca6fa` — code half: migration 0015 + `normalize.py` (Rule A +
  Rule B) + 8 unit tests + `ConversationMessage` ORM + plugin
  `_INSERT_SQL` swap from `messages_json` to `n_messages_at_request`
  + new `_UPSERT_MESSAGE_SQL` per-index path + 2 plugin tests.
- `a4727fc` — STATUS / worklog code-half checkpoint.
- `4c2babd` — live apply: migration 0015 applied via Supabase MCP
  `execute_sql`, 1242 → 234 dedup ratio (5.31× whole-dataset, 6.48×
  STRESS conv), backfill via SQL `INSERT ... DISTINCT ON ... ON
  CONFLICT DO NOTHING` with Python `canonical_message()` equality
  spot-check (checked=5 mismatches=0), `messages_json` column drop
  via migration 0016 (DROP VIEW + DROP COLUMN + CREATE VIEW in one
  atomic transaction).
- `7d3dad3` — track closure: operator `fly deploy` confirmed; 14:44
  KST smoke against `[CANDIDATE1-SMOKE]` Read tool chain returned
  5 rows all green across `pa_n` non-NULL / `cm_visible == pa_n ==
  view_n` / smoke tag in `messages[0]` / `conversation_id` stability
  / `turn_seq` cumulative growth / `ON CONFLICT DO NOTHING` working.

This session does no further Candidate-1 work — that track is fully
closed.

## What's left / known limits

- **Migration 0017 not yet applied to live Supabase.** Operator-owned
  per the standard apply pattern (Supabase MCP `execute_sql` in one
  atomic `BEGIN; ... COMMIT;` block matching the 0013 / 0014 / 0015
  / 0016 precedent), then `fly deploy` from `main` so the new image's
  helpers stop writing the dropped column. Until that ships, the
  running image continues to write `"server"` to the still-existing
  column — safe, just vestigial.
- **§"Queued follow-ups" menu after this session**: `plugin_analytics`
  RLS item is **closed** (settled by ADR-0033); `session_id`
  populator + deletion endpoint item is **closed** (retired by the
  column drop). Remaining items: task hierarchy (session/task/exchange
  layer), i18n email scrubbing.

## Handoff

**Next single step (operator-owned)**: `fly deploy` from `main`.
Migration 0017 is now applied live — the running image's helpers
(which still pass the dropped column via the prior compiled SQL
shape from the `Exchange` ORM) will `UndefinedColumn`-fail every
happy-path / blocked / failure helper invocation until redeploy.
So the deploy is non-skippable and is the only remaining gate
before the track is end-to-end closed.

Post-deploy smoke is a single non-blocked proxy exchange — verify
the helper write succeeds (a row lands in `exchanges` with
`status_code=200`) and no `UndefinedColumn` error appears in Fly
logs for `record_exchange_timing` / `record_exchange_blocked` /
`record_exchange_failure`.

After `fly deploy` lands, the §"Queued follow-ups" menu has two
remaining items (task hierarchy + i18n email scrubbing) — pick one
or leave undecided per the existing posture precedent.

## Continuation — `content_level` configurable via env (same day)

User request: replace the hardcoded `content_level="L3"` at the three
`Exchange(...)` constructor sites with a configurable env var
(`LLMTRACK_CONTENT_LEVEL`, default `"L3"`). Per CLAUDE.md §9
`content_level` is a public interface — the operator-knob shape
needs to exist even if production keeps the default.

### Step d check — design.md content level definitions

`docs/design.md` defines L0/L1/L2/L3 cleanly (§7.1 table):

| L0 | Metadata only — token counts, model name, latency, tool names, status code |
| L1 | L0 + deterministic hashes (SHA-256) of bodies, lengths |
| L2 | L0 + scrubbed body (secrets/PII/paths/emails/IPs removed) |
| L3 | Raw (still scrubber-passed) |

`packages/llm_tracker_sdk/src/llm_tracker_sdk/levels.py` already
ships these as a `ContentLevel` IntEnum. No ambiguity, no "Decision
needed" stop — proceeded to implementation.

### What was done (commit `2a68c56`)

- Modified `packages/llm_tracker_server/src/llm_tracker_server/config.py`
  — added `content_level: Literal["L0", "L1", "L2", "L3"] = "L3"` to
  `Settings`. `Literal` lets pydantic-settings reject typos at
  instantiation so a bad env value fails the server boot rather
  than silently mis-labelling rows.
- Modified `packages/llm_tracker_server/src/llm_tracker_server/storage/exchanges.py`
  — added `content_level: str` as a required keyword-only argument
  to all three helpers (`record_exchange_timing`,
  `record_exchange_blocked`, `record_exchange_failure`); the
  hardcoded `"L3"` literal at each `Exchange(...)` constructor
  call site now reads the kwarg. Module docstring updated to name
  the env-var path.
- Modified `packages/llm_tracker_server/src/llm_tracker_server/app.py`
  — `app.state.content_level = resolved.content_level` plumbed onto
  app state alongside `session_factory`.
- Modified `packages/llm_tracker_server/src/llm_tracker_server/proxy/forwarder.py`
  — reads `content_level` from `app.state` once at the top of
  `forward_request` (with `"L3"` fallback for unit-test paths that
  build a bare `Request` with no app in scope); threaded through
  all six helper call sites (3× `record_exchange_blocked`, 2×
  `record_exchange_failure`, 1× `record_exchange_timing`).
- Modified `packages/llm_tracker_server/tests/test_record_exchange_failure_db.py`
  — two direct-helper call sites now pass `content_level="L3"`
  (required kwarg).

### Decisions

- **`content_level` is a required kwarg, not a defaulted one.**
  Giving it a default would let a forgotten forwarder call site
  silently regress to hardcoded `"L3"` — the very thing this track
  is removing. Required kwarg means any future caller has to make
  the choice explicit; tests pass `"L3"` because that's the
  documented production default. The forwarder's `"L3"` fallback at
  the `getattr(state, "content_level", "L3")` line is only for
  tests that bypass `create_app` — production always reads through
  `Settings`.
- **Validation via `Literal[...]` in pydantic-settings, not a
  field_validator.** Same outcome, less code; pydantic native
  Literal handling rejects typos at `Settings()` instantiation
  exactly when the server boots. The four-level enumeration is
  closed (design.md §7.1), so `Literal` is the right primitive.
- **`Settings.content_level` is a `str`, not the SDK `ContentLevel`
  IntEnum.** The `exchanges.content_level` column is `TEXT`
  (migration 0001); the storage helpers treat it as a string label.
  Keeping the type as `str` at the config + helper boundary avoids
  an unnecessary conversion at every call site. Validation that
  the string is one of the four labels happens once, at Settings
  instantiation.

### Verification

```
$ .venv/bin/python3.12 -m pytest \
    packages/llm_tracker_sdk \
    packages/llm_tracker_plugin_analytics_sink \
    packages/llm_tracker_server -q
157 passed, 18 skipped in 5.57s

$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_server/
All checks passed!
```

Test count unchanged from the prior commit (157 + 18 skipped) — no
new tests added; existing call-shape tests already cover the kwarg
plumbing since the forwarder hooks tests exercise the three
short-circuit paths. The Literal validation gets implicit coverage
the moment any operator sets a typo and the server fails to boot.

### Live state

`LLMTRACK_CONTENT_LEVEL` is **not yet set in Fly secrets** — the
running image will default to `"L3"` (matching the previous
hardcoded behaviour), so no behaviour change at deploy time. If
the operator later wants L0/L1/L2 on production, set
`fly secrets set LLMTRACK_CONTENT_LEVEL=L0` (or other) and
redeploy; the next exchange writes the new label.

## Continuation — i18n email scrubbing (same day)

User request: extend the email scrubber so internationalized addresses
(Unicode local parts, raw IDN domains, punycode IDN domains) are
correctly redacted without corrupting JSON structure or producing
false positives. This was the last `i18n email scrubbing` follow-up on
the §"Queued follow-ups" menu (ADR-0029 §"Open questions").

### Step b — case-by-case status (before changes)

Current regex:
``\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b``

| Case | Status | Why |
|---|---|---|
| 1. Unicode local part (``ünîcödé@…``) | NOT handled | Local-part class is ASCII-only; ``ü`` never matches, no run reaches ``@``. Privacy hole. |
| 2. Raw IDN domain (``user@münchen.de``) | NOT handled | Domain class is ASCII-only; ``ü`` breaks the run before ``.de``. Privacy hole. |
| 3. Punycode IDN (``user@xn--mnchen-3ya.de``) | Already handled | Punycode wire format is pure ASCII; matches the existing class. |
| JSON structure preservation | Already handled | JSON-aware fast path with ``ensure_ascii=False`` (added 2026-05-19). |
| No false positives on non-email | Already handled | TLD ``[A-Za-z]{2,}`` constraint blocks ``1.2``-style matches. |

### What was done (commit `8b59887`)

- Modified ``packages/llm_tracker_sdk/tests/test_scrubbers.py``
  — added five tests under a new ``i18n emails`` section:
  ``test_email_with_unicode_local_part_redacted``,
  ``test_email_with_idn_domain_raw_unicode_redacted``,
  ``test_email_with_punycode_domain_redacted``,
  ``test_scrub_unicode_email_in_json_body_round_trips``,
  ``test_unicode_text_without_email_unchanged``. Confirmed three failed
  before the regex fix (cases 1, 2, plus the JSON-Unicode round-trip);
  the punycode + no-false-positive cases passed already.
- Modified ``packages/llm_tracker_sdk/src/llm_tracker_sdk/scrubbers.py``
  — ``_EMAIL_RE`` local-part class swapped from
  ``[A-Za-z0-9._%+\-]`` to ``[\w.%+\-]``, non-TLD-domain class swapped
  from ``[A-Za-z0-9.\-]`` to ``[\w.\-]``; TLD stayed ``[A-Za-z]{2,}``.
  Added an inline comment explaining the ``\w``/Unicode rationale and
  why the raw Unicode-TLD case (e.g. ``example.中国``) is deferred.

### Decisions

- **Extend the existing pattern, do not add a second pass.** A second
  pattern would have to coordinate with the first to avoid
  double-tagging; extending the char classes keeps the rule single-
  sourced. ``\w`` is Python 3 Unicode-aware by default — no new
  regex engine, no new dep.
- **TLD stays ASCII (`[A-Za-z]{2,}`).** The TLD constraint is the
  scrubber's main false-positive guard. Real Unicode TLDs exist
  (``.한국``, ``.中国``, ``.рф``) but the canonical wire form is
  punycode (which is ASCII), and the user-prompt cases the task names
  all carry ASCII TLDs (``.com``, ``.de``). Loosening the TLD to
  ``\w`` would over-match numeric pairs like ``1.23`` — privacy-tilted
  but bad for log noise. Defer raw Unicode-TLD until there's evidence
  it appears in real prompts.
- **Test-first per step c.** Wrote the five new tests before the regex
  change; confirmed three failed cleanly (the two privacy holes plus
  the JSON variant which combines both). Then applied the regex fix.
  All 24 scrubber tests pass after the fix.

### Verification

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_sdk/tests/test_scrubbers.py -q
24 passed in 0.05s

$ .venv/bin/python3.12 -m pytest \
    packages/llm_tracker_sdk \
    packages/llm_tracker_plugin_analytics_sink \
    packages/llm_tracker_server -q
162 passed, 18 skipped in 5.57s

$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_sdk/
All checks passed!
```

Test count went 157 → 162 (+5 from this track). The +5 are:
``test_email_with_unicode_local_part_redacted``,
``test_email_with_idn_domain_raw_unicode_redacted``,
``test_email_with_punycode_domain_redacted``,
``test_scrub_unicode_email_in_json_body_round_trips``,
``test_unicode_text_without_email_unchanged``.

### Live state

The scrubber is exercised every time
``HookContext.request_text`` / ``HookContext.response_content_json``
fires under any plugin — analytics_sink, scope_guard (when re-enabled),
future plugins. After the next ``fly deploy`` the running image picks
up the broader pattern automatically. No live data backfill is needed
because the historic rows were already scrubbed via the prior regex;
the new behaviour applies to new exchanges only. The §"Queued
follow-ups" menu's last `i18n email scrubbing` item is now closed by
this commit.

## Continuation — task hierarchy won't-do closure (same day)

User question: "task hierarchy는 뭐야?" After explaining the
`task_id` layer's role (operator-side aggregation above `exchange_id`,
queued from 2026-05-17, referenced by ADR-0002 §"Cache key",
ADR-0030 §Deferred 5, and `roadmap.md` Phase 1c LRU cache), user
followed up: "난 conversation id로 왠만한 분석 목적은 전부 달성할 수
있다고 생각이 되어서, 굳이 task id가 필요할 것 같지는 않아." Agreed
to close as won't-do via docs-only patch.

### Rationale for closure

- `plugin_analytics.conversation_id` (added by ADR-0032 /
  Candidate-1 dedup, 2026-05-19) groups every exchange by the
  hash of `messages[0]` (with normalisation Rules A + B), so
  per-chain rollups (cost, turn count, message dedup ratio) are
  already available without a new schema axis.
- `first_msg_hash` is the stable retry-collapsing identifier; same
  prompt across retries lands under the same conversation.
- Task-level aggregation (e.g., "all conversations about feature
  X") can be expressed as operator SQL grouping on `conversation_id`
  plus an external label (git branch name, date range, conv-list
  union). No first-class column needed for the queries we have.
- ADR-0002's original "user must specify a task ID at startup" was
  a Phase-0-era hard constraint already softened by ADR-0005 (the
  reframing-as-plugin note in its status line); the `task_id` cache
  key was the last living dependency.

### What was done (docs-only — no commit hash on this entry yet)

- Modified ``docs/STATUS.md`` — §"Current phase" §"Queued
  follow-ups" reorganised: task hierarchy moved to the closed
  list with the won't-do reason; §"Next single step" rewritten
  to note the menu is empty.
- Modified ``docs/decisions/0030-scope-guard-plugin.md`` §Deferred 5
  — renamed to "Conversation-level alert aggregation" and pointed
  at `plugin_analytics.conversation_id` instead of the never-built
  `task_id` layer.
- Modified ``docs/decisions/0002-task-scope-enforcement.md``
  §"Cache key" — LRU cache key now reads
  `(conversation_id, sha256(...))` with a one-paragraph closure
  note explaining the supersede. ADR-0002's status line already
  says "reframed by ADR-0005" so the §"Consequences" bullets
  ("user must specify a task ID at startup") stay as historical
  context, not active contract.
- Modified ``docs/roadmap.md`` Phase 1c LRU cache line — same
  swap, with the closure note inline.

### Decisions

- **Won't-do, not a future ADR.** The task-hierarchy axis was
  always design-first deferred, never had an accepted ADR of its
  own. Closing it inside the existing `Followup cleanup` worklog
  + the three ADR/roadmap one-line patches is sufficient — no
  separate `0034-task-hierarchy-wont-do.md` ADR is warranted.
- **Don't touch ADR-0002's "user must specify a task ID at
  startup" Consequences bullets.** That ADR was already marked
  `reframed by ADR-0005`, so the bullets are historical. Adding
  closure noise to them would risk overwriting the original
  acceptance shape.
- **Cache key swap is one-paragraph in-line.** Both ADR-0002 and
  roadmap.md were edited in place rather than via a separate
  supersede ADR — the change is mechanical (rename the cache key
  field), not a re-decision of the cache itself.

### Verification

- ``grep -rn "task_id" docs/`` after the edits — every remaining
  match is either historical (sub-issue lists, prior worklogs, the
  ADR-0002 status line itself) or this worklog's closure-section
  references. No live "queued" or "deferred" pointers remain.
- No code touched; no tests run. Docs-only patch.

### Live state

§"Queued follow-ups" menu under §"Current phase" + §"Next single
step" both show the same empty state. Next active track is
intentionally undecided per the existing posture precedent (same
shape as the 2026-05-18 schema-cleanup closure). Operator can
either pick a fresh ad-hoc track or leave the queue empty
indefinitely; nothing is gating.

## Suggestions (untouched)

- **`ruff format` drift across five files** unrelated to this track:
  `packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/plugin.py`,
  `packages/llm_tracker_plugin_analytics_sink/tests/test_analytics_sink.py`,
  `packages/llm_tracker_plugin_analytics_sink/tests/test_classifier.py`,
  `packages/llm_tracker_plugin_analytics_sink/tests/test_normalize.py`,
  `packages/llm_tracker_sdk/tests/test_harness.py`. Multi-line call
  shapes that ruff now wants on a single line. Reverted to keep this
  commit surgical (per CLAUDE.md §2.3 — don't mix mass formatting
  into feature commits); pick up in a standalone `style:` commit when
  convenient.
