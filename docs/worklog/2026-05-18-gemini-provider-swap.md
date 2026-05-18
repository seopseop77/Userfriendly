# 2026-05-18 · scope_guard provider swap: OpenAI → Gemini

**Author**: Claude Code
**Session trigger**: "혹시 지금 openai api key 사용하는 거 대신에 gemini
api key를 사용하도록 코드를 수정해줄 수 있음? 내가 gemini api key가
있어서."
**Related docs**: ADR-0030 (§D3 / §D4 / §D8 / §D9 / §Consequences —
Disclosure — the sub-decisions partially superseded here), ADR-0031
(new — this swap, drafted in the same session), prior worklog
`2026-05-18-scope-guard-impl.md` (the OpenAI-era implementation).

## Interpretation

The user asked to swap the API provider. Surfaced (and confirmed with
the user before touching code) that this is not a one-line key rename
because:

- The embedding vector dim changes (1536 → 768), which means the
  `scope_chunks.embedding` pgvector column has to be redefined.
- The egress allowlist's exact-URL entries change.
- The public env-var name changes (`OPENAI_API_KEY` →
  `GEMINI_API_KEY`).
- ADR-0030 §D3 / §D4 pinned OpenAI explicitly — the change needs an
  ADR record, not just a code edit.

Three clarifying questions answered:

1. **Operational state**: "아직 안 씀, 개발 단계" — no production
   `scope_chunks` rows. Vector-dim change is safe as drop-and-add.
2. **Swap shape**: "Gemini로 완전 교체" — not a dual-provider
   abstraction. Honours CLAUDE.md §2.2 (no speculative configurability).
3. **Models**: `text-embedding-004` (768d) + `gemini-2.5-flash`.

## What was done

- Created `docs/decisions/0031-scope-guard-gemini-provider.md` —
  records the swap, supersedes ADR-0030 §D3 / §D4, freezes the request
  / response shapes for both endpoints, pins the new env var name +
  egress URLs + disclosure paragraph.
- Created
  `packages/llm_tracker_server/alembic/versions/0012_scope_chunks_embedding_dim_768.py`
  — `scope_chunks.embedding` `vector(1536)` → `vector(768)` via
  drop-and-add (pgvector does not allow dimension-changing ALTER).
  NOT NULL preserved; downgrade restores 1536. Migration docstring
  explicitly notes the empty-table precondition so future operators
  don't run it against populated data.
- Rewrote
  `packages/llm_tracker_plugin_scope_guard/src/llm_tracker_plugin_scope_guard/embeddings.py`
  — `POST .../text-embedding-004:embedContent`, `x-goog-api-key`
  header, `{"model": "models/text-embedding-004", "content": {"parts":
  [{"text": ...}]}}` request, `{"embedding": {"values": [...]}}`
  response, 768-dim assertion.
- Rewrote
  `packages/llm_tracker_plugin_scope_guard/src/llm_tracker_plugin_scope_guard/judge.py`
  — `POST .../gemini-2.5-flash:generateContent`, `x-goog-api-key`,
  `systemInstruction` + `contents` + `generationConfig.{temperature,
  responseMimeType}`, `candidates[0].content.parts[0].text` extraction.
  The frozen `_SYSTEM_PROMPT` wording (ADR-0030 §Q4) is carried over
  unchanged — that's deliberate; the swap is the transport / shape,
  not the prompt contract.
- Edited
  `packages/llm_tracker_plugin_scope_guard/src/llm_tracker_plugin_scope_guard/plugin.py`
  — `OPENAI_API_KEY_ENV` constant renamed to `GEMINI_API_KEY_ENV`,
  `on_init` reads the new var, log key `scope_guard.openai_failure` →
  `scope_guard.gemini_failure`, all OpenAI mentions in module +
  comments retargeted to Gemini.
- Edited
  `packages/llm_tracker_plugin_scope_guard/src/llm_tracker_plugin_scope_guard/plugin.toml`
  — `egress_destinations` swapped to the two Gemini URLs (exact-URL
  match, no wildcard).
- Edited
  `packages/llm_tracker_plugin_scope_guard/src/llm_tracker_plugin_scope_guard/process_scope_document.py`
  — env var rename + docstring + `_ToolEgressClient` comment.
- Edited
  `packages/llm_tracker_plugin_scope_guard/src/llm_tracker_plugin_scope_guard/chunker.py`
  — docstring + size-bounds comment updated to reference Gemini
  `text-embedding-004`'s ~2048-token input ceiling instead of OpenAI's
  8191.
- Edited
  `packages/llm_tracker_plugin_scope_guard/src/llm_tracker_plugin_scope_guard/__init__.py`
  — module-level summary swapped to Gemini.
- Rewrote
  `packages/llm_tracker_plugin_scope_guard/tests/test_embeddings.py`
  — Gemini URL / header / body / response shape pinned; 768d assertion.
- Rewrote
  `packages/llm_tracker_plugin_scope_guard/tests/test_judge.py` —
  Gemini URL / `systemInstruction` / `contents` shape pinned; frozen
  prompt sentinels unchanged (ADR-0030 §Q4 contract); fallback paths
  re-targeted at `candidates[]` shape.
- Edited
  `packages/llm_tracker_plugin_scope_guard/tests/test_plugin.py` —
  three `OPENAI_API_KEY` env-var test names + `monkeypatch.{set,
  del}env` calls renamed to `GEMINI_API_KEY`.
- Edited
  `packages/llm_tracker_plugin_scope_guard/tests/test_integration.py`
  — `_EMBED_DIM` 1536 → 768; vector-helper docstrings updated;
  module-level docstring "OpenAI clients" → "Gemini clients"; stubs
  comment retitled.
- Edited
  `packages/llm_tracker_plugin_scope_guard/tests/test_process_scope_document.py`
  — `_EMBED_DIM` 1536 → 768.
- Edited `.env.example` — section header rev'd; `OPENAI_API_KEY` →
  `GEMINI_API_KEY` block; `LLMTRACK_PLUGIN_SCOPE_GUARD_WINDOW` comment
  updated for the new 2048-token ceiling + `scope_guard.gemini_failure`
  log signal; `JUDGE_MODEL` default `gpt-4o-mini` → `gemini-2.5-flash`.
- Edited `docs/deploy.md` §"Data collection & privacy" — disclosure
  paragraph rewritten to name Google's Gemini API + the two model ids,
  ToS link points at Gemini API additional terms.
- Edited `docs/plugins.md` §11 process-scope-document section —
  required env var line says `GEMINI_API_KEY` with ADR-0031 cross-ref.

## Decisions

- **New ADR (ADR-0031) instead of editing ADR-0030 in place.** ADRs
  are immutable records of decisions at a point in time; the swap is
  a fresh decision, not an erratum. ADR-0031 cites the superseded
  sub-decisions (§D3, §D4) explicitly so a future reader following
  ADR-0030 from elsewhere lands on the swap notice.
- **Migration 0012 (new), not in-place edit of 0010.** Alembic
  revisions are immutable post-merge — even though the user confirmed
  no production data, the prior migration already passed an
  alembic `upgrade --sql` round-trip in CP1's verification log
  (commit `2511c3a`). Rewriting it would invisibly diverge any
  environment that already ran 0010.
- **Drop-and-add column instead of ALTER TYPE.** pgvector rejects
  `ALTER COLUMN … TYPE vector(N)` across dimensions (its in-place
  upgrade is restricted to identical type). Drop-and-add is the only
  reliable path; safe today because the column is empty. The
  migration's docstring spells this out so the next operator does
  not run it against populated data without a re-embedding pass.
- **Carry the §Q4 frozen prompt forward unchanged.** The prompt
  template is part of the ADR-0030 contract surface, not a
  provider-specific artifact. Models that honour JSON-mode tend to
  honour the same instructional wording; rewriting it under the swap
  would conflate two changes. If Gemini-specific re-wording becomes
  necessary, a follow-up commit + an updated `test_judge.py
  ::test_q4_prompt_template_is_frozen` sentinel set is the right
  shape — the rewrite stays diff-visible.
- **`scope_guard.openai_failure` log key renamed.** The structured
  log key is part of the operator-debugging surface (per `docs/deploy.md`
  guidance). Carrying the old name forward would silently mislead a
  future operator grepping for the failure path. Renamed to
  `scope_guard.gemini_failure` in the same commit.
- **`JUDGE_MODEL` default documentation only.** The env var still
  exists (ADR-0030 §D9) for operator override; the default literal
  ships as `gemini-2.5-flash` in `.env.example`. Runtime behaviour is
  unchanged — the value is appended to the URL path either way.
- **No abstraction layer.** Rejected the "provider-selectable" option
  per CLAUDE.md §2.2. Two concrete vendors after the swap are not
  enough to justify an interface; a third vendor (if requested later)
  is the right moment to extract one.

## Verification

```
$ .venv/bin/python3.12 -m ruff format packages/llm_tracker_plugin_scope_guard/ \
  packages/llm_tracker_server/alembic/versions/0012_scope_chunks_embedding_dim_768.py
4 files reformatted, 13 files left unchanged

$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_plugin_scope_guard/ \
  packages/llm_tracker_server/alembic/versions/0012_scope_chunks_embedding_dim_768.py
All checks passed!

$ cd packages/llm_tracker_plugin_scope_guard && ../../.venv/bin/python3.12 -m pytest \
  tests/test_embeddings.py tests/test_judge.py tests/test_plugin.py \
  tests/test_process_scope_document.py -q
......................................sss                                [100%]
38 passed, 3 skipped in 0.35s

$ cd /Users/minseop/Desktop/MyProjects/Userfriendly && .venv/bin/python3.12 -m pytest -q
... 213 passed, 26 skipped in 5.99s
```

The 26 skips are the pre-existing DB-fixture suite (skipped when
`LLMTRACK_TEST_DATABASE_URL` is unset — same as every prior
checkpoint in this repo). The full test surface passes against the
new code; no regressions in the rest of the repo.

Final OpenAI sweep:

```
$ grep -rn "OPENAI_API_KEY\|api\.openai\.com\|gpt-4o-mini\|text-embedding-3-small" \
    --include="*.py" --include="*.toml" --include="*.md" . \
    | grep -v "docs/worklog/2026-05-18-scope-guard-impl\|docs/worklog/2026-05-18-adr-0030-scope-guard\|docs/decisions/0030\|docs/decisions/0031\|docs/STATUS\|test_scrubbers.py\|.venv\|__pycache__"
packages/llm_tracker_plugin_scope_guard/src/llm_tracker_plugin_scope_guard/judge.py:16:Supersedes the OpenAI ``gpt-4o-mini`` client picked in ADR-0030 §D4.
packages/llm_tracker_plugin_scope_guard/src/llm_tracker_plugin_scope_guard/embeddings.py:13:Supersedes the OpenAI ``text-embedding-3-small`` client picked in
packages/llm_tracker_server/alembic/versions/0012_scope_chunks_embedding_dim_768.py:8:``text-embedding-3-small`` (1536d) to Gemini ``text-embedding-004``
packages/llm_tracker_server/alembic/versions/0010_scope_guard_tables.py:19:  ``vector(1536)`` (OpenAI ``text-embedding-3-small`` dim).
```

All four are deliberate historic / supersession references:

- judge.py / embeddings.py / 0012: explicit "Supersedes …" / cite
  lines required so a future reader of the new module learns about
  the prior choice in-place.
- 0010: the migration is immutable historic record; rewriting its
  docstring would falsify the as-shipped state.

No `pytest` was run against a live Gemini key — the operator-side
live smoke under a real `GEMINI_API_KEY` is the next operational
step (see Handoff). All offline contract surface (URL / header / body
/ response shape) is pinned in the unit tests.

## What's left / known limits

- **Live smoke not performed.** ADR-0031 closes only the in-repo
  contract change; the operator still has to exercise the real
  `text-embedding-004` + `gemini-2.5-flash` round-trips against a
  production-shape `scope_chunks` corpus.
- **No production data migration concern today.** If `scope_chunks`
  ever accumulates rows under one dimension and a future swap is
  needed, migration 0012's drop-and-add is the *wrong* tool — the
  right tool is a re-embedding pass + a tailored migration that copies
  vectors across. The 0012 docstring spells this out.
- **Token-input ceiling for `text-embedding-004` (~2048) is lower
  than OpenAI's 8191.** Default `WINDOW=5` is left unchanged.
  Operators monitor `scope_guard.gemini_failure` log lines on long
  user-initiated turns; tune `LLMTRACK_PLUGIN_SCOPE_GUARD_WINDOW`
  downward if non-trivial.

## Handoff

Phase 1c scope_guard is end-to-end on Gemini now. **Next single step
is operational, not implementation: operator-side live smoke against
a real `GEMINI_API_KEY` to exercise the actual `text-embedding-004` +
`gemini-2.5-flash` round-trips on production traffic.** Once that's
green, ADR-0030's "operator-side live smoke" step closes and the
plugin moves out of "code-complete, unverified live" status.

If the live smoke surfaces token-ceiling failures, the right knob is
`LLMTRACK_PLUGIN_SCOPE_GUARD_WINDOW` (default 5) — drop it to 3 and
re-check.

## Suggestions (untouched)

- The Stage-2 prompt was carried over verbatim. If real Gemini
  traffic shows the JSON-mode adherence dropping on long
  `numbered_chunks`, that's the moment to revisit the prompt and bump
  the `test_q4_prompt_template_is_frozen` sentinels — not before.
