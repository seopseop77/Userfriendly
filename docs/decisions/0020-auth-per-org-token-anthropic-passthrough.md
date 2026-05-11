# ADR-0020 · Auth model: per-org token (agent→server) + Anthropic key pass-through (server→Anthropic)

- **Status**: Accepted; resolves ADR-0017 §Open questions
  ("Authentication between local agent and server")
- **Date**: 2026-05-11
- **Author**: Claude Cowork (user-approved; decision made in the
  2026-05-11 Phase-3a decision interview)
- **Related**: ADR-0017, ADR-0018 (per-org tenancy — auth aligns),
  `docs/STATUS.md`

## Context

ADR-0017 left agent-to-server authentication as an open question,
citing three coupled concerns: rate-limit posture, Anthropic ToS
exposure, and the multi-tenancy boundary on the server. ADR-0018 has
now settled tenancy as per-org; the auth model must align with that
boundary.

The single phrase "authentication" in ADR-0017 conflates two
separable decisions:

1. **Agent → Server.** How does the locally-running agent prove its
   identity to our server?
2. **Server → Anthropic.** Whose API key does our server present
   when calling `api.anthropic.com`?

The second decision is where Anthropic-ToS exposure lives; the first
is where multi-tenancy enforcement lives. Each axis is decided
independently below.

## Options considered

### Axis 1: Agent → Server

- **1A. Shared dev token.** One bearer token in an env var, shared
  across testers. Demo-only.
- **1B. Per-org token (chosen).** A bearer token issued per org at
  provisioning time. Aligns directly with ADR-0018's tenancy
  boundary.
- **1C. Per-user token.** A token per user. Finer-grained revocation;
  over-scoped for current needs.
- **1D. OAuth handshake.** Broker the user's Anthropic credential
  through the server. Complex; depends on Anthropic OAuth support.

### Axis 2: Server → Anthropic

- **2A. Pooled team key.** Server calls Anthropic with one shared
  API key. Maximum ToS exposure ("API redistribution").
- **2B. Per-org key.** Each org registers its own Anthropic API key
  with the server; server stores it encrypted and uses it for that
  org's traffic.
- **2C. Per-user key.** Same idea, finer-grained.
- **2D. Pass-through (chosen).** The agent includes the user's
  Anthropic API key on every request to the server; the server
  forwards that key when calling Anthropic and does not persist it.

## Decision

**Axis 1: Per-org token (Option 1B).**

At org-creation time the server issues an opaque bearer token bound
to that org. The agent — or, during demo, Claude Code via a manually
set environment variable — sends this token in `Authorization:
Bearer <token>` on every request. The server validates the token,
resolves the org, and sets the per-request RLS context
(`app.org_id`) used by ADR-0018's policies.

Token revocation is per-org: if a token leaks, only that org's
access is disrupted. Rotation is supported by issuing a new token
and revoking the old one with a short overlap window.

**Axis 2: Pass-through of the user's Anthropic API key (Option 2D).**

Every request the server receives carries the user's Anthropic
credential as an inbound header (matching whatever header Claude
Code natively sends — typically `x-api-key`; confirmed during Phase
3c). The server uses that credential to call Anthropic upstream,
then discards it from memory once the response stream is fully
forwarded.

The server **never persists** the Anthropic credential to disk,
database, or logs. Logging middleware must strip the credential
header before any structured log line is emitted; this is enforced
by a single scrubber on the outbound logging path, and pinned by
test.

## Consequences

### What this enables

- **Zero Anthropic-credential storage on the server.** No KMS/Vault
  build-out, no rotation responsibility for Anthropic keys, no
  breach-disclosure obligation for those keys.
- **Anthropic-ToS posture is the safest available.** The server is a
  router; each user calls Anthropic with their own credential. No
  shared key acting as a redistribution surrogate.
- **Per-org rate limits.** Each org's Anthropic quota applies to its
  own traffic; no pooling effects across customers.
- **Direct alignment with ADR-0018.** The agent→server token resolves
  to an org; RLS reads that org. One auth check at the edge populates
  the tenancy context.

### What this constrains

- **The server cannot serve a request without the user's Anthropic
  credential.** If the credential is missing or invalid, the server
  returns an error rather than transparently using a fallback key.
  (ADR-#1, fallback policy when *server* is unreachable, is a
  separate concern — that ADR governs what the *agent* does when the
  server is unreachable, not what the server does when the user's
  key is missing.)
- **Memory-window exposure.** The Anthropic credential is in server
  process memory for the duration of each request. A server-side
  compromise during a request would briefly expose the credential.
  Mitigations: never log the header; do not persist any intermediate
  buffer that includes the header; treat the header as a P0-class
  secret in code review.
- **Operations cannot replay a user's request offline.** Since the
  server never stored the user's credential, operators debugging a
  stored exchange cannot re-issue it against Anthropic. Acceptable;
  we capture request/response state for forensics, not the
  credential needed for replay.

### What it forecloses

- A "demo billing" arrangement where the team eats Anthropic costs
  on behalf of users. If that's ever wanted, it becomes a new auth
  mode (per-org server-side key) and a new ToS conversation.
- Server-mediated rate-limit pooling across users.
- Any feature that requires the server to make Anthropic calls
  outside a user's request lifecycle (e.g., periodic background
  drift analysis using the team's key). Such features need a
  separate, explicit team API key with its own ADR.

### Reversibility

High on Axis 1 (per-org tokens can be supplemented or replaced; the
token-to-org mapping is one table). Lower on Axis 2: switching from
pass-through to *also accept* stored per-org keys is additive (the
server can begin accepting registered keys without breaking
pass-through), but switching to a pooled team key changes ToS posture
and is a real decision, not a config flip.

## Open questions

- **Header convention for the pass-through credential.** Confirm
  during Phase 3c which header Claude Code uses natively
  (`x-api-key` is Anthropic-canonical; Claude Code may forward
  differently). Choose the header that requires zero modification to
  Claude Code, since the thin agent (Phase 3b) shouldn't have to
  rewrite the request.
- **Token issuance UX.** How orgs receive their first token (sign-up
  flow, operator hand-off, etc.) — Phase 3c.
- **Thin-agent secret storage.** Where the agent caches the per-org
  token on the user's machine. Tied to ADR-#4 (agent
  language/distribution).
- **Rate-limit error mapping.** When Anthropic returns 429, the
  server must forward the rate-limit response transparently — the
  user's own quota is being throttled. Confirm during Phase 3c.
