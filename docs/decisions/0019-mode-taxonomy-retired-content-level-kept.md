# ADR-0019 · L/A/R modes retired; L0–L3 content level survives as plugin capability

- **Status**: Accepted; resolves ADR-0017 §Open questions
  ("What survives of ADR-0006 L/A/R modes")
- **Date**: 2026-05-11
- **Author**: Claude Cowork (user-approved; decision made in the
  2026-05-11 Phase-3a decision interview)
- **Related**: ADR-0006 (superseded by ADR-0017; this ADR closes its
  loose ends), ADR-0017, ADR-0012 (HookContext content-level routing
  — preserved by this ADR), ADR-0018 (single-shape storage assumed),
  `docs/STATUS.md`

## Context

ADR-0006 defined a deployment-mode taxonomy (L = local-only,
A = audit-light, R = research) and a four-rung content-level ladder
(L0 = metadata, L1 = structure, L2 = scrubbed text, L3 = raw text).
The mode controlled what egress was permitted from the user's
machine; the content level controlled how much information each
plugin received.

ADR-0017's central-server pivot invalidated the mode premise. All
traffic now transits the team's infrastructure by design; there is no
longer a "no egress from your machine" mode to honour. ADR-0017
§Open questions left two related decisions:

1. What survives of L/A/R? (Possibly: recast as server-side
   retention/visibility tiers.)
2. Is per-user differentiation needed at all?

This ADR settles both. The companion ADR-0018 already commits to a
single uniform per-org storage shape; that constrains what answers
this ADR can give.

## Options considered

### A. Full retirement of both L/A/R and L0–L3

Retire the mode taxonomy and the content-level ladder entirely.
Server stores raw, plugins all see raw, retention is uniform.

- Pros: simplest data model; plugin host code shrinks; smallest
  surface area.
- Cons: discards the plugin-isolation primitive that L0–L3 provided.
  Future plugin authors (in-house or external) all run with full-raw
  access; "least-privilege per plugin" must be invented from scratch
  later.

### B. Reframe L/A/R as retention tiers + keep L0–L3

Convert L/A/R into "how long / how broadly is the data kept on the
server" tiers, paired with a per-user opt-in choice.

- Pros: gives users explicit retention choice; preserves a
  drift-research path; aligns ADR-0006 semantics with the new trust
  model.
- Cons: triples server data-shape complexity (three persistence
  paths); strongly coupled to the still-undecided ADR-#2 (consent +
  data-handling); designing it now risks needing rework once #2
  lands.

### C. Retire L/A/R; keep L0–L3 as plugin capability (chosen)

Retire the mode taxonomy entirely. Keep the L0–L3 content-level
ladder, repurposed: each plugin declares the minimum content level
it needs in its manifest; the plugin host grants only up to that
level. Server-side storage and retention are uniform (decided in
ADR-#2 consent).

- Pros: preserves plugin isolation at near-zero cost (the routing
  code already exists in HookContext). Simple, uniform data model.
  No per-user differentiation work. Plugin authors can be granted
  "metadata only" or "structure only" without seeing raw prompts.
- Cons: doesn't itself solve "user wants metadata-only retention" —
  but the user has confirmed that problem is empty for now (see
  Decision below).

## Decision

**1) The L/A/R deployment-mode taxonomy is retired.**

The `Mode` enum, mode-aware capability policy, mode-keyed
content-level defaults, and the `LLMTRACK_MODE` env var are removed
during the Phase 3c migration. ADR-0006 was already marked
*superseded* by ADR-0017; this ADR closes its loose ends.

**2) The L0–L3 content level survives as a plugin-level capability.**

The four content levels keep their meaning:

- **L0** — metadata only (timing, model id, token counts, structural
  hashes).
- **L1** — structural data (message boundaries, tool-call shapes), no
  textual content.
- **L2** — scrubbed text (secrets / PII / paths / emails / IPs
  removed; Phase-1c scrubber primitives still owed).
- **L3** — raw text.

Plugins declare a `min_content_level` in their manifest. The
server-side plugin host hands each plugin data degraded to its
declared level via `HookContext`. The
intersection-with-deployment-mode logic from ADR-0006 is removed; the
level a plugin gets is simply the level it asked for, subject to its
manifest having been accepted at deploy time.

**3) Server-side storage is a single uniform shape, per ADR-0018.**

There is **no per-user retention differentiation** in the near term.
Every org's data is stored in the same shape; what that shape is
(raw vs scrubbed) is settled in ADR-#2 (consent + data-handling).
The "user picks tier at install" pattern is explicitly not built.
If a customer ever requests it, it becomes a new ADR — easier to add
to a uniform baseline than to walk back from a multi-shape baseline.

## Consequences

### What this enables

- `HookContext.content_level` routing code (built in Phase 1b) is
  reused server-side without changes.
- Plugin author contract is unchanged: a plugin written for the
  local-sidecar model declares `min_content_level` the same way.
- Server data model is one table per concept
  (`exchanges` / `events` / `tool_calls` / `audit_log`), not three
  retention-tiered shapes.
- Plugin isolation primitive survives: an external-contributor
  plugin (when those exist) can be deployed at L0 or L1 without
  seeing user prompts.

### What this forecloses

- Per-user "metadata-only retention" as a near-term feature. Adding
  it later requires a consent-tier ADR plus a second storage shape.
- The mode-based capability matrix (Mode L denies certain
  capabilities outright). Capability gating in the server-side host
  is now a flat allowlist per plugin; mode-keyed denial logic
  disappears.

### What it constrains

- `min_content_level` semantics in the plugin manifest. ADR-0012
  §Open questions flagged this as Phase-1c work; that work now
  lands in Phase 3c as part of the server-side plugin host.
- Phase-1c scrubber primitives are still owed before L2 has its
  proper meaning. Until they exist, an L2-declaring plugin receives
  the same bytes as L3. Documented in `docs/STATUS.md §Phase 1c
  prerequisites`; carries forward into Phase 3c.

### Reversibility

Medium. Re-introducing modes or per-user tiers later is *additive* —
a new column, a new policy axis — not a breaking schema change. The
hard direction is removing them *after* they've shaped data; the
easy direction is adding them on top of a uniform baseline. This ADR
takes the easy direction.

## Open questions

- **`min_content_level` manifest field.** Add the schema field +
  validator + host enforcement during Phase 3c. Tracked as a
  follow-up to ADR-0012.
- **Scrubber primitives.** Phase-1c work, pre-existing, reframed:
  scrubbers must run server-side rather than per user machine.
  Inherits the test-pinned contract from
  `test_hook_context.py::test_request_text_returns_body_at_l2_when_ceiling_allows`.
- **Cross-org research data.** Aggregate views across orgs (Phase
  3d) belong to ADR-#2 (consent) + Phase 3d, not here.
