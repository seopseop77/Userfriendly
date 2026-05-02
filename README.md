# Userfriendly

A local sidecar proxy **framework** that observes — and optionally intervenes
in — the LLM API traffic of CLI coding agents (Claude Code first; others via
adapter abstraction). The core only provides hook points, capability gating,
and egress control. Concrete features (scope guard, drift metrics, data
upload, etc.) are built as **plugins**.

This repository covers the local proxy and reference plugins. Metric design
and prompt-set curation are owned by separate collaborators.

## One-liner

Users run Claude Code as usual; we sit a transparent local proxy between it
and the API server, structure every request/response, and let plugins act on
that data under operator-controlled policy. **Data does not leave the
machine by default.**

## Quick start

Not yet implemented. To be filled in after Phase 0.

The intended runtime flow:

```bash
# Initialize once
llm-tracker init

# Pick a deployment mode (L = local-only, A = audit-light, R = research)
# Approve plugins and capabilities

# Start the proxy
llm-tracker start

# Point Claude Code at it
export ANTHROPIC_BASE_URL=http://127.0.0.1:8787

# Use Claude Code as usual
claude
```

## Documents

- `docs/STATUS.md` — current state (start here when resuming work)
- `docs/design.md` — architecture, security model, data model
- `docs/roadmap.md` — phased plan
- `docs/plugins.md` — plugin authoring guide
- `docs/decisions/` — ADRs
- `docs/worklog/` — per-session work logs

## When working with Claude Code

Read `CLAUDE.md` first. It defines tracking, verification, and git
conventions designed for cutoff-resilient work.
