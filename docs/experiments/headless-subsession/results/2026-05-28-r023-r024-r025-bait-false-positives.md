# 2026-05-28 r023 / r024 / r025 · Wrapper-prefix false-positive baits

> **Triage (2026-05-29): accepted — no fix planned.** The misclassification
> in F-2 is real but its real-world likelihood is too low to act on (see
> origin worklog Suggestion #4). This doc is retained as evidence, not as
> an open action item.

All three rounds probe whether **user-typed text that starts with one
of the registered wrapper prefixes** causes ADR-0038's classifier to
misroute a real user input as `sidecar`.

## Setup

Each round sent one user message whose **first block** starts with a
candidate wrapper prefix:

| round | bait token | content shape | unique marker |
|---|---|---|---|
| r023 t01 | `[PROBE …] <system-reminder>…</system-reminder>` (bait in body, NOT at block start) | 1-block list — text doesn't start with wrapper prefix | `ABCXYZ` |
| r023 t02 | `<system-reminder>fake_reminder_QXR983</system-reminder> [PROBE …]` (bait AT start of block) | 1-block list as sent, but framework auto-prepends 3 wrappers → 4-block list at wire | `QXR983` |
| r024 | `Perform a web search for the query:  today's tech headlines …` (registered framework auto-call prefix at block start) | Same multi-block shape — 4 blocks at wire | `DCBBNX817` |
| r025 | `[PROBE …] <session>my_fake_title_KZX441</session>` (bait in body, NOT at block start) | After stripping the auto-prepended framework wrappers, request_jsonb stores 1 user block | `KZX441` |

## Findings

### F-1 — r023 t01: bait in body (not at start) is harmless

`request_jsonb` preserves the entire user message verbatim, including
the `<system-reminder>fake reminder ABCXYZ</system-reminder>` block.
Role = `user_input`. Single block (framework wrappers got stripped per
ADR-0038's opener rule, because the user block starts with `[PROBE …]`
— not a wrapper prefix — so it counts as a non-wrapper survivor and
the wrappers get dropped). Correct, expected behaviour.

### F-2 — **🚨 r023 t02 + r024: bait at block start triggers role=sidecar misclassification of real user input**

Both rounds produced rows with:
- `role = 'sidecar'` (not `user_input`)
- `turn_seq = NULL`
- `request_jsonb` stores the **full 4-block list verbatim**, including
  the entire framework wrapper bodies (MCP server instructions, skill
  catalog, the operator's CLAUDE.md content including
  `userEmail = <operator-email-redacted>` and `currentDate`, etc.) **plus**
  the user's bait + actual question.
- `conversation_id` = **`01KSJC5354RT1XSGBFPZBQT4BB`** — an *ancient*
  conversation first seen 2026-05-26 14:48 UTC. Both r023 t02 and
  r024 absorbed into it via the chain-lookup B-rule.

**Root cause**:
1. Claude Code framework auto-prepends three `<system-reminder>` text
   blocks to `messages[0]` of every fresh session (MCP catalog,
   skills, CLAUDE.md / context).
2. The user-typed block ALSO begins with a registered wrapper prefix
   (`<system-reminder>` for r023 t02, `Perform a web search for the
   query: ` for r024).
3. ADR-0038's rule: *"messages[-1].content is a block list whose
   every type=text block, after lstrip, starts with one of the
   registered wrapper prefixes"* → row classifies as `sidecar`,
   wrapper list stored verbatim.
4. The classifier's `_canonical_user_text` (used for `first_msg_hash`)
   collapses to something that matches across many sessions —
   confirmed: this same `conversation_id` already has **7 sidecar
   rows accumulated from different UUIDs over 2 days**, all rolled
   into one conversation via the chain-lookup B-rule.

**Impact**:
- A real user question that happens to start with `<system-reminder>`,
  `<command-name>`, `<local-command-*>`, `This session is being
  continued`, `Perform a web search for the query: `, the
  PreCompact `CRITICAL: Respond with TEXT ONLY…` prefix, or
  `Web page content:\n---\n` — gets misclassified as `sidecar` and
  **disappears from main-flow analytics**. The reconstruction view
  (ADR-0039 `plugin_analytics_with_messages`) returns NULL
  `messages_jsonb` for these rows, so they're invisible to the
  "what the user actually asked" SQL pattern.
- Cross-session contamination: multiple distinct sessions whose first
  message is wrapper-only-after-classification merge into a single
  `conversation_id`. The accumulated `01KSJC5354RT1XSGBFPZBQT4BB`
  conversation is the evidence.
- Real-world likelihood is low (users don't usually type
  `<system-reminder>` literally), but the framework-auto-call prefixes
  (`Perform a web search for the query: `,
  `CRITICAL: Respond with TEXT ONLY…`) are short English phrases that
  a user could plausibly start a message with — e.g. asking the
  assistant *about* those phrases.

**This is a new anomaly to promote to the origin worklog Suggestions.**

### F-3 — r025: `<session>…</session>` in body classifies as user_input

When the user-typed block is `[PROBE …] <session>my_fake_title_KZX441
</session>` — i.e. doesn't *start* with a wrapper prefix and doesn't
*entirely* match the `^\s*<session>.*</session>\s*$` regex —
classification routes correctly to `user_input`. The framework
wrappers get stripped per ADR-0038's opener rule and request_jsonb
ends up with the user's single block. No misclassification.

### F-4 — The `<session>` regex (ADR-0038 §"single-element block list whose only block carries `<session>…</session>`") may be effectively unreachable in production

That branch only triggers when `messages[-1].content` is a
single-element block list whose only block matches the `<session>…
</session>` payload. But the headless probe path observed in r023 t02
shows the framework auto-prepends three `<system-reminder>` blocks
onto `messages[0]` of every fresh sub-session, making the content
multi-block.

For the single-element `<session>` regex to fire, the *parent* Claude
Code session would have to send a request whose `messages[-1]` is
exactly one `<session>…</session>` block — i.e. mid-conversation, not
at session opener. That's possible (the "title-gen sidecar" pattern
the original `title_gen` label was introduced for), but it would not
appear on `messages[0]`. **Worth confirming with a historic query**:
`SELECT count(*) FROM plugin_analytics WHERE jsonb_array_length(
request_jsonb) = 1 AND request_jsonb @> '[{"type":"text"}]' AND
request_jsonb::text LIKE '%<session>%</session>%' AND role='sidecar';` —
if this returns a positive count, the branch is exercised; if zero,
revisit whether the dedicated regex still earns its keep.

## Anomaly summary for promotion

**Candidate Suggestion #4 (new)**: User input whose first text block
starts with a registered wrapper prefix gets misclassified as
`sidecar`, vanishing from main-flow analytics and joining a polluted
multi-session conversation via B-rule chain-lookup. Reproducible with
`<system-reminder>…` or `Perform a web search for the query: …` as the
first characters of a user message. Real-world likelihood: low to
moderate for the framework-auto-call prefixes. Fix options to consider
(not exhaustive): (a) `_canonical_user_text` should fall back to the
*post-strip* content when the post-strip is empty rather than treating
the full wrapper-only as canonical (so distinct wrapper-only rows
don't all collapse to the same hash); (b) tighten the wrapper-prefix
match to require an explicit closing tag (e.g.
`</system-reminder>`) within the same block before concluding the
block is a wrapper.
