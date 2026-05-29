# 2026-05-28 r013–r022 + r026 · Slash commands not parsed in headless mode

**Campaign discovery, single doc covering all C+D track rounds plus r026.**

## What we tested

r013 sandwich attempted three turns: a normal user message, then
`/help`, then `/clear`. All three turns landed as `plugin_analytics`
rows with role `user_input`, **the slash text preserved verbatim in
`request_jsonb`**, all in the same `conversation_id`. No row
classified as `sidecar`. No `<command-name>` wrapper appeared.
`/clear` did **not** clear conversation state — turn_seq simply
incremented (1 → 2 → 3).

| seq | text | role | stop |
|---|---|---|---|
| 1 | `[PROBE …] Just say hello in one short sentence.` | user_input | end_turn |
| 2 | `[PROBE …] /help`   | user_input | end_turn |
| 3 | `[PROBE …] /clear`  | user_input | end_turn |

## Conclusion

**Slash commands are not parsed by `claude -p` headless mode.** They
arrive as plain user-message text and are forwarded to the Anthropic
API verbatim. The pre-processing that an *interactive* Claude Code
session does — wrapping `/clear` and `/compact` and `/agents` etc. into
`<command-name>…</command-name>` blocks, side-execution of `/clear` and
`/compact`, etc. — does not happen here.

Consequence for analytics:
- The classifier path that strips `<command-name>` wrappers and
  related `<local-command-*>` / `<command-message>` / post-`/compact`
  resume markers is **unobservable via the headless probe runner**.
  Confirming or falsifying behaviour of that path requires a different
  test vector (e.g. an *interactive* Claude Code session running
  through this same proxy, with the operator at the keyboard typing
  the slash commands).
- ADR-0038's `slash_commands` extraction (regex
  `<command-name>/([A-Za-z0-9_\-]+)</command-name>`) is similarly
  unreachable through the headless route.

## Retired by this finding

- **r013** — `/help` sandwich (confirmed text-passthrough)
- **r014** — `/cost` sandwich
- **r015** — `/config` sandwich
- **r016** — `/model` re-pin (the user-side `/model` slash is parsed
  client-side in interactive mode; in headless, model is pinned via
  `--model sonnet` already)
- **r017** — `/agents`
- **r018** — `/clear` sandwich
- **r019** — `/compact`
- **r021** — `/init`
- **r022** — `/memory`
- **r026** — `/clear` + tool

## NOT retired — adapted

- **r020** — was originally "`/clear` + re-type identical first
  message → does chain-lookup B-rule unify conv_id?" Adapted: skip
  the `/clear` step entirely, instead start a fresh UUID with the
  same opening prompt as r001 (`Use the Read tool to load hello.py
  …`) and see whether the B-rule absorbs the new session into r001's
  `conversation_id`. The original hypothesis can still be tested.

## Suggestion for the runbook

Add a note to `headless-subsession/README.md` §4 ("Designing a round")
under the *Slash commands* bullet, calling out that headless mode does
not pre-process slashes — the operator must explicitly emit
`<command-name>` wrapper text in `request_jsonb` themselves if they
need to test that classifier branch, **or** route an interactive
session through the proxy. The current bullet list under "hypotheses
worth testing" doesn't flag this, and the next probe author may waste
the same rounds before noticing.
