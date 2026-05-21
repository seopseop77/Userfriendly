# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `CLAUDE.md §5, §6` for the rules.
>
> **Keep this file short.** Timestamp + active worklog + last 5 commits +
> where we paused + next step. History belongs in worklogs and git log.

---

**Last updated**: 2026-05-21

## Active worklog

`docs/worklog/2026-05-21-signup-app.md`

## Recent commits (last 5)

- `a77358b` signup: fly.toml for llm-tracker-signup app
- `ab2924f` signup: FastAPI app + Tailwind HTML templates + route tests
- `070361f` signup: config + registration core (PDF extract, token issuance, tests)
- `5f52873` signup: package skeleton + root testpaths
- `b35b524` server: migration 0018 participant_registrations

## Where we paused

**Signup app (llm_tracker_signup) — code-complete, live DB aligned.**

- Migration 0018 applied to Supabase (alembic ledger at `0018_participant_registrations`).
- Code: `packages/llm_tracker_signup/` — FastAPI app, HTML form, PDF extraction,
  token issuance, `fly.toml`. Tests: 168 passed + 23 skipped (full regression clean).

**Two operator-owned deploys still pending:**

1. **Proxy server** (`llm-tracker-server`): `fly deploy` from `main`.
   Migration 0017 (`exchanges.session_id` drop) was applied live but the
   running image still emits the old SQL shape — will `UndefinedColumn`-fail
   every exchange until redeployed.

2. **Signup app** (`llm-tracker-signup`): first-ever deploy.
   ```
   fly apps create llm-tracker-signup
   fly secrets set LLMTRACK_DATABASE_URL=… LLMTRACK_PROXY_SERVER_URL=… \
     -a llm-tracker-signup
   fly deploy -c packages/llm_tracker_signup/fly.toml
   ```
   Then smoke a test registration end-to-end.

## Next single step

**Thin-agent distribution** — write ADR + GitHub Actions release workflow
for `llm_tracker_agent` wheel distribution via GitHub Releases.
Cowork prompt already written (2026-05-21 session); hand to Claude Code.

After that, update the `[GITHUB_RELEASE_URL]` placeholder in
`packages/llm_tracker_signup/src/llm_tracker_signup/templates/success.html`
with the real wheel URL from the first release tag.

---

## Inactive tracks

**scope_guard** — paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031)
but no live smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`
