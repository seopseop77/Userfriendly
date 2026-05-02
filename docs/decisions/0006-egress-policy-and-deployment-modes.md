# ADR-0006 · Egress policy and deployment modes (L/A/R)

- **Status**: Accepted
- **Date**: 2026-05-01
- **Author**: Claude Cowork (user-approved)
- **Related**: `docs/design.md §7, §8`

## Context

The framework must safely host two kinds of deployment on the same core:

- **Customer scenario**: the user runs Claude Code at work; logs must not
  leave the machine. Highly sensitive data risk.
- **Research scenario**: an operator wants rich data flowing to a central
  backend, after explicit user opt-in.

To support both safely, *data egress must be off by default and only
permitted with explicit approval*. Furthermore, the conditions under which
data may leave must not be scattered across the code; they must be
enforced through a single policy axis: **deployment mode**.

## Decision

**1) All outbound HTTP goes through EgressGuard, a single path.**

Whether a plugin or a core-side helper, anything wanting to reach an
external endpoint asks EgressGuard. EgressGuard checks:

- Does the requester (plugin) have the `egress_http` capability?
- Is the URL on the requester's manifest `egress_destinations` allowlist
  (exact match; no wildcards)?
- Does the current deployment mode permit that capability?

All three must pass. Every attempt (success or denial) is recorded in
`audit_log`.

The upstream LLM (e.g., `api.anthropic.com`) is called by the core
directly on a separate path, but logged in the same audit stream.

**2) Three deployment modes.**

| Mode | Use | Egress policy | Default content level |
|---|---|---|---|
| **L** Local-only | Highly sensitive customers | Deny everything except the LLM upstream | n/a |
| **A** Audit-light | Compliance / lightweight tracking | One operator-approved destination, L0 only | L0 |
| **R** Research | Research data collection | Manifest-driven, multiple destinations after user opt-in (L1–L3) | L1 (L2/L3 with opt-in) |

Mode is fixed at startup. Changing it requires restart and re-approval
(prevents silent escalation).

**3) Content-level downgrade.**

When the core hands data to a plugin, the level is the *intersection* of
the mode default and the plugin's declared minimum. In Mode L, even a
plugin that requests L3 receives only L0/L1. The plugin never has access
to information it shouldn't, so leakage is structurally prevented.

## Consequences

- The core gains a small *policy evaluator*: `(plugin, capability,
  destination, mode) → allow/deny`.
- New modes cost a one-line addition to the policy matrix. New
  capabilities require an ADR.
- All security events flow into one audit log, easing operator review.
- Static lint rules and code review forbid plugins from importing raw HTTP
  libraries (`requests`, `urllib`, `socket`, `httpx.AsyncClient`, etc.).
  Only the SDK-provided `egress.fetch(...)` is permitted.

### What we give up

- The convenience of a one-off "let me just do this once" capability grant.
- A plugin's freedom to talk to new destinations behind the operator's back.

### Reversibility

Low. EgressGuard and the mode policy are localized to one core module.
Loosening the policy is a config change; tightening depends on plugins'
ability to comply.

## Open questions

- *Runtime* enforcement of EgressGuard against in-process Python plugins
  that try to bypass via `socket.socket()` directly. Until Phase 3
  subprocess isolation, static lint + code review is best effort. The
  operating policy is: do not install untrusted plugins.
- Audit log integrity (preventing operator-side deletion). Append-only
  triggers help, but operators can still touch the SQLite file directly
  — limitation acknowledged.
- UX for the user opt-in flow (CLI prompt vs. separate tool).
