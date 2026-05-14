# 2026-05-14 · Plugin ecosystem — Option B SSE extractor + analytics_sink + keyword_block

**Author**: Claude Code
**Session trigger**: Multi-checkpoint task — Option B SSE Extractor + `analytics_sink`
plugin + `keyword_block` plugin promotion + Dockerfile/fly.toml bundling. ADR-0026
(HookContext response accessors) and ADR-0027 (exchange row close-out policy) gate
the code changes per CLAUDE.md §4 (HookContext is a public interface).
**Related docs**: `docs/decisions/0026-hookcontext-response-accessors.md` (new),
`docs/decisions/0027-exchange-row-close-out-policy.md` (new),
`docs/worklog/2026-05-13-phase3b-agent.md` (prior session), STATUS.md ("Next
single step" before this session = ADR-0026/close-out policy).

## Interpretation

The task as written said "Write `docs/decisions/0024-hookcontext-response-accessors.md`"
and "Do not touch ... `docs/decisions/` files other than 0024." Two collisions with
the live repo:

- ADR-0024 was already taken by the Phase-3b agent fail-closed ADR
  (commit `79a0ae9`). Overwriting it would erase a load-bearing decision.
- STATUS.md (commit `55cb2e3`, same session lineage) explicitly queued a separate
  ADR — "exchange row close-out policy" — as the *prerequisite* to Option B, so the
  second signature extension on `record_exchange_timing` lands under a stable
  contract. The task skips this ADR entirely.

Surfaced both to the user via `AskUserQuestion`. The user picked **ADR-0026** for
the HookContext accessors ADR and **bundled in this session** the close-out policy
ADR (now **ADR-0027**), so both ADRs land before the code-touching β/γ/δ/ε/ζ
checkpoints. The user also picked all three "recommended" answers for ADR-0027's
substantive decisions (best-effort NULL on response side, write a row on pre-SSE
upstream failure, pull `ended_at`/`latency_ms`/`model_requested` into the blocked
helper).

Other reinterpretations from the task as written:

- `inpokens` → `input_tokens` (typo); `thr` → `the`; `contnt` → `content`;
  `t_tokens` → `input_tokens`; `ugin.py` → `plugin.py`; `init.py` → `__init__.py`;
  `hook"on_request_received"]` → `hooks = ["on_request_received"]`;
  `https://-tracker-server.fly.dev` → `https://llm-tracker-server.fly.dev`.
- Anthropic's standard SSE puts cache tokens in
  `message_start.message.usage.cache_read_input_tokens` /
  `cache_creation_input_tokens` (the task's `ca_tokens` is a truncation); the
  extractor reads the canonical names.
- `keyword_block` is already a proper package (`packages/llm_tracker_plugin_keyword_block/`)
  — the task's "promote from test harness" framing is outdated by one Phase-2
  workstream. The ε checkpoint becomes: rename `LLMTRACK_KEYWORDS_BLOCK_LIST` →
  `LLMTRACK_KEYWORD_BLOCK_LIST` (canonical name per task), default to empty list
  (was: two built-in test defaults), refresh docstrings to drop "TEST-ONLY"
  framing now that it ships in the server image.

## What was done

### Checkpoint α — ADR-0026 + ADR-0027 (commit `<pending>`)

- Created `docs/decisions/0026-hookcontext-response-accessors.md` — Accepted.
  Amends ADR-0012; adds `_parsed_response: object | None` field +
  `response_usage()` / `response_content_json()` accessors + `org_id` field on
  `HookContext`. Settles STATUS.md "Phase 1c prerequisites" response-side
  bullet for the L3 case.
- Created `docs/decisions/0027-exchange-row-close-out-policy.md` — Accepted.
  Three axes settled: best-effort NULL on response-side columns; write a row
  on pre-SSE upstream failure (documented; impl is a follow-up checkpoint
  under this ADR's banner); pull `ended_at`/`latency_ms`/`model_requested`
  into `record_exchange_blocked` (impl in checkpoint β alongside the helper
  signature change).
- Created this worklog scaffold (`docs/worklog/2026-05-14-plugin-ecosystem.md`).

## Decisions

- **ADR number split**: HookContext response accessors → ADR-0026; exchange row
  close-out policy → ADR-0027. ADR-0024 stays as agent fail-closed (commit
  `79a0ae9`). Confirmed with the user via `AskUserQuestion`.
- **ADR-0027 §"Decision"**:
  1. Best-effort NULL on response-side columns (`model_served`, `input_tokens`,
     `output_tokens`, `cache_*`, `stop_reason`) — extractor never raises; missing
     fields stay NULL.
  2. Pre-SSE upstream failure path writes a row anyway with `status_code` +
     `ended_at` + `model_requested` + `latency_ms` populated. Response-side
     fields NULL. Today the pre-SSE-failure path has no INSERT at all.
  3. Blocked-path parity: pull `ended_at_ms` + `latency_ms` + `model_requested`
     into `record_exchange_blocked` so blocked rows are queryable on the same
     axes as happy-path rows.

## Verification

(per-checkpoint blocks appended below)

## What's left / known limits

- Checkpoint β — SSE extractor module + SDK changes + forwarder wire-up +
  storage helper signature extension + tests.
- Checkpoint γ — migration 0007 `plugin_analytics` table.
- Checkpoint δ — `analytics_sink` plugin package.
- Checkpoint ε — `keyword_block` plugin polish (env var rename, default empty,
  drop "TEST-ONLY" framing).
- Checkpoint ζ — Dockerfile + fly.toml bundling.
- Pre-SSE failure-path row write (ADR-0027 axis 2 impl) — deferred to a
  follow-up checkpoint after ζ ships. Listed here so the next session does
  not re-litigate the policy.

## Handoff

Both gating ADRs landed in checkpoint α. The next checkpoint (β — SSE
extractor + SDK changes + forwarder wiring + tests) is the largest code
change of this session and is unblocked.
