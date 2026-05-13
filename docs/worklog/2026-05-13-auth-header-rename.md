# 2026-05-13 · ADR-0023 — server auth header rename (`X-LLM-Tracker-Token`)

**Author**: Claude Code
**Session trigger**: User flagged a P0 blocker for CP14: OAuth Claude
Code users hit `403 unknown or revoked token` against the live server
because `AuthMiddleware` consumed their Anthropic OAuth bearer in
`Authorization`, mistaking it for the per-org tracker token. User
supplied the chosen solution (rename our header to
`X-LLM-Tracker-Token`) and a six-step implementation plan; this
worklog captures execution + verification.
**Related docs**: ADR-0023 (new), ADR-0020 (amended Axis 1 only),
`docs/STATUS.md`, `docs/deploy.md`, prior worklog
`docs/worklog/2026-05-13-cp13b-fly-deploy.md`.

## Interpretation

The collision is structural: `AuthMiddleware` reads `Authorization:
Bearer ...` *for our token*, but OAuth Claude Code (the majority
client) sends the user's Anthropic credential in that same slot. Two
mutually-exclusive consumers cannot share one header. ADR-0023
permanently splits the slot: our auth moves to
`X-LLM-Tracker-Token`; `Authorization` becomes pass-through-only.

ADR-0020 Axis 1 stands — the decision is still "per-org opaque
bearer token". Only the wire-level header name moves. Axis 2
(Anthropic credential pass-through) is unaffected at the policy
level; what changes is that `Authorization` is now a *third* valid
pass-through slot alongside `x-api-key` / `anthropic-api-key`,
because OAuth users send it that way and the server no longer
consumes it.

Zero external clients exist (no thin agent yet; operator-only smoke
is the only caller), so this is a pre-launch rename with no
migration cost.

## What was done

- Created `docs/decisions/0023-server-auth-header-rename.md` —
  Status Accepted; amends ADR-0020 Axis 1 only. Options A/B/C
  considered; A picked (one-line client change vs. forcing every
  user to manually configure `ANTHROPIC_API_KEY`, or stateful
  prefix-sniffing on `Authorization`) (commit 21e9fa5).
- Modified `packages/llm_tracker_server/src/llm_tracker_server/auth/middleware.py`
  — header read swapped from `Authorization: Bearer <token>` to
  `X-LLM-Tracker-Token: <token>`. Removed the bearer-scheme parse;
  the new header is a plain opaque value. Module docstring rewritten
  to cite ADR-0020 Axis 1 + ADR-0023 and explicitly state
  `Authorization` is never read here (commit af6bd8f).
- Modified `packages/llm_tracker_server/src/llm_tracker_server/proxy/forwarder.py`
  — `_LOCAL_ONLY` swapped from `{"authorization"}` to
  `{"x-llm-tracker-token"}`. Inline comment now states
  `Authorization` is intentionally absent from the strip set so
  OAuth Anthropic bearers pass through unchanged (commit af6bd8f).
- Modified `packages/llm_tracker_server/src/llm_tracker_server/auth/__init__.py`
  + `packages/llm_tracker_server/src/llm_tracker_server/proxy/credential.py`
  — package docstrings updated to describe the new header on Axis 1
  and the OAuth pass-through case on Axis 2 (commit af6bd8f).
- Modified `packages/llm_tracker_server/tests/test_auth_middleware.py`
  — all four auth tests (`test_missing_authorization_returns_401`,
  `test_unknown_token_returns_403`, `test_valid_token_binds_org_axis`,
  `test_revoked_token_returns_403`) swapped to send
  `X-LLM-Tracker-Token: <plaintext>`. The 401 detail-string
  assertion updated to look for `X-LLM-Tracker-Token`. Module
  docstring's points 1–2 updated to reference the new header. Test
  function names kept (legacy literal references — would have
  caused churn for no test-behaviour benefit) (commit af6bd8f).
- Modified `packages/llm_tracker_server/tests/test_credential_passthrough.py`
  — `test_outbound_strips_authorization_bearer` replaced with two
  new tests: `test_outbound_strips_x_llm_tracker_token` (asserts
  `X-LLM-Tracker-Token` does NOT reach Anthropic and `x-api-key`
  survives) and `test_outbound_passes_authorization_bearer_through`
  (asserts `Authorization: Bearer oauth-token-xyz` AND `x-api-key`
  BOTH reach Anthropic unchanged — the OAuth case). `TRACKER_BEARER`
  constant retained, repurposed as the `X-LLM-Tracker-Token` value.
  Module docstring updated to enumerate three valid Anthropic
  credential headers (commit af6bd8f).
- Modified `packages/llm_tracker_server/tests/test_two_org_e2e_isolation.py`
  — line 104 swapped from `Authorization: Bearer {plaintext_a}` to
  `X-LLM-Tracker-Token: {plaintext_a}` so the e2e RLS isolation
  test still authenticates after the middleware change (commit af6bd8f).
- Modified `docs/deploy.md` — Step 5 (token-mint instructions) and
  Step 6 (curl recipe + "no Authorization → 401" prose) updated to
  the new header name. The architecture-decisions list at the top
  not modified — ADR-0020 reference stays valid since this rename
  amends Axis 1 only (commit 21e9fa5).
- Modified `.env.example` — Section 1 (per-org bearer token)
  updated to `X-LLM-Tracker-Token`; Section 2 (Anthropic credential
  pass-through) extended to enumerate `Authorization: Bearer
  <oauth-token>` as a third accepted form (commit 21e9fa5).

## Decisions

- **Dedicated header (`X-LLM-Tracker-Token`) instead of
  prefix-sniffing `Authorization` (option C in ADR-0023).** Stateful
  parsing of a shared header slot would be fragile and would still
  require a second header for users without a tracker token; the
  dedicated header makes the contract explicit at every call site.
- **No deprecation window or backwards-compatibility shim for
  `Authorization: Bearer <org-token>`.** Pre-launch (no external
  clients), zero migration cost; supporting both shapes during a
  transition would re-introduce exactly the collision ADR-0023
  closes. CLAUDE.md §10 lists CLI/env contracts as public but the
  *wire-level HTTP header* is not enumerated there — the operator-
  facing change is a one-line edit in `ANTHROPIC_BASE_URL` setup.
- **Kept the test function name
  `test_missing_authorization_returns_401`.** The literal user
  request was to update the *assertion*, not the function name.
  Renaming costs churn and breaks the obvious "git blame → previous
  test name" trail; the docstring inside the function was updated
  for clarity. (Per CLAUDE.md §2.3 — surgical changes; touch only
  what you must.)
- **Updated source-code docstrings in `auth/__init__.py` and
  `proxy/credential.py` even though they were not in the user's
  step list.** Both contained authoritative descriptions of the
  header contract that became factually wrong after the rename;
  leaving them stale would lie to a future reader. These are
  *changed-surface* edits, not adjacent-code improvements.

## Verification

```
$ .venv/bin/python3.12 -m ruff format <7 modified files>
7 files left unchanged

$ .venv/bin/python3.12 -m ruff check <7 modified files>
All checks passed!

$ .venv/bin/python3.12 -m pytest packages/llm_tracker_server/tests/test_credential_passthrough.py -q
..........                                                               [100%]
10 passed in 0.22s

$ export LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_server/tests/test_auth_middleware.py packages/llm_tracker_server/tests/test_two_org_e2e_isolation.py -q
......                                                                   [100%]
6 passed in 6.83s

$ .venv/bin/python3.12 -m pytest packages/llm_tracker_server/tests -q
............................................................. 61 passed in 23.04s
```

Repo-wide sweeps confirm no stale `Authorization: Bearer` references
remain in server source or tests; the only remaining occurrences are
inside ADR-0023 itself (the rename rationale), the new OAuth-
pass-through test, and worklog history files (kept for historical
accuracy).

## What's left / known limits

- **Live-server re-test owed under CP14.** The deployed server at
  `https://llm-tracker-server.fly.dev/` is still running the
  pre-rename build (`Authorization`-reading middleware). CP14 will
  re-deploy after this commit lands and exercise the new header
  end-to-end with a real OAuth Claude Code session.
- **Thin-agent specification (Phase 3b) inherits the new header.**
  No spec exists yet, so there is nothing to update. When the spec
  is written, it will be against ADR-0023 from day one.
- **`docs/STATUS.md` "Next single step" remains CP14** (operator-
  only smoke). This worklog closes the OAuth-collision side-quest
  ahead of CP14; CP14 itself is unchanged.

## Handoff

ADR-0023 is **accepted and implemented**; all 61 server tests pass
locally. Three commits expected in this checkpoint:

1. Source + tests (`server: ...`).
2. ADR + operator docs (`docs: ADR-0023 + deploy/env recipes`).
3. STATUS + this worklog finalize (`docs: STATUS + worklog ...`).

**Next single step**: CP14 — operator-only end-to-end smoke. The new
header makes that smoke meaningful for OAuth Claude Code users out
of the box. Operator still owes the `fly deploy` to pick up this
build before running CP14's `/v1/messages` curl.

## Suggestions (untouched)

- **CLAUDE.md §10 public-interface catalogue does not list HTTP
  headers.** ADR-0023 is the kind of change that benefits from a
  CLAUDE.md entry ("Wire-level inbound header names are public
  contracts — changes require an ADR"). One-line addition; outside
  scope of this checkpoint, surfaced for a future docs pass.
- **`docs/decisions/0020-auth-per-org-token-anthropic-passthrough.md`
  could carry a one-line "Amended on Axis 1 only by ADR-0023"
  footer at the top.** ADR-0023 already cites ADR-0020 as amended,
  so the cross-reference is one-way; bi-directional is a tighter
  index for someone reading ADR-0020 first. Not strictly required —
  the ADR README points future readers chronologically anyway.
