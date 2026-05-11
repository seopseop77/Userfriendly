# 2026-05-11 · Architectural pivot — central server deployment

**Author**: Claude Cowork
**Session trigger**: User-driven direction change. Brief delivered as
a structured prompt: switch the project from a local-sidecar
deployment to a team-operated central server with a thin local
agent; document only, no code yet.
**Related docs**: ADR-0017 (new), ADR-0001/0006/0007 (superseded),
docs/design.md, docs/roadmap.md, docs/STATUS.md

## Important: this is a direction change, not a code change

No source code is modified in this workstream. All deliverables are
documents: one new ADR, supersession notes on three existing ADRs, a
roadmap rewrite, and this worklog + STATUS update. The project's
existing local-sidecar code (`packages/llm_tracker/`,
`packages/llm_tracker_sdk/`, plugin packages, `packages/llm_tracker_server/`)
is **left untouched**. ADR-0017 §Reversibility argues most of that
code is reusable on the server-side, but the migration itself is
Phase-3a/3c work and not started here.

## Interpretation

The user's brief was explicit. Each step had a clear deliverable; the
only judgement calls were:

- **Where to insert the new ADR.** Next available number = 0017
  (existing ADRs are 0001–0016).
- **How aggressively to supersede ADR-0001.** The brief said
  "supersede"; ADR-0001 is primarily about Python+FastAPI+httpx, with
  "local sidecar" appearing as the deployment-shape framing. The
  status note records this as a *partial* supersession — stack choice
  preserved, deployment shape invalidated — and surfaces the
  local-agent language as an explicit ADR-0017 open question. Flagged
  to the user in chat.
- **What to do with the L/A/R taxonomy, EgressGuard, content-level
  ladder, manifest signing.** All have their *premise* changed by the
  pivot. The brief explicitly forbade making new decisions beyond the
  five enumerated; everything else surfaces as an ADR-0017 open
  question. ADR-0006 (modes) is marked superseded outright because
  its premise — local trust boundary — is no longer the trust model.
  ADR-0008 (signing) is *not* superseded by this workstream because
  its primitive may yet be re-purposed; that re-purposing is itself
  an open question.

## What was done

- Created `docs/decisions/0017-central-server-deployment-model.md` —
  formal adoption of the central server deployment model with three
  explicit context drivers (plugin tamper surface, local inference
  cost, operational simplicity), the four-part Decision per the
  brief, full Consequences section, and seven Open questions
  (fallback policy, consent/data handling, auth model, agent
  language, multi-tenancy, mode-taxonomy fate, signing-model fate).
  Commit f74710f.
- Updated `docs/decisions/0001-python-fastapi-httpx.md` — Status
  line replaced with a "Partially superseded by ADR-0017" note that
  preserves the Python+FastAPI+httpx choice for the central server
  while invalidating the local-sidecar framing. Related links
  appended. Commit 87142f9.
- Updated `docs/decisions/0006-egress-policy-and-deployment-modes.md`
  — Status line replaced with "Superseded by ADR-0017". The
  egress-off-by-default premise is gone; L/A/R taxonomy parked as
  ADR-0017 open question. Commit 87142f9.
- Updated `docs/decisions/0007-central-server-as-optional-plugin.md`
  — Status line replaced with "Superseded by ADR-0017". The
  optional-plugin framing is inverted; the Supabase-receiver pattern
  remains usable server-side. Commit 87142f9.
- Rewrote `docs/roadmap.md` — top-of-file pivot note; existing
  Phase 0/1a/1b/1c/2 entries preserved as record-of-built work with
  per-item annotations where ADR-0017 invalidates a premise; new
  Phase 3 (Central server build-out) added with four sub-phases:
  3a decision ADRs (seven items), 3b thin local agent, 3c server
  build-out, 3d carry-overs from old Phase 3. Commit 8a47b2f.
- This worklog + a STATUS update (this commit).

## Decisions

- The new ADR is **0017**, not 0005 (which was the user's textual
  reference last time we received a brief with a wrong number). No
  ambiguity in this case because every ADR slot 0001–0016 is
  occupied; only 0017 is free.
- Per the brief's explicit constraint, no additional architectural
  decisions were made. Everything that the pivot touches but the
  brief didn't pre-decide is logged as an Open question in
  ADR-0017, not silently chosen.

## Verification

This workstream is documentation only. Verification = reading the
new and updated files and checking they say what the brief required.
A reviewer should:

1. Open ADR-0017 and confirm Status / Context / Decision /
   Consequences / Open questions sections match the brief.
2. Open ADR-0001, 0006, 0007 and confirm each carries a supersession
   note pointing at ADR-0017.
3. Open `docs/roadmap.md` and confirm the pivot note + Phase 3
   appear, and existing phases are annotated rather than rewritten.
4. Open `docs/STATUS.md` and confirm the active workstream now
   reflects this pivot.

No tests run, no lint, no implementation. Status of the codebase is
unchanged from commit 2a21f4d (`supabase-sink: CP9 manual e2e
shipped`).

## What's left / known limits

The pivot creates real follow-up work, but none of it is owed by
this workstream:

- Seven Phase-3a decision ADRs (fallback policy, consent + data
  handling, agent auth, agent language/distribution, multi-tenancy,
  mode fate, signing fate). Roadmap lists them.
- Migrate existing proxy code to a server deployment shape (Phase
  3c).
- Build the thin local agent (Phase 3b).
- Resolve what happens to the supabase_sink plugin in the
  server-side world — it stops being a Mode-R *opt-in sink* and
  becomes either a server-side analytics output or an enterprise
  self-hosted plugin pattern. Touched in roadmap §Phase 2 but not
  decided here.

## Handoff

The next session — whether Cowork or Claude Code — should treat
**Phase 3a decision ADRs** as the work queue. They gate the actual
build-out: nothing in Phase 3b/3c can be designed concretely until
the fallback policy and auth model are settled, and nothing should
launch until consent + data-handling is decided. The roadmap lists
seven candidates; the user will likely want to prioritise them in a
short planning interview (which two are most blocking? which can be
delegated to legal/privacy review and run in parallel?).

The codebase remains in the state it was at commit 2a21f4d. Any
Claude Code session resumed by reading STATUS today should
explicitly stop and re-orient before touching code — STATUS now
points at a documentation workstream, not the supabase_sink one.

## Suggestions (untouched)

- The `docs/design.md` body still describes the local-sidecar
  architecture (§4 principles, §6 architecture, §7 security model,
  §8 modes) and was *not* edited as part of this workstream — the
  brief did not include it. Once the Phase-3a decision ADRs land,
  design.md will need a rewrite or a v0.3 layered on top. Flagged
  here so a future session knows to handle it then.
- ADR-0008 (signing) is *not* superseded by this workstream because
  its primitive may yet be re-purposed (developer-to-deployment
  signing). Whichever Phase-3a decision settles the new threat
  model will tell us whether to supersede or amend it.
- The `supabase_sink` plugin shipped in Phase 2 partial is still
  installed and signed. It is not removed by this pivot, but its
  framing changes; whoever designs the server-side analytics output
  should decide whether to keep it as-is, move it server-side, or
  replace it with a direct server-side write.
