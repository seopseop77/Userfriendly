# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `CLAUDE.md §5, §6` for the rules.
>
> **Keep this file short.** Timestamp + active worklog + last 5 commits +
> where we paused + next step. History belongs in worklogs and git log.

---

**Last updated**: 2026-05-26

## Active worklog

`docs/worklog/2026-05-26-display-role-vocab.md`

## Recent commits (last 5)

- `<pending>` docs: backfill 937f6d1 hash in worklog + STATUS
- `937f6d1` analytics_sink: fix title_gen list-shape classify
- `400a68c` docs: backfill d34818a + 5f60435 hashes in worklog + STATUS
- `5f60435` analytics_sink: ADR-0037 backfill script + applied
- `d34818a` analytics_sink: ADR-0037 display role vocab split

## Where we paused

**ADR-0037 fully delivered + post-deploy regression fixed.**
`conversation_messages.role` now uses the 5-value display vocab
(`system_prompt`, `user_input`, `title_gen`, `model_output`,
`assistant`); the session-opener splits into its own row at
`msg_index=0` and the user's first typed text lives at
`msg_index=1`. Forward writes, the priority UPSERT, and the helper
view all updated; backfill applied to the 246 historic rows.

**Follow-up (937f6d1)**: first title-gen sidecar to arrive after
the ADR-0037 deploy (conv `01KSGW0CHY3HAFEM4QRRJ3Y1ST`,
2026-05-26 00:47) was misclassified as `user_input`.
`classify_message` only fired the `<session>` rule on string
content; title-gen arrives as a single-block list and Rule B
collapses to string at storage time, so the un-normalised
classification missed the shape. Added a narrow list-of-one branch
mirroring the string rule + two unit tests + one-shot UPDATE on
the affected row. All 11 string-`<session>` rows now carry
`title_gen`.

- Backfill applied via Supabase MCP `execute_sql` in three phases.
  Phase A: one UPDATE renamed roles across un-migrated convs
  (104 model_output, 65 → assistant, 53 → user_input, 24 split
  between title_gen / assistant by `<session>` content shape;
  one historic mislabel auto-corrected).
  Phase B: DO block split 26 msg_index=0 array rows whose first
  block was a synthetic wrapper, shifting siblings +1 via a
  temp-negative trick.
  Phase C: `plugin_analytics.n_messages_at_request += 1` for every
  exchange in a split conv.
- Final state: 272 rows (was 246, +26 system_prompt inserts), 37
  conversations, 0 stragglers, helper view `gap = 0` against
  `n_messages_at_request` on the sample conv.
- Backfill script committed at
  `packages/llm_tracker_plugin_analytics_sink/scripts/backfill_display_role_vocab.py`
  (idempotent — re-runs skip already-migrated convs).

## Next single step

**Operator's choice.** ADR-0037 is closed. Two outstanding tracks:

1. (back-burner) Participant-#1 install — see ADR-0035 follow-up
   in `docs/worklog/2026-05-25-uv-tool-install.md`. Owner: operator;
   waits on signup-app redeploy.
2. (paused) scope_guard live smoke — still at `0c1ca9d`, separate
   owner. Do not auto-resume.

---

## Inactive tracks

**scope_guard** — paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031)
but no live smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`
