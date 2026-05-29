# 2026-05-28 · Headless sub-session tool/slash matrix — campaign summary

**Date**: 2026-05-28
**Runner variant**: `runner-allow.sh` (tool-allow, `bypassPermissions`,
`--max-turns 10`, fixed workdir
`/Users/minseop/Desktop/MyProjects/Userfriendly_test`).
**Model**: `claude-sonnet-4-6` (pinned via `--model sonnet`).
**Auth**: OAuth (Claude Code subscription) via macOS Keychain.
**Total rounds planned**: 26. **Run as fresh probes**: 11 (r001–r007,
r010–r011, r020-adapted, r023–r025). **Retired by coverage**: 2
(r008, r009 covered by r002, r004). **Retired by environment
limitation**: 11 (r013–r022 + r026 — slash commands not parsed in
headless mode).

## What was confirmed working as designed

| invariant | rounds | status |
|---|---|---|
| Per-LLM-round-trip → exactly one `plugin_analytics` row | r001–r011 | ✅ |
| `role ∈ {user_input, tool_result}` alternates correctly | r001–r011 | ✅ |
| `turn_seq` gap-free over main-flow rows, including across `--resume` and across model-initiated tool chains | r001 (depth 2), r002 (parallel), r004 (depth 4), r010 (mixed user/tool) | ✅ |
| `conversation_id` stable across `--resume` calls | r001, r002, r003, r004 | ✅ |
| Parallel `tool_use` (2-way and 3-way) collapses to a single `tool_result` row with N blocks; `turn_seq` increments by exactly 1 | r002 | ✅ |
| Model-initiated tool chains within one user prompt produce contiguous rows with `stop_reason: tool_use` on chained rows and `end_turn` on the terminator | r004 | ✅ |
| `cache_read[N] ≈ cache_write[N-1]` chain holds within-round | r001, r002 | ✅ |
| `system_prompt_jsonb` variation tracker stores on first row, NULL on subsequent unchanged rows | every round | ✅ |
| `is_error: false` for Bash with non-zero exit; `is_error: true` for Read on missing file; both still `role: tool_result` | r010 | ✅ |
| **Chain-lookup B-rule unifies identical first messages from different UUIDs into one conversation_id** | r020 (adapted) | ✅ working as designed |
| Wrapper-prefix stripping on opener: user block that doesn't start with a wrapper prefix → wrappers stripped, user content preserved | r023 t01, r025 | ✅ |

## Anomalies / candidate findings

### A-1 (triaged 2026-05-29 — accepted, no fix; low likelihood): Wrapper-prefix false positive misclassifies real user input as `sidecar` and merges into a contaminated conversation_id

Reproduced by r023 t02 and r024. See
`results/2026-05-28-r023-r024-r025-bait-false-positives.md` for the
full diagnosis. Polluted conv `01KSJC5354RT1XSGBFPZBQT4BB` already
holds 7 sidecar rows from different UUIDs accumulated 2026-05-26 →
2026-05-28.

**Triage**: accepted as low-likelihood; no fix planned. Recorded in
origin worklog Suggestion #4 as a closed (non-action) finding, not as
an open item. Evidence retained here for reference.

### A-2 (NEW, low-frequency, recording but not promoting): `claude-manage` segfault on `new`-mode exit

r001 t01 segfaulted (exit code 139) **after** all required LLM
round-trips successfully completed and the rows landed in supabase.
r002 t01, r003 t01, r004 t01, r005 t01, r006 t01, r007 t01, r010 t01,
r011 t01, r013 t01, r020 anchor, r020 clone, r023 t01, r023 t02, r024,
r025 — none segfaulted. **1 in 16 `new`-mode invocations.** Data flow
unaffected. No traceback recovered (sub-session stdout/stderr
discarded by the runner). Recording so a future probe author can
re-encounter it without surprise.

### A-3 (NEW, sane behaviour, recording): UUID re-use under `new` mode is rejected

`runner-allow.sh new <uuid-of-existing-conversation>` exits 1
immediately with no traffic, no exchange, no audit log entry. Sane —
the agent refuses to overwrite an existing conversation store under
`new` mode. Probe author should always use `resume` for second-and-
later turns; the early failure is a useful guardrail.

### A-4 (NEW, observation only — not a bug, but contradicts ADR-0038 prose): Framework-typed `tool_result` blocks DO carry `cache_control`

r006 (WebFetch) + r007 (WebSearch) both show `cache_control: {ttl:
"1h", type: "ephemeral"}` on the framework-emitted `tool_result`
blocks. ADR-0038 §"Sidecar separation signals" notes the observed
pattern "every observed framework-typed block does *not* carry
`cache_control`" as an unreliable signal it was rejected for
classification — this round provides a concrete counterexample for
both Web* tools. The classifier doesn't depend on `cache_control` for
routing, so no behaviour bug; but the ADR's observation could be
updated.

### A-5 (NEW, observation only): Registered wrapper prefixes
`Web page content:\n---\n` (d1e8ae4) and
`Perform a web search for the query: ` were NOT exercised by their
respective tool-use paths

r006 (model-driven WebFetch) returned summarised structured content
(`**Main Heading:** …`), not the `Web page content:\n---\n` raw
envelope. r007 (model-driven WebSearch) returned the WebSearch
runtime's body, not the `Perform a web search for the query: `
prompt. **Either**: those wrapper-prefix entries are reserved for a
different code path (likely Claude Code framework auto-calls that
synthesise a `role=user` text block bearing the literal prefix —
plausibly the `/web*` slash command on the *interactive* code path),
**or** the entries are currently dead. Confirm with a historic query
of `plugin_analytics::text LIKE` against each prefix — out of scope
for this campaign.

## Behavioural observations worth recording (not anomalies)

1. **Server-side prompt cache hits across client-side conversations.**
   r002 t01's first row already showed `cache_read_tokens = 47208`
   despite being a fresh conversation_id — Anthropic's prefix-hash
   cache matches the near-identical system prompt + tool registrations
   shared with prior rounds in the same workdir. "First row of a round
   has `cache_read = 0`" is true only on a *cold* workdir.
2. **The model self-skips tool calls when it judges the output
   excessive or describable.** r011 t01 and t02 prompts asked for
   `seq 1 20000 | …` Bash execution; sonnet declined to call the
   tool both times, even with "you MUST invoke" framing. Probe authors
   targeting tool_result size limits need prompts whose answer the
   model cannot fabricate (e.g. Read of an opaque or unseen file).
3. **`output_tokens` accounting for Write tool**: a Write tool_use
   with a 50-object JSON body cost `output_tokens=1753` on its
   *user_input* row, not on the tool_result row — the model's
   emission of the JSON payload is what was billed, registered against
   the row that triggered it (r005). Slightly counter-intuitive for
   token-accounting queries; worth documenting in the dashboard.
4. **`is_error` semantics differ by tool.** Bash sets `is_error: false`
   even on a failing command (the tool itself worked); Read/Edit/Write
   set `is_error: true` when the tool cannot do its job. Bash
   always emits the field explicitly; Read/Glob/Grep emit it only on
   failure (the success case omits `is_error` from the block).
   Querying `is_error = true` finds *tool-level* failures, not command
   exit-code failures — for the latter, inspect `tool_result.content`.

## Environment / runbook limitations discovered

1. **Slash commands are not parsed by `claude -p` headless mode.** They
   pass through as plain user text, preserved verbatim in
   `request_jsonb`. The classifier paths that strip `<command-name>`
   wrappers, the post-`/compact` resume marker, and other interactive
   pre-processing artefacts are unreachable through this probe runner.
   **Suggestion for runbook**: add a §"Slash commands" subsection to
   `README.md` flagging this so the next probe author doesn't burn
   rounds rediscovering it. Testing those classifier paths requires
   an interactive Claude Code session routed through the same proxy,
   typed by the operator.
2. **`request_jsonb` prefix filter only matches the `user_input`
   row.** The `[PROBE …]` prefix lives in `messages[-1].content` for
   exactly the round-opening user turn. Tool_result rows in the same
   round don't carry the prefix — they carry the tool_result blocks.
   **Effective filter**: get the conversation_id from the user_input
   row, then pull all rows in that conversation. README §5's query
   pattern is *correct* but it's worth a note that the prefix filter
   alone misses ~half the rows of any round.

## Suggested runbook updates

- README §1: deviations table (this campaign's tool-allow variant) →
  consider promoting `runner-allow.sh` to a documented sibling of
  `runner.sh`, with the variant flagged for tool/slash-mapping
  campaigns.
- README §3: clarify that the prefix lives only on the row whose
  `request_jsonb` carries the user's typed text — not on follow-up
  tool_result rows in the same round.
- README §4: add a "Slash commands" caveat per Limitation 1 above.
- README §7: append new non-bugs A-3, A-4 — and the resolved bait
  case A-1 (once it has a Suggestions entry on the origin worklog).
- A-2 segfault tracker: add a small bullet to §8 "Pitfalls" noting
  the 1-in-16 segfault rate on `new` mode and that it doesn't block
  data flow.

## Suggested follow-on probes (not for this campaign)

- **Interactive Claude Code session routed through the proxy** to
  exercise slash command classifier branches (the only path that
  produces real `<command-name>…`, `<local-command-*>`, and
  post-`/compact` resume marker wrappers).
- **Direct historic SQL audit** to confirm or falsify whether the
  WebFetch and WebSearch wrapper-prefix entries are dead, plus
  whether the single-element `<session>` regex branch ever fires.
- **Adversarial conversation hijack via B-rule chain-lookup**: send a
  message whose `messages[0]` text is engineered to collide with a
  victim conversation's `first_msg_hash`. The polluted conv
  `01KSJC5354…` already proves the mechanism — a hostile probe
  could confirm the worst-case scope.
- **Larger tool_result size probe**: design prompts the model cannot
  fabricate (e.g. Read on an opaque file the workdir contains by
  fixture), to push tool_result content past 100 kB and observe any
  truncation / storage behaviour. r011's blocker was model
  self-skipping.

## Costs

OAuth quota. ~30 sub-session LLM round-trips across the campaign at
sonnet pricing equivalent. No out-of-pocket.
