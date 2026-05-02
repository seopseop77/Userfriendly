# Plugin Authoring Guide

All *features* in this framework live in plugins. This document defines the
contract a plugin author can rely on. Core design is in `design.md`; the
security policy is in ADR-0006.

> **Status**: skeleton. The SDK lands in Phase 1a; this document will fill
> out then. For now, it's enough for a collaborator considering writing a
> plugin to know what they will get and what they must declare.

## 1. What a plugin is

- A Python package, distributed normally.
- It registers itself via the `llm_tracker.plugins` setuptools entry point.
- It carries a `plugin.toml` manifest at the package root.
- It binds to one or more hooks.
- Outside of its declared capabilities, it cannot do anything (enforced).

## 2. `plugin.toml` schema

```toml
name = "<plugin-name>"             # alphanumeric + hyphen/underscore; becomes the namespace
version = "0.1.0"
description = "..."
author = "..."

# Compatible core versions
core_version_constraint = ">=0.1.0,<0.2.0"

# Hooks to bind
hooks = ["before_forward", "on_persisted"]

# Capabilities required (operator must approve)
capabilities = ["read_request_content", "block_request"]

# Egress allowlist for outbound HTTP (exact match; no wildcards)
egress_destinations = []          # empty = no outbound

# Modes in which the plugin is allowed to run
allowed_modes = ["A", "R"]

# DB table prefix for plugin-owned tables
db_namespace = "<plugin-name>"

# Minimum content level the core must pass to this plugin
required_content_level = "L2"

# (optional) operator-supplied configuration schema
[config_schema]
my_field = "string"
```

## 3. Hook lifecycle

| Hook | When | Return |
|---|---|---|
| `on_init` | once at proxy boot | (none) |
| `on_request_received` | right after intake | `Pass` / `Block(reason)` / `Transform(req)` |
| `before_forward` | just before upstream call | `Pass` / `Block(reason)` / `Transform(req)` |
| `on_upstream_response_start` | response headers arrive | `Pass` / `Abort(reason)` |
| `on_response_chunk` | per chunk | `Pass` / `Abort(reason)` |
| `on_response_complete` | `message_stop` | (observe only) |
| `on_persisted` | after local DB persistence (async OK) | (observe only) |
| `on_shutdown` | at process shutdown | (none) |

`Block` / `Abort` results in a synthetic SSE response that explains the
block to the user.

## 4. Capability vocabulary

| Capability | Meaning |
|---|---|
| `read_request_metadata` | model name, token counts, scrubbed headers |
| `read_request_content` | user prompts and tool_result bodies |
| `read_response_metadata` | response usage, stop_reason |
| `read_response_content` | response body (incl. streamed chunks) |
| `modify_request` | mutate the upstream request before forward |
| `block_request` | issue a synthetic block response |
| `abort_response` | terminate an in-progress response stream |
| `read_persisted_data` | read the local DB |
| `write_plugin_tables` | write to your own namespace |
| `egress_http` | outbound HTTP through EgressGuard |

## 5. Plugin code skeleton (planned SDK shape)

```python
# src/my_plugin/__init__.py
from llm_tracker_sdk import BasePlugin, hook, Pass, Block

class MyPlugin(BasePlugin):

    @hook("before_forward")
    async def check_scope(self, ctx):
        user_msg = ctx.last_user_message_text   # masked per capability
        if "..." in user_msg:
            return Block(reason="...")
        return Pass()

    @hook("on_persisted")
    async def maybe_export(self, ctx, exchange_id):
        # Use ctx.egress.fetch(...) only. Raw httpx is forbidden.
        ...
```

## 6. DB tables

A plugin creates tables only inside its `db_namespace`. Naming:
`plugin_<namespace>__<table>`. Schema migrations live in the plugin's
own Alembic version directory; the core applies them at install time.

## 7. Outbound HTTP

Direct use of `requests` / `urllib` / `httpx` is **forbidden** — caught by
static lint and code review. All outbound HTTP goes through the SDK-provided
`ctx.egress.fetch(url, ...)`. EgressGuard enforces (a) exact-match against
the manifest's `egress_destinations`, (b) operator approval, (c) mode
permission.

## 8. Mode-aware behavior

The manifest's `allowed_modes` decides where the plugin can run:

- `["L", "A", "R"]` — works anywhere.
- `["A", "R"]` — needs outbound, so disabled in Mode L.
- `["R"]` — data upload sink; only Mode R.

## 9. Isolation and trust

Through Phase 1, plugins run in-process. A determined plugin can in
principle bypass EgressGuard with raw sockets — policy forbids it, but
strict isolation is Phase 3 (subprocess). Therefore: *do not install
plugins you don't trust*. Manifest signature verification, code review,
and explicit capability approval are the first defense.

## 10. Reference plugins

- `scope_guard` — task-scope enforcement (ADR-0002 spec).
- `supabase_sink` — Mode R central upload (ADR-0007).
- `hello_world` — Phase 0 verification no-op.

Each reference plugin is a separate package, but lives in this repository
tree under `src/llm_tracker_plugin_<name>/` for now. Splitting to dedicated
repos is deferred.
