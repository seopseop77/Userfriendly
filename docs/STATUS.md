# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-11 (Cowork; architectural pivot to central server documented in ADR-0017 — direction change, no code yet)
**Updated by**: Claude Cowork

## Current phase

- **Phase**: **Architectural pivot in flight (ADR-0017).** The
  project's deployment model is changing from local-sidecar + in-
  process plugins to a **team-operated central server + thin local
  agent**. ADR-0017 is sealed; ADR-0001/0006/0007 are marked
  superseded; `docs/roadmap.md` is rewritten to add a new Phase 3
  (Central server build-out). No source code has been changed —
  the existing codebase at commit 8d4422b (Phase-1b loose-ends
  closed) is left intact pending Phase 3 implementation.
- **Active task**: None in code. Seven **Phase-3a decision ADRs**
  are queued in `docs/roadmap.md §Phase 3a`; they gate any Phase
  3b/3c implementation work.

## Active worklog

`docs/worklog/2026-05-11-central-server-pivot.md` (open; closes with
the STATUS-update commit). Predecessor `docs/worklog/2026-05-09-phase1b-loose-ends.md`
remains closed.

## Recent commits

```
<this>    docs: STATUS + worklog for ADR-0017 pivot
8a47b2f   docs: roadmap reflects central server pivot (ADR-0017)
87142f9   docs: supersede ADR-0001/0006/0007 per ADR-0017
f74710f   docs: ADR-0017 central server deployment model
8d4422b   docs: Phase-1b loose-ends CP2 closed
```

## Where we paused

**Architectural pivot, documentation-only.** ADR-0017 records a
project-level direction change agreed with the user: the deployment
model moves from local-sidecar + in-process plugins to a central
server operated by the team, with users running only a thin local
agent that sets `ANTHROPIC_BASE_URL`. No code has been changed in
this workstream; ADR-0017's §Reversibility argues most of the
existing Phase 0–2-partial code is reusable on the server side, but
the migration itself is Phase-3a/3c work and is not started here.

Three motivations cited in ADR-0017 §Context:

1. **Plugin tamper surface.** ADR-0008 signing only covers the
   manifest; plugin *code* on a user's machine is still
   user-modifiable. Server-side execution eliminates that surface
   structurally.
2. **Local inference cost.** Embedding judge + LLM judge on each
   user's machine duplicates compute; centralising amortises it.
3. **Operational simplicity.** One deployment, one audit trail,
   instant fix cadence.

What the pivot **explicitly costs** (also in ADR-0017
§Consequences): all Claude Code requests/responses traverse the
team's infrastructure (raw user prompts and code visible to the
team); single point of failure; Anthropic ToS exposure as a
proxy intermediary; the egress/mode/content-level system encoded
in ADR-0006 loses its primary justification.

**ADRs touched in this workstream**:

- ADR-0017 (new, Accepted) — central server deployment model.
- ADR-0001 (Python+FastAPI+httpx) — **partially superseded**.
  Stack choice survives for the central server; local-agent
  language is an explicit open question under ADR-0017.
- ADR-0006 (egress + L/A/R modes) — **superseded**. Local trust
  boundary no longer the model; what survives of the mode taxonomy
  is an ADR-0017 open question.
- ADR-0007 (central server as optional plugin) — **superseded**.
  Inverted by ADR-0017: the central server is the core deployment,
  not an optional sink.
- ADR-0008 (manifest signing) — **not superseded**. Original threat
  (user-side tamper) is eliminated structurally, but the primitive
  may be re-purposed as deployment-time trust; ADR-0017 leaves the
  fate open.

**Roadmap rewrite**: existing Phase 0/1a/1b/1c/2 entries preserved
as record-of-built work with per-item annotations where ADR-0017
invalidates a premise. New top-level **Phase 3 — Central server
build-out** added with four sub-phases (3a decision ADRs, 3b thin
local agent, 3c server build-out, 3d carry-overs).

## Phase 3a — decision ADR queue (gates Phase 3b/3c)

Seven ADRs are owed before Phase 3b/3c can be designed concretely.
Listed verbatim from `docs/roadmap.md §3a`:

1. **Fallback policy when server unreachable** — fail-open vs
   fail-closed (ADR-0017 §Open questions; trade-offs documented
   there).
2. **Consent + data-handling policy** — what we collect, retention,
   deletion, lawful basis, user-facing surface. Required before
   launch.
3. **Agent-to-server auth model** — shared org token vs per-user
   token vs OAuth pass-through. Affects Anthropic ToS posture.
4. **Local agent language/distribution** — Python vs Go vs shell
   wrapper. Affects install friction.
5. **Multi-tenancy boundary on the server** — org vs user; RLS vs
   application-level enforcement.
6. **What survives of ADR-0006 L/A/R modes** — possibly recast as
   server-side retention/visibility tiers; or fully retired.
7. **What survives of ADR-0008 signing** — possibly recast as
   developer-to-deployment signing.

Items 1 + 2 are the most blocking. 4 + 6 + 7 can run in parallel.

---

### Prior workstream — `supabase_sink` (closed 2026-05-08, CP9)

ADR-0007's reference Mode-R plugin is operational against the
operator's real Supabase project (7 rows in `public.exchanges` from
Path 1). All three safety paths verified against real traffic in CP9:

- **Path 1 — Happy** (`Mode R` + opted_in + correct manifest):
  7 rows landed; `request_text` / `response_text` / `usage`
  populated as expected; one row has `model_served=null` (HTTP
  error response from Anthropic — non-SSE body — by-design
  observability hole, see CP9 worklog "Observation").
- **Path 2 — Mode L safety**: `capability_denied` at proxy
  startup, plugin never loaded, 0 new rows, `claude` response
  flowed through the proxy normally. Production equivalent of
  `test_e2e_mode_l_rejects_plugin_at_load_time`.
- **Path 3 — Allowlist mismatch**: manifest's `egress_destinations`
  set to a bogus URL → plugin loaded but `EgressGuard` denied
  every fetch with `reason=destination_not_in_allowlist`; 0 new
  rows; 4 `egress_blocked` audit rows; manifest restored +
  re-signed (ed25519 deterministic → byte-identical to CP8).

**Workstream artefacts** (per CLAUDE.md §10 public-interface
catalogue):

- ADR-0015 — `EgressClient` Protocol + `EgressResponse` +
  `EgressDenied`; `BasePlugin.egress` / `HookContext.egress`
  reference the *same* per-plugin instance bound at load time.
- ADR-0016 — `LLMTRACK_USER_OPTED_IN` env knob (interim consent
  surface; per-task UX still deferred per ADR-0006 §"Open
  questions").
- New SDK module: `llm_tracker_sdk.egress`.
- New core module: `llm_tracker.egress_guard.client` (`HostEgressClient`).
- New `PluginHost` constructor params: `http_client`,
  `user_opted_in`. New `SHUTDOWN_HOOK_TIMEOUT` = 30 s for sink
  drain.
- New plugin package: `packages/llm_tracker_plugin_supabase_sink/`
  (signed by `minseop`, 55 unit + 3 integration tests).
- Supabase: `public.exchanges` table + RLS enabled (CP4).
- Operator UX: proxy reads `.env` at lifespan; refreshed
  `.env.example` to match the current `Settings` surface.

Closed-checkpoint roll-up (cleanup pass A–G + stop gates +
side-quests):

- A (e2ee4f0): EgressGuard wired into proxy lifespan
- B (3010aae): signature verifier wired + signing CLI
- C (a2bc3d4): on_persisted ordering fix
- D (b1724fa): synthetic SSE block response
- E (2891e8f): audit_log append-only triggers
- F (6a08c9c): ADR-0008 housekeeping
- G (96305e1): session_factory property + ADR-0009
- 14 (654fbfb): ADR-0010 retroactive (Block/Abort.plugin)
- 15 (cfbbb8e): ADR-0011 Transform policy
- 16 (bbb33e7): Transform impl + 4 tests
- 17 (4606ed0): ADR-0012 hook payload routing
- 18 (75ff46a): HookContext impl + 14 tests
- pre-1c verification (2c28f68): TEST-ONLY token_counter + keyword_block
- side-quest #2 (d2e33d5, 9aa8321): `claude-manage` wrapper + async cleanup
- side-quest #3 (0a43502, 161505d): plugin disable config + `/admin/plugins`
- supabase_sink workstream (8712183, f75a841, dff7e3e, a3b5dff,
  9088825, 6ab979c, 4294d10, f420000, f2f53b7, + this CP9
  finalize commit): ADR-0015/0016 + `EgressClient` SDK +
  `LLMTRACK_USER_OPTED_IN` + Supabase schema + the plugin itself
  + `SHUTDOWN_HOOK_TIMEOUT` + signed manifest + `.env` lifespan
  loader + manual e2e

## Phase 1c prerequisites

These three items are blocked on Phase 1c (scrubber primitives,
`scope_guard`, the Phase-2 Extractor) — not Phase-1b debt. They're
documented here so the next session knows what `scope_guard` and the
Extractor unlock when they land.

- **L2 scrubbed shape of `request_text`**. Today
  `HookContext.request_text(L2)` returns the raw decoded body — same
  bytes as L3. Per design.md §7.1 L2 should be the scrubbed body
  (secrets / PII / paths / emails / IPs removed). The switch needs
  the Phase-1c scrubber primitives. Pinned by
  `test_hook_context.py::test_request_text_returns_body_at_l2_when_ceiling_allows`
  so the eventual change is test-visible.
- **Manifest `min_content_level` field** (ADR-0012 §"Open
  questions"). Plugins should declare the lowest content level they
  can function at; the host can then short-circuit dispatch when the
  effective ceiling is below it. Add this when `scope_guard` becomes
  the first plugin that actually needs it; separate ADR (refines
  ADR-0012).
- **Response-side `ctx` accessors** (`response_text`,
  `tool_call_inputs`, etc.). ADR-0012 ships only the request-side
  accessors. Response-side data needs the Phase-2 Extractor to
  surface structured response records first; separate ADR if the
  semantics surface anything non-obvious (e.g. partial vs assembled).

## Next single step

**Prioritise the Phase 3a decision ADR queue with the user.**
Nothing in Phase 3b (thin agent) or 3c (server build-out) can be
designed concretely until at least the fallback policy and auth
model are settled. A short planning interview should:

- Pick which two of the seven ADRs are most blocking (likely #1
  fallback policy and #3 auth model, since they constrain the
  thin-agent design directly).
- Identify which can be delegated to legal/privacy review and run
  in parallel (#2 consent + data-handling is the obvious one).
- Order the rest into a sequence.

**Phase 1c (`scope_guard`) is paused, not killed.** Reframed: the
embedding/LLM judges run server-side rather than per user machine.
The SDK contract (`BasePlugin`, hook lifecycle, `HookContext`,
`EgressClient`) survives. Re-open the Phase 1c planning interview
*after* the Phase 3a ADRs settle the server-side trust model — the
TaskDefinition issuance flow and judge auth depend on the decisions
queued above.

A Claude Code session resumed by reading STATUS today should
explicitly stop and re-orient before touching code. STATUS now
points at a documentation workstream, not an implementation one.

## Blocking / decisions needed

The seven Phase-3a ADRs above are all blocking for Phase 3
implementation. None blocks further documentation work.

- The user-deferred items from prior workstreams (Phase 1c, Phase 2
  consent UX, manifest HTTPS-only validator) are all subsumed by
  the pivot — they're folded into Phase 3a items 2, 4, 6, 7.

## Progress

- [x] Design v0.1 written
- [x] Framework pivot v0.2
- [x] English-only documentation pass
- [x] ADRs 0001–0008 sealed (0004 superseded by 0007)
- [x] Phase 0 — core skeleton (CLOSED 2026-05-04)
- [x] Phase 1a — plugin SDK (CLOSED 2026-05-05)
- [x] Phase 1b — security boundary hardening (CLOSED 2026-05-06)
- [x] Pre-Phase-1c verification — TEST-ONLY plugins (token_counter, keyword_block) (2026-05-06, commit 2c28f68)
- [x] `claude-manage` wrapper — auto-spawn proxy + lifecycle-coupled cleanup (2026-05-07, commits d2e33d5, 9aa8321)
- [x] Plugin disable config + `/admin/plugins` introspection (2026-05-07, commits 0a43502, 161505d)
- [x] **Phase 2 partial — `supabase_sink` reference plugin (CLOSED 2026-05-08, 9 commits 8712183 → CP9 finalize)**
- [x] **Phase 1b loose-ends (CLOSED 2026-05-09, commits 86acecd / 14b6f7a / 86caf03 / 8d4422b)**
- [x] **Architectural pivot to central server documented (2026-05-11, ADR-0017; commits f74710f / 87142f9 / 8a47b2f + this STATUS commit)**
- [ ] **Phase 3a — seven decision ADRs** (fallback / consent / auth / agent language / multi-tenancy / mode fate / signing fate)
- [ ] Phase 3b — thin local agent (new deliverable per ADR-0017)
- [ ] Phase 3c — server build-out (migrate existing proxy logic + plugins server-side)
- [ ] Phase 1c — `scope_guard` (paused; reframed server-side; gated on Phase 3a outcomes)
- [ ] Phase 3d — carry-overs: OpenAI/Gemini adapters, analytics interface, response-side policy plugins

---

## Update rules (for Claude Code)

At every checkpoint, do these three as one atomic unit (CLAUDE.md §5.3):

1. `git commit` the code change (CLAUDE.md §11).
2. Append the new commit hash to the active worklog's "What was done"
   section, and rewrite the "What's left / Handoff" section as of *now*.
3. Refresh this STATUS.md:
   - Last-updated timestamp (YYYY-MM-DD).
   - Active worklog path.
   - Last 3–5 commits.
   - "Where we paused".
   - "Next single step".

If you don't bundle these three, the next session won't know where to pick
up.
