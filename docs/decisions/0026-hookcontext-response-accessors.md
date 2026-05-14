# ADR-0026 · HookContext response accessors (Option B prerequisite)

- **Status**: Accepted
- **Date**: 2026-05-14
- **Author**: Claude Cowork (decision) / Claude Code (drafting)
- **Related**: ADR-0012 (HookContext shape — request-side accessors),
  ADR-0017 (central server deployment model),
  STATUS.md Phase 1c prerequisites ("response-side `ctx` accessors"),
  `docs/worklog/2026-05-14-plugin-ecosystem.md`
- **Amends**: ADR-0012 (extends the same dataclass with read-only response-side
  fields and accessors)

## Context

Phase 3c CP14 follow-up Option B introduces an SSE Extractor on the central
server that parses the upstream Anthropic response stream into structured data:
`model_served`, `input_tokens`, `output_tokens`, `cache_read_tokens`,
`cache_write_tokens`, `stop_reason`, and the full assembled response body as a
JSON string.

Plugins that run on `on_persisted` (analytics sinks, downstream uploaders, drift
detectors) need access to that data. ADR-0012 ships only request-side accessors
on `HookContext`; the queued response-side accessors were deferred under
STATUS.md "Phase 1c prerequisites" pending the Extractor.

Two architectural options for surfacing the parsed response to plugins:

- **A. Each plugin parses SSE chunks itself in `on_response_chunk`**. Duplicates
  parsing logic across every plugin that wants response data, makes the parsing
  budget N× larger than necessary, and forces plugin authors to track Anthropic
  SSE schema changes individually.
- **B. The core parses the SSE stream once, stores the structured result on
  `HookContext`, plugins read via accessors**. Single source of truth; plugin
  authors get a typed handle rather than a byte stream; parsing changes land in
  one place.

`HookContext` is a public interface (CLAUDE.md §9), so the choice — and the
exact shape of the new field and accessors — is an ADR-level decision rather
than an implementation detail.

## Options considered

1. **Option A** — Per-plugin SSE parsing. Pros: no SDK change. Cons: N× parse
   cost; N× maintenance surface as Anthropic adds event types; plugin authors
   forced to learn the Extractor protocol; harder to reason about plugin order
   (the parser stays per-plugin, so on_response_complete ordering matters).
2. **Option B** — Single core parse + accessors. Pros: O(1) parse cost;
   `HookContext` is the canonical place plugins already read from; new plugins
   pick this up free. Cons: SDK minor version bump; one more field on a public
   dataclass.
3. **Option C** — Emit parsed records as `events` rows the plugin queries from
   the database. Pros: most decoupled. Cons: round-trip via Postgres on every
   exchange; the plugin would block on DB I/O it does not strictly need; on
   `on_persisted` the events row write itself is downstream of the SSE parse,
   so a DB-readback pattern at this hook would race or require an explicit
   barrier.

## Decision

**Pick Option B — single core parse with read-only accessors on `HookContext`.**

Three reasons:

1. **Single source of truth.** The Anthropic event grammar is owned by the
   `extractors/anthropic.py` module on the server; plugins read structured
   data without ever touching SSE bytes. Future Anthropic schema changes land
   in one file.
2. **Cost proportional to traffic, not plugin count.** With N plugins
   interested in response data, Option A multiplies the parse cost by N;
   Option B keeps it at one parse regardless of how many plugins read it.
3. **Mirrors the existing request-side shape from ADR-0012.** Plugins already
   read `ctx.request_text()` / `ctx.request_hash()` / `ctx.request_length()`;
   adding `ctx.response_usage()` / `ctx.response_content_json()` is a
   right-side completion of the same pattern.

### Surface

In `packages/llm_tracker_sdk/src/llm_tracker_sdk/hook_context.py`:

```python
@dataclass
class HookContext:
    ...
    # Set by the server core after SSE parse (forwarder.py's extract_task).
    # Plugins read via the accessors; never assign directly.
    _parsed_response: object | None = field(default=None, repr=False)

    def response_usage(self) -> object | None:
        """Return the parsed ResponseUsage (model_served + token counts + stop_reason),
        or None if the extractor has not run yet or produced no usage data.
        """
        return self._parsed_response.usage if self._parsed_response is not None else None

    def response_content_json(self) -> str | None:
        """Return the assembled response as a JSON string, or None if the
        extractor has not run yet.
        """
        return (
            self._parsed_response.response_json
            if self._parsed_response is not None
            else None
        )
```

The field is typed `object | None` (not `ParsedResponse | None`) deliberately:
the `ParsedResponse` / `ResponseUsage` dataclasses live in
`llm_tracker_server.extractors.anthropic` so the SDK does not import from the
server package. Plugins that want type-checking can `cast(ResponseUsage, ...)`
or import the server-side dataclass under `if TYPE_CHECKING:`.

A small additional SDK change rides under this ADR: `HookContext` also gains
`org_id: uuid.UUID | None = None`. The forwarder sets it inside
`begin_exchange`; plugins that write to org-scoped tables (e.g. the new
`analytics_sink`) read it to populate their own `org_id` columns under the same
RLS axis the server already enforces (ADR-0018).

### Non-goals

- **Streaming/partial response accessors.** `response_content_json()` returns
  the *fully assembled* response after the stream completes. Plugins that want
  to react to chunks individually still use `on_response_chunk` with raw bytes.
- **Typed access to nested content blocks.** The accessor returns a JSON
  string. Plugins that want structured content parse it themselves (one JSON
  parse per plugin is acceptable; SSE parse cost is what Option B saves).

## Consequences

- **Enables**: the `analytics_sink` plugin and any future plugin that wants the
  parsed response without re-parsing SSE bytes. Closes STATUS.md "response-side
  `ctx` accessors" bullet from Phase 1c prerequisites.
- **Forecloses**: nothing that was previously possible — the accessors return
  `None` when the extractor has not run, so existing plugins that ignore them
  are unaffected.
- **Reversibility**: high. The accessors are read-only; the field is private.
  Reverting Option B is a single-file edit on the SDK + removing the extractor
  wire-up in the forwarder.
- **SDK version**: minor bump (`0.0.1` → `0.1.0`) is owed when the SDK package
  next publishes. The package is workspace-local today so this is a doc-only
  consequence until distribution starts.

## Open questions

- **Response-side level degradation.** ADR-0012 made request accessors honour
  the per-plugin `_ceiling` (manifest-driven L0/L1/L2/L3). The response
  accessors land L3-only this round — the per-plugin ceiling enforcement on
  response data is queued behind the scrubbers (Phase 1c) and will get its own
  ADR if its semantics surface anything non-obvious. Until then, plugins with
  `min_content_level < L3` should not be wired to read response data.
- **Cost cap on `response_content_json`.** A long-form response with cache
  hits can be hundreds of KB. The current accessor returns the full assembled
  payload unconditionally. If we observe a plugin that only wants a tail-end
  summary, a size cap or truncation accessor lands as a separate ADR.

## Settles

ADR-0017 §"Open questions" deferred response-side accessors behind the
Extractor; this ADR closes that question for the L3 case. The scrubber-aware
shape stays open under Phase 1c.
