# ADR-0012 · `HookContext` for content-level → hook payload routing

- **Status**: Accepted
- **Date**: 2026-05-06
- **Author**: Claude Code (user-approved option (b))
- **Related**: `docs/design.md §6.3, §7.1` (content levels), ADR-0006
  (mode-based default ceilings), ADR-0008 (signing — unrelated but
  shipped alongside),
  `packages/llm_tracker/src/llm_tracker/content_levels/levels.py`
  (the `effective_ceiling` / `degrade` primitives that already
  encode the math), `docs/worklog/2026-05-05-phase1b-security.md`
  (checkpoint 17 onward), CLAUDE.md §10 (hook lifecycle is a
  public-interface contract)

## Context

Today every plugin hook receives only `exchange_id`. The host
holds the `mode` and the deployment ceiling; plugins have no
access to request or response payloads. Phase 1c plans to ship
`scope_guard`, which classifies the **user message text** as
in-scope or out-of-scope for the registered task. Without a way
to hand the user text to the plugin, the scope-guard hook has
nothing to judge.

Three options were on the table (Cowork's Gate 2 brief):

1. **(a) Extend hook signatures with typed payloads.**
   `on_request_received(exchange_id, request: RequestRecord)` etc.
   The host pre-degrades the payload to the plugin's declared
   `min_content_level` before dispatch.
2. **(b) `HookContext`.** Hooks gain one extra parameter
   `ctx: HookContext`. The plugin asks `ctx.request_text(level=…)`
   when it needs the data; the host degrades at access time
   based on `mode × user_opted_in`.
3. **(c) Plugins query the DB.** Hooks remain unchanged; plugins
   call `read_persisted_data` (a capability) and the storage
   layer degrades. `on_request_received` runs *before* the
   exchange row exists, so this option does not satisfy
   scope_guard's contract.

## Decision

**Pick option (b) — `HookContext` with lazy accessors.** Three
core reasons:

- **Smallest contract change.** Every hook gains exactly one
  parameter; existing return types and dispatch ordering are
  untouched. Plugins that don't need data ignore `ctx` and keep
  working.
- **Lazy degradation matches the security model.** The host
  applies `effective_ceiling(mode, user_opted_in=…)` at the
  *moment of access*, not at dispatch time. A plugin that never
  asks for the request text never costs anything; a plugin that
  asks for it gets exactly the level the deployment policy
  permits, no more.
- **No manifest schema change today.** The `min_content_level`
  field design.md §7.1 envisions stays deferred to Phase 1c —
  it's the right time to add it when scope_guard is being
  written and a real plugin demonstrates the need. Until then,
  plugins request a `level=` explicitly per-call.

### Contract

```python
@dataclass
class HookContext:
    """Per-exchange context handed to every plugin hook.

    The host constructs one HookContext per exchange and passes
    the same instance to every hook invocation for that exchange.
    Plugins read request/response data via lazy accessors; the
    accessor degrades the returned content according to
    mode × user_opted_in (ADR-0006, ADR-0012).
    """

    session_id: str
    exchange_id: str
    mode: str
    user_opted_in: bool = False

    def effective_ceiling(self) -> ContentLevel: ...
    def request_text(self, level: ContentLevel = L3) -> str | None: ...
```

The accessor returns `None` when the requested level is degraded
to `L0` (no plugin-visible content) or when the data is not yet
available at the hook's place in the lifecycle (e.g.
`request_text()` called from a hook that fires before the
request body is read).

`min_content_level` manifest field: deferred to Phase 1c.

### Hook signature changes

The six per-exchange hooks gain `ctx: HookContext`:

- `on_request_received(self, exchange_id, ctx)`
- `before_forward(self, exchange_id, ctx)`
- `on_upstream_response_start(self, exchange_id, ctx)`
- `on_response_chunk(self, exchange_id, chunk, ctx)`
- `on_response_complete(self, exchange_id, ctx)`
- `on_persisted(self, exchange_id, ctx)`

`on_init` and `on_shutdown` are lifecycle hooks not tied to a
specific exchange and remain unchanged.

`PluginHost` builds a `HookContext` once per request (in
`on_request_received` / `before_forward` etc.) and reuses the
same instance for that exchange's later hooks. The host owns
the mode and the request data; plugins see only what `ctx`
exposes.

## Consequences

### What this enables

- `scope_guard` (Phase 1c) and any future content-aware plugin
  can read user-message text at the level the deployment
  permits without bespoke per-plugin plumbing.
- Lazy access keeps hot paths cheap: a plugin that returns
  `Pass()` without inspecting the request never serialises or
  copies the body.
- Tests exercise the degradation math directly by constructing
  `HookContext` with explicit `mode` / `user_opted_in` values.

### What this constrains

- Every existing plugin override of the six per-exchange hooks
  must accept `ctx: HookContext` (or `**kwargs`). Test plugins
  in this repo will be updated alongside the SDK change. No
  external plugins exist yet; impact zero.
- The `request_text()` data source is wired by the host based
  on what is available at each lifecycle point. Plugins should
  treat a `None` return as "data not available at this hook's
  position"; the docstring will spell this out.

### Reversibility

Medium. Reverting to no-ctx hooks is mechanical (drop the
parameter from every signature, drop the HookContext class).
Switching from option (b) to option (a) later — extending
hooks with typed payloads — is incremental: the typed payload
classes can be added to HookContext without removing the
`request_text()` accessor first.

## Open questions

- **`min_content_level` manifest field.** Deferred to Phase 1c;
  expected to be added when scope_guard is being built and a
  real `min_content_level` consumer exists. Its addition is a
  separate ADR.
- **Response-side accessors.** This ADR ships `request_text()`
  as the smoke-test accessor. Response-side accessors
  (`response_text()`, `tool_call_inputs()`) are added when the
  Extractor lands and structured response data is available;
  separate ADR if their semantics surface anything non-obvious.
