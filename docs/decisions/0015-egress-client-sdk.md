# ADR-0015 · `EgressClient` SDK API and per-plugin lifetime

- **Status**: Accepted
- **Date**: 2026-05-07
- **Author**: Claude Code (user-approved in chat; critic-vetted)
- **Related**: ADR-0006 (egress policy and modes), ADR-0007 (supabase_sink as
  reference Mode-R plugin), ADR-0012 (HookContext),
  `docs/plugins.md §8`, `docs/design.md §6.2 EgressGuard`,
  `docs/worklog/2026-05-07-supabase-sink.md`,
  CLAUDE.md §10 (SDK contracts are public-interface)

## Context

`docs/plugins.md §8` (last revised in Phase 1a) promised plugins a host-mediated
egress API:

> A safe egress API (`ctx.egress.fetch(url, ...)` routed through EgressGuard)
> arrives in Phase 1b.

Phase 1b sealed without delivering it. EgressGuard exists at the host level
(`packages/llm_tracker/src/llm_tracker/egress_guard/guard.py`), the plugin
host registers each manifest with the guard at load time
(`plugin_host/host.py:271-272`), but plugins have no way to actually call
through it — and `httpx`/`requests`/raw sockets are forbidden in plugin code.
The Phase-2 reference plugin `llm_tracker_plugin_supabase_sink` (ADR-0007)
cannot ship without this surface.

A second concern surfaced in critic review of the supabase_sink plan: the
plugin pattern that motivates this API — a **batched background flusher** —
runs *outside* any exchange's lifecycle. So binding the egress API solely to
`HookContext` (which is per-exchange and stashed in
`PluginHost._exchange_contexts`) would leave the flusher with no way to call
`fetch()` after its triggering exchange ends. The lifecycle of the egress
client is the load-bearing decision in this ADR.

## Options considered

1. **No SDK addition; plugins import `EgressGuard` directly.** A plugin
   imports the host module, looks up the guard via the proxy `app.state`
   singleton, calls `guard.check(...)` and then uses raw `httpx`.
   - Pro: zero SDK change.
   - Con: the SDK isolation promised in `plugins.md §8` is broken. Every
     plugin must re-implement the check / fetch / audit-fold pattern.
     Plugins now depend on core internal module paths
     (`llm_tracker.egress_guard.*`) that are not part of the SDK contract.
     Discharging plugins.md §8 by *deleting* the promise rather than honouring
     it.

2. **Per-exchange `ctx.egress` only.** `HookContext` gains an `egress` field;
   the host populates it on `begin_exchange` and tears it down on
   `end_exchange`. Plugins call `await ctx.egress.fetch(...)` from inside a
   hook.
   - Pro: matches ADR-0012's "per-exchange context" framing.
   - Con: **breaks every plugin that posts asynchronously**. The supabase_sink
     enqueues records inside `on_response_complete` and a background task
     drains the queue in batches. By the time the flusher fires, the ctx is
     gone (or worse — leaks, because `end_exchange` is currently never
     called; STATUS.md "Phase 1b loose ends"). The flusher would have to
     either smuggle a closure over `ctx` (lifetime hazard) or fall back to
     option 1.

3. **Per-plugin lifetime, `ctx.egress` is the same instance.** The host
   constructs one `EgressClient` per loaded plugin at *plugin load time*,
   binds the plugin's name and the shared `EgressGuard`/`httpx.AsyncClient`
   into it, and assigns the instance to `BasePlugin.egress`. `HookContext`
   exposes the same instance under `ctx.egress` purely for in-hook
   ergonomics — both reads return the same Python object. Background tasks
   call `self.egress.fetch(...)` and continue working past their triggering
   exchange.
   - Pro: works for both in-hook and background patterns. Audit log is
     correct regardless of caller (the plugin name is baked in at construction
     time, not threaded through every call). One `httpx.AsyncClient` is
     shared across plugins, matching the proxy's existing pattern.
   - Con: a plugin that *swaps* its instance at runtime would fool the audit
     log. Mitigation: the type is treated as immutable; `BasePlugin.egress`
     is set by the host once and not re-written.

## Decision

**Pick option (3) — per-plugin `EgressClient`, `ctx.egress` as the same
instance.** Three core reasons:

- **The motivating plugin pattern requires it.** Batched/retry/asynchronous
  upload is the canonical Mode-R plugin shape (ADR-0007 §1, design.md §13.1
  "batches exchange records"). Per-exchange lifetime would make every such
  plugin work around the API.
- **Audit fidelity is structural.** The `plugin` field on every
  `egress_attempt` / `egress_blocked` row comes from the EgressClient's
  bound plugin name, not from a caller-supplied argument. A plugin literally
  cannot mis-attribute an egress.
- **No core architecture is committed beyond what `plugins.md §8` already
  promised.** The contract is the same one that has been documented since
  Phase 1a; this ADR specifies its lifecycle so the executor doesn't have
  to invent it.

### Surface (SDK)

```python
# packages/llm_tracker_sdk/src/llm_tracker_sdk/egress.py

@dataclass(frozen=True)
class EgressResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class EgressDenied(Exception):
    """Raised by EgressClient.fetch when EgressGuard denies the request."""
    def __init__(self, url: str, reason: str) -> None: ...


class EgressClient(Protocol):
    async def fetch(
        self,
        url: str,
        *,
        method: str = "POST",
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout: float = 30.0,
    ) -> EgressResponse: ...
```

`BasePlugin` gains:

```python
class BasePlugin:
    name: str = "unnamed"
    egress: EgressClient | None = None   # populated by the host at load time
```

`HookContext` gains a parallel `egress: EgressClient | None` field; the host
sets it to the *same instance* attached to the dispatching plugin.

### Lifecycle

The host owns the lifecycle:

1. **At plugin load** (`PluginHost.load_plugins`) — after manifest parse,
   denylist, signature, and capability checks succeed and the plugin
   instance has been constructed, the host calls
   `plugin.egress = self._build_egress_client(manifest)`. The client is
   bound to `(manifest.name, self._egress_guard, self._http_client)` and
   has the plugin's identity baked in for the rest of its lifetime.
2. **Per exchange** (`begin_exchange`) — the `HookContext`'s `egress` is
   filled by looking up the dispatching plugin's `.egress` reference. A
   plugin can use `self.egress` or `ctx.egress` interchangeably; both point
   at the same object.
3. **At plugin shutdown** (`on_shutdown`) — the client is *not* torn down
   per-plugin. The shared `httpx.AsyncClient` is closed by the host during
   `lifespan` exit, after every plugin's `on_shutdown` has run (so a
   plugin's shutdown flusher can still call `fetch`).

### EgressClient → EgressGuard → httpx

`HostEgressClient.fetch` is implemented in
`packages/llm_tracker/src/llm_tracker/egress_guard/client.py`:

```python
async def fetch(self, url, *, method="POST", headers=None, body=None, timeout=30.0):
    ok = await self._guard.check(plugin=self._plugin_name, url=url,
                                 capability="egress_http")
    if not ok:
        # EgressGuard already wrote the egress_blocked audit row; raise
        # so the plugin sees the denial without an extra DB read.
        raise EgressDenied(url, reason="denied_by_egress_guard")
    resp = await self._http_client.request(
        method, url, headers=dict(headers or {}), content=body, timeout=timeout,
    )
    return EgressResponse(
        status_code=resp.status_code,
        headers=dict(resp.headers),
        body=resp.content,
    )
```

The httpx client is the proxy's existing shared client (forwarder.py:24-31)
to avoid duplicate connection pools.

## Consequences

### What this enables

- The supabase_sink plugin (and every future Mode-R sink) can ship without
  re-importing core internals.
- Audit log binding is structurally correct: every `egress_attempt` /
  `egress_blocked` row's `plugin` column reflects the actual code path,
  enforced at the type level.
- Background task patterns (queues, retry workers) become idiomatic — they
  hold `self.egress` and operate independently of `HookContext` lifecycles,
  which removes the pressure on `end_exchange` cleanup (STATUS.md "Phase 1b
  loose end") for this use case.

### What this constrains / forecloses

- The SDK now exposes an HTTP-shaped surface. A future plugin that wants
  another protocol (gRPC, a Postgres TCP connection, etc.) would have to
  go through a parallel SDK-side helper or — more likely — keep being
  forbidden, since EgressGuard's allowlist is URL-shaped. This is in line
  with ADR-0006's intent: HTTP is the only egress path.
- `BasePlugin.egress` is `Optional` to keep the in-process test harness
  (`PluginHarness`) trivial; production code paths that might run before
  the host populates the field must defensive-check (or simply be `on_init`
  or later, where the host has already set it).

### Reversibility

High at the API level. Removing `ctx.egress` while keeping
`BasePlugin.egress` is mechanical (one `HookContext` field deletion); the
inverse is also cheap. Replacing the protocol with a different egress
shape would require a new ADR (CLAUDE.md §10 — SDK contracts are
public-interface).

## Open questions

- **Streaming responses.** `EgressResponse.body: bytes` materialises the full
  response. For sinks that POST and discard the body that's fine; future
  plugins that *fetch* large payloads (e.g. a model card) will want a
  streaming variant. Deferred until a concrete plugin needs it.
- **Per-plugin httpx settings.** Today every plugin shares one
  `httpx.AsyncClient` (timeouts, transport, http2). A plugin that needs
  custom settings would have to negotiate them through the SDK; deferred
  until a concrete plugin needs it.
- **Subprocess isolation (Phase 3).** Once plugins run in subprocesses, the
  EgressClient becomes an IPC stub. The protocol shape stays the same —
  this ADR is forward-compatible — but the implementation moves.
