# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `CLAUDE.md §5, §6` for the rules.
>
> **Keep this file short.** Timestamp + active worklog + last 5 commits +
> where we paused + next step. History belongs in worklogs and git log.

---

**Last updated**: 2026-06-03

## Active worklog

`docs/worklog/2026-06-02-local-storage-migration.md` — migrate storage from
Supabase to a self-hosted local box (ADR-0042, supersedes ADR-0022).
**Stack live + publicly reachable via Cloudflare Tunnel on `userfriendly.win`;
only client cutover (step 5) remains.**

## Recent commits (last 5)

- `909e039` infra: self-host stack on local Postgres (ADR-0042)
- `87bc575` docs: fully close session-id track
- `a9a8878` docs: 0023 view-session_id follow-up worklog/STATUS
- `62f56b3` storage: surface session_id in plugin_analytics_with_messages
- `fbd2da9` docs: close session-id track (deployed + verified)

## Where we paused

Topology 1 (ADR-0042) is **live and publicly reachable** (CP4). On the box:
server :8080 + signup :8000 + Postgres (pgvector image), schema at head
(0023), RLS role present, auth middleware verified. Fronted by a **Cloudflare
Tunnel on `userfriendly.win`**: `llm-tracker.userfriendly.win` → server,
`signup.userfriendly.win` → signup (tunnel id
`694232c8-b020-469a-bdb7-dd6135c4f801`). Off-box `/healthz` 200 on both;
no-token `POST /v1/messages` → 401 through the tunnel. `PUBLIC_SERVER_URL`
set to the server host. No Fly/Supabase involved; no source code changed.

Persistence: cloudflared installed as a **systemd service**
(`/etc/cloudflared/config.yml`, `active`+`enabled`); Docker stack has
`restart: unless-stopped` + daemon enabled on boot. Whole stack survives
reboot.

Deferred decisions (recorded, not blocking): pin the DB to an explicit
fixed storage path (currently the Docker named volume
`userfriendly_pgdata`); backups; retention. See the active worklog. Capacity
is a non-issue for the participant scale.

## Next single step

**Client cutover (step 5).** Issue a real-org token (`docker compose exec
server llm-tracker-server tokens issue --org <org>`), then on a participant
PC `claude-manage setup <TOKEN> --server-url
https://llm-tracker.userfriendly.win`, run one real exchange, and confirm a
`plugin_analytics` row lands. Then step 6: tear down Fly + Supabase. Steps in
`docs/deploy-selfhost.md §5`.

---

## Inactive tracks

### scope_guard

Paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031) but no live
smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`

### Participant-#1 install

Back-burner, waits on signup-app redeploy. See ADR-0035 follow-up
in `docs/worklog/2026-05-25-uv-tool-install.md`.
