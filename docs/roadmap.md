# Roadmap

> **2026-05-11 architectural pivot.** ADR-0017 moves the project from a
> local-sidecar deployment to a **central server operated by the team**,
> with users running only a thin local agent. Phase 0–Phase 2-partial
> were executed against the local-sidecar premise; their *artefacts*
> (hook lifecycle, SDK, plugin signing, EgressGuard, content-level
> ladder, supabase_sink plugin) remain valuable, but several of the
> premises they encoded — most notably "egress off by default" and the
> L/A/R mode taxonomy — no longer hold. See ADR-0017 §Consequences and
> §Open questions for what changes and what is deferred to follow-up
> ADRs.
>
> The phases below are preserved as a record of what was built. A new
> top-level entry, **Phase 3 — Central server build-out**, captures the
> work the pivot creates.

The original order was **framework → plugin SDK → first plugin →
ecosystem**. Concrete features (scope guard, drift tracking, etc.) live
in plugins, never the core.

Each phase has a **Definition of Done**.

## Phase 0 — Core framework skeleton (CLOSED 2026-05-04)

> Built against the local-sidecar premise. Components are reusable on
> the central server (FastAPI app, hook dispatch, audit log, storage
> models). Items checked as part of the *local* build; some no longer
> make sense in the central-server model and will not be carried over
> as-is — see Phase 3.

Goal: a transparent forwarder with the plugin host scaffolding wired up,
to the point that an empty no-op plugin can be loaded and its hook
invocations show up in the audit log.

- [x] `pyproject.toml` dependencies filled in; `pip install -e .[dev]` works.
- [x] FastAPI catch-all route + httpx SSE transparent forwarding (with Tee).
- [x] Local SQLite schema (`exchanges`, `events`, `tool_calls`, `audit_log`)
      via Alembic.
- [x] `llm-tracker` Typer CLI: `init`, `start`, `audit` skeletons.
- [x] PluginHost skeleton: setuptools entry-point loading, manifest parsing,
      hook dispatcher.
- [x] All eight hook points invoked at the right times in the request
      lifecycle.
- [x] AuditLog: hook invocations and lifecycle events recorded.
- [x] EgressGuard skeleton — *premise changed by ADR-0017; the egress
      boundary in the new model is the network hop between the local
      agent and the central server, not a per-plugin allowlist.*
- [x] Mode configuration (L/A/R) — *superseded by ADR-0017; replacement
      taxonomy, if any, is an open question under ADR-0017.*
- [x] `hello_world` no-op sample plugin loads and its hook calls show
      up in the audit log.
- [x] End-to-end with Claude Code in the no-op-plugin state works.
- [x] PoC measurement: first-token-latency overhead ≤ 50 ms vs. direct call.

## Phase 1 — Plugin SDK + first plugin (`scope_guard`) + security hardening

> Phase 1a and 1b CLOSED. Phase 1c (`scope_guard`) was deferred and is
> now reframed: in the central-server model, the embedding judge and
> LLM judge run server-side rather than on each user's machine.

### 1a. Plugin SDK (CLOSED 2026-05-05)
- [x] `llm_tracker_sdk` package: `BasePlugin`, hook decorators, capability
      tokens.
- [x] `plugin.toml` schema validator + signing tool.
- [x] Plugin test harness (mock hook contexts, mock SQLite).
- [x] `docs/plugins.md` first complete pass — authoring guide + examples.

### 1b. Security boundary hardening (CLOSED 2026-05-06)
- [x] EgressGuard enforces plugin-level allowlist + audit. *Premise
      changed by ADR-0017; primitive survives, server-side role TBD.*
- [x] Manifest signature verification (at install + at startup). *Original
      threat (user-side tamper) eliminated by ADR-0017; possible recast
      as deployment-time trust, see ADR-0017 §Open questions.*
- [x] Capability use is always audit-logged.
- [x] Content-level routing (L0–L3): core degrades data before passing to
      plugins. *Trust boundaries change in the new model; the ladder may
      still describe server-side retention/visibility tiers.*
- [x] Mode-by-mode capability policy enforcement (with tests). *Mode
      taxonomy superseded by ADR-0017.*

### 1c. `scope_guard` plugin (DEFERRED; reframe under ADR-0017)
- [ ] TaskDefinition schema + per-task cache.
- [ ] Stage-1 embedding judge — *now runs on the central server, not
      per user machine. The cost-amortisation argument in ADR-0017
      §Context cites exactly this.*
- [ ] Stage-2 LLM judge — *server-side egress to the judge model, not
      a per-plugin allowlist.*
- [ ] LRU cache keyed on `(conversation_id, message_hash)`.
      (Original draft used `task_id`; superseded 2026-05-21 — the
      deferred `task_id` layer was closed as won't-do, and
      `conversation_id` from ADR-0032 / Candidate-1 dedup
      provides the same per-chain scope.)
- [ ] Synthetic SSE response on `out_of_scope`.
- [ ] Eval set 50/50, false-positive rate ≤ 5%.

DoD (original): an external collaborator can read `docs/plugins.md` and
ship a toy plugin; `scope_guard` blocks/allows correctly on the eval
set. The "external collaborator" framing is preserved — plugins are
still authored against the SDK — but the *deployment* of those plugins
is now to the central server, not each user's machine.

## Phase 2 — Reference upload sink + plugin ecosystem starts

> Partial. `supabase_sink` shipped end-to-end (2026-05-08) as a Mode-R
> output sink under ADR-0007's framing. ADR-0017 supersedes that
> framing — the central server is no longer an optional sink — but the
> Supabase-receiver pattern remains usable as a *server-side* analytics
> output.

- [x] `llm_tracker_plugin_supabase_sink`: batched upload, exponential
      backoff. *Reframed: the sink now runs on the central server, not
      each user's machine.*
- [x] `src/llm_tracker_server/`: Supabase connection skeleton. Empty
      routes — to be filled in Phase 3.
- [ ] User consent flow — *required dependency for ADR-0017 launch;
      surface, retention period, deletion mechanism, and lawful basis
      are open questions under ADR-0017. Own ADR.*
- [ ] Plugin compatibility / version matrix documented.
- [ ] Integration test for at least one contributor plugin (e.g.,
      `drift_metrics`).

## Phase 3 — Central server build-out (NEW per ADR-0017)

Goal: deploy the team-operated central server and a thin local agent,
move plugin execution server-side, and resolve the open questions
under ADR-0017 in their own ADRs.

This phase replaces what would have been Phase-3 ("subprocess
isolation, multi-provider, analytics") in the local-sidecar plan.
Isolation, multi-provider, and analytics are still real work — they
move under §"Server build-out" below.

### 3a. Decision ADRs (precondition to building)
- [ ] **Fallback policy when server unreachable** — fail-open vs
      fail-closed (ADR-0017 §Open questions).
- [ ] **Consent + data-handling policy** — what we collect, retention,
      deletion, lawful basis, user-facing surface.
- [ ] **Agent-to-server auth model** — shared org token vs per-user
      token vs OAuth pass-through. Affects Anthropic ToS posture.
- [ ] **Local agent language/distribution** — Python vs Go vs shell
      wrapper. Affects install friction.
- [ ] **Multi-tenancy boundary** — org vs user; RLS vs
      application-level enforcement.
- [ ] **What survives of ADR-0006 L/A/R modes** — possibly recast as
      server-side retention/visibility tiers; or fully retired.
- [ ] **What survives of ADR-0008 signing** — possibly recast as
      developer-to-deployment signing.

### 3b. Thin local agent (new deliverable)
- [ ] Choose language per 3a.
- [ ] Single responsibility: set `ANTHROPIC_BASE_URL` to the central
      server endpoint + handle bootstrapping (auth handshake).
- [ ] No proxy logic, no plugins, no local storage.
- [ ] Distribution channel (PyPI vs Homebrew vs single binary) per 3a.
- [ ] Fallback behaviour per 3a.

### 3c. Server build-out
- [ ] Migrate the existing `packages/llm_tracker/` proxy logic to
      `packages/llm_tracker_server/` (or wherever the server lives).
      Hook lifecycle and plugin host largely portable.
- [ ] Server-side plugin execution; ADR-0008 trust model reframed per
      3a's outcome.
- [ ] Operator-facing audit + retention controls.
- [ ] Operational SLA, redundancy, monitoring (single point of failure
      mitigations).

### 3d. Carry-overs from the old Phase 3
- [ ] OpenAI / Gemini adapters.
- [ ] Analytics interface (direct SQL vs REST) and implementation.
- [ ] Response-side policy plugin category (anomaly detection on
      streams).
