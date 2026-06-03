# 2026-06-03 · Harden the stack before sharing the public signup link

**Author**: Claude Code
**Session trigger**: User: "이제 실제로 사람들이 쓸 수 있도록 signup 링크를
알려줄 생각인데, 그러기 전에 마지막으로 검토해야 할 사항 (안정성/보수)?" →
after review, user chose: "백업 크론 걸고, Cloudflare 캡차 + 핑도 진행."
**Related docs**: ADR-0042, `docs/worklog/2026-06-02-local-storage-migration.md`

## Interpretation

Go-live readiness review of the self-hosted stack (live on
`userfriendly.win`). Findings, by risk:

- **No backups** (biggest gap) — live data is a single copy on the NVMe
  (`/srv/llm-tracker/pgdata`); no `pg_dump` cron. Once participants use it,
  this is the only copy.
- **Open signup** — no captcha/rate-limit/email-verify. Cost risk is low
  (credential is **pass-through**: participants bring their own Anthropic
  key — `proxy/credential.py` — so proxy abuse does not bill the operator),
  but bot submissions can junk the DB, and `audit_log` rows are
  un-deletable (immutability trigger) so junk orgs can't be cleaned.
- **No uptime alerting** — home box + home uplink; if it drops the operator
  has no signal.

Pipeline is already proven live: `plugin_analytics` has 6 rows, so step-5
cutover is effectively done. Chosen actions: ① backups, ② captcha, ③ ping.

## What was done

### ① Daily Postgres backups to a separate physical disk (commit 97093b4)

- `scripts/pg-backup.sh` — `pg_dump -Fc` (custom/compressed) + `pg_dumpall
  --roles-only`, timestamped, atomic temp→mv, 14-day retention, sha256 in a
  `last-backup.txt` marker mirroring the box's existing convention.
- Destination **`/srv/backup/llm-tracker/`** on **sdb** (1.8T) — physically
  separate from the NVMe holding live data, so an NVMe failure does not take
  the backups with it. The box is shared with another tenant
  (`server-hbc`/robodb on the same disk); we use an owned namespace and do
  not touch their files. Dir created by the operator via sudo (this session
  has no passwordless sudo).
- Installed as **user cron, daily 03:30** (offset from server-hbc's 00:00).
- Verified: ran once → `llm_tracker-20260603T134323.dump`; `pg_restore
  --list` shows 92 objects incl. all core tables + the audit trigger + the
  vector extension → restorable. cron daemon `active`.

### ② Optional Cloudflare Turnstile captcha on the signup form (commit 0e090ee)

- `turnstile.py` — `verify_turnstile()`, **fail-closed** siteverify (missing
  token / network error / non-success → reject). Fail-closed is fine because
  Cloudflare already fronts the whole site.
- `app.py` — verification runs **before** the DB insert when a secret is
  configured, so rejected bots never create rows. A `render_form` helper
  threads the site key into every form render (GET, captcha-fail,
  duplicate-email).
- `register.html` — widget + `api.js`, both gated on `turnstile_site_key`.
- `config.py` — `LLMTRACK_TURNSTILE_SITE_KEY` / `LLMTRACK_TURNSTILE_SECRET`,
  **both blank by default = captcha disabled** (no behaviour change until
  the operator sets real keys). `docker-compose.yml` + `selfhost.env.example`
  wire the two optional vars.
- `tests/test_app.py` — widget-renders test + failed-verification-400 test
  (no DB needed; reject happens pre-insert).

### ③ Uptime ping — operator action (external, not code)

External monitoring must run **off-box** (an on-box checker can't alert when
the box is down). Left as an operator step (account-bound); see Handoff.

## Decisions

- **Backups on sdb, not NVMe** — only a physically separate disk survives an
  NVMe failure; logical-error protection alone (same disk) was insufficient
  for "this is the only copy."
- **Captcha optional + fail-closed, verify-before-insert** — keeps the
  feature zero-impact until keys are set, and ensures bots never reach the DB.
- **New env vars** (`LLMTRACK_TURNSTILE_*`) — additive config, not a change
  to an existing public interface; flagged per CLAUDE.md §4/§9, no ADR (small,
  reversible, user-requested).

## Verification

- Backup: live run + `pg_restore --list` (92 objects); cron installed +
  daemon active.
- Turnstile: `py_compile` on all changed modules; signup image rebuilt;
  no-keys GET `/` renders **no** widget (prod unchanged); in-container run
  against **real Cloudflare siteverify** with official test keys —
  widget renders, always-fail secret → 400 (pre-DB), always-pass secret →
  303 (DB stubbed, no prod row). All three branches pass.

## What's left / Handoff

Code is in place; two operator actions remain (both external/account-bound):

1. **Activate captcha.** Cloudflare dashboard → Turnstile → add a widget for
   the signup hostname (`signup.userfriendly.win`) → copy site key + secret
   into `.env` (`LLMTRACK_TURNSTILE_SITE_KEY`, `LLMTRACK_TURNSTILE_SECRET`)
   → `docker compose up -d signup`. Until then captcha is off (form works).
2. **Uptime alerting.** Add an external monitor (e.g. UptimeRobot free, 5-min
   interval) on `https://llm-tracker.userfriendly.win/healthz` and
   `https://signup.userfriendly.win/healthz`, with email/Slack alert on down.

Still deferred from ADR-0042 (not blocking): retention (pg_cron absent);
read-only analyst DB role.

Next single step: operator sets Turnstile keys → I wire `.env` + recreate +
verify live; then set up the UptimeRobot monitors.
