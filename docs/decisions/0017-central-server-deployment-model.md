# ADR-0017 · Central server deployment model

- **Status**: Accepted
- **Date**: 2026-05-11
- **Author**: Claude Cowork (user-approved; documents a project-level
  direction change agreed with the user)
- **Related**: ADR-0001 (partially superseded), ADR-0005, ADR-0006
  (superseded), ADR-0007 (superseded), ADR-0008 (signing premise
  changes), `docs/design.md §1–§8`, `docs/roadmap.md`

## Context

Through Phase 0–Phase 2-partial, the project followed the
**framework-first / local-sidecar** model (ADR-0005): every user
installs the full proxy on their machine, plugins run in-process there,
and data stays local unless an explicitly opt-in Mode-R sink ships it
out (ADR-0006, ADR-0007). The architectural pivot recorded here moves
the deployment surface to a **central server operated by the team**;
users install only a thin local agent.

Three concrete forces drive the change:

1. **Plugin tamper surface.** ADR-0008 introduced manifest signing to
   detect operator tampering with `plugin.toml`. The signature covers
   the manifest only — plugin *code* on a user's machine is still
   modifiable by that user. As long as plugins execute on user machines,
   any capability-grant model can be circumvented by editing the
   installed source. Running plugins on a server we control removes the
   entire local-tampering attack surface in one step.
2. **Cost and complexity of local inference.** `scope_guard`'s Stage-1
   embedding judge (sentence-transformers) and Stage-2 LLM judge both
   cost compute. Each user machine pays the cost separately; cold starts
   on laptops are slow; the model files must be distributed and updated.
   Centralising amortises the compute, fixes the model versions in one
   place, and lets us tune them without a user upgrade.
3. **Operational simplicity.** One deployment, one audit trail, one
   release surface. Bug fixes ship in minutes rather than waiting for
   every user to `pip install -U`. Data needed for drift research is
   already on the server.

The cost of the change is real and documented in §Consequences: every
user prompt and response now crosses our infrastructure, the L/A/R mode
distinction (ADR-0006) loses its primary justification, and we acquire
a single point of failure plus Anthropic-ToS exposure that the local
model did not have.

## Options considered

### A. Status quo: local sidecar + in-process plugins

- Pros: privacy-by-default, no central infra, no SPOF, no ToS proxy
  question.
- Cons: cannot prevent plugin-code tampering; embedding/LLM-judge cost
  duplicated per user; every fix needs a user-side upgrade; collecting
  drift data needs the Mode-R sink dance (ADR-0007) which most users
  never enable.

### B. Central server + thin local agent  (**chosen**)

- Pros: structural plugin tamper prevention; centralised compute; one
  audit trail; instant fixes; drift research data is already where the
  research lives.
- Cons: all user traffic transits our infra; SPOF; Anthropic ToS
  exposure; the entire egress/mode/content-level system (ADR-0006)
  built on local-trust premises is invalidated.

### C. Hybrid: local for some plugins, server for others

- Pros: keeps lightweight policy plugins local (no extra hop) while
  centralising heavy ones.
- Cons: doubles the trust model — local plugins remain tamperable, so
  the "structural prevention" benefit is lost where it matters. Doubles
  the code surface. Discarded.

## Decision

Adopt **Option B: central server + thin local agent**.

1. **Server operator.** The team operates a single central server
   initially. **Enterprise self-hosted deployment is explicitly retained
   as a future option** — the server must be designed deployable
   (containerised, configurable, no team-cloud lock-in beyond what an
   external operator can replicate). This forecloses no enterprise
   conversations later.
2. **Local install.** Users install a **thin local agent only**. Its
   sole jobs are:
   - Set `ANTHROPIC_BASE_URL` to the central server endpoint.
   - Handle local bootstrapping (auth handshake with the server, any
     per-user configuration the agent needs to read once).
   No proxy logic, no plugin execution, no SQLite, no signature
   verification — none of that runs locally any more.
3. **Plugin execution.** Plugins run on the central server. The plugin
   author / SDK contract (ADR-0005, ADR-0012, ADR-0015) survives; the
   *deployment surface* changes from "each user's machine" to "the
   server we operate." Plugin tamper by end users is eliminated
   structurally.
4. **Data flow.** All Claude Code requests and responses traverse the
   central server by design. The team can see raw traffic. **User
   consent, data retention, and data-handling policy are required but
   are out of scope for this ADR** — see Open questions.

## Consequences

### What this enables

- Plugin code tamper prevention is structural, not policy-based. ADR-0008
  signing of `plugin.toml` becomes a server-side trust mechanism only;
  end users cannot interpose.
- Embedding model and LLM-judge costs amortise across users.
- One audit trail, one release artefact, one bug-fix cadence.
- Drift-research data lives where the researchers operate, without a
  per-user upload pipeline.
- The server-side codebase can share more aggressively with
  `llm_tracker_server` (ADR-0007's reference receiver) since the
  separation between "local proxy" and "central receiver" disappears.

### What this constrains

- **Privacy.** Every prompt, every tool result, every model response
  transits the team's infrastructure as plaintext on the wire (TLS to
  Anthropic from the server is unchanged, but our server sees the
  cleartext). User code, file contents, secrets in prompts — all
  visible to the team. The "data egress off by default" stance of
  ADR-0006 is no longer the default; **all traffic is egress by
  definition**. A user-facing consent surface and a data-handling
  policy are now hard prerequisites, tracked as open questions below.
- **Single point of failure.** If the central server is down or
  unreachable, the user's Claude Code may stop working. The fallback
  policy is an open question (below). Operational SLA, redundancy, and
  user-visible failure modes become real responsibilities.
- **Anthropic ToS dependency.** Operating a many-user proxy in front of
  Anthropic's API materially changes our relationship with their ToS:
  rate-limit pooling, API-key vs OAuth pass-through architecture, the
  question of whether we are "redistributing" the API. Out of scope
  here but a known dependency for launch.
- **L/A/R modes (ADR-0006) lose their primary motivation.** Mode L's
  "no egress except upstream LLM" cannot be honoured when the user's
  machine has already shipped the bytes to us. The mode taxonomy is
  superseded; a replacement (if any) belongs in a follow-up ADR.
- **Manifest signing (ADR-0008) is moot for the original threat.** The
  bundled trust registry was designed to defeat user-side tampering
  with `plugin.toml`. With plugins server-side, that threat is gone.
  Signing may survive as a *deployment-time* trust mechanism (which
  developers can deploy which plugins to the server); that re-purposing
  is a follow-up review, not a decision here.
- **EgressGuard, content-level routing, HookContext per-mode
  degradation** were all defined against the local trust boundary.
  Their server-side analogues need redesign: the new trust boundaries
  are (a) between the local agent and our server (network), and
  (b) between users' data on our server and team operators (access
  control, retention, deletion). The Phase 1b primitives don't
  disappear, but their *meaning* changes.

### Reversibility

Medium-high.

- The plugin contract (`BasePlugin`, hook lifecycle, capability
  vocabulary, `HookContext`, `EgressClient`) is unchanged; plugin
  packages can in principle run in either deployment.
- The local sidecar code in `packages/llm_tracker/` is not deleted by
  this ADR — much of it is reusable on the server (FastAPI app, hook
  dispatch, audit log, storage models).
- What does change irreversibly once we launch: data flowing to our
  servers. Users cannot retroactively unsend their prompts. Therefore
  the consent and retention policy must be settled *before* launch,
  not after.

## Open questions

These are explicitly left unresolved by this ADR. Each becomes its own
ADR or workstream.

- **Fallback policy when server is unreachable.** Two options:
  - **Fail-open.** The local agent transparently routes to
    `api.anthropic.com` directly when the server is unreachable. UX
    continuity preserved; observability lost for the outage window;
    can be deliberately abused by a user spoofing unreachability to
    bypass observability.
  - **Fail-closed.** The local agent refuses to proxy when the server
    is unreachable. 100% visibility preserved; user workflows break
    during outages; requires SLA discipline.
  Pick one for the demo default; an enterprise self-hosted operator
  may choose differently. Decision deferred.
- **User consent and data-handling policy.** Required before launch:
  what data we store, retention period, deletion mechanism, what the
  user is told before they install the agent, lawful basis under
  applicable privacy regimes. Its own ADR.
- **Authentication between local agent and server.** Options include
  shared org token, per-user token, OAuth pass-through of the user's
  Claude credential, or some combination. Affects ToS posture
  (per-user keys vs pooled key) and the rate-limit model. Its own ADR.
- **Local agent language and distribution.** Python (consistent with
  the rest of the stack) vs Go / a single small binary (lower install
  friction). Affects how users get and update the agent. Its own ADR.
- **Multi-tenancy boundary on the server.** Which team's data is
  isolated from which; org-level vs user-level boundary; RLS-style
  enforcement vs application-level. Its own ADR.
- **What survives of ADR-0006's L/A/R modes** (if anything) in the
  new model. Possible reframing: modes describe *server-side data
  retention and visibility tiers* rather than *egress behaviour*.
  Decision deferred.
- **What survives of ADR-0008's signing model.** Possibly recast as
  developer-to-deployment signing (which contributor's keys may push
  which plugins to the server). Review when the server-side plugin
  deploy pipeline is designed.
