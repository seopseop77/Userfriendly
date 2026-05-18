# 2026-05-18 · ADR-0030 — scope_guard plugin design (Proposed)

**Author**: Claude Cowork (decisions captured in user interview) /
Claude Code (drafting)
**Session trigger**: User-driven design pass for Phase 1c — capture
all design decisions for the `scope_guard` plugin into an ADR before
implementation. Brief delivered as nine pre-decided axes + a Known
Limitations list + a Deferred list.
**Related docs**: ADR-0030 (new), ADR-0002 (settled in reframed
form), ADR-0019, ADR-0026, ADR-0027, ADR-0029, ADR-0018, ADR-0015,
ADR-0013, `docs/decisions/TEMPLATE.md`.

## Interpretation

User asked Cowork to (a) state-of-the-project review, (b) draft
ADR-0030 from the supplied brief, (c) identify gaps that need
clarification before sealing, (d) ask if any decisions need user
input. Brief was thorough (nine pre-decided axes + Known Limitations
+ Deferred) but had four genuine ambiguities Cowork surfaced before
drafting:

1. Stage-2 judge said to bypass EgressGuard via the Anthropic SDK —
   inconsistent with the project's security model (no other plugin
   bypasses; EgressGuard's audit trail is the boundary).
2. Decision 5 listed "assistant text responses" in the embedding
   input — measures conversation drift vs user intent; doubles
   third-party data exposure.
3. `scope_alerts` schema was minimal (`max_similarity`, `flagged`) —
   loses Stage-2 verdict, reason, and matched chunk for threshold
   tuning.
4. Sending user prompts to OpenAI is a new external-disclosure axis
   not covered by ADR-0029's `docs/deploy.md` paragraph.

User responded "전부 default OK" — Cowork's proposed defaults locked
in. ADR drafted with those defaults plus ten smaller details (chunk
size bounds, idempotent re-registration, regex sentence segmentation
for MVP, etc.) that were missing from the brief and would have
forced re-litigation during implementation.

## Decisions (captured in ADR-0030)

The four operator-confirmed Q1–Q4 answers (all defaults):

- **Q1**: Stage-2 judge uses OpenAI `gpt-4o-mini` via the same
  EgressGuard path as Stage-1 embeddings. Anthropic SDK bypass
  rejected. Single egress vendor, two destinations under one
  manifest allowlist.
- **Q2**: Embedding input is **user-initiated turns only**. No
  assistant text. No top-level Anthropic `system` field. No
  `tool_result` blocks. Minimises both signal noise and the data
  surface sent to OpenAI.
- **Q3**: `scope_alerts` gets four extra columns — `stage`,
  `stage2_verdict`, `stage2_reason`, `matched_chunk_id` — so
  threshold tuning has direct evidence in the table.
- **Q4**: ADR-0030 §Consequences — Disclosure binds in this ADR;
  the actual `docs/deploy.md` edit lands as a separate commit
  alongside the implementation checkpoint.

Plus ten small-detail defaults pinned in the ADR (chunk size 50–500
tokens, regex sentence segmentation for MVP, plain-text + markdown
inputs, idempotent re-registration on `(org_id, title)`,
`idx_scope_chunks_org`, 6-month retention on alerts + indefinite on
operator-curated docs/chunks, settles ADR-0002, etc.).

## What was done

- Created `docs/decisions/0030-scope-guard-plugin.md` (commit
  `27b6d92`). Full design: nine axes options + decisions, schema
  with RLS policy + retention, plugin package layout, six env
  vars, Open questions, Deferred (7 items), Known limitations
  (4 items), implementation surface map for the follow-up session.
- This worklog (committed alongside STATUS update).
- STATUS.md updated below.

## Decisions deliberately not made

Each is recorded as an Open question or Deferred in the ADR rather
than silently chosen:

- Q1 — exact semantic-boundary detection algorithm
- Q2 — pgvector ANN index choice (linear scan in MVP)
- Q3 — whether to extend migration 0009 vs add a new 0011 for
  `scope_alerts` retention
- Q4 — exact Stage-2 prompt template (frozen in `judge.py` at
  implementation time)

## Verification

Documentation only. Verification = reading the ADR and the related
ADR cross-references resolve. A reviewer should:

1. Open ADR-0030 and confirm Status/Context/Decision/Consequences/
   Open questions sections match the brief's nine decisions plus
   Cowork's Q1–Q4 defaults.
2. Confirm the ADR cross-references (ADR-0002, 0019, 0026, 0027,
   0029, 0018, 0015, 0013) are all live ADRs in the project.
3. Confirm the disclosure binding in §Consequences — Disclosure
   does NOT itself edit `docs/deploy.md`; the edit lands with the
   implementation checkpoint, not this ADR.

No tests run, no implementation. The codebase remains at
`703106c` (yesterday's followup-batch round 2 finalize) plus the
two new doc commits in this workstream.

## What's left / known limits

- ADR-0030 is **Proposed**, not Accepted. Operator review pending
  before implementation.
- The disclosure-paragraph edit to `docs/deploy.md` is queued for
  the implementation checkpoint; not done in this workstream.
- Four Open questions in the ADR will surface during implementation
  if they become blocking; otherwise the implementing session
  picks at impl time as the ADR allows.

## Handoff

Next session — Cowork or Claude Code — should treat **operator
acceptance of ADR-0030** as the gate. Once Accepted, the
implementation work has a fixed target:

1. Migration `0010_scope_guard_tables` per ADR-0030 §D8.
2. New package `packages/llm_tracker_plugin_scope_guard/` per §D9.
3. `tools/process_scope_document.py` CLI per §D5.
4. `.env.example` extension with the six new env vars per §D9.
5. `docs/deploy.md §"Data collection & privacy"` paragraph
   extension per §Consequences — Disclosure (binds to ADR-0029).
6. `docs/plugins.md §11` entry for `scope_guard`.

The ADR's §"Implementation surface" lists the file touchpoints so
the implementing session can start without re-deriving them.

If the user requests a follow-up before acceptance — additional
axes, schema changes, threshold-tuning policy — surface as a new
ADR or as an amendment commit on ADR-0030 (still Proposed, so
amendment is cleaner than supersession).

## Suggestions (untouched)

- The repository's `docs/design.md` still describes the
  local-sidecar architecture in places. Cowork did not edit
  design.md in this workstream (brief didn't include it). After
  ADR-0030 lands and the implementation ships, a `design.md` v0.3
  pass against ADR-0017 + ADR-0019 + ADR-0030 is owed — flagged
  here so a future session knows to pick it up.
- `CLAUDE.md §1` still mentions "Mode-aware" as a core principle
  even though ADR-0019 retired the L/A/R modes. The
  `min_content_level` framing replaces it. Worth a one-line edit
  on the next CLAUDE.md touch.
