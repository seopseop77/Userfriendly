# ADR-0016 · `LLMTRACK_USER_OPTED_IN` env knob (interim consent surface)

- **Status**: Accepted
- **Date**: 2026-05-07
- **Author**: Claude Code (user-approved in chat)
- **Related**: ADR-0006 (modes + content levels — Open question on opt-in
  UX), ADR-0007 (supabase_sink as the first plugin that actually depends
  on opt-in), ADR-0012 (`HookContext.user_opted_in`),
  `docs/design.md §7 (content levels L0–L3)`,
  `docs/roadmap.md` Phase 2 ("User consent flow (per-task opt-in in Mode R)"),
  CLAUDE.md §10 (env vars are public-interface)

## Context

In Mode R, `effective_ceiling` lifts to L3 only when the per-exchange
`HookContext.user_opted_in` flag is True (see
`packages/llm_tracker_sdk/src/llm_tracker_sdk/levels.py`). Today nothing
sets that flag — `PluginHost.begin_exchange` defaults it to `False` and the
forwarder doesn't pass anything in. ADR-0006 §"Open questions" leaves the
real consent UX (CLI prompt vs. separate tool, per-task scope) explicitly
unresolved, and `roadmap.md` schedules it for Phase 2 alongside the
supabase_sink plugin.

The Phase-2 reference plugin `supabase_sink` is being brought forward (per
the worklog dated 2026-05-07), and it cannot exfiltrate prompt or response
text without the ceiling lifting to ≥L2. So *some* path to set
`user_opted_in=True` has to ship before that plugin ships. Two questions to
answer:

1. Do we build the per-task consent UX now, or defer it to its own work?
2. If we defer, what's the *minimum* surface that lets a real Mode-R deploy
   exercise the supabase_sink end-to-end without conflating the two
   workstreams?

## Options considered

1. **Hardcode `user_opted_in=True` whenever Mode is R.** Treat Mode R as
   intrinsically opted-in.
   - Pro: zero new surface.
   - Con: collapses two distinct decisions into one (mode is operator-set,
     opt-in is user-set; ADR-0006 §"Three deployment modes" + §"Content
     level downgrade" treats them as orthogonal axes). An operator who
     boots Mode R for *metadata* analytics would silently leak prompt
     content. Violates ADR-0006's "explicit, never default" axiom.

2. **Build the per-task consent UX now.** Add an interactive CLI prompt or
   per-task signed token that lifts the ceiling for the lifetime of one
   task.
   - Pro: ships the real Phase-2 deliverable.
   - Con: large surface in its own right (CLI ergonomics, signed-token
     schema, task-scope grouping — ADR-0006 §Open questions §3 explicitly
     calls this out as needing its own design pass). Bundling it with the
     supabase_sink work doubles the scope and prevents shipping either
     piece independently.

3. **Process-wide `LLMTRACK_USER_OPTED_IN` env flag.** A boolean env var
   the operator (in this Phase-2-early window: also the user) sets when
   starting the proxy. Default `False`. The flag flows from `Settings` →
   `PluginHost` → every `HookContext` produced for the lifetime of the
   proxy.
   - Pro: tiny surface, explicit, easy to test, easy to *remove* once the
     real per-task UX lands. Honours ADR-0006's "off by default" axiom
     (operator must take an action). Symmetric with the existing
     `LLMTRACK_MODE` knob (process-wide, fixed-at-startup).
   - Con: process-wide consent ≠ per-task consent. An operator who sets
     this and runs Claude Code through the proxy is effectively saying "I
     consent to everything that flows through this proxy session." That's
     fine for the local-research use case the supabase_sink targets but
     not enough for the multi-user / multi-task scenarios Phase 2's full
     consent flow will eventually serve.

## Decision

**Pick option (3) — `LLMTRACK_USER_OPTED_IN` env flag.** Three core reasons:

- **Smallest surface that unblocks supabase_sink.** One field on
  `Settings`, one constructor argument on `PluginHost`, one assignment in
  `begin_exchange`. No new CLI surface, no new file, no new ADR axis.
- **Consent stays explicit.** Default is `False`. Booting the proxy and
  running supabase_sink with the wrong env results in `request_text()` /
  `response_text()` returning `None` (per the L0 ceiling), which the
  plugin observes and skips — no silent data leak.
- **Reversible without API churn.** When the per-task UX lands (its own
  ADR), the env flag either becomes a per-task default override or is
  removed; either path is a one-line `Settings` deletion plus an env var
  deprecation note. No plugin code changes.

### Surface

```bash
# Default (off): ceiling stays at the mode default (L1 in Mode R)
LLMTRACK_MODE=R llm-tracker start

# Opt in process-wide (lifts ceiling to L3 in Mode R only)
LLMTRACK_MODE=R LLMTRACK_USER_OPTED_IN=1 llm-tracker start
```

The env value is parsed by pydantic-settings' default boolean coercion
(`1`/`true`/`yes` → True; everything else → False). Interaction with
`LLMTRACK_MODE`:

| Mode | `LLMTRACK_USER_OPTED_IN` | Effective ceiling |
|---|---|---|
| L | (any)        | L0 (mode override; opt-in is irrelevant) |
| A | (any)        | L0 (mode override; opt-in is irrelevant) |
| R | unset / 0    | L1 |
| R | 1            | L3 |

The L/A rows match the existing `effective_ceiling` matrix; this ADR adds
no new policy, only the operator-facing knob.

### Plumbing

Per the supabase_sink plan and critic review, `user_opted_in` is held as a
**`PluginHost` startup-time field** (parallel to `mode`):

```python
class Settings(BaseSettings):
    ...
    user_opted_in: bool = False
    model_config = {"env_prefix": "LLMTRACK_"}
```

```python
class PluginHost:
    def __init__(self, *, mode: str, user_opted_in: bool = False, ...):
        self._mode = mode
        self._user_opted_in = user_opted_in
        ...

    def begin_exchange(self, exchange_id: str, *, request_body: bytes | None) -> HookContext:
        ctx = HookContext(
            ...,
            mode=self._mode,
            user_opted_in=self._user_opted_in,
            _raw_request_body=request_body,
        )
        ...
```

The forwarder is *not* touched; it doesn't need to know about consent.

## Consequences

### What this enables

- The supabase_sink plugin can be shipped, tested end-to-end, and run
  manually against a real Supabase project without conflating its work
  with the consent-UX design pass.
- Tests exercising L2/L3 plugin paths now have a deterministic, env-driven
  way to set up the ceiling.
- The pattern (mode-orthogonal, fixed-at-startup, env-driven) is a
  precedent for future "operator stance" knobs without needing per-knob
  ADRs.

### What this constrains / forecloses

- Operators who run multi-tenant or shared proxies must not enable this
  flag without acknowledging that *every* exchange in the proxy session
  inherits the opted-in stance. The README/docs for supabase_sink will
  spell this out; deferring to a real per-task UX is the long-term fix.
- The flag is fixed at startup. Toggling consent mid-session requires
  proxy restart. This matches the existing `mode` discipline (ADR-0006
  §"Three deployment modes" — "Mode is fixed at startup").

### Reversibility

High. The flag is one field on `Settings`, one constructor argument on
`PluginHost`. When the real per-task consent UX lands, this env var
becomes either a default override or a removal; either way, no plugin
code changes (plugins read `ctx.user_opted_in`, not the env directly).

## Open questions

- **Per-task consent UX** — design deferred to ADR-0006's existing open
  question §3. Likely shape: a CLI prompt at task boundary, a signed
  task token threaded through HTTP headers, or a sidecar consent service.
  This ADR makes no commitment.
- **Audit-log signal for opt-in state.** Currently nothing audit-logs the
  opt-in stance. A future ADR could add `proxy_started` payload fields
  capturing `(mode, user_opted_in)` so the audit log answers "what was
  the consent stance during this exchange". Out of scope here.
