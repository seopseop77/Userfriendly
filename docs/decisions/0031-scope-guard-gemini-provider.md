# ADR-0031 · scope_guard provider swap: OpenAI → Gemini

- **Status**: Accepted (2026-05-18 by operator; implementation lands in
  `docs/worklog/2026-05-18-gemini-provider-swap.md`).
- **Date**: 2026-05-18
- **Author**: Claude Code (drafting from a 2026-05-18 operator request:
  "혹시 지금 openai api key 사용하는 거 대신에 gemini api key를 사용하도록
  코드를 수정해줄 수 있음? 내가 gemini api key가 있어서.").
- **Related**: ADR-0030 §D3 (embedding provider), ADR-0030 §D4 (Stage-2
  judge provider), ADR-0030 §D8 (`scope_chunks.embedding` schema),
  ADR-0030 §D9 (env vars), ADR-0030 §Consequences — Disclosure,
  ADR-0029 (consent + data handling), ADR-0015 (EgressClient SDK).
- **Supersedes (in part)**: ADR-0030 §D3 and §D4 — the embedding /
  judge providers picked there are replaced; everything else in
  ADR-0030 (two-stage pipeline, async `on_persisted`, schema layout
  *modulo dimension*, RLS, retention) stays in force.

## Context

ADR-0030 was Accepted on 2026-05-18 and shipped end-to-end across CP1–
CP8 on the same day. It picked OpenAI for both pipeline stages:
`text-embedding-3-small` for Stage 1 and `gpt-4o-mini` for Stage 2.
Both selections were made under §"Open questions" §"Provider
diversity": the ADR explicitly notes that "A future ADR introducing
Anthropic / local-model judges is additive (pipeline.py picks the
client)."

The operator runs the plugin against their own API budget. They hold
a Google Gemini API key and do not hold an OpenAI key. ADR-0030's
"operator-side live smoke" (STATUS.md "Next active step") cannot run
without a paid key on the configured provider, so the provider choice
is a blocking practical constraint, not a research preference.

Scope `scope_guard` has no production data yet (operator confirmed
2026-05-18 — `scope_chunks` is empty). A vector-dimension change is
therefore reversible at zero data-migration cost.

## Options considered

1. **Keep OpenAI; ask the operator to obtain an OpenAI key.** Honours
   ADR-0030 verbatim. Fails on the operator's actual procurement
   posture (no OpenAI relationship; Gemini key already in hand). Would
   block CP9 (live smoke) indefinitely.
2. **Provider switch: full migration to Gemini** *(chosen)*.
   `text-embedding-004` (768d) + `gemini-2.5-flash` over the same
   `EgressClient` path. Egress destination changes
   (`generativelanguage.googleapis.com`); env var renames
   (`OPENAI_API_KEY` → `GEMINI_API_KEY`); one Alembic migration
   collapses `scope_chunks.embedding vector(1536)` to `vector(768)`.
   Disclosure paragraph (ADR-0029 §Axis 5) re-targets Google instead
   of OpenAI.
3. **Dual-provider abstraction (env-switched `PROVIDER=openai|gemini`).**
   Adds one interface layer + two client implementations + provider
   selection plumbing. Rejected: CLAUDE.md §2.2 ("No 'flexibility' or
   'configurability' that wasn't requested") and §2.3 ("Don't refactor
   things that aren't broken"). The plugin runs one provider per
   deployment in practice; a future second provider can land its own
   ADR + minimal interface extraction at that point. Adding the
   abstraction now is speculative.

## Decision

**Pick option 2 — full migration to Gemini.** Three reasons:

1. **Operator constraint, not a strategy reversal.** ADR-0030's §D3/§D4
   selected OpenAI for cost + single-vendor egress reasons; Gemini
   matches both (the comparable price tier, one egress vendor). The
   only thing changing is *which* single vendor.
2. **Zero data-migration risk.** `scope_chunks` is empty in every
   deployment that exists. The dimension change is a drop-and-add on
   an empty column; no backfill, no production data loss vector. If
   data accumulated later under one provider, switching providers
   would require a re-embedding pass — but that's not the situation
   today.
3. **No speculative abstraction.** Provider-pluggability is genuinely
   easier to add *later* (after a second concrete provider has known
   requirements) than to design upfront with one consumer.

### D1 — Embedding provider: Gemini `text-embedding-004`

Vector dim **768**. Endpoint:
`https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent`.
Authentication via the `x-goog-api-key` header (Gemini's standard;
distinct from OpenAI's `Authorization: Bearer …`).

Request shape (`embedContent`):

```json
{
  "model": "models/text-embedding-004",
  "content": {"parts": [{"text": "<input>"}]}
}
```

Response shape (single-input `embedContent` returns one `embedding`
object, not the batched `embeddings[]` array used by
`batchEmbedContents`):

```json
{"embedding": {"values": [0.123, ...]}}
```

The token-input ceiling for `text-embedding-004` (~2048 tokens) is
*lower* than `text-embedding-3-small`'s 8191. The default
`LLMTRACK_PLUGIN_SCOPE_GUARD_WINDOW=5` user-initiated turns plus the
first-turn `<system-reminder>` typically stays inside that ceiling for
Claude Code traffic, but the operator should treat it as an empirical
margin to watch in the first 100 alerts — same posture ADR-0030
Known-limitations §3 already prescribed for `THRESHOLD` /
`AMBIGUOUS_BAND`. No code-level pre-check on input length: the API
returns an explicit error which the plugin's existing
`EmbeddingError` path already logs + skips (ADR-0030 §D1 observe-only).

### D2 — Stage-2 judge: Gemini `gemini-2.5-flash`

Endpoint:
`https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent`.
Same `x-goog-api-key` header.

Request shape:

```json
{
  "systemInstruction": {"parts": [{"text": "<frozen prompt>"}]},
  "contents": [{"role": "user", "parts": [{"text": "<user prompt>"}]}],
  "generationConfig": {
    "temperature": 0.0,
    "responseMimeType": "application/json"
  }
}
```

Response shape (`candidates[0].content.parts[0].text` carries the model
text; same single-text extraction the OpenAI implementation used over
`choices[0].message.content`).

`systemInstruction` is Gemini's first-class concept; the OpenAI client
encoded it as the first `messages[]` entry with `role: "system"`. The
frozen prompt template itself (ADR-0030 §Q4) **does not change** —
sentinels still in `tests/test_judge.py::test_q4_prompt_template_is_frozen`
pin the same string. Gemini honours `responseMimeType=application/json`
the same way OpenAI honours `response_format={"type": "json_object"}`,
so the existing `_parse_verdict` / fallback path continues to apply.

### D3 — Schema: `scope_chunks.embedding vector(1536)` → `vector(768)`

Alembic migration `0012_scope_chunks_embedding_dim_768`:

```sql
ALTER TABLE scope_chunks DROP COLUMN embedding;
ALTER TABLE scope_chunks ADD COLUMN embedding vector(768) NOT NULL;
```

Down-migration restores `vector(1536)`. Both directions drop +
re-create the column; pgvector does not permit `ALTER COLUMN … TYPE
vector(N)` to a different dimension. The drop-and-add is safe today
*only* because `scope_chunks` is empty — the migration's docstring
spells this out so a future operator does not run it against
populated data without re-embedding.

ADR-0030 §D8's schema block in the ADR text is **not** edited; this
ADR's record stands as the supersession. Migration 0010 is left
unchanged for the same reason — alembic revisions are immutable once
shipped.

### D4 — Env var rename: `OPENAI_API_KEY` → `GEMINI_API_KEY`

The plugin's `on_init` reads `GEMINI_API_KEY` instead of
`OPENAI_API_KEY`. `process-scope-document` CLI does the same. No
fallback / aliasing — the previous name is gone. ADR-0030 §D9's
silent-no-op posture continues: missing key → `structlog.warning` +
disabled, no crash.

The `LLMTRACK_PLUGIN_SCOPE_GUARD_JUDGE_MODEL` default changes
documentation from `gpt-4o-mini` to `gemini-2.5-flash` in
`.env.example`; runtime behaviour is identical (the value is the
exact model id appended to the URL path).

### D5 — Egress allowlist: Gemini destinations

`plugin.toml`:

```toml
egress_destinations = [
  "https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent",
  "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
]
```

The egress guard's allowlist is exact-URL; both destinations are
listed explicitly so no widcarding is introduced. ADR-0015's audit
trail covers both calls unchanged.

### D6 — Disclosure paragraph re-targets Google

`docs/deploy.md §"Data collection & privacy"` is updated alongside the
code commit (ADR-0030's §Consequences — Disclosure obligation
transfers). The new disclosure paragraph:

> When `scope_guard` is enabled, the most recent user-initiated turns
> from each exchange are sent to Google's Gemini API
> (`text-embedding-004` for the Stage-1 embedding; `gemini-2.5-flash`
> for the Stage-2 judge on ambiguous-band requests). Assistant
> responses and tool-result contents are not sent. Google's standard
> API ToS applies; the operator should review
> [Gemini API additional terms](https://ai.google.dev/gemini-api/terms)
> for data-use posture on the API key used.

## Consequences

### What this enables

- The operator can run scope_guard against the API key they actually
  hold. CP9 (live smoke) becomes unblocked.

### What it forecloses (until lifted by a follow-up ADR)

- **OpenAI as the scope_guard provider.** Reverting requires this
  ADR's down-migration + the inverse of the code changes; both are
  in-scope of one PR.

### Reversibility

- **Code path**: High. `EmbeddingClient` and `JudgeClient` remain
  one-method interfaces. Switching back is two file rewrites + one
  migration.
- **Schema dim**: High *while `scope_chunks` is empty*. Low once data
  accumulates under one dimension — at that point a swap means
  re-embedding the full corpus per org.
- **Disclosure paragraph**: Low against existing deployments (operators
  may have advertised one vendor). The deploy.md update lands in the
  same commit as the code change so the disclosure is always in sync
  with the runtime.

## Open questions

- **`text-embedding-004`'s 2048-token ceiling vs. the embedding
  window.** Default `WINDOW=5` is unchanged; if real traffic produces
  long user-initiated turns the embedding call will fail and the
  plugin will skip that exchange (ADR-0030 §D1 observe-only). The
  operator monitors `scope_guard.openai_failure` log lines (now named
  `scope_guard.gemini_failure` in code) and tunes `WINDOW` downward if
  the failure rate is non-trivial. Empirical, not gate-blocking.
- **Future provider diversification.** This ADR is a one-for-one swap,
  not a multi-provider framework. If a third provider is requested
  later, the right move is to extract a minimal `EmbedProvider` /
  `JudgeProvider` interface from the two known concrete implementations
  — not to design that interface upfront with one consumer (CLAUDE.md
  §2.2).
