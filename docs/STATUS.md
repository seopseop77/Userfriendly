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
**Stack up + verified locally; Cloudflare Tunnel + client cutover pending.**

## Recent commits (last 5)

- `909e039` infra: self-host stack on local Postgres (ADR-0042)
- `87bc575` docs: fully close session-id track
- `a9a8878` docs: 0023 view-session_id follow-up worklog/STATUS
- `62f56b3` storage: surface session_id in plugin_analytics_with_messages
- `fbd2da9` docs: close session-id track (deployed + verified)

## Where we paused

Topology 1 (ADR-0042) is **running and verified locally** on the box:
`docker compose up` brought up server :8080 + signup :8000 + Postgres
(pgvector image), `migrate` reached head (0023), RLS role present, demo
token issued (wrote to local DB), auth middleware verified (reject w/o
token, forward w/ token). No Fly/Supabase involved. No source code changed
— DB repoint is purely `LLMTRACK_DATABASE_URL`. Docker is reachable in this
session without sudo.

Pre-staged (CP3, domain not needed): `cloudflared` 2026.5.2 installed to
`~/.local/bin`; compose given `restart: unless-stopped` (survives reboot,
docker daemon already enabled on boot).

## Next single step

**Blocked on the operator buying a Cloudflare-managed domain.** Once it
exists: `cloudflared tunnel login` → `tunnel create llm-tracker` → route
`<domain>` (server) + `signup.<domain>` (signup) → set `PUBLIC_SERVER_URL`
in `.env`, `docker compose up -d` → repoint a client (`claude-manage setup
<TOKEN> --server-url https://<domain>`) → confirm a live `plugin_analytics`
row. Steps in `docs/deploy-selfhost.md §4–5`.

---

## Inactive tracks

### scope_guard

Paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031) but no live
smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`

### Participant-#1 install

Back-burner, waits on signup-app redeploy. See ADR-0035 follow-up
in `docs/worklog/2026-05-25-uv-tool-install.md`.
