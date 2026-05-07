# ADR-0014 · `llm-tracker plugins` and `/admin/plugins` introspection

- **Status**: Accepted
- **Date**: 2026-05-07
- **Author**: Claude Code (user-approved in chat)
- **Related**: ADR-0013 (plugin disable config — sister change),
  `packages/llm_tracker/src/llm_tracker/cli/main.py`,
  `packages/llm_tracker/src/llm_tracker/proxy/app.py`,
  CLAUDE.md §10 (CLI flags + HTTP paths are public-interface contracts)

## Context

ADR-0013 lets an operator disable a plugin via env var. That feature
is only useful if the operator can also confirm what is *actually*
loaded by the running proxy. Three failure modes need to be visible:

- `LLMTRACK_PLUGINS_DISABLED` typo'd a name → plugin still loads.
- A new plugin's `plugin.toml.sig` failed verification → plugin
  silently absent.
- Mode policy denied the plugin's capabilities → plugin silently
  absent.

Today the only way to learn the loaded set is to grep the audit log
for `plugin_loaded` rows since the last `proxy_started`, which is
hostile to interactive use.

## Options considered

1. **Read the audit log from the CLI.** Existing `llm-tracker audit`
   already reads `AuditLog`. A new subcommand could derive "currently
   loaded" by walking the rows after the most recent `proxy_started`.
   - Pro: zero new HTTP surface; no proxy code touched.
   - Con: stale view of a *crashed* proxy reads as "loaded" until the
     next start. Distinguishing live from dead requires probing the
     pid/port anyway. Logic is fragile and audit-row drift would
     silently break the command.
2. **HTTP introspection endpoint on the proxy.**
   `GET /admin/plugins` returns the live, in-memory loaded set; the
   CLI HTTPs the proxy and pretty-prints. No DB scan, no liveness
   reasoning — if the request succeeds, the answer is live; if it
   fails, the proxy is down and the CLI says so.
   - Pro: source of truth, simple semantics, mirrors how Kubernetes
     `kubectl get` etc. work for local sidecars.
   - Con: adds an HTTP path beside the catch-all proxy route; the
     route ordering must be explicit so `/admin/plugins` doesn't get
     forwarded upstream as a "passthrough" call.
3. **Static `pkg_resources` scan from the CLI.** Iterate
   `entry_points(group="llm_tracker.plugins")` and report what
   *would* load.
   - Pro: works without a running proxy.
   - Con: doesn't answer the actual question. Can't see denylist
     hits, signature failures, or capability denials — exactly the
     failure modes the user wants visibility into.

## Decision

**Pick option (2) — `GET /admin/plugins` + `llm-tracker plugins`
CLI.** Three core reasons:

- **Live truth.** The endpoint reads `PluginHost._manifests` directly,
  which is exactly the set the dispatcher iterates. There is no
  inference step that can drift.
- **Symmetric with the disable feature.** ADR-0013 ships the knob;
  this ADR ships the read-back. They are designed together so the
  operator's mental model is "set env var, restart proxy, run
  `llm-tracker plugins` to confirm".
- **Cheap to implement and revert.** One FastAPI route, one Typer
  subcommand. The proxy gains no auth surface — the route is
  `127.0.0.1`-only by virtue of `proxy_host` defaulting to localhost
  (mode L policy already keeps the proxy off the network).

### Surface

```http
GET /admin/plugins
200 OK
[
  {"name": "hello_world", "version": "0.1.0",
   "hooks": ["on_init"], "capabilities": [], "allowed_modes": ["L","A","R"]},
  {"name": "token_counter", "version": "0.1.0", ...}
]
```

```text
$ llm-tracker plugins
hello_world          v0.1.0   hooks=on_init                          modes=L,A,R
token_counter        v0.1.0   hooks=on_persisted                     modes=L,A,R
```

When the proxy is unreachable:

```text
$ llm-tracker plugins
Failed to query proxy at http://127.0.0.1:8787/admin/plugins: <reason>
(exit code 1)
```

### Route registration

The catch-all `@app.api_route("/{path:path}", ...)` matches every
path. FastAPI dispatches in registration order, so `/admin/plugins`
must be registered **before** the catch-all. The implementation puts
the admin route between `lifespan` setup and the catch-all
definition.

### `PluginHost` contract addition

`PluginHost` gains:

- A private `self._manifests: list[PluginManifest]` populated only
  for plugins that pass every load-time check (manifest parse,
  denylist, signature, capability policy).
- A public `loaded_plugins() -> list[dict]` returning a serialisable
  view: name, version, hooks, capabilities, allowed_modes.

The list shape is stable for the CLI to depend on. Adding fields is
additive (the CLI ignores unknown keys); removing or renaming a key
is a breaking change and requires a follow-up ADR per CLAUDE.md §10.

## Consequences

### What this enables

- Operator can confirm a disable took effect:
  `LLMTRACK_PLUGINS_DISABLED=token_counter llm-tracker start ...` and
  in another shell `llm-tracker plugins` shows `token_counter` is
  absent.
- The same endpoint supports future debug tooling (e.g. a TUI status
  page) without re-litigating the data shape.
- New audit kinds (`plugin_skipped` from ADR-0013, plus pre-existing
  `manifest_rejected`/`capability_denied`) all map to "this plugin
  did not appear in `loaded_plugins()`" — a single, clean negative
  signal.

### What this constrains / forecloses

- Adding the admin route expands the proxy's HTTP surface. Future
  admin endpoints (e.g. `/admin/audit`, `/admin/health`) inherit the
  precedent: namespaced under `/admin/`, registered before the
  catch-all, no auth (localhost-only), additive JSON shape.
- The CLI subcommand is synchronous and short-circuits on connect
  errors. It is *not* a substitute for a long-lived monitoring
  client; it answers "what's loaded right now" and exits.

### Reversibility

High. Removing the route, the helper, and the CLI subcommand is a
mechanical revert. No persistent state.

## Open questions

- **`/admin/health`.** Out of scope. A liveness/readiness endpoint
  has a wider blast radius (Kubernetes hooks, monitoring tooling) and
  warrants its own ADR if and when it ships.
- **JSON output flag for `llm-tracker plugins`.** Deferred. The
  current CLI is human-pretty; if a downstream wants machine-readable
  output, adding `--json` is a non-breaking extension (no ADR needed
  unless the JSON shape diverges from the endpoint).
- **Auth on `/admin/*`.** Deferred. Today the proxy listens on
  `127.0.0.1` by default; if a future deployment binds to a wider
  interface, an admin token will be needed and is a separate ADR.
