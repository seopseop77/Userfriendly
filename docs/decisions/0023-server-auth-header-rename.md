# ADR-0023 · Rename server auth header to `X-LLM-Tracker-Token`

- **Status**: Accepted
- **Date**: 2026-05-13
- **Author**: Claude Code (CP14 prep; OAuth blocker triage)
- **Related**: ADR-0020 (auth model — amended on Axis 1 only),
  ADR-0017 (central-server pivot), `docs/STATUS.md`,
  `docs/deploy.md`

## Context

ADR-0020 picked `Authorization: Bearer <token>` as the agent→server
auth header (Axis 1), and `x-api-key` / `anthropic-api-key` as the
inbound channel for the user's Anthropic credential which the server
forwards upstream (Axis 2). At the time, the working assumption was
that Claude Code always sends the Anthropic credential in `x-api-key`,
so reusing `Authorization` for our own bearer token was free.

That assumption holds only for users with a manually configured
`ANTHROPIC_API_KEY` (sent as `x-api-key`). Users who sign in to Claude
Code via OAuth — the majority of the population — send their
Anthropic credential as `Authorization: Bearer <oauth-token>`
instead. The two uses of `Authorization` collide:

1. The server's `AuthMiddleware` consumes the header, hashes it as if
   it were our per-org token, fails the `api_tokens` lookup, and
   returns 403.
2. The OAuth token never reaches Anthropic — it was eaten by us
   before the request was forwarded.

This is a P0 blocker for CP14 / external testing: any OAuth Claude
Code user hitting the central server is locked out, and the failure
shape (`403 unknown or revoked token`) doesn't hint at the actual
cause.

The local proxy did not have this problem because it was a
transparent pass-through with no auth layer of its own — every
header, including `Authorization`, flowed straight through. The
central server is the first surface in this project that ever
*consumed* a header.

## Options considered

1. **Move our token to `X-LLM-Tracker-Token`.** Dedicated header for
   server auth; `Authorization` is reserved for Anthropic
   pass-through (OAuth) alongside `x-api-key` (API key). One-line
   client change (the curl/header recipe in `docs/deploy.md`); no
   migration cost — no external clients exist yet.
2. **Keep `Authorization: Bearer` and demand API-key-only users.**
   Forces every external tester to configure `ANTHROPIC_API_KEY`
   manually before they can use the server. Punts the problem onto
   the user; ADR-0020's "zero modification to Claude Code" goal
   (§Open questions) is broken.
3. **Sniff the bearer prefix (`lts_` vs others) and route either to
   our auth or to upstream.** Stateful header parsing on a single
   slot. Fragile (depends on a token-prefix convention that we don't
   currently enforce), and an OAuth user without a tracker token at
   all would still need a second header — at which point Option 1 is
   simpler.

## Decision

**Pick Option 1.** Replace `Authorization: Bearer <token>` with
`X-LLM-Tracker-Token: <token>` for server authentication.
`Authorization` is henceforth reserved exclusively for Anthropic
pass-through: it carries the OAuth bearer for OAuth users, is absent
for API-key users (who send `x-api-key`), and is never read or
consumed by our middleware.

This amends ADR-0020 Axis 1 only. Axis 2 (Anthropic credential
pass-through, whose key never persists) is unchanged.

## Consequences

### Positive

- **OAuth Claude Code users work out of the box.** Setting
  `ANTHROPIC_BASE_URL` to the central server is the only client
  change required; `Authorization` keeps its OAuth-token value and
  passes through to Anthropic untouched.
- **No header is read by both us and Anthropic.** Single
  responsibility per header slot — no risk of regressing the
  collision the next time a new auth mode appears.
- **Auth header is explicitly namespaced.** `X-LLM-Tracker-Token`
  reads at-a-glance as "ours"; future readers (and security review)
  won't have to remember a header-slot convention.

### Negative

- **Existing curl recipes and operator notes change.** Any caller
  currently sending `Authorization: Bearer <org-token>` must switch
  to `X-LLM-Tracker-Token: <org-token>`. No external clients exist
  yet — this is a pre-launch rename with zero migration cost — but
  every doc and test that pinned the old header has to move.
- **`docs/deploy.md` Step 6 ("Verify auth middleware is live") and
  the thin-agent specification (Phase 3b) must be updated** to the
  new header name. The deploy guide is updated in the same
  checkpoint as this ADR; the thin-agent spec doesn't exist yet, so
  it inherits the new name when written.

### Reversibility

High. The change is symmetric on both sides (server read + client
send); reverting is a four-line code edit plus the doc churn.

## Amends

- ADR-0020 — **Axis 1 only.** The decision to use a per-org token
  stays; only the wire-level header name changes.

## Open questions

None. Axis 2 (Anthropic credential pass-through) is unaffected;
ADR-0020's existing "header convention" open question already
resolves separately on the upstream side.
