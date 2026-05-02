# Design Document — LLM Traffic Observation/Intervention **Framework**

**Status**: Draft v0.2 (2026-05-01, framework pivot)
**Owner**: Minseop Lee
**Scope**: A local sidecar proxy **framework** targeting Claude Code first.
Concrete features (scope enforcement, drift tracking, data upload, response
inspection, etc.) are all built as **plugins**. The core in this repository
provides the plugin host and security boundary.

---

## 1. Project context

The parent project's goals are LLM-usage tracking and intervention, but we
recognized the following and redefined this repository's role from *product*
to *framework* (ADR-0005):

- **Collaborators will keep adding features.** The core must rarely be
  touched; new features should arrive as plugins. We don't yet know the full
  feature list.
- **In customer scenarios, sending logs externally is unacceptable.**
  Claude Code usage logs in a corporate setting can be highly sensitive.
  Therefore *data egress is opt-in, explicit, and never default* in this
  framework.
- **In research scenarios, richer data collection is desired.** For opted-in
  participants, we want structured uploads to a central backend.

Supporting all three scenarios on one core means the core must be a
*feature-less host*, and every *behavior* must be encapsulated and audited
as a plugin.

Metric design and prompt-set curation are owned by other contributors; their
output flows in as plugins (e.g., `drift_metrics`).

## 2. Locked decisions

| # | Item | Decision | Source |
|---|---|---|---|
| 1 | Distribution shape | Local sidecar (framework) | ADR-0001 |
| 2 | Language | Python 3.11+, FastAPI, httpx | ADR-0001 |
| 3 | Target agent | Claude Code (Anthropic Messages) first | ADR-0001 |
| 4 | Architecture | **Framework + plugin** model | **ADR-0005** |
| 5 | Data egress | **Off by default.** Plugins request it explicitly. | **ADR-0006** |
| 6 | Deployment modes | L (local-only) / A (audit-light) / R (research) | **ADR-0006** |
| 7 | Central server | Not a core component. A *reference upload-sink plugin* for Mode R. | **ADR-0007** (supersedes ADR-0004) |

## 3. Non-goals

- Token-level rewriting of the model's response (permanent non-goal).
- Putting domain *features* in the core — every behavior is a plugin.
- TLS MITM (`ANTHROPIC_BASE_URL` is sufficient).
- Non-Python plugin SDKs (WASM/subprocess isolation) before Phase 3.

## 4. Core design principles

Every decision in this framework is filtered through these three principles.
On conflict, top wins.

**1) Extensibility first.** New functionality arrives as a plugin package, no
core change required. The core defines hook points and capability vocabulary
only; it carries *no* features. "Let's put it in the core" is almost always
the wrong answer.

**2) Security first.** Defaults are conservative. Data does not leave the
machine by default. A plugin that wants external communication or sensitive
data access must declare a capability, get operator approval, and every use
is recorded in the audit log. *No egress ever happens that the operator did
not explicitly authorize.*

**3) Mode-aware.** The framework knows the current deployment mode (L/A/R)
and enforces what capabilities each mode permits. In Mode L, the
`egress_http` capability simply does not exist — a plugin can request it,
but the core will refuse.

## 5. Operator and user flow

### 5.1 Operator (admin / PI / the user themselves)

```
1. llm-tracker init                    # initialize config
2. Choose a mode: L | A | R
3. Pick plugins; review and approve each plugin's manifest capabilities.
4. llm-tracker start                   # boot the proxy
5. export ANTHROPIC_BASE_URL=http://127.0.0.1:8787
6. claude                              # use as normal
```

### 5.2 Lifecycle of one request (high-level)

```
Claude Code → local proxy
   │
   ▼
[Router] → [PluginHost: on_request_received]    ─┐ plugins return PASS|BLOCK|TRANSFORM
                                                 │ (BLOCK → synthetic response now)
   ▼                                             │
[PluginHost: before_forward]                    ─┘
   │
   ▼
[Forwarder] → api.anthropic.com (SSE)
   │
   ▼
[Tee] ─┬─ pass-through to client (no delay)
       └─ [Extractor] → [Scrubber] → [local SQLite]
                                       │
                                       ▼
                                 [PluginHost: on_response_chunk]    (during stream)
                                 [PluginHost: on_response_complete] (end of stream)
                                 [PluginHost: on_persisted]         (after persist)
```

Plugins run only on the hooks they registered for, and only within the
capabilities granted to them.

## 6. Framework architecture

### 6.1 Core components

```
┌────────────────────────────────────────────────────────────────────┐
│ llm_tracker (core)                                                 │
│                                                                    │
│  ┌─────────┐   ┌──────────────┐   ┌─────────────┐                  │
│  │ Router  │──▶│ Plugin Host  │──▶│ Forwarder   │──▶ api.anthropic │
│  └─────────┘   │ (hooks +     │   └──────┬──────┘                  │
│                │ capability)  │          │                         │
│                └──────┬───────┘          │ SSE                     │
│                       │                  ▼                         │
│                       │             ┌────────┐                     │
│                       │             │  Tee   │──▶ to client        │
│                       │             └───┬────┘                     │
│                       │                 ▼                          │
│                       │            ┌──────────┐                    │
│                       └───────────▶│Extractor │                    │
│                                    └────┬─────┘                    │
│                                         ▼                          │
│                                    ┌──────────┐   ┌──────────────┐ │
│                                    │ Scrubber │──▶│ local SQLite │ │
│                                    └──────────┘   └──────────────┘ │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ EgressGuard ── single path for all outbound HTTP. Allowlist. │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ AuditLog ── records hook invocations, capability uses,       │  │
│  │             egress attempts, plugin lifecycle events         │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

### 6.2 Component responsibilities

**Router**. FastAPI catch-all that accepts every Anthropic path. Auth headers
pass through transparently.

**Plugin Host**. Loads registered plugins per mode policy and capability
grants. Dispatches to plugins at the eight hook points. Each hook runs
within the plugin's declared capabilities; violations cause the plugin to
be rejected or quarantined.

**Forwarder**. Calls upstream via `httpx.AsyncClient.stream()`. Splits the
stream through the Tee.

**Tee**. Splits the SSE response in two: client-direction with no delay,
internal-direction for Extractor and hook consumption.

**Extractor**. Accumulates SSE events (`message_start`, `content_block_*`,
`tool_use`, `message_delta`, `message_stop`) into structured records.

**Scrubber**. Removes/hashes secrets, PII, paths, emails, IPs based on the
content level (§7.1). Runs **before plugins see the data** so non-sensitive
plugins never touch raw content.

**Local SQLite**. Core tables (§9.1) plus the per-plugin namespaces.

**EgressGuard**. The single path for *any* outbound HTTP. A plugin must call
through EgressGuard, which checks (a) does the plugin hold `egress_http`,
(b) is the URL on its manifest's allowlist, (c) does the current mode permit
this capability. All attempts (success/deny) go to AuditLog.

**AuditLog**. Append-only record of the above events into a dedicated table
(or DB). For operator review.

### 6.3 Plugin host model

#### 6.3.1 Plugin manifest

A plugin is a Python package that registers itself via the
`llm_tracker.plugins` setuptools entry point and ships a `plugin.toml`
manifest.

```toml
# plugin.toml example
name = "scope_guard"
version = "0.1.0"
description = "Block requests outside the declared task scope."

# Hooks the plugin binds to
hooks = ["before_forward", "on_persisted"]

# Capabilities required (operator must approve)
capabilities = [
  "read_request_content",
  "block_request",
  "egress_http",            # for Stage 2 LLM judge; omit if local-only
]

# Egress destination allowlist (exact match)
egress_destinations = ["https://api.anthropic.com"]

# Modes in which the plugin can run
allowed_modes = ["A", "R"]

# DB table prefix this plugin owns
db_namespace = "scope_guard"
```

#### 6.3.2 Hook lifecycle (8 points)

| Hook | When | Possible return |
|---|---|---|
| `on_init` | Once at proxy boot | (none) |
| `on_request_received` | Right after intake, before validation | PASS / BLOCK / TRANSFORM |
| `before_forward` | After validation, before upstream | PASS / BLOCK / TRANSFORM |
| `on_upstream_response_start` | Upstream response headers arrive | PASS / ABORT |
| `on_response_chunk` | Each response chunk | PASS / ABORT |
| `on_response_complete` | `message_stop` arrives | (observe only) |
| `on_persisted` | After local DB persistence (async OK) | (observe only) |
| `on_shutdown` | At process shutdown | (none) |

`BLOCK` / `ABORT` produces a synthetic SSE response back to the client and
skips later hooks for that exchange.

#### 6.3.3 Capability vocabulary (initial set)

| Capability | Meaning |
|---|---|
| `read_request_metadata` | model name, token counts, scrubbed headers, timing |
| `read_request_content` | user prompts and tool_result bodies |
| `read_response_metadata` | response usage, stop_reason |
| `read_response_content` | response body (including streamed chunks) |
| `modify_request` | mutate the upstream request before forward |
| `block_request` | issue a synthetic block response |
| `abort_response` | terminate an in-progress response stream |
| `read_persisted_data` | read the local DB |
| `write_plugin_tables` | write to the plugin's own namespace |
| `egress_http` | outbound HTTP through EgressGuard (allowlist required) |

The operator approves capabilities at install time. A manifest change
triggers re-approval (signature catches tampering).

#### 6.3.4 Isolation

Plugins run in-process with the core, with these protections:

- Plugin calls are bounded by timeout and exception isolation. A plugin
  fault does not crash the core.
- The core hands data to plugins via function arguments only — no shared
  global state.
- Outbound HTTP must go through EgressGuard. Direct use of raw socket /
  `requests` / `urllib` is forbidden by style guide and code review;
  enforced isolation lives in Phase 3 (subprocess).
- DB access is restricted to handles scoped by `db_namespace`.

### 6.4 Adapter abstraction

Provider-agnostic interface for future expansion:

```python
class ProviderAdapter(Protocol):
    name: str                              # "anthropic", "openai", ...
    def match(self, request) -> bool: ...
    def parse_request(self, raw) -> RequestRecord: ...
    def parse_response_stream(self, stream) -> AsyncIterator[Event]: ...
    def upstream_url(self, request) -> str: ...
```

Only `llm_tracker.adapters.anthropic` is implemented for now. OpenAI/Gemini
deferred.

## 7. Security model

### 7.1 Content levels

Data flows through four levels. The level a plugin sees in a hook is
*degraded by mode default and by the plugin's declared minimum*.

| Level | Meaning |
|---|---|
| L0 | Metadata only — token counts, model name, latency, tool names, status code |
| L1 | L0 + deterministic hashes (SHA-256) of bodies, lengths |
| L2 | L0 + scrubbed body (secrets/PII/paths/emails/IPs removed) |
| L3 | Raw (still scrubber-passed) |

Defaults: Mode L → L0–L1, Mode A → L0, Mode R → opt-in L2–L3. A plugin
declares its minimum required level in its manifest; it receives data at
that level only if the operator approves it.

### 7.2 Capability system

The capability list in §6.3.3 is the permission model. Invariants:

- A plugin cannot do anything outside its declared capabilities.
- No capability is active without operator approval.
- Manifest tampering is caught by signature check; the plugin is disabled.
- Every capability use is recorded in AuditLog as `(plugin, hook,
  capability, outcome)`.

### 7.3 Egress control

The framework's strongest enforced security boundary.

- **Every** outbound HTTP goes through EgressGuard. Plugin code must not use
  raw HTTP libraries (lint rule + review).
- EgressGuard does strict matching on the manifest's `egress_destinations`
  allowlist. No wildcards (e.g., `https://api.anthropic.com` is OK,
  `https://*.com` is not).
- In Mode L, EgressGuard refuses every destination except the LLM upstream
  itself, regardless of plugin manifest.
- In Mode A, only the operator-approved destination is allowed.
- All egress attempts (success/deny) → AuditLog.

The upstream LLM (api.anthropic.com) is called by the core directly, on a
separate path from EgressGuard, but logged in the same audit stream.

### 7.4 Audit log

```sql
CREATE TABLE audit_log (
  id          TEXT PRIMARY KEY,            -- ULID
  ts          INTEGER NOT NULL,            -- epoch ms
  kind        TEXT NOT NULL,               -- plugin_loaded | hook_invoked |
                                           -- capability_used | egress_attempt |
                                           -- egress_blocked | manifest_rejected
  plugin      TEXT,                        -- plugin name (if applicable)
  hook        TEXT,                        -- hook name (if applicable)
  capability  TEXT,                        -- capability (if applicable)
  destination TEXT,                        -- egress destination (if applicable)
  outcome     TEXT NOT NULL,               -- ok | denied | error
  detail_json TEXT
);
CREATE INDEX idx_audit_ts ON audit_log(ts);
CREATE INDEX idx_audit_plugin ON audit_log(plugin);
```

Operator inspects via `llm-tracker audit ...`. Append-only (DB triggers
block update/delete).

## 8. Deployment modes

The operator picks the mode at startup. Mode constrains capability
permissions and content-level defaults.

| | Mode L (local-only) | Mode A (audit-light) | Mode R (research) |
|---|---|---|---|
| Use case | Highly sensitive customers | Compliance / lightweight tracking | Research data collection |
| `egress_http` capability | Denied | Operator-approved single destination | Manifest-driven, multiple |
| Default outbound content level | n/a (no outbound) | L0 | L1 (L2/L3 if user opts in) |
| User consent flow | None needed | "Send metadata" once | Per-task opt-in |
| Example plugins | scope_guard (local judge) | scope_guard, audit_export | + drift_metrics, upload_sink |

Mode change requires restart and re-approval (no silent escalation).

## 9. Data model

### 9.1 Core tables (all modes)

```sql
CREATE TABLE exchanges (
  id                 TEXT PRIMARY KEY,
  session_id         TEXT NOT NULL,
  started_at         INTEGER NOT NULL,
  ended_at           INTEGER,
  provider           TEXT NOT NULL,
  endpoint           TEXT NOT NULL,
  model_requested    TEXT,
  model_served       TEXT,
  status_code        INTEGER,
  input_tokens       INTEGER,
  output_tokens      INTEGER,
  cache_read_tokens  INTEGER,
  cache_write_tokens INTEGER,
  latency_ms         INTEGER,
  stop_reason        TEXT,
  tool_call_count    INTEGER DEFAULT 0,
  content_level      TEXT NOT NULL,   -- L0 | L1 | L2 | L3
  blocked_by         TEXT             -- plugin name if blocked
);

CREATE TABLE events (
  id           TEXT PRIMARY KEY,
  exchange_id  TEXT NOT NULL REFERENCES exchanges(id),
  seq          INTEGER NOT NULL,
  ts           INTEGER NOT NULL,
  kind         TEXT NOT NULL,
  payload_json TEXT
);

CREATE TABLE tool_calls (
  id           TEXT PRIMARY KEY,
  exchange_id  TEXT NOT NULL REFERENCES exchanges(id),
  name         TEXT NOT NULL,
  input_hash   TEXT,
  input_json   TEXT,
  result_hash  TEXT,
  result_json  TEXT
);

-- audit_log lives in §7.4

CREATE INDEX idx_exchanges_started ON exchanges(started_at);
CREATE INDEX idx_events_exchange   ON events(exchange_id, seq);
```

### 9.2 Plugin tables (each plugin owns its namespace)

A plugin creates tables only inside its manifest's `db_namespace`. Naming:
`plugin_<namespace>__<table>`. Schema migrations live with the plugin's own
Alembic version directory; the core applies them on plugin install.

Example: the scope_guard plugin owns
`plugin_scope_guard__task_definitions` and `plugin_scope_guard__verdicts`.
Concrete schema lives with the plugin (ADR-0002 / `docs/plugins/scope_guard.md`).

## 10. Technical risks

| Risk | Verification | Pass condition |
|---|---|---|
| Plugin hooks accumulate first-token-latency | Measure latency with empty plugin and average plugin | ≤ 5 ms per hook |
| Plugin crash impact on the core | Stress with a deliberately-throwing plugin | Core unaffected |
| EgressGuard bypass attempts | Plugin uses raw httpx in test | Caught by static lint + best-effort runtime detection |
| Mode escalation (L→A→R unauthorized) | Simulated config tampering | Refuses to start |
| Manifest tampering for extra capability | Inject fake manifest | Signature rejects |
| Scrubbing miss | Fake session with secrets → grep SQLite + plugin payloads | Zero pattern matches |
| SSE tee adds user-visible delay | Direct vs. via-proxy first-token latency | ≤ 50 ms overhead |

## 11. Dependencies (planned)

- `fastapi`, `uvicorn[standard]`, `httpx[http2]`
- `pydantic`, `pydantic-settings`
- `structlog`
- `typer`
- `sqlalchemy[asyncio]`, `aiosqlite`, `alembic`
- `python-ulid`, `keyring`
- Signing: `pynacl` (ed25519)
- Dev: `pytest`, `pytest-asyncio`, `respx`, `ruff`, `mypy`

Plugins are free to bring additional dependencies. Core deps are
deliberately narrow.

## 12. Open issues

- Session identification (grouping a Claude Code conversation across HTTP
  calls). Heuristic vs. metadata-driven.
- Anthropic API ToS compatibility (legal review).
- Whether scrubbing is core-enforced (plugins only get post-cleanup
  augmentation) or plugins may add their own. Default: core-enforced;
  plugins may add only.
- When to move plugin isolation from in-process to subprocess/seccomp
  (Phase 3 candidate).
- Plugin signing trust model (operator's own key vs. our central key).
- ADR-0003 (distribution): needs an update for the framework + plugin
  separated-distribution model.

## 13. Appendices

### 13.1 Appendix A — Reference upload-sink plugin (Mode R)

Per ADR-0007, this is the reference plugin we ship. **Lives in a separate
package** from the core.

- Tentative package name: `llm_tracker_plugin_supabase_sink`.
- Behavior: in `on_persisted`, batches exchange records to a Supabase
  Postgres instance.
- Required capabilities: `read_persisted_data`, `egress_http`.
- Egress destination: the operator's Supabase URL (filled in at manifest
  approval).
- Recommended hosting (for the research operator): the
  `llm_tracker_server` app deployed on Fly.io. Supabase is used as plain
  Postgres (no RPC / RLS / Edge Function).

Operating manual: `docs/plugins/upload_sink.md` (to be written in Phase 2).

### 13.2 Appendix B — Migration-friendly code structure

Same principle for the core and the reference plugin. Full layout in
`docs/plugins.md`.

- Layers: `api/` → `domain/` → `storage/`. `domain/` knows no IO.
- DB access is confined to `storage/repositories/`. Standard SQL only.
- Migrations via Alembic. Each plugin has its own alembic versions.
- `DATABASE_URL` env var is the single config knob for swapping DBs.

---

## See also

- Phased plan: `docs/roadmap.md`
- Decisions log: `docs/decisions/`
- Plugin authoring guide: `docs/plugins.md`
- Distribution analysis: `docs/distribution.md`
- Claude Code working rules: `/CLAUDE.md`
