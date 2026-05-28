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
- Cross-checked `exchanges` + `plugin_analytics` for probe traffic.
  Surfaced 3 candidate anomalies, then followed each to root cause
  (`extractors/anthropic.py`, `plugin_analytics_sink/plugin.py`, and a
  re-run of the supabase queries with a correct time window). **None
  require a fix** — see Suggestions for the individual diagnoses.
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
- **Investigated all 3 surface observations to root cause in this same
  session; none warrant a fix** (see Suggestions). Original plan had
  been to defer remediation to the matrix session, but reading the
  code + re-querying supabase took only a few minutes and removed
  three would-be false leads from the matrix's plate.
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

## Suggestions — investigated, no action needed

Each candidate "anomaly" surfaced during the probe was followed up to a
root cause in this session. None require a code change. They are kept
here so a future session doesn't re-investigate the same surface.

1. **`model_served` context suffix (`[1m]`) absent in supabase.**
   Root cause: `extractors/anthropic.py:120` stores whatever
   `message_start.message.model` contains. Anthropic returns the
   resolved model id *without* the `[1m]` tag — `[1m]` is a
   Claude-Code-internal display string, not a wire model id. The single
   404 row (`01KSPPY37TS...`) was a transient case where the client
   sent `[1m]` verbatim and Anthropic rejected it; in steady state the
   client appears to strip the suffix before the wire call. Not a
   manage-logic bug. No fix — stripping in proxy would be "fixing what
   isn't ours" and violates CLAUDE.md §2.2 (simplicity first).
2. **`plugin_analytics` initially appeared to omit Haiku.** Re-checked:
   it does not. The original verification used `now() - 5 minutes`
   windows that happened to land *after* the Haiku round had landed,
   so the rows existed but were outside the time filter. Re-queried
   with `created_at BETWEEN '2026-05-28 07:24' AND '07:27'`: Haiku
   rows `01KSPQM5NN...` (T1, cache_write=41065) and `01KSPQMCTA...`
   (T2, cache_read=41540) are present and match stdout 1:1. Sink code
   (`plugin_analytics_sink/.../plugin.py`) confirmed to have no model
   filter — every exchange the `on_persisted` hook fires for becomes a
   row, regardless of model. False positive; no fix.
3. **`stop_reason` / `model_served` NULL on some 200 rows.** Intended
   behaviour. `extractors/anthropic.py` docstring lines 8–9 cite
   ADR-0027 axis 1 ("best-effort NULL"). Both columns are captured
   from streamed events (`message_start` for `model_served`,
   `message_delta` for `stop_reason`). Streams that end without those
   events — mid-flight cancellation, very long latency,
   error-truncated replies — honestly record NULL instead of guessing.
   NULL is the intended signal for "no information". No fix.
