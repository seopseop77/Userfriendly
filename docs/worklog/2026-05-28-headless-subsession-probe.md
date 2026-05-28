# 2026-05-28 · Headless sub-session probe

**Author**: Claude Code
**Session trigger**: User asked whether Claude (inside Claude Code) can drive
`claude-manage` directly to send conversation patterns and surface
manage-logic defects, then asked to verify cache-hit mechanics under
`--resume`.
**Related docs**: `docs/experiments/headless-subsession/README.md`,
ADR-0038/0039 (analytics reconstruction),
`packages/llm_tracker_agent/src/llm_tracker_agent/cli.py`

## Interpretation

Investigation track — not on the STATUS.md critical path (fly deploy is
still the next single step). User wants to run a probe matrix in a
*separate* Claude session to stress manage logic; today's session
establishes the invocation contract and writes a runbook so the matrix
run is consistent and reproducible.

## What was done

- Identified the headless invocation contract that survives parent-process
  env pollution and Claude Code's `--bare` keychain-disable trap.
- Verified `--resume` preserves conversation memory but `cache_read`
  collapses to 0 unless the model is pinned (autoselect flips between
  `claude-opus-4-7[1m]` and `claude-opus-4-7` across turns of one
  session, defeating the prompt cache).
- Cross-checked `exchanges` + `plugin_analytics` for probe traffic and
  surfaced 3 manage-logic anomalies (recorded under Suggestions — not
  fixed in this session).
- Created
  `docs/experiments/headless-subsession/{README.md,runner.sh,results/}`
  as a self-contained runbook for the follow-on matrix session
  (commit 2b69a72).
- Created `docs/experiments/README.md` describing the new folder's
  purpose — probe / investigation track, separate from worklog and
  decisions (commit 2b69a72).

## Decisions

- **`docs/experiments/` (not `docs/probes/`)** per user instruction.
- **Pin `--model sonnet` in the runbook** per user instruction. Today's
  verification used `claude-haiku-4-5` because pinning *any* model is
  enough to demonstrate cache survival, and Haiku kept the verification
  cost down. The matrix session uses the user-chosen sonnet.
- **No fixes for the 3 anomalies yet** — the matrix session will collect
  broader reproductions before remediation is designed. Logged in
  Suggestions only.
- **STATUS.md untouched** — investigation track, fly deploy remains the
  active critical path.

## Verification

Two probe rounds against the live proxy + Fly server + Supabase.

| | Round A (autoselect) | Round B (pinned haiku) |
|---|---|---|
| T1 result | "Noted, teal is your color." | "Your favorite color is teal." |
| T2 result (`--resume`) | "Teal." | "Teal." |
| T1 cache_write / read | 16624 / 56250 | 41065 / 0 |
| T2 cache_write / read | 73547 / **0** | 12063 / **41540** ✓ |
| Round cost | $0.61 | $0.075 |
| Model on T1 / T2 | `opus-4-7[1m]` / `opus-4-7` (flipped) | `haiku-4-5-20251001` (pinned) |

Stdout JSON `usage` counters matched supabase columns 1:1 for the Opus
round. Haiku round confirmed missing from `plugin_analytics` while
present in `exchanges` (see Suggestion #2).

## What's left / known limits

- Matrix execution itself is deferred to a separate Claude session
  following the runbook in `docs/experiments/headless-subsession/`.
- Anomalies recorded as Suggestions, not fixed.

## Handoff

For the next session driving the matrix:

1. Read `docs/experiments/headless-subsession/README.md` end to end.
2. Use `runner.sh` for the standard recipe; don't reinvent the env-unset
   + stdin-redirect + model-pin combo — it is load-bearing.
3. Each round writes one result doc under `results/`.
4. If a round confirms a 4th anomaly, append a numbered entry to the
   Suggestions section of this worklog (or start a follow-up worklog if
   the round itself is a work-unit). Don't bury findings only in
   `results/`.

For the human operator: STATUS.md still says "fly deploy" is the next
critical step. This investigation track is parallel and does not block
it.

## Suggestions (untouched — found while probing)

1. **`model_served` context-window suffix is lost in supabase.** Claude
   Code identifies 1M-context Opus as `claude-opus-4-7[1m]` client-side.
   Two bad downstream outcomes were observed in `exchanges`:
   - Row `01KSPPY37TS... 2026-05-28 07:14:14` —
     `model_requested = 'claude-opus-4-7[1m]'` reached Anthropic
     verbatim → `status_code = 404`. The `[1m]` suffix is a
     Claude-Code-internal display tag, not a valid Anthropic model ID.
   - Successful 200 rows record `model_served = 'claude-opus-4-7'` even
     when the client reported `[1m]`. The 1M vs 200k distinction is not
     queryable in supabase, which breaks any cost / latency cohort by
     context window.
2. **`plugin_analytics` sink omits Haiku traffic.** `exchanges` rows
   `01KSPQKKRP...` and `01KSPQM9DP...` (Haiku 200 `end_turn`) have no
   matching `plugin_analytics` row, while Opus 200 `end_turn` rows from
   the same window do. Sink filter is likely model-gated. Breaks
   model-cohort analytics.
3. **`stop_reason` / `model_served` NULL on some 200 rows.** Example:
   row `01KSPQQWN93Z... 07:28:20` — status 200 but both columns null.
   Data-quality gap; root cause not investigated.
