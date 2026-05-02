# Roadmap (framework-first)

The order is **framework → plugin SDK → first plugin → ecosystem**. Concrete
features (scope guard, drift tracking, etc.) are never in the core — only
in plugins.

Each phase has a **Definition of Done**.

## Phase 0 — Core framework skeleton

Goal: a transparent forwarder with the plugin host scaffolding wired up,
to the point that an empty no-op plugin can be loaded and its hook
invocations show up in the audit log.

- [ ] `pyproject.toml` dependencies filled in; `pip install -e .[dev]` works.
- [ ] FastAPI catch-all route + httpx SSE transparent forwarding (with Tee).
- [ ] Local SQLite schema (`exchanges`, `events`, `tool_calls`, `audit_log`)
      via Alembic.
- [ ] `llm-tracker` Typer CLI: `init`, `start`, `audit` skeletons.
- [ ] PluginHost skeleton: setuptools entry-point loading, manifest parsing,
      hook dispatcher.
- [ ] All eight hook points invoked at the right times in the request
      lifecycle (Phase 0: dispatch only, no actual plugin logic).
- [ ] AuditLog: hook invocations and lifecycle events recorded.
- [ ] EgressGuard skeleton: single egress entry point. Phase 0: deny by
      default, allow only the LLM upstream.
- [ ] Mode configuration (L/A/R) — fixed at startup.
- [ ] A no-op sample plugin (`hello_world`) loads and its hook calls show
      up in the audit log.
- [ ] End-to-end with Claude Code in the no-op-plugin state works.
- [ ] PoC measurement: first-token-latency overhead ≤ 50 ms vs. direct call.

DoD: a user can keep the proxy running and use Claude Code as usual; the
operator can see the hook-call flow in the audit log.

## Phase 1 — Plugin SDK + first plugin (`scope_guard`) + security hardening

Goal: external collaborators can author plugins. We ship the first plugin —
the task-scope guard from ADR-0002 — as a reference implementation.

### 1a. Plugin SDK
- [ ] `llm_tracker_sdk` package: `BasePlugin`, hook decorators, capability
      tokens.
- [ ] `plugin.toml` schema validator + signing tool.
- [ ] Plugin test harness (mock hook contexts, mock SQLite).
- [ ] `docs/plugins.md` first complete pass — authoring guide + examples.

### 1b. Security boundary hardening
- [ ] EgressGuard enforces plugin-level allowlist + audit.
- [ ] Manifest signature verification (at install + at startup).
- [ ] Capability use is always audit-logged.
- [ ] Content-level routing (L0–L3): core degrades data before passing to
      plugins.
- [ ] Mode-by-mode capability policy enforcement (with tests).

### 1c. `scope_guard` plugin (separate package)
- [ ] TaskDefinition schema + local cache (`plugin_scope_guard__*`).
- [ ] Stage-1 embedding judge (local sentence-transformers).
- [ ] Stage-2 LLM judge — uses an external model registered in the
      manifest's egress destinations.
- [ ] LRU cache keyed on `(task_id, message_hash)`.
- [ ] Synthetic SSE response on `out_of_scope`.
- [ ] Eval set 50/50, false-positive rate ≤ 5%.

DoD: an external collaborator can read `docs/plugins.md` and ship a toy
plugin; `scope_guard` blocks/allows correctly on the eval set.

## Phase 2 — Reference upload sink + plugin ecosystem starts

Goal: Mode R operators can ship data to a central backend via the reference
plugin; first contributor plugin lands.

- [ ] `llm_tracker_plugin_supabase_sink`: batched upload in `on_persisted`,
      exponential backoff.
- [ ] `src/llm_tracker_server/`: Supabase connection + ingest API. Fly.io
      deployment via `fly.toml`.
- [ ] User consent flow (per-task opt-in in Mode R).
- [ ] Plugin compatibility / version matrix documented.
- [ ] Integration test for at least one contributor plugin (e.g.,
      `drift_metrics`).

## Phase 3 — Stronger isolation + multi-provider + analytics

Deferred. Tackle when external usage scales.

- [ ] Subprocess isolation option for plugins (for security-sensitive
      operators).
- [ ] OpenAI / Gemini adapters.
- [ ] Analytics interface decision (direct SQL vs. REST) and implementation.
- [ ] Response-side policy plugin category (anomaly detection on streams).
