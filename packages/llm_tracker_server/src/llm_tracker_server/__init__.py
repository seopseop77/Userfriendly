"""llm-tracker central server package.

The team-operated central server: proxies Claude Code traffic to
Anthropic, runs server-side plugins, persists exchanges per ADR-0017
(central-server pivot) and ADR-0018 (per-org RLS).

See `docs/worklog/2026-05-11-phase3c-plan.md` for the Phase 3c build
plan.
"""

__version__ = "0.0.1"
