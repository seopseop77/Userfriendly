# ADR-0024 · Thin local agent — fallback policy: fail-closed

- **Status**: Accepted
- **Date**: 2026-05-13
- **Author**: Claude Cowork (decision) / Claude Code (drafting)
- **Related**: ADR-0017 §Open questions (Phase-3a item #1),
  `docs/roadmap.md#3a`, `docs/worklog/2026-05-13-phase3b-agent.md`

## Context

ADR-0017 moved the project to a central-server deployment model. The thin
local agent (Phase 3b) sets `ANTHROPIC_BASE_URL` to point at the central
server so that every Claude Code request flows through server-side
observation and policy. The agent itself is intentionally dumb: it
forwards bytes.

The open question ADR-0017 left for Phase 3a is what the agent should do
when the central server is unreachable — network partition, DNS failure,
container restart, deploy roll, etc. Two ends of the spectrum:

- **Fail-open**: the agent forwards directly to `api.anthropic.com`,
  bypassing the central server. Claude Code keeps working; the user does
  not notice the outage. The trade-off is that the *monitoring guarantee*
  ADR-0017 establishes — "every team request is observed" — silently
  evaporates exactly when the operator most needs to know about it.
- **Fail-closed**: the agent refuses the request and returns an error to
  Claude Code. The user sees an explicit failure; nothing escapes the
  observation boundary.

For the current team-demo phase, the central server has a single Fly.io
region with no redundancy (per ADR-0022). Server downtime *will* happen.
The cost of fail-open is hard to model — silently unobserved traffic is
exactly the failure mode that observation exists to prevent — whereas
the cost of fail-closed is straightforward: Claude Code stops until the
server comes back, and the user is told why.

## Options considered

1. **Fail-closed** — block on unreachable server; return HTTP 503 with a
   clear detail message. Pro: monitoring invariant holds. Con: server
   downtime fully blocks the team's coding work.
2. **Fail-open** — forward directly to Anthropic when the server is
   unreachable. Pro: zero perceived downtime. Con: silent loss of
   monitoring; defeats ADR-0017's premise; an operator with a flaky
   server has no signal that they are missing data.
3. **Fail-open with audit ping** — forward to Anthropic, then queue a
   "ran-without-server" event for later upload. Pro: keeps Claude Code
   working. Con: complicates the agent (queue, retry, local storage)
   exactly contrary to the "thin agent, no local state" principle; the
   audit ping itself depends on a server that is by hypothesis down.

## Decision

**Pick option 1 — fail-closed.** Three reasons:

1. The monitoring guarantee is the central server's reason to exist.
   Quietly bypassing it on the failure path defeats ADR-0017 in exactly
   the situation the policy was meant to govern.
2. Fail-closed makes the agent stateless. No queue, no local storage,
   no replay logic — consistent with "the local agent does nothing but
   set `ANTHROPIC_BASE_URL` and forward" from ADR-0017.
3. The cost is honest. The team-demo phase has acknowledged downtime
   risk (single Fly region, single Supabase project); fail-closed
   surfaces that risk to the operator immediately instead of hiding it.

The agent returns HTTP 503 with body
`{"detail": "llm-tracker central server unreachable"}` on any of:
`httpx.ConnectError`, `httpx.TimeoutException`, or a non-2xx response
from the central server's `/healthz` (if used as a pre-flight).

## Consequences

- **Enables**: full observation guarantee for every Claude Code request
  routed through `claude-manage`. Operator confidence that the dataset
  is complete.
- **Forecloses**: zero-downtime UX for end users. Server downtime
  immediately blocks Claude Code for everyone using `claude-manage`.
- **Reversibility**: easy. Fail-closed → fail-open is a localised
  change in `proxy.py` plus a config knob; no schema, no data
  migration. A future ADR can revisit this when the team takes on an
  uptime SLA, or when external (non-team) users start relying on the
  agent.

## Open questions

- **Operator alerting**: when the server is unreachable, who finds out
  first — the operator, or the team member who hits the 503? Out of
  scope for this ADR; tracked under the operational-SLA item in Phase
  3c carry-overs.

## Settles

Phase-3a item #1 (fallback policy when server unreachable) from
ADR-0017 §Open questions and `docs/roadmap.md#3a`.
