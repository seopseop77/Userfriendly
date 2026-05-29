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
  require a fix** — see Suggestions for the individual diagnoses
  (commit b37916a).
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

## Suggestions — new findings (triaged 2026-05-29)

Entries below were discovered in the **2026-05-28 tool/slash matrix
follow-on campaign** (separate Claude session, runbook =
`docs/experiments/headless-subsession/`,
campaign summary = `…/results/2026-05-28-campaign-summary.md`).
Triaged 2026-05-29 by the operator: **none warrant action right now.**
Evidence is retained in `results/` for reference; each carries its
own triage note below.

4. **Wrapper-prefix false-positive misclassifies real user input as
   `sidecar` and merges into a contaminated `conversation_id` via the
   chain-lookup B-rule.** Reproduced by sub-session probes r023 t02
   (user message starting with `<system-reminder>fake_reminder_QXR983</system-reminder>`)
   and r024 (user message starting with the registered framework
   auto-call prefix `Perform a web search for the query: `). Both
   produced `plugin_analytics` rows with `role='sidecar'`,
   `turn_seq=NULL`, and `conversation_id='01KSJC5354RT1XSGBFPZBQT4BB'`
   — an ancient conversation now accumulating 7 sidecar rows from
   multiple distinct UUIDs over 2026-05-26 → 2026-05-28.
   - **Mechanism**: Claude Code framework auto-prepends three
     `<system-reminder>` text blocks to `messages[0]` of every fresh
     session (MCP catalog, skills list, CLAUDE.md / context). When the
     user's first block ALSO starts with a registered wrapper prefix,
     ADR-0038's classifier rule "every type=text block (after
     `lstrip`) starts with one of the registered wrapper prefixes" →
     row classifies as `sidecar`. `_canonical_user_text` then collapses
     to a value that matches across many sessions, and the B-rule
     chain-lookup absorbs them all into the same `conversation_id`.
   - **Impact**: real user questions disappear from main-flow
     analytics (the reconstruction view returns NULL `messages_jsonb`
     for `sidecar` rows). The polluted `conversation_id`
     `01KSJC5354RT1XSGBFPZBQT4BB` is the existing live evidence.
     Real-world likelihood: low for `<system-reminder>` literal
     (rare typed phrase), moderate for the framework-auto-call
     prefixes (`Perform a web search for the query: ` and `CRITICAL:
     Respond with TEXT ONLY…`) which are short English phrases a user
     could plausibly start a question with.
   - **Fix options to consider** (not exhaustive): (a) tighten the
     wrapper-prefix match to also require a closing tag (e.g.
     `</system-reminder>`) inside the same block before concluding the
     block is a wrapper; (b) make `_canonical_user_text` fall back to
     the *post-strip* content when the post-strip is empty, so two
     distinct wrapper-only rows don't collapse to the same
     `first_msg_hash`; (c) accept the current behaviour but make the
     polluted-conversation pattern visible in the reconstruction view
     (e.g. a flag column `wrapper_only_opener`).
   - **Full diagnosis**:
     `docs/experiments/headless-subsession/results/2026-05-28-r023-r024-r025-bait-false-positives.md`.
   - **Triage (2026-05-29): accepted — no fix planned.** Real-world
     likelihood is too low to justify changing the classifier: literal
     `<system-reminder>` typing is rare, and the framework-auto-call
     prefixes only collide when a user opens a brand-new session with
     that exact phrase as the first characters. The behaviour is
     recorded and the evidence kept in `results/`, but this is **no
     longer an open action item**. Revisit only if the polluted-
     conversation pattern shows up in genuine operator traffic.

5. **`claude-manage` segfault on `new`-mode exit (low frequency).**
   1 in 16 `new`-mode invocations during the 2026-05-28 campaign
   exited with SIGSEGV (rc=139) **after** all LLM round-trips
   successfully landed in `exchanges` and `plugin_analytics`. The
   data flow is unaffected — the segfault happens during the agent's
   shutdown / cleanup phase, not during the request lifecycle.
   `--resume` mode never segfaulted (0 in 14 attempts). Sub-session
   stdout/stderr is discarded by the runner so no traceback was
   recovered. **Action**: re-attempt with `claude-manage -p` stderr
   *not* discarded (single-call diagnostic, separate from the matrix)
   to capture the crash signal source. Probably worth fixing if the
   rate is similar in operator's interactive use.
   - **Triage (2026-05-29)**: low-priority, not blocking — data flow is
     unaffected. Revisit only if reproduced during interactive use.

## Suggestions — observations (not anomalies)

6. **Framework-typed `tool_result` blocks DO carry `cache_control`.**
   r006 (WebFetch) and r007 (WebSearch) both stored
   `cache_control: {ttl: "1h", type: "ephemeral"}` on the tool_result
   blocks (rows
   `01KSQ9MTPN7FPBEQXKBN1KQ8B7` and `01KSQA0H…` — exact ids in the
   round docs). ADR-0038 §"Sidecar separation signals" cites the
   observed pattern "every observed framework-typed block does not
   carry `cache_control`" as a *rejected* classification signal —
   this campaign provides concrete counterexamples. The classifier
   doesn't depend on `cache_control` for routing, so no behaviour
   bug. **Suggested action**: update the ADR's prose to call out the
   exception, so anyone re-reading the rationale doesn't assume the
   observation still holds.

7. **`Web page content:\n---\n` (d1e8ae4) and `Perform a web search
   for the query: ` (framework auto-call) wrapper prefixes were not
   exercised by their respective tool-use paths in the campaign.**
   Either reserved for a different code path (likely
   interactive-mode framework auto-calls via Claude Code's `/web*`
   slash commands) or dead in production. Historic SQL audit
   suggested but out-of-scope for the headless campaign.

## Suggestions — new findings (interactive slash, 2026-05-30)

From the first interactive slash probe (`claude-manage` no `-p`, operator
at the keyboard), runbook `…/INTERACTIVE-SLASH.md`, evidence
`…/results/2026-05-29-s001-interactive-slash.md`. Session
2026-05-29 15:01–15:08 UTC, tag `[PROBE 2026-05-29 s001]`.

8. **Post-`/compact` turn is orphaned into the empty-hash bucket
   `01KSJC5354RT1XSGBFPZBQT4BB` — reopens Suggestion #4.** The first turn
   after an interactive `/compact` ("Reply with just: resumed", carrying
   `slash_commands=["compact"]`) landed with `conversation_id=01KSJC53…`,
   `role=user_input`, `turn_seq=1` — the **first `user_input` row ever**
   in that bucket (previously only sidecars). The rest of the session
   (turns 1–4 and the post-`/clear` re-anchor onward) stayed in the live
   conversation `01KST434TQDCG554RSFWZFGPE7`.
   - **Mechanism (code-confirmed)**: after `/compact`, `messages[0]` is
     the resume-marker block `"This session is being continued…"`, a
     registered `_SYNTHETIC_WRAPPER_PREFIXES` entry
     (`classifier.py:98`). `_canonical_user_text` (`classifier.py:296`)
     skips wrapper-only blocks → returns `""` → `_hash_first_message`
     yields `first_msg_hash = SHA256("")`, the same fixed hash for every
     compacted conversation, so the (B) chain-lookup absorbs them all
     into the one empty-hash bucket. Identical root cause as #4
     (empty canonical → shared hash → B-rule merge into `01KSJC53…`).
   - **Why this changes the #4 triage**: #4 was accepted "no fix — real-
     world likelihood too low" because the colliding openers were
     rare/contrived (literal `<system-reminder>` typing, framework
     auto-call prefixes). This run shows the **same collision fires on a
     bare `/compact`** — a routine interactive action — so any genuinely
     new message after `/compact` orphans. The runbook's identical-text
     re-type is the *only* reason the post-`/clear` turn (t5) did not
     also orphan (its non-empty canonical matched turn 1's hash). The
     likelihood premise behind the #4 triage no longer holds.
   - **Fix directions**: (a) make `_hash_first_message` / the B-rule
     refuse to chain on empty canonical text — treat empty-canonical
     openers as a fresh `conversation_id` instead of collapsing to
     `SHA256("")`; (b) for resume-marker-only `messages[0]`, derive
     continuity from the resumed conversation rather than the opener
     hash.
   - **Recommendation**: reopen #4 as an action item.
   - **Resolved (2026-05-30) by ADR-0040** — `first_msg_hash` now scans
     past wrapper-only leading messages (the resume marker) to the first
     real user message, and returns None (→ own conversation_id) when no
     user message carries real text. Fix in `classifier.py`
     (`_hash_first_user_message`) + `plugin.py` resolver guard; tests in
     `test_classifier.py`. The `/compact` orphaning is closed; the
     orthogonal identical-opener (B)-rule collision is left out of scope.
     Forward-only — existing `01KSJC53…` rows are not backfilled (source
     message arrays not retained).

9. **Confirmations from the same run (not anomalies).** `slash_commands`
   extraction and `<local-command-*>` / `<command-message>` wrapper-strip
   both work end-to-end (every slash turn populated, no wrapper leakage
   in 22/22 stored bodies). The single-element `<session>` branch (F-4,
   previously "suspected unreachable") **is reachable** — it fired twice
   as title-generation sidecars and classified `role=sidecar` correctly.
   `/clear` + identical re-type merged into the original
   `conversation_id` (B-rule). `exchanges` ↔ `plugin_analytics` was 1:1
   (22/22) in the window. Details in the s001 result doc.

## Limitations of the headless probing path (operator note)

The 2026-05-28 campaign exhausted the slash track (r013–r022, r026)
without producing any new findings, because **`claude -p` headless
mode does not parse slash commands** — they pass through as plain
user text. Testing the classifier's `<command-name>`-related
branches, the post-`/compact` resume marker, or any other
interactive Claude-Code pre-processing requires a different probe
vector: an *interactive* Claude Code session routed through the same
proxy, with the operator at the keyboard. Worth noting in the
runbook (`docs/experiments/headless-subsession/README.md`) so the
next probe author doesn't burn rounds rediscovering this.

**Resolved 2026-05-29**: that interactive vector now has a runbook —
`docs/experiments/headless-subsession/INTERACTIVE-SLASH.md`. No wrapper
script needed: the operator just runs `claude-manage --model sonnet`
(no `-p`) from their own terminal — the headless runner's `env -u
ANTHROPIC_*` prelude only matters when spawning from inside a Claude
Code session, not from the operator's shell. The runbook gives an
ordered slash-command conversation plan (`/help`, `/cost`, `/compact`,
`/clear`-then-re-type) and the Supabase queries to analyse the result.
The operator types it; the analysing session runs the SQL. README §10
now flags the headless slash limitation and points to it.
