# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `CLAUDE.md §5, §6` for the rules.
>
> **Keep this file short.** Timestamp + active worklog + last 5 commits +
> where we paused + next step. History belongs in worklogs and git log.

---

**Last updated**: 2026-05-27

## Active worklog

`docs/worklog/2026-05-27-webfetch-wrapper-prefix.md`

(Single-prefix surgical add — `"Web page content:\n---\n"` joins
the `_SYNTHETIC_WRAPPER_PREFIXES` tuple alongside WebSearch trigger
and PreCompact prompt. Closes out the last documented small
follow-up; no operator-side track is in flight.)

## Recent commits (last 5)

- `<pending>` docs: backfill <pending> hash in worklog + STATUS
- `<pending>` analytics_sink: register WebFetch result as wrapper prefix
- `b4aaaee` docs: backfill c599d08 hash in worklog + STATUS
- `c599d08` docs: close three operator-side tracks
- `65e0839` docs: backfill c4e695d hash in worklog + STATUS

## Where we paused

Quiet point. WebFetch wrapper prefix added, tested, ruff-clean, and
live-DB backfill confirmed no-op (zero historic `user_input` rows
match the new prefix). All three prior deferred operator tracks
remain closed (see git history + the three closed-track worklogs
referenced from the previous STATUS entry).

## Next single step

**Operator deploys `llm-tracker-server` to fly** to activate the new
WebFetch wrapper prefix in production:

```
fly deploy -c packages/llm_tracker_server/fly.toml
```

After deploy, send one WebFetch-bearing exchange through and confirm
it lands as `role='sidecar'` (or stays `user_input` with the WebFetch
block stripped from `request_jsonb` if accompanied by user-typed
text). Until deploy, fresh WebFetch results keep writing as
`role='user_input'` with the unstripped block — self-correcting on
next deploy, no DB backfill needed.

If the operator wants to keep going on this repo instead of touching
fly, there is no documented next item — wait for the next request.

---

## Inactive tracks

### scope_guard

Paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031) but no live
smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`

### Participant-#1 install

Back-burner, waits on signup-app redeploy. See ADR-0035 follow-up
in `docs/worklog/2026-05-25-uv-tool-install.md`.
