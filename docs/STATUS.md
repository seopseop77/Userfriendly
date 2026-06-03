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

`docs/worklog/2026-06-03-signup-hardening.md` — go-live readiness before
sharing the public signup link: **daily off-disk backups (done) + optional
Cloudflare Turnstile captcha (code done, keys pending) + uptime ping
(operator action)**. Migration track:
`docs/worklog/2026-06-02-local-storage-migration.md`.

## Recent commits (last 5)

- `0e090ee` signup: add optional Cloudflare Turnstile captcha
- `97093b4` infra: add daily pg_dump backup to separate disk
- `b00e29a` infra: pin DB to bind mount /srv/llm-tracker/pgdata
- `79eaf60` docs: refresh STATUS recent-commits list
- `ddad009` signup: trim form to name + email + institution

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

DB storage path **resolved (2026-06-03)**: data moved to an explicit bind
mount **`/srv/llm-tracker/pgdata`** (cold-copy, counts verified identical;
old `userfriendly_pgdata` volume kept as backup). See
`docs/worklog/2026-06-03-db-storage-path.md`.

**Go-live hardening (2026-06-03)**: daily backups now run via `scripts/
pg-backup.sh` (user cron 03:30 → `/srv/backup/llm-tracker/` on sdb, a
physically separate disk; 14-day retention; restorable dump verified).
Turnstile captcha is **LIVE** on `signup.userfriendly.win` (keys in
`.env`, gitignored; verified through the tunnel — bogus submit → 400, no DB
row).

Still deferred (recorded, not blocking): retention (pg_cron absent);
read-only analyst DB role. Capacity is a non-issue for the participant scale.

## Next single step

**Go-live ready — the public signup link can be shared.** All hardening
done and verified: daily off-disk backups, Turnstile captcha (live, bots
rejected pre-insert), UptimeRobot monitors (HEAD `/healthz` → 200 after the
GET+HEAD fix), and a real browser signup that wrote through end-to-end
(`participant_registrations` = 2). See
`docs/worklog/2026-06-03-signup-hardening.md`. No blocking next step.

---

## Inactive tracks

### scope_guard

Paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031) but no live
smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`

### Participant-#1 install

Back-burner, waits on signup-app redeploy. See ADR-0035 follow-up
in `docs/worklog/2026-05-25-uv-tool-install.md`.
