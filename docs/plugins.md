# Plugin Authoring Guide

All *features* in this framework live in plugins. This document defines the
contract a plugin author can rely on. Core design is in `design.md`; the
security policy is in ADR-0006.

## 1. What a plugin is

- A Python package, installed alongside the core.
- It registers itself via the `llm_tracker.plugins` setuptools entry point.
- It carries a `plugin.toml` manifest at the package root.
- It subclasses `BasePlugin` and overrides whichever hooks it needs.
- Outside of its declared capabilities, it cannot do anything (enforced).

## 2. `plugin.toml` schema

All fields are validated by `llm_tracker_sdk.manifest.PluginManifest` at
load time. Unknown fields are rejected.

```toml
name = "my_plugin"          # required; becomes the DB namespace
version = "0.1.0"           # required
description = "..."         # optional

# Hooks the plugin binds to (subset of the 8 hooks below)
hooks = ["before_forward", "on_persisted"]

# Capabilities required (operator must approve each one)
capabilities = ["read_request_content", "block_request"]

# Egress allowlist (exact match; no wildcards). Requires egress_http capability.
egress_destinations = []

# Deployment modes in which this plugin runs ("L", "A", "R")
allowed_modes = ["A", "R"]

# SQLite table prefix (defaults to empty; use name if you own tables)
db_namespace = "my_plugin"
```

Use `PluginManifest.from_path(Path("plugin.toml"))` to validate programmatically.

## 3. Hook lifecycle

| Hook | When | Allowed returns |
|---|---|---|
| `on_init` | Once at proxy boot | (none) |
| `on_request_received` | Right after intake, before validation | `Pass` / `Block(reason)` |
| `before_forward` | After validation, before upstream | `Pass` / `Block(reason)` / `Transform(headers, body)` |
| `on_upstream_response_start` | Upstream response headers arrive | `Pass` / `Abort(reason)` |
| `on_response_chunk` | Each streamed chunk | `Pass` / `Abort(reason)` |
| `on_response_complete` | `message_stop` event | (observe only) |
| `on_persisted` | After local DB write (async OK) | (observe only) |
| `on_shutdown` | At process shutdown | (none) |

`Block` / `Abort` results in a synthetic response delivered to the client.

### 3.1 What `HookContext` exposes per level

Every per-exchange hook receives a `HookContext` (ADR-0012). The
context has lazy accessors for the request body that degrade against
the deployment mode and operator opt-in flag (design.md §7.1).

| Effective level | `request_text(level)` | `request_hash()` | `request_length()` |
|---|---|---|---|
| L0 (Mode A)                          | `None`           | `None`         | `None`         |
| L1 (Mode L; Mode R no opt-in)        | `None`           | hex SHA-256    | byte length    |
| L2 (Mode R + opt-in, asking for L2)  | raw decoded text\* | hex SHA-256  | byte length    |
| L3 (Mode R + opt-in, asking for L3)  | raw decoded text | hex SHA-256    | byte length    |

\* L2 returns the raw decoded text today. The "scrubbed" shape
described in design.md §7.1 lands in Phase 1c alongside the scrubber
primitives — until then a plugin asking for L2 receives the same
bytes it would get at L3.

**Reading rules of thumb**:

- Plugins that only need fingerprints (dedup, "did this exact prompt
  repeat") call `request_hash()` / `request_length()` — these work in
  Mode L without any consent flow.
- Plugins that must read the body call `request_text(level)`. Treat
  `None` as "no signal at this ceiling, fall through" rather than
  blocking blindly — that's the policy the test-only `keyword_block`
  plugin demonstrates.
- The accessor returns `None` if the body has not been delivered to
  the context yet (e.g. a hook firing before the forwarder reads the
  body) and if the body is not valid UTF-8.

## 4. Capability vocabulary

Declare required capabilities in `plugin.toml`. The operator approves each
at install time; changing the manifest requires re-approval.

| Constant (`llm_tracker_sdk.capabilities.*`) | Token string | Meaning |
|---|---|---|
| `READ_REQUEST_METADATA` | `read_request_metadata` | Model name, token counts, scrubbed headers, timing |
| `READ_REQUEST_CONTENT` | `read_request_content` | User prompts and tool_result bodies |
| `READ_RESPONSE_METADATA` | `read_response_metadata` | Response usage, stop_reason |
| `READ_RESPONSE_CONTENT` | `read_response_content` | Response body (incl. streamed chunks) |
| `MODIFY_REQUEST` | `modify_request` | Mutate the upstream request before forward |
| `BLOCK_REQUEST` | `block_request` | Issue a synthetic block response |
| `ABORT_RESPONSE` | `abort_response` | Terminate an in-progress response stream |
| `READ_PERSISTED_DATA` | `read_persisted_data` | Read the local SQLite DB |
| `WRITE_PLUGIN_TABLES` | `write_plugin_tables` | Write to your own DB namespace |
| `EGRESS_HTTP` | `egress_http` | Outbound HTTP through EgressGuard (requires allowlist) |

## 5. Writing a plugin

### Install

```
pip install "git+https://github.com/<owner>/Userfriendly.git#subdirectory=packages/llm_tracker_sdk"
```

### Minimal plugin

```python
# src/my_plugin/__init__.py
from llm_tracker_sdk import BasePlugin, Block, Pass


class MyPlugin(BasePlugin):
    name = "my_plugin"

    async def before_forward(self, exchange_id: str) -> Pass | Block:
        # exchange_id identifies this request in the local DB
        return Pass()
```

Register via `pyproject.toml`:

```toml
[project.entry-points."llm_tracker.plugins"]
my_plugin = "my_plugin:MyPlugin"
```

### Overriding hooks

Override only the hooks your plugin needs. Unoverridden hooks default to
`Pass()` (or no-op for observe-only hooks). `BasePlugin` is a concrete
class — no abstract methods to satisfy.

```python
from llm_tracker_sdk import Abort, BasePlugin, Block, Pass, Transform
from llm_tracker_sdk import capabilities


class MyPlugin(BasePlugin):
    name = "my_plugin"

    async def on_request_received(self, exchange_id: str) -> Pass | Block:
        return Pass()

    async def before_forward(self, exchange_id: str) -> Pass | Block | Transform:
        return Transform(headers={"x-custom": "1"})

    async def on_response_chunk(self, exchange_id: str, chunk: bytes) -> Pass | Abort:
        return Pass()
```

## 6. Testing your plugin

Use `llm_tracker_sdk.testing.PluginHarness`:

```python
from llm_tracker_sdk.testing import PluginHarness
from my_plugin import MyPlugin


async def test_passes_normal_request():
    harness = PluginHarness(MyPlugin())
    await harness.init()
    result = await harness.on_request_received()
    harness.assert_pass(result)


async def test_blocks_flagged_request():
    harness = PluginHarness(MyPlugin())
    result = await harness.on_request_received("special-exchange-id")
    harness.assert_block(result, reason_contains="out of scope")
```

Assertion helpers: `assert_pass`, `assert_block(reason_contains=...)`,
`assert_transform`, `assert_abort(reason_contains=...)`.

## 7. DB tables

A plugin owns tables inside its `db_namespace`. Naming convention:
`plugin_<namespace>__<table>`. Schema migrations live in the plugin's
own Alembic version directory; the core applies them at install time.

## 8. Outbound HTTP (Phase 1b)

Direct use of `requests` / `urllib` / `httpx` from plugin code is
**forbidden** — blocked by lint rule and code review. A safe egress API
(`ctx.egress.fetch(url, ...)` routed through EgressGuard) arrives in Phase
1b. For now, plugins that need egress must wait for that phase. EgressGuard
enforces: (a) exact-match against `egress_destinations`, (b) operator
approval, (c) mode permission.

## 9. Mode-aware behavior

The manifest's `allowed_modes` decides where the plugin loads:

- `["L", "A", "R"]` — works anywhere.
- `["A", "R"]` — needs outbound capability; disabled in Mode L.
- `["R"]` — data upload sink; only Mode R.

## 10. Isolation and trust

Through Phase 1, plugins run in-process. A determined plugin can bypass
EgressGuard with raw sockets — policy forbids it, but strict sandboxing is
Phase 3 (subprocess). Therefore: *do not install plugins you don't trust*.
Manifest signature verification, code review, and explicit capability
approval are the primary defense.

## 11. Reference plugins

| Package | Location | Purpose |
|---|---|---|
| `llm-tracker-plugin-hello-world` | `packages/llm_tracker_plugin_hello_world/` | Phase 0 verification no-op |
| `llm-tracker-plugin-scope-guard` | `packages/llm_tracker_plugin_scope_guard/` | Task-scope enforcement (Phase 1c) |
| `llm-tracker-plugin-supabase-sink` | `packages/llm_tracker_plugin_supabase_sink/` | Mode R upload sink (Phase 2) |

Install from git URL:

```
pip install "git+https://github.com/<owner>/Userfriendly.git#subdirectory=packages/llm_tracker_plugin_hello_world"
```
