# ADR-0002 · Task-scope enforcement: input, judging, blocking

- **Status**: Accepted (reframed by ADR-0005 — this decision now describes
  the `scope_guard` *plugin*, not a core feature)
- **Date**: 2026-05-01
- **Author**: Claude Cowork (user-approved)
- **Related**: `docs/design.md §13.1`, `docs/roadmap.md` Phase 1c, ADR-0005

## Context

The parent project's second goal — "intervention in LLM use" — has been
made concrete as **task-scope enforcement**. When a user requests something
unrelated to the registered task (research topic, work scope), the proxy
auto-blocks the response. Three sub-decisions are required:

1. How to take in the task-scope information.
2. How to judge whether an incoming prompt is in or out of scope.
3. How to compose the block response when out-of-scope.

## Options considered

### (1) Task-definition input

- **A. User-edited free text.** Simplest, but the user can broaden their
  own scope arbitrarily, which neuters enforcement.
- **B. Centrally issued + locally cached + signed.** Operator (PI / admin)
  authors the definition; the user cannot edit it. Costs an issuance
  workflow.
- **C. Allow A, but sync everything centrally for audit.** Free-form +
  traceability. Real-time enforcement is weaker — operators only catch
  violations after the fact.

### (2) Judging

- **A. Keyword / regex.** Fast and deterministic. Low precision; trivial
  to bypass.
- **B. Embedding cosine similarity.** Fast, no external calls. Weak in
  borderline cases.
- **C. LLM judge (one extra LLM call per request).** High accuracy.
  Latency, cost, and privacy overhead.
- **D. Hybrid — B first; escalate to C only when uncertain.** Low average
  latency with sharp accuracy at the boundary. Higher complexity.

### (3) Block response

- **A. Return HTTP 4xx.** Simple, but cannot control how Claude Code
  surfaces it. Risk of retry storms.
- **B. Synthetic SSE stream returning 200 OK with a block message.** From
  Claude Code's view, a normal response. Lets us shape the user-facing
  text. The synthetic payload must be precise.
- **C. Empty (204).** Risk of breaking Claude Code's parser.

## Decision

**(1) Option B**: TaskDefinition is centrally issued and locally cached
under signature/checksum verification. Local edits are ignored.

**(2) Option D**: hybrid two-stage judge.
- Stage 1: a local embedding model (e.g., a small sentence-transformers)
  compares the user message to the task's positive/negative example
  centroids. If confident, decide here.
- Stage 2: only on low confidence, call a cheap LLM (provisionally Claude
  Haiku) with a prompt that demands `{verdict, reason}` JSON.
- Cache: LRU keyed on `(conversation_id, sha256(normalized user message))`.
  (Original draft used `task_id`; the deferred `task_id` layer was
  closed 2026-05-21 as won't-do. `conversation_id`, added by
  ADR-0032 / Candidate-1 dedup, provides the per-chain scope this
  cache key needs.)
- Subject of judging: only the `text` content of the **last `role: user`**
  in the `messages` array. Tool results and prior turns are ignored.

**(3) Option B**: synthetic SSE stream, 200 OK. The body is a single chunk
prefixed with `[llm-tracker]`, containing the block reason and one or two
in-scope examples. `stop_reason: end_turn`. **Never** include `tool_use`
(must not trigger tool execution).

## Consequences

- The user must specify a task ID at startup. No task → proxy refuses to
  start.
- All verdicts go to the `scope_verdicts` table for post-hoc audit and
  false-positive review.
- No user-side override (preserves enforcement). False positives are
  resolved by the operator updating the task definition.
- A latency tax is added to in-scope requests (target: Stage 1 +30 ms,
  Stage 2 +500 ms).

### What we give up

- The convenience of editing one's own task definition locally.
- A more general response-side policy engine that watches the model's
  behavior (Phase 3).
- Token-level rewriting of the response (permanent non-goal).

### Reversibility

Medium. Each of the input / judge / block decisions is modular and can be
swapped piecewise. However, the TaskDefinition schema is coupled to the
central issuance/signing system, so changing it requires synchronized
changes on both sides.

## Open questions

- Final pick for Stage 2 judge: Claude Haiku (convenient but external) vs.
  a local model (better privacy, more setup). Sealed in a follow-up ADR.
- TaskDefinition issuance workflow (who, how to sign, refresh cadence).
  Decided alongside the central server build.
- Behavior of Claude Code on consecutive blocks — does it auto-retry, and
  if so, how do we keep it stable?
