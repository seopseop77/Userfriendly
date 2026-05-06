# ADR-0010 · `Block` and `Abort` carry an optional `plugin` field

- **Status**: Accepted (retroactive — code landed in commit b1724fa as
  part of Phase 1b checkpoint 10)
- **Date**: 2026-05-06
- **Author**: Claude Code (user-approved retroactive ADR)
- **Related**: ADR-0002 (synthetic SSE block response),
  `docs/worklog/2026-05-05-phase1b-security.md` (checkpoints 10
  and 14), `packages/llm_tracker_sdk/src/llm_tracker_sdk/hooks.py`,
  `packages/llm_tracker/src/llm_tracker/proxy/forwarder.py`,
  CLAUDE.md §10 (hook return values are a public-interface
  contract)

## Context

ADR-0002 §3 mandates that the synthetic block response persists an
`exchanges` row with `blocked_by=<plugin>`. The forwarder is the
component that writes the row, so it needs the blocking plugin's
name. The dispatcher iterates plugins and returns the first
`Block` (or `Abort`); the iteration knows which plugin produced
the result, but the result type itself did not carry that
information.

Three implementation routes were considered while landing
checkpoint 10:

1. **Per-host transient state** — `PluginHost._last_block_plugin`,
   set during dispatch and read by the forwarder. Concurrency
   risk: two in-flight requests on the same host would race on
   the slot.
2. **Tuple return** — change the dispatcher signatures from
   `Pass | Block` to `Pass | tuple[str, Block]`. Breaks every
   `isinstance(result, Block)` call site (existing tests, the
   forwarder, future plugins observing dispatcher results in
   tests).
3. **Optional field on the dataclass** — add `plugin: str = ""`
   to `Block` and `Abort`. The host sets it before returning;
   plugins ignore it (the default keeps them backward compatible).

CLAUDE.md §10 lists "Hook lifecycle — names, timing, and meaning
of return values for the 8 hooks" as a public-interface contract
requiring an ADR. Adding a field to `Block` and `Abort` modifies
the return-value shape, so this ADR documents the choice that was
already made in code (commit b1724fa) and was subsequently
flagged for retroactive ratification.

## Decision

**Adopt option 3.** `Block` and `Abort` each gain a single field:

```python
@dataclass
class Block:
    reason: str
    plugin: str = ""

@dataclass
class Abort:
    reason: str
    plugin: str = ""
```

The field is **set by the host** before the dispatcher returns:

```python
if isinstance(result, Block):
    result.plugin = plugin.name
    return result
```

Plugins should leave it at the default (`""`); the host
overwrites whatever a plugin happened to put there. A docstring
on each dataclass states this explicitly.

The forwarder reads `result.plugin` to populate
`exchanges.blocked_by` via `record_exchange_blocked`.

## Why option 3

- **No concurrency hazard.** The plugin name travels with the
  result object itself; nothing on the host needs to be mutated
  after dispatch returns.
- **No breaking change.** Existing plugin code that builds
  `Block(reason="…")` keeps compiling and behaving identically.
  The host-set value only affects the host-side audit path.
- **No cascade through dispatcher signatures.** Every existing
  `isinstance(result, Block)` test continues to work without
  edits. Tuple-return would have forced changes across all
  load-plugins / forwarder tests.

## Consequences

### What this enables

- `exchanges.blocked_by` is reliably populated for every
  Block / Abort path in the forwarder.
- Future audit-log enrichments (e.g., recording which plugin
  emitted an Abort mid-stream) get the same affordance for free.

### What this constrains

- Plugin authors will see `plugin` in the dataclass repr and
  type. The docstring nudges them to leave it alone, but a
  malicious or confused plugin could set it; the host
  unconditionally overwrites, so the worst case is "plugin sets
  a value that gets immediately replaced". No security impact.
- The SDK now has one more field to keep stable. Renaming or
  removing it would be a breaking change requiring a follow-up
  ADR.

### Reversibility

High. Reverting is one line per dataclass plus removing the
`result.plugin = plugin.name` assignments in `host.py`. The
forwarder's `_persist_block` would need a different path to
get the plugin name — likely option 1 or 2 from the Context
section.

## Open questions

None. The decision is self-contained.
