# 2026-05-11 · Phase 3a decision ADRs (4 of 7 settled)

**Author**: Claude Code
**Session trigger**: User-driven decision interview. The user
requested decisions on Phase-3a ADRs **#5 multi-tenancy**, **#6 mode
taxonomy fate**, **#3 auth model**, and **#7 signing fate**, with
**#1 fallback**, **#2 consent**, and **#4 agent language** explicitly
deferred. Strategic intent: server build-out and demo first; thin
agent (Phase 3b) work intentionally postponed.
**Related docs**: ADR-0017, new ADR-0018 / 0019 / 0020 / 0021,
ADR-0008 (superseded), ADR-0006 (open question closed),
`docs/roadmap.md §Phase 3a`, `docs/STATUS.md`

## Interpretation

The user reframed the Phase-3a priority queue away from the
STATUS.md default ("#1 fallback + #3 auth are most blocking"). Under
the new framing — *get the central server stood up and demo it
first; defer all thin-agent-related decisions* — the four ADRs
decided here are the ones that shape the **server-side database
schema and the request-handling edge**:

- **#5** → server schema (tenancy columns + RLS policies).
- **#6** → server data model (single uniform shape + plugin
  capability surface).
- **#3** → server auth middleware + Anthropic-credential handling.
- **#7** → cleanup of an obsolete primitive before Phase 3c starts.

The four are mutually coherent:

- ADR-0018's per-org tenancy is directly populated by ADR-0020's
  per-org tokens (one auth check at the edge sets `app.org_id`).
- ADR-0020's pass-through removes the need for any server-side
  Anthropic-key storage column under ADR-0018's schema.
- ADR-0019's single-shape storage is the assumption ADR-0018's
  single set of RLS policies depends on.
- ADR-0021's signing retirement clears the deck for Phase 3c by
  removing a primitive whose threat model the pivot eliminated.

## What was done

- Wrote `docs/decisions/0018-multi-tenancy-per-org-rls.md` (#5):
  per-org tenancy boundary with Postgres RLS as the **sole**
  enforcement mechanism; no service-role bypass for ops tooling;
  operator access expressed as RLS-policy branches under an
  `admin` role.
- Wrote `docs/decisions/0019-mode-taxonomy-retired-content-level-kept.md`
  (#6): L/A/R modes fully retired; the L0–L3 content-level ladder
  survives as a plugin-manifest `min_content_level`; single uniform
  server storage shape; no per-user retention differentiation.
- Wrote `docs/decisions/0020-auth-per-org-token-anthropic-passthrough.md`
  (#3): per-org bearer token for agent→server auth; Anthropic
  credential pass-through (server never persists user keys);
  Anthropic-ToS posture maximally safe; zero KMS/Vault build-out
  needed.
- Wrote `docs/decisions/0021-retire-plugin-manifest-signing.md`
  (#7): full retirement of ed25519 signing infrastructure;
  deploy-pipeline-as-trust-root; code removal queued as a separate
  Phase-3c-prep housekeeping checkpoint.
- Updated `docs/decisions/0008-plugin-signing-trust-model.md`
  status line to **Superseded by ADR-0021 (2026-05-11)** with a
  short explanation; the original "What remains deferred"
  subsection is now moot.
- Updated `docs/decisions/0006-egress-policy-and-deployment-modes.md`
  status note to point at ADR-0019 as the ADR that closes its
  "what survives of L/A/R" open question.
- Updated `docs/STATUS.md` per CLAUDE.md §5.3: timestamp; active
  worklog; recent commits; "where we paused"; Phase-3a queue status
  (4/7 done); next single step.
- This worklog.

(All files in this checkpoint share a single commit; hash filled
into STATUS.md and into the eventual commit body. Per CLAUDE.md
§11 this is a documentation-only commit; no code changed.)

## Decisions

The four **substantive** decisions are recorded in the new ADRs and
are not duplicated here. Procedural decisions made during the
interview:

- **Interview order** was set by priority under the user's
  server-first reframe: #5 → #6 → #3 → #7 (DB-schema impact first,
  plugin housekeeping last). The new ADRs reference each other in
  that order; readers should expect to read them in the same order.
- **Documentation-only checkpoint.** The user picked "ADR 4개 작성
  + STATUS/worklog 갱신 (문서만)" — document the decisions but do
  not yet remove signing code or write any Phase-3c code. ADR-0021
  §Consequences enumerates the queued code-removal items.
- **Where my recommendation differed from the user's pick.** For
  ADR-#7 I recommended Option B (repurpose signing as
  deployment-time trust). The user picked Option A (full retirement)
  on YAGNI grounds. The new ADR records Option A as the decision;
  my reasoning is preserved here in case the team grows beyond one
  contributor and the question reopens.

## Verification

Documentation only. Verification = reading the new and updated files
and confirming they say what the interview produced. A reviewer
should:

1. Open ADR-0018 / 0019 / 0020 / 0021 and confirm each ADR's
   **Decision** section matches the user's selection in the
   interview transcript (this conversation).
2. Open ADR-0008 and confirm the Status line is
   **Superseded by ADR-0021 (2026-05-11)** with a brief note.
3. Open ADR-0006 and confirm the existing supersession note now
   also points at ADR-0019 as the ADR that closes its open
   question.
4. Open `docs/STATUS.md` and confirm:
   - Last-updated timestamp is 2026-05-11.
   - Active worklog points here.
   - Phase-3a queue shows 4/7 decided with ADR cross-references.
   - Next single step reflects the user's server-first intent.
5. Confirm cross-references resolve: every new ADR's "Related"
   line points at real files; ADR-0017 §Open questions still reads
   as the originating queue.

No tests run, no code changed. The codebase remains at commit
8d4422b (Phase-1b loose-ends CP2 closed).

## What's left / known limits

**Phase-3a queue status**:

- **Settled**: #5 (ADR-0018), #6 (ADR-0019), #3 (ADR-0020),
  #7 (ADR-0021).
- **Remaining**: #1 fallback policy, #2 consent + data handling,
  #4 agent language/distribution.
- **#2 consent** is the most blocking remaining item *before any
  external testing* of the central server. Operator-only demo is
  not blocked.
- **#1 fallback** and **#4 agent language** only block Phase 3b
  (thin agent). The user intentionally deferred Phase 3b until
  after a working server-build-out demo, so these are no longer on
  the critical path.

**Follow-ups created by this checkpoint**:

- **ADR-0021 code-removal checkpoint.** Delete the signing module,
  CLI commands, registry, and `.sig` files per ADR-0021
  §Consequences. Self-contained; can land before or alongside
  Phase 3c kick-off.
- **ADR-0019 follow-ups.** `min_content_level` manifest field +
  validator + host enforcement (was Phase-1c work; now lands in
  Phase 3c). Phase-1c scrubber primitives also reframed
  server-side.
- **ADR-0018 follow-ups.** `org_members` table + role taxonomy;
  cross-org admin scope; cross-org analytics surface (Phase 3d).
- **ADR-0020 follow-ups.** Header convention for the pass-through
  credential; token issuance UX; rate-limit error mapping.

## Handoff

The next session can pick one of three forward paths:

1. **ADR-0021 code-removal housekeeping** — small, self-contained,
   clears the deck before Phase 3c. Delete signing module / CLI /
   registry / `.sig` files; update `docs/plugins.md`; add a test
   that confirms plugin loading still works without signing.
2. **Phase 3c kick-off planning** — larger; a `ralplan`-style
   consensus plan that breaks down the server build-out into
   commit-sized checkpoints, anchored on ADR-0018 / 0019 / 0020.
3. **ADR-#2 consent decision** — the remaining most-blocking
   Phase-3a item before any external demo. Requires legal/privacy
   input that the user has signalled is not yet sourced.

**Suggested order**: 1 → 2 → 3. Code-removal first frees Phase 3c
from carrying dead code; #2 can run in parallel with Phase 3c
since the demo has no external testers.

Codebase remains at commit 8d4422b. Any Claude Code session resumed
by reading STATUS today should stop and read this worklog before
touching code — Phase 3a is mid-flight, not Phase 3c.

## Suggestions (untouched)

- The original ADR-0008 "What remains deferred" subsection (boot-
  time cache, key rotation, revocation mechanism) is moot under
  ADR-0021's full retirement. Those bullet points will be removed
  when the code-removal checkpoint lands; left in place here so a
  future reader of ADR-0008's history isn't confused by their
  apparent abandonment.
- `docs/design.md` body still describes the local-sidecar
  architecture and was not touched by this workstream or the pivot
  one. Once Phase 3c is underway and the server data model is
  concrete, `design.md` needs a v0.3 layered on top.
- The `supabase_sink` plugin's framing changes again with
  ADR-0021's signing retirement — its `.sig` file disappears as
  part of the code-removal checkpoint. The plugin itself remains
  valid as a server-side analytics output.
- ADR-0017 §Open questions list is not edited here; resolved items
  are tracked via the new ADRs' back-references plus this
  worklog's "Settled / Remaining" split. If the project later
  prefers to annotate ADR-0017 inline with "Resolved by ADR-NNNN"
  notes per item, that's a one-edit follow-up, but not done here
  to keep sealed ADRs sealed.
