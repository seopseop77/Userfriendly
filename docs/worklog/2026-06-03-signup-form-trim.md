# 2026-06-03 · Trim the signup form to name + email + institution

**Author**: Claude Code
**Session trigger**: User: "폼 작성 단계에서 연구 설명 + pdf를 선택하는 부분을
제거해줄래? ... 그냥 이름 + 메일 + 소속 정도만 작성하고 토큰이 발급되도록 해줘"

## Interpretation

The public signup app (`packages/llm_tracker_signup`) collected name, email,
institution, a free-text **research description**, and an optional
**research-proposal PDF** (text extracted, file discarded). The operator
concluded the last two are no longer needed. Remove them from the form so a
participant only enters name + email + institution and still gets a token.

## Decision needed → resolved

`participant_registrations.research_description` is **`NOT NULL`** (migration
0018); `proposal_text` is nullable. Removing the form fields forces a choice
on the DB columns. Per CLAUDE.md §4 (storage-schema changes are not made
unilaterally) the user was asked and chose:

- **Keep the schema, stop collecting.** No migration. INSERT now writes
  `research_description = ''` and `proposal_text = NULL`. Fully reversible;
  leaves the two columns in place (always empty/NULL going forward).

(The alternative — dropping the columns via a new migration — was declined.)

## What was done

- `templates/register.html` — removed the research-description `<textarea>`
  and the proposal-PDF file input; removed the now-orphaned file-validation
  JS that referenced the deleted `#proposal` input.
- `app.py` — `POST /register` no longer takes `research_description` (Form)
  or `proposal` (File); dropped the PDF-extraction block and the
  `research_description` echo in the duplicate-email re-render. Removed the
  now-unused `File`, `UploadFile`, and `extract_pdf_text` imports.
- `registration.py` — `register_participant()` signature dropped
  `research_description` / `proposal_text`; the INSERT keeps both columns but
  writes literal `''` / `NULL`. Removed the orphaned `extract_pdf_text()`
  function and its `io` / `pdfplumber` imports. Updated the module docstring.
- `__init__.py`, `tests/conftest.py` — updated stale docstrings that
  referenced the PDF.
- `tests/test_app.py` — dropped the PDF helper/import; `GET /` assertions now
  check name/email/institution (not research_description/`.pdf`); register
  POSTs send only the three fields; removed the now-redundant
  `test_register_route_no_proposal_pdf` (identical to the happy-path test
  once the PDF branch is gone).
- `tests/test_registration.py` — removed the three `extract_pdf_text` unit
  tests + `fpdf`/`extract_pdf_text` imports; `register_participant()` calls
  send only the three fields. The happy-path test still asserts
  `proposal_text is None`.

(commit: pending)

## Verification

Local tooling (ruff/pytest/uv) is not installed on this box — the stack runs
in Docker — so verification is **live end-to-end against the rebuilt signup
container** (§8), plus a syntax gate:

- `python3 -m py_compile` on all four changed `.py` files → OK.
- `docker compose build signup && up -d signup` → healthy.
- `GET http://127.0.0.1:8000/` → form has `name`, `email`, `institution`;
  **no** `research_description`, **no** `accept=".pdf"`.
- `POST /register` with only name/email/institution →
  **HTTP 303** → `/success?token=lts_…`.
- DB row in `participant_registrations`: `research_description = ''`,
  `proposal_text = NULL` (columns preserved, written empty).
- The issued token authenticates end-to-end: `POST /v1/messages` with it
  passes our middleware and reaches upstream Anthropic (401 "x-api-key
  header is required") — proving signup-issued tokens still work.
- Test data cleaned up (see below).

## Notes / leftovers

- **Test-org cleanup is partial by design.** The token-validity check above
  created an `exchanges` row and **two `audit_log` rows**. `audit_log` is
  append-only (a trigger rejects DELETE), and it FK-references `orgs`, so the
  throwaway org `participant:formtest@example.invalid` **cannot** be deleted
  without violating the immutability control. Removed everything removable
  (token, registration, exchange); the inert org + its 2 audit rows remain
  intentionally. This is the audit log working as designed, not a leak.

## Suggestions (untouched)

- **Now-unused dependencies**: `pdfplumber` (runtime) and `fpdf2` (dev) in
  `packages/llm_tracker_signup/pyproject.toml` are orphaned by this change.
  Left in place — removing them touches the lockfile + image rebuild and is a
  separate, easily-reversible follow-up.
- The `research_description` / `proposal_text` columns are now dead. If they
  stay empty long-term, a future migration could drop them (the declined
  option above).

## Handoff

Signup form is trimmed to name + email + institution and verified live on
the running stack (`signup.userfriendly.win`). No schema change. The DB
columns are retained but always empty/NULL. Next: unrelated — client cutover
(step 5) in `docs/worklog/2026-06-02-local-storage-migration.md`.
