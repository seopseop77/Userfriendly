# Deploying the stack self-hosted (local Postgres + Cloudflare Tunnel)

The operator-followed guide for running the whole `llm-tracker` stack on a
single Linux box: the central server, the signup app, and PostgreSQL, with
the public edge fronted by a Cloudflare Tunnel. This replaces the Fly.io +
Supabase flow in `docs/deploy.md` (kept for historical reference).

Decision record: **ADR-0042** (supersedes ADR-0022). Companion artifacts:
`docker-compose.yml`, `selfhost.env.example`.

Topology:

```
participant PC ── claude-manage ──┐
                                   ▼
                       Cloudflare Tunnel (HTTPS)
                                   │
                   ┌───────────────┴───────────────┐
                   ▼                               ▼
            server :8080 (127.0.0.1)        signup :8000 (127.0.0.1)
                   └───────────────┬───────────────┘
                                   ▼
                       Postgres (compose-internal, not published)
```

Postgres never leaves the box. Only the two authenticated HTTP services are
reachable, and only through the tunnel.

---

## Prerequisites

Install on the box (Ubuntu/Debian shown; `sudo` required):

- **Docker Engine + Compose plugin**
  ```
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER"   # re-login so `docker` works without sudo
  docker compose version            # confirm the Compose v2 plugin is present
  ```
- **cloudflared** (Cloudflare Tunnel agent)
  ```
  # Debian/Ubuntu package:
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
    | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] \
    https://pkg.cloudflare.com/cloudflared any main" \
    | sudo tee /etc/apt/sources.list.d/cloudflared.list
  sudo apt-get update && sudo apt-get install -y cloudflared
  ```
- **A domain on a Cloudflare account** (free plan is fine) — the tunnel
  binds a public hostname like `llm-tracker.example.com` to the local
  server.

pgvector and Postgres themselves are **not** installed on the host — they
ship inside the `pgvector/pgvector:pg16` container.

---

## Step-by-step

### 1. Configure environment

```
cp selfhost.env.example .env
```

Edit `.env`:

- `POSTGRES_PASSWORD` — strong password for the local DB superuser.
- `PUBLIC_SERVER_URL` — the HTTPS hostname the tunnel will expose for the
  **server** (set this after step 4 if you don't know the hostname yet; the
  signup app only reads it to display on its success page).

`.env` is gitignored.

### 2. Bring up Postgres + run migrations + start services

```
docker compose up -d --build
```

This:

1. starts `db` (Postgres + pgvector) on a private compose network,
2. runs the one-shot `migrate` service (`alembic upgrade head`) — creates
   the schema, the `llm_tracker_app` RLS role (migration 0005), and grants
   (0006); the pg_cron retention jobs (0009/0011) log a `NOTICE` and skip
   because the extension is absent,
3. starts `server` on `127.0.0.1:8080` and `signup` on `127.0.0.1:8000`.

Verify:

```
docker compose ps                       # db/server/signup Up; migrate Exited(0)
docker compose logs migrate | tail       # ends at the head revision
curl -s http://127.0.0.1:8080/healthz    # {"status":"ok","version":"..."}
curl -s http://127.0.0.1:8000/healthz    # signup health
```

### 3. Issue a demo org + token (sanity check)

The server CLI ships inside the image:

```
docker compose exec server llm-tracker tokens issue --org demo
```

Save the printed token (shown once). Confirm auth is live:

```
# With token → passes middleware, fails upstream 400 (empty messages):
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8080/v1/messages \
  -H "X-LLM-Tracker-Token: <token>" -H "Content-Type: application/json" \
  -d '{"model":"claude-opus-4-5","max_tokens":1,"messages":[]}'   # expect 400

# Without token → rejected by auth middleware:
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8080/v1/messages \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-opus-4-5","max_tokens":1,"messages":[]}'    # expect 401
```

### 4. Expose via Cloudflare Tunnel

```
cloudflared tunnel login                 # opens a browser; pick your domain
cloudflared tunnel create llm-tracker    # creates the tunnel + credentials file
```

Map two hostnames to the two local services. Create
`~/.cloudflared/config.yml`:

```yaml
tunnel: llm-tracker
credentials-file: /home/<user>/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: llm-tracker.example.com        # the server (participants point here)
    service: http://127.0.0.1:8080
  - hostname: signup.example.com             # the signup app
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Route DNS and run the tunnel:

```
cloudflared tunnel route dns llm-tracker llm-tracker.example.com
cloudflared tunnel route dns llm-tracker signup.example.com
# foreground test:
cloudflared tunnel run llm-tracker
# then install as a service so it survives reboots:
sudo cloudflared service install
```

Set `PUBLIC_SERVER_URL=https://llm-tracker.example.com` in `.env` and
`docker compose up -d` to refresh the signup app's success-page URL.

Verify from off-box:

```
curl -s https://llm-tracker.example.com/healthz     # 200
curl -s https://signup.example.com/healthz          # 200
```

### 5. Point clients at the new server

Participants run:

```
claude-manage setup <TOKEN> --server-url https://llm-tracker.example.com
claude-manage
```

Run one real request and confirm a row lands:

```
docker compose exec db psql -U llm_tracker -d llm_tracker \
  -c "SELECT count(*) FROM plugin_analytics;"
```

---

## Operations

- **Logs**: `docker compose logs -f server` / `signup`.
- **Restart**: `docker compose restart server`.
- **Backups** (ADR-0042 open question): `docker compose exec db pg_dump -U
  llm_tracker llm_tracker | gzip > backup-$(date +%F).sql.gz`. Schedule via
  host `cron`.
- **Retention** (pg_cron absent): if needed, host-cron a `DELETE` — see
  `docs/deploy.md §Data collection & privacy` for the column predicates.
- **Schema upgrades**: rebuild and re-run migrate —
  `docker compose run --rm migrate`.

## Relationship to the Fly.io guide

`docs/deploy.md` (Fly.io + Supabase) is retained for history. The Fly apps
(`llm-tracker-server`, `llm-tracker-signup`) and the Supabase project are no
longer the source of truth once this cutover completes; tear them down at
the operator's discretion (no in-repo dependency on them remains).
