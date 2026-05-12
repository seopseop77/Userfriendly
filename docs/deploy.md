# Deploying the central server (Fly.io + Supabase)

This is the step-by-step guide the operator follows to ship the central
`llm_tracker_server` to Fly.io against a Supabase Postgres database. It
covers **Phase 3c CP13-b** (the user-executed half of CP13); CP13-a wrote
the in-repo artefacts (`Dockerfile`, `.dockerignore`, `fly.toml`).

Architecture decisions referenced below:

- ADR-0017 — central-server pivot.
- ADR-0018 — per-org RLS on PostgreSQL.
- ADR-0020 — per-org bearer token + Anthropic credential pass-through.
- ADR-0022 — Fly.io for the app, Supabase for Postgres.

Companion files:

- `Dockerfile` — multi-stage build that produces the runtime image.
- `fly.toml` — Fly.io app manifest (no secrets).
- `packages/llm_tracker_server/alembic*` — migrations shipped inside the
  image and run by the Fly release command.

---

## Prerequisites

Before starting CP13-b, the operator should have:

- [ ] **`flyctl` installed** — either of:
      - `brew install flyctl`, or
      - `curl -L https://fly.io/install.sh | sh`
- [ ] **Signed in to Fly.io** — `fly auth login` completed; `fly auth whoami`
      returns the operator's address.
- [ ] **A Supabase project** with a **pooled connection string** ready —
      Supabase dashboard → Settings → Database → Connection pooling →
      *Transaction mode*. The pooled URL is the one used at runtime; the
      direct (non-pooled) URL is used only by `alembic` if migrations open
      multiple sessions in one process. For this deployment the pooled
      URL is sufficient for both (`alembic upgrade head` runs in a
      one-shot Machine).
- [ ] **Supabase IPv4 add-on enabled if needed.** Fly.io egress is IPv4
      while Supabase's free-tier database endpoints default to IPv6-only.
      If `fly deploy` fails the release command with a connection timeout
      to Supabase, enable the IPv4 add-on at Supabase dashboard →
      Settings → Add-ons. (Paid Supabase tiers already include IPv4.)
- [ ] **The CP12 image builds locally** — sanity check before paying
      Fly.io for a remote build:
      ```
      docker build -t llm-tracker-server:local .
      ```

---

## Step-by-step

### 1. Create the Fly.io app (one-time)

```
fly apps create llm-tracker-server
```

The name in `fly.toml` (`app = "llm-tracker-server"`) must match. If the
name is taken, pick another, then update `fly.toml` to match and commit
the change.

### 2. Set secrets (never goes in `fly.toml`)

The single secret the server needs at runtime is the Supabase database
URL. Set it once; Fly stores it encrypted and injects it into every
Machine (including the release-command Machine):

```
fly secrets set \
  LLMTRACK_DATABASE_URL="postgresql+asyncpg://<user>:<password>@<host>:5432/<db>?ssl=require"
```

Verify with `fly secrets list` — the value is redacted, but the key
should appear with a digest and a "Created at" timestamp.

### 3. Deploy

```
fly deploy
```

This runs:

1. A remote `docker build` against the repo (using the local
   `Dockerfile` + `.dockerignore`).
2. The release command — `alembic upgrade head` — in a one-shot
   ephemeral Machine, against the same image and the same secrets. If
   migrations fail here, the rolling deploy is aborted and no traffic
   is shifted.
3. The rolling deploy of the new image to the app Machines.

### 4. Verify the deploy

```
fly status
curl https://llm-tracker-server.fly.dev/healthz
```

Expected:

- `fly status` lists at least one Machine in state `started` and
  `passing` against the health check.
- `curl` returns `HTTP/2 200` and the body `{"status":"ok","version":"0.0.1"}`.

### 5. Issue a demo org + token

The server CLI is shipped inside the runtime image. Invoke it through
`fly ssh console`:

```
fly ssh console -C "llm-tracker-server tokens issue --org demo"
```

Save the printed token — it is shown **once**. This bearer token is what
goes in the client's `ANTHROPIC_BASE_URL` setup (the client sends
`Authorization: Bearer <token>` on each request to the proxy).

### 6. Verify auth middleware is live

A request without a bearer token must be rejected by the server's auth
middleware (ADR-0020). A request *with* a token must pass middleware and
reach the upstream (and predictably fail upstream with a 400 because the
body is intentionally malformed):

```
curl -X POST https://llm-tracker-server.fly.dev/v1/messages \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-opus-4-5","max_tokens":1,"messages":[]}'
```

Expected: **HTTP 400** (Anthropic rejecting the empty `messages` array).
A 401/403 here means auth middleware rejected the token; a 502/504 means
the server reached Anthropic but something else failed upstream.

A request **without** the `Authorization` header should be rejected with
401:

```
curl -i -X POST https://llm-tracker-server.fly.dev/v1/messages \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-opus-4-5","max_tokens":1,"messages":[]}'
```

Expected: **HTTP 401**.

---

## Troubleshooting

### `alembic upgrade head` fails in the release command

- Check `fly secrets list` shows `LLMTRACK_DATABASE_URL`.
- Run `fly logs` to see the alembic traceback. The most common shape is
  `OperationalError: connection ... timed out` (next item) or
  `password authentication failed` (the URL's `<password>` placeholder
  was not substituted).
- Re-run the migration explicitly:
  ```
  fly ssh console -C "alembic upgrade head"
  ```

### Supabase connection times out

Fly's outbound network is IPv4; Supabase's free-tier database endpoint
is IPv6-only by default. Enable the **IPv4 add-on**:

- Supabase dashboard → Settings → Add-ons → *IPv4* → Enable.
- Wait ~1 minute for the DNS to flip.
- Re-run `fly deploy` (or just `fly ssh console -C "alembic upgrade head"`
  if only the migration failed and the app machines are already up).

Paid Supabase tiers include IPv4 by default; this troubleshooting step
applies to the free tier only.

### `/healthz` reports unhealthy after deploy

- `fly logs` — look for startup errors. The boot contract from CP1 is
  that the server attaches no auth-gated routes if no DB is available;
  if `LLMTRACK_DATABASE_URL` is missing, `/healthz` itself still serves
  but downstream routes won't.
- `fly status --all` — confirm a Machine is in state `started`, not
  `crashed` or `pending`.
- `fly ssh console -C "ls -la /app"` — confirm `alembic.ini` and the
  `alembic/` directory shipped into the image; if either is missing
  the release command would have failed earlier, but worth confirming.

### A subsequent deploy needs a fresh secret

`fly secrets set ...` triggers a new deploy by default. To stage
multiple changes (`LLMTRACK_DATABASE_URL` plus an env update plus a
code change), pass `--stage` and then `fly deploy` once:

```
fly secrets set --stage LLMTRACK_DATABASE_URL="..."
fly deploy
```

---

## What lands after CP13-b

- The server is live at `https://llm-tracker-server.fly.dev` (or the
  operator's chosen app name).
- The Supabase schema has been migrated by the release command.
- One demo org + bearer token exists in `public.api_tokens`.

**Next**: CP14 — operator-only end-to-end smoke. Send one real
`/v1/messages` request through the deployed server with a valid
Anthropic API key in the `x-api-key` header and verify (a) the
response stream returns to the client unchanged, (b) one row lands
in `public.exchanges` scoped to the demo org, and (c) Fly logs show
no traceback. The operator-only flavour of CP14 has **no Phase-3a
dependency**; external-tester flavours of CP14 require ADR-#2 (consent
+ data handling) to be settled first.
