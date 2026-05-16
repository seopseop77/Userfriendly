# ADR-0029 · Consent + data-handling policy

- **Status**: Accepted
- **Date**: 2026-05-17
- **Author**: Claude Cowork (decisions) / Claude Code (drafting)
- **Related**: ADR-0017 (central server pivot), ADR-0018 (RLS multi-tenancy),
  ADR-0020 (per-org token + Anthropic credential pass-through),
  ADR-0026 (HookContext response accessors), ADR-0028 (faithful response
  reassembly), STATUS.md "Phase 3a — decision ADR queue" item #2,
  `docs/worklog/2026-05-17-adr-0029-consent.md`.
- **Settles**: Phase 3a queue item #2 ("Consent + data-handling policy").

## Context

After ADR-0017's pivot to a central server, every request through
`llm-tracker-server.fly.dev` writes one row to `public.exchanges`, and the
`analytics_sink` plugin (CP shipped in the 2026-05-14 + 2026-05-16 workstream)
writes one row to `public.plugin_analytics` carrying the parsed request body
in `messages_json` and the parsed Anthropic response in `response_json`.
ADR-0028 strengthened that storage contract to faithful reassembly, so today
`response_json` carries the model's full output (text blocks, thinking blocks
with signatures, tool_use blocks with parsed `input` dicts).

This is far past the threshold at which "store everything, decide later"
needs an explicit consent + data-handling policy. STATUS.md has flagged the
gap since 2026-05-11: **"#2 consent + data-handling: still owed before any
external testing of the central server"**. The 2026-05-16 operator-smoke
closure ("smoke gate closed; next blocking item is ADR-#2") moved this from
queued to immediate.

Six interlocking questions need a single coherent answer:

1. **What does the server collect?** Full bodies, or some scrubbed subset?
2. **How is collection disclosed to end users?** Code-level consent gate, or
   documentation only?
3. **How long is data retained?** Indefinite, time-bounded, or per-user?
4. **How are deletion requests serviced?** API surface, or operator-handled
   out-of-band?
5. **What kinds of secrets / PII are scrubbed from the plugin-visible
   data?** And where in the pipeline does scrubbing run?
6. **At what level of the architecture does the scrubber sit?** Storage
   layer, plugin layer, or accessor layer?

The user-driven interview produced binding decisions on all six. This ADR
records them, the trade-offs considered, and the implementation that ships
with it.

## Decisions (one axis per question)

### Axis 1 — Collection scope: full storage

**Operate at full L3 fidelity by default.** The central server stores the
parsed system prompt, the parsed messages array, and the faithfully
reassembled response under `analytics_sink`. The plugin-level toggle
(`LLMTRACK_PLUGINS_DISABLED`, ADR-0013) remains the operator's off-switch --
disabling `analytics_sink` stops the per-exchange write to
`plugin_analytics` while the per-request audit row in `public.exchanges` is
unchanged.

Rationale: the project's purpose (per CLAUDE.md §1) is a *tracker*. A
scrubbed-only collection mode would foreclose the analyses that motivated
the build (drift detection, scope-guard evaluation, latency vs. token-count
investigation), and the L0/L1/L2/L3 ladder already exists for plugins that
want narrower views. Storage stays L3; per-plugin `min_content_level`
manifest clamps (ADR-0019 / CP10) are how a plugin opts down.

Forecloses: "we never had the prompt" is no longer a defensive posture
available to the operator. The privacy posture is now policy + scrubbing +
deletion, not absence.

### Axis 2 — Disclosure: documentation only

**No code-level consent gate at this stage.** Disclosure lands as a clear
"Data collection & privacy" paragraph in `docs/deploy.md` (operator-facing)
and a one-paragraph note under the `analytics_sink` entry of `docs/plugins.md`.

Rationale: the only client today is the same operator who runs the server
(team/internal use). Adding a per-task consent surface (the path ADR-0016
sketched for the local-sidecar era) would be premature -- it would bake in
a consent UI before the distribution method (hosted vs. self-hosted vs. SDK)
is settled. The decision is reversible: a code-level gate can be added on
top of the same accessor surface without breaking existing plugins.

Revisit trigger: when distribution moves beyond the operator-known team
(hosted SaaS, external pilots), this decision is the first one to re-open.

### Axis 3 — Retention: 6 months

**`public.exchanges` and `public.plugin_analytics` rows are retained for
6 months from `started_at` / `created_at`.** Beyond that window the operator
deletes; the server does not auto-delete in this round.

Rationale: 6 months is long enough to support the planned drift analyses
(month-over-month comparisons, regression hunts) and the immediate
operational uses (latency investigation, post-incident review) without
accumulating an indefinite liability. The policy is stated explicitly so a
future automated-deletion job has a fixed target rather than re-litigating
the duration.

Forecloses: "we kept it longer than 6 months because no one asked us to
delete it" -- the policy is now the answer.

### Axis 4 — Deletion requests: operator-handled manual

**No deletion API surface in this round.** When a deletion request arrives,
the operator runs a parameterised SQL `DELETE FROM public.exchanges WHERE
org_id = $1` (or `WHERE session_id = $2`) through the Supabase MCP
`execute_sql` path. The plugin-side `public.plugin_analytics` rows are
deleted on the same axis.

Rationale: `session_id` is currently hardcoded `"server"` in the forwarder
(noted under the close-out worklog) so per-session deletion is not usefully
distinct from per-org deletion today. Building an API endpoint for a
predicate that does not yet discriminate would lock in a contract before the
underlying identity is real. The fix order is: populate `session_id`
properly first, then surface deletion through a typed endpoint.

Revisit trigger: once a real `session_id` populator lands (queued behind
Phase 3b agent identity work), the deletion endpoint becomes a small, typed
follow-up.

### Axis 5 — PII / secret patterns scrubbed

**Five pattern families are scrubbed from plugin-visible content, regardless
of whether they sit in the request body or echoed back in the response:**

1. `sk-` prefixed tokens (Anthropic / OpenAI API keys; ≥ 8 chars after
   the prefix).
2. `lts_` prefixed tokens (llm-tracker per-org bearer tokens, ADR-0020;
   ≥ 8 chars after the prefix).
3. `Bearer <value>` mentions, case-insensitive (also catches the value
   half of an `Authorization: Bearer <value>` header echoed in body text;
   the `Authorization:` prefix itself is preserved as it is not sensitive).
4. Email addresses (RFC 5322 subset; covers the practical cases that show
   up in user prompts).
5. (Reserved) any pattern already handled by an existing scrubber module.
   The pre-existing `llm_tracker_server.proxy.credential` log-side
   redactor stays where it is (defence-in-depth on log event dicts);
   ADR-0029 explicitly does not unify the two layers.

Replacement tags are kind-tagged so an operator querying historical rows
can grep for what fired: `[REDACTED:secret]`, `[REDACTED:token]`,
`[REDACTED:bearer]`, `[REDACTED:email]`.

Privacy-tilted on ambiguity: word-boundary matches on `\bsk-` will
over-redact substrings like `task-sk-something` where `-` is non-word,
trading false positives for the certainty that a real key is never
forwarded to a plugin. Documented in the scrubber's docstring.

### Axis 6 — Scrubbing location: HookContext accessor

**Scrubbing runs inside `HookContext.request_text()` and
`HookContext.response_content_json()` at the SDK accessor level.** Every
plugin that reads either accessor receives scrubbed content automatically;
plugins cannot opt out, and new plugins inherit the protection on day one.

The raw bytes on `HookContext._raw_request_body` and the parsed response on
`HookContext._parsed_response` are left untouched -- the storage layer
(forwarder → `public.exchanges` + `analytics_sink` → `public.plugin_analytics`)
still keeps the canonical body so the operator can investigate incidents
against the original payload.

Wait -- doesn't this contradict Axis 5 ("scrubbed regardless of where it
sits")? No: Axis 5 names what plugins see; it does *not* say the database
mirrors are scrubbed. Storage is canonical (matching the
faithful-reassembly contract of ADR-0028), the accessor is privacy-floor.
The retention policy in Axis 3 is what bounds the canonical-storage
liability over time.

Rationale: the accessor is the one place every plugin already calls. A
storage-layer scrub would block the operator's "show me the row that
caused the incident" path; a per-plugin scrub would be optional and would
forget the new plugins. The accessor is also where ADR-0026 already
established the public read surface, so adding a transform at the same
seam is structurally minimal.

## Options considered (compact)

For each axis, the rejected alternatives:

- **Axis 1**: scrubbed-only collection (forecloses drift / latency analyses
  that motivate the build); operator-toggled collection scope (overkill --
  the existing plugin-disable env var already exposes the on/off knob).
- **Axis 2**: per-task consent UI now (premature; bakes in a surface before
  distribution model is decided); deferred entirely until distribution
  ships (loses the chance to write the disclosure in plain text once).
- **Axis 3**: 30-day retention (too short for month-over-month drift);
  indefinite (accumulates liability without a stated end-state).
- **Axis 4**: deletion API endpoint now (premise -- `session_id` -- not yet
  real); no deletion mechanism at all (defensible only if storage is
  short-lived, contradicted by Axis 3).
- **Axis 5**: redact only `sk-` (misses every other family; observed
  pattern in real traffic includes the operator's own `lts_` token echoing
  back in `tool_result` blocks); broader heuristic redaction (e.g., long
  base64 strings) -- too prone to chewing through legitimate code blocks.
- **Axis 6**: scrub at storage write (operator loses the canonical body
  needed for incident response); scrub per plugin (forgetting one new
  plugin re-opens the gap); scrub at extractor (would intersperse a
  privacy concern into the SSE parser, which has its own contract under
  ADR-0028).

## Consequences

- **Enables**:
  - The first guarded path through which external (non-team) testing of
    the central server can begin, once the disclosure documentation lands.
  - A single scrub point (`llm_tracker_sdk.scrubbers.scrub`) that every
    future plugin inherits.
  - A stated retention horizon (6 months) the operator can plan automation
    against later.
- **Forecloses**:
  - "We don't store user prompts" is no longer accurate; the project posture
    becomes "we store, scrub at the plugin boundary, retain for 6 months,
    delete on request" -- this needs to be communicated explicitly to any
    new external user.
- **Reversibility**:
  - Axis 1 (storage scope) -- medium. Switching to scrubbed-storage is a
    refactor of the storage write path and a backfill plan for old rows.
  - Axis 2 (disclosure surface) -- high. Adding a code-level consent gate
    is additive on top of the accessor surface.
  - Axis 3 (retention horizon) -- high. The 6-month number is a property
    of a future deletion job, not of any schema.
  - Axis 4 (deletion path) -- high. A typed endpoint can be added on top
    of the existing SQL operation.
  - Axis 5 (scrubber patterns) -- high. Patterns are pure-function lines;
    changes are observable in unit tests.
  - Axis 6 (scrubber location) -- medium. Moving the call site away from
    the accessor is a one-file SDK change, but every plugin would need
    re-verification.

## Open questions

- **Automated retention deletion.** Stated as policy (6 months) but not
  enforced by code. A periodic job that deletes `WHERE started_at < now() -
  interval '6 months'` is a future CP; the policy date this ADR sets is
  what that job will key off.
- **`session_id` populator.** Today `"server"` is hardcoded, making
  per-session deletion equivalent to per-org. The fix is queued behind
  Phase 3b agent identity work; once it lands, the deletion endpoint
  question (Axis 4) can be re-opened with a real predicate.
- **`messages_json` request-side fidelity vs. scrubbing.** The
  `analytics_sink` plugin writes `messages_json` via parsing the request
  body on its own path (not through `ctx.request_text()`). That code path
  still receives the canonical body. The current decision is consistent --
  storage is canonical, accessors are scrubbed -- but it does mean a
  plugin author who reads `messages_json` *from the database* sees the
  same unscrubbed content the operator sees. The privacy floor is at the
  plugin-API boundary, not at the SQL boundary. Documented in
  `docs/plugins.md` so a plugin author querying the table directly is not
  surprised.
- **Cross-locale email patterns.** The RFC 5322 subset covers ASCII
  addresses; internationalised email addresses are not redacted. If real
  traffic surfaces them, a separate ADR amendment.
