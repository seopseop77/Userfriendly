# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `CLAUDE.md §5, §6` for the rules.
>
> **Keep this file short.** Timestamp + active worklog + last 5 commits +
> where we paused + next step. History belongs in worklogs and git log.

---

**Last updated**: 2026-06-02

## Active worklog

`docs/worklog/2026-06-02-local-storage-migration.md` — migrate storage from
Supabase to a self-hosted local box (ADR-0042, supersedes ADR-0022).
**Repo scaffolding done; machine-side execution pending.**

## Recent commits (last 5)

- `909e039` infra: self-host stack on local Postgres (ADR-0042)
- `87bc575` docs: fully close session-id track
- `a9a8878` docs: 0023 view-session_id follow-up worklog/STATUS
- `62f56b3` storage: surface session_id in plugin_analytics_with_messages
- `fbd2da9` docs: close session-id track (deployed + verified)

## Where we paused

Decided topology 1 (self-host server + signup + Postgres on the operator
box, expose only auth'd HTTP via Cloudflare Tunnel; ADR-0042). Authored the
repo artifacts: `docker-compose.yml`, `selfhost.env.example`,
`docs/deploy-selfhost.md`, ADR-0042. No source code changed — DB repoint is
purely `LLMTRACK_DATABASE_URL`. The box has no docker/postgres/cloudflared
yet, so nothing is live-verified.

## Next single step

On the box: install Docker Engine + Compose plugin and cloudflared, then
`cp selfhost.env.example .env`, set `POSTGRES_PASSWORD`, and
`docker compose up -d --build`. Verify `/healthz` on :8080 and :8000. Full
step list in `docs/deploy-selfhost.md` / the active worklog's "What's left".

---

## Inactive tracks

### scope_guard

Paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031) but no live
smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`

### Participant-#1 install

Back-burner, waits on signup-app redeploy. See ADR-0035 follow-up
in `docs/worklog/2026-05-25-uv-tool-install.md`.
