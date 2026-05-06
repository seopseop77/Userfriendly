# ADR-0011 · Transform handling policy

- **Status**: Accepted
- **Date**: 2026-05-06
- **Author**: Claude Code (user-approved choice for each
  sub-decision)
- **Related**: `docs/design.md §6.3.2` (hook lifecycle, the
  `before_forward` slot), ADR-0002 (Block path),
  `packages/llm_tracker_sdk/src/llm_tracker_sdk/hooks.py` (the
  `Transform` dataclass), `packages/llm_tracker/src/llm_tracker/proxy/forwarder.py`
  (where Transform must be honoured), CLAUDE.md §10 (hook
  semantics is a public-interface contract)

## Context

`before_forward` is the only hook that may return a `Transform`
result, replacing the request that the proxy forwards upstream.
The dataclass exists in the SDK:

```python
@dataclass
class Transform:
    headers: dict[str, str] | None = None
    body: bytes | None = None
```

`PluginHost.before_forward` already iterates plugins and returns
the first non-`Pass` result, but the **forwarder ignores it**:
the upstream request still uses the original headers and body
the client sent. Without a Transform contract, no plugin can
modify outbound traffic — which forecloses the most natural
plugin shape for things like injecting a tracing header,
rewriting a model name, or stripping client-side metadata.

Three independent sub-decisions are needed:

1. **Header policy** — how `Transform.headers` interacts with
   the request's existing headers.
2. **Body policy** — what `Transform.body` may replace.
3. **Multi-plugin policy** — what happens if more than one
   plugin returns a Transform.

## Sub-decision 1: Header policy

### Options

- **(i) Merge.** `result.headers` is merged into the existing
  request headers; on conflict, the plugin value wins.
- **(ii) Overwrite conflicts only.** Same as merge but only
  conflicting keys are touched; `result.headers` cannot
  introduce new headers.
- **(iii) Replace all headers.** The forwarder's outbound
  request uses *only* `result.headers`, discarding the original
  request headers entirely.

### Decision

**Option (i) — merge, plugin wins on conflict.**

Reasoning:

- **Most plugin use cases are additive.** Injecting an
  `x-llm-tracker-task-id`, an audit cookie, or a tracing header
  doesn't mean the plugin wants to nuke `x-api-key`,
  `anthropic-version`, or `content-type` — option (iii) would
  silently break upstream auth.
- **Plugin-wins on conflict is the only useful semantic.** If
  the plugin sets a header explicitly, it almost certainly
  intended to replace whatever was there. Otherwise the plugin
  has no way to override a header the client set.
- **Hop-by-hop headers (`host`, `content-length`, etc.) are
  already filtered by the forwarder before forwarding upstream**;
  Transform's merge happens after that filter, so a plugin
  can't accidentally re-introduce them.

## Sub-decision 2: Body policy

### Options

- **(i) Replace whole body.** If `result.body is not None`, the
  forwarder replaces the upstream request body entirely with
  it.
- **(ii) Not allowed.** `Transform.body` is rejected; only
  headers can be modified. Plugins wanting to alter the body
  use a separate hook or a different result type.
- **(iii) Patch.** Diff- or JSON-Patch-style structured edits.

### Decision

**Option (i) — replace whole body when `body is not None`.**

Reasoning:

- **Plugins that need to rewrite the body have to know the
  whole shape anyway.** Rewriting a model name, redacting PII
  from `messages`, or normalising tool definitions all involve
  parsing the JSON, mutating it, and re-serialising it. A
  whole-body replace gives the plugin a clean canvas without
  the framework imposing structure.
- **Patch (option iii) is impractical at this layer.** The
  request bodies are JSON for Anthropic Messages today, but the
  framework's adapter abstraction (design.md §6.4) means the
  body shape may differ for OpenAI / Gemini later. A
  structured-patch contract would either lock the SDK to JSON
  or expose multiple patch dialects per provider; both bad.
- **Disallowing body changes (option ii) cripples the most
  important compliance use cases**, e.g. scrubbing PII from
  user messages before they leave the machine. That's exactly
  the kind of plugin Mode A / Mode R operators will want.
- **`body is None` means "don't touch the body"**, so a plugin
  that only wants to add a header doesn't have to rebuild the
  body it didn't change.

## Sub-decision 3: Multi-plugin policy

### Options

- **(i) Chain in order.** Each plugin sees the prior plugin's
  Transform output; the forwarder applies the cumulative
  result.
- **(ii) First-wins.** The first plugin that returns a
  non-`Pass` result is applied; subsequent plugins are not
  called for that hook invocation.

### Decision

**Option (ii) — first-wins.**

Reasoning:

- **Consistent with the existing `Block` semantics.** The
  dispatcher already short-circuits on the first `Block`;
  treating `Transform` the same way means the dispatcher's
  rule is just "first non-`Pass` decides".
- **Chaining (option i) creates non-local interactions between
  plugins** that are hard to debug. Plugin A redacts a field;
  plugin B, written separately, still expects the field to be
  there. Errors surface only when both are installed in the
  same order — exactly the kind of fragile dependency the
  plugin model is supposed to avoid.
- **First-wins is the right default; chaining can be added
  later if a real use case appears.** Reversing the choice
  (going from first-wins to chaining) is mechanical and
  backward-compatible: a single-plugin world looks the same
  under both rules.

## Implementation contract

`forwarder.py::forward_request`, in the `before_forward`
branch:

```python
result = await plugin_host.before_forward(exchange_id)
if isinstance(result, Block):
    ... # existing path
elif isinstance(result, Transform):
    if result.headers is not None:
        headers.update(result.headers)  # plugin wins on conflict
    if result.body is not None:
        body = result.body
```

`PluginHost.before_forward` already returns the first
`Transform` it encounters and ignores subsequent plugins —
first-wins is already the dispatcher's behaviour for this
hook. Verify in tests; no host-side change required by this
ADR.

## Consequences

### What this enables

- Plugins can inject headers (auditing, tracing, tagging) and
  rewrite request bodies (PII scrubbing, model rewriting,
  tool-definition normalisation) before the proxy forwards
  upstream.
- The forwarder's contract is small enough to test exhaustively
  (header merge, header conflict, body replace, header-only
  Transform, multi-plugin first-wins).

### What this constrains

- Plugins authoring conflicting Transforms get undefined
  cross-plugin behaviour relative to install order; the
  framework's stance is "use one Transform plugin per slot, or
  expect first-wins".
- Body replacement is unstructured. A plugin that breaks the
  Anthropic JSON shape will produce an upstream 400; the
  forwarder will not attempt to validate. Same blast-radius
  contract as today's Block path.

### Reversibility

Medium. Switching to chaining later is mechanical (loop
through Transforms instead of returning the first). Switching
header policy from merge to replace would force every existing
Transform plugin to enumerate every header the request needs;
breaking but trivially detectable in tests.

## Open questions

- **Does the SDK want a separate `request_id` slot in
  `Transform` for echoing the exchange_id back into headers?**
  Out of scope for this ADR; addressed when a real plugin
  motivates it.
- **Is there ever a Transform on `on_request_received` (before
  the request is even read)?** The current SDK puts Transform
  only on `before_forward`; that's the right place — see
  design.md §6.3.2.
