# Claude Code Working Guide (CLAUDE.md)

Rules Claude Code follows in this repository. Strategy lives in Claude Cowork
and `docs/`; Claude Code's job here is **implementation**.

## 1. Project at a glance

- **Purpose**: A central server **framework** between CLI coding agents
  (Claude Code, etc.) and LLM API servers. The core only provides hook points,
  capability gating, and egress control. Actual *features* (scope guard, drift
  metrics, data upload, etc.) are built as **plugins**.
- **Three core principles** (top wins on conflict):
  1. Extensibility first — new feature = new plugin, not a core change.
  2. Security first — data egress off by default, capabilities granted
     explicitly, every action audited.
  3. Mode-aware — the framework knows the deployment mode (L/A/R) and
     enforces what capabilities each mode permits.
- **Distribution**: Central server. Collaborators extend functionality via plugins.
- **Language/stack**: Python 3.11+, FastAPI, httpx, PostgreSQL, Alembic.
- **Scope**: Core targets Claude Code (Anthropic Messages API) first. Adapter
  abstraction exists, but OpenAI/Gemini implementations are deferred. Domain
  features live outside the core — plugins.

Details: `docs/design.md`, `docs/plugins.md`. Don't reverse decisions silently — open an ADR.

## 2. Engineering principles

### 2.1 Think before coding

- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2.2 Simplicity first

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

### 2.3 Surgical changes

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

Scope drift: note observed improvements in a "Suggestions" worklog section; don't mix mass formatting into feature commits; when ambiguous, interpret minimally and ask.

### 2.4 Goal-driven execution

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [step] → verify: [check]
2. [step] → verify: [check]
3. [step] → verify: [check]
```

## 3. Language and communication

- **All artifacts** (source code, comments, commit messages, worklogs, ADRs,
  design docs, status pages, READMEs) in **English**.
- **Chat replies to the user** in **Korean**.

## 4. Roles (important)

| Area | Owner | Output |
|---|---|---|
| Direction, architecture, scope | Human + Claude Cowork | `docs/design.md`, `docs/decisions/*.md` |
| Code, refactoring, tests, fixes | Claude Code | `packages/`, `tests/`, `docs/worklog/*.md` |

**Claude Code does not make architectural decisions alone.** Examples: adding
a new dependency, changing storage schema, changing proxy behavior, changing
public interfaces (CLI flags, env vars, event schema). When such a need
arises, **stop**, write a "decision needed" section in the worklog, and tell
the user.

## 5. Work tracking (required)

### 5.1 Three entry points

| File | Role | Updated by |
|---|---|---|
| `docs/STATUS.md` | "Where are we right now?" One-page entry for any new session. | Every checkpoint |
| `docs/worklog/<YYYY-MM-DD>-<slug>.md` | Current session's narrative — intent, decisions, verification. | Every meaningful unit of work |
| git log | Code-level checkpoints — what *exactly* changed. | Every commit (automatic) |

### 5.2 Worklog rules

- Path: `docs/worklog/YYYY-MM-DD-<slug>.md`
- Template: `docs/worklog/TEMPLATE.md`
- One file per (date, topic). New topic → new file.
- **Update during work, not after.**

A worklog must contain:
- The user's request and your interpretation.
- Files created/modified (path + one-line summary + commit hash).
- Decisions made and their rationale.
- Verification — tests run, manual checks, results.
- What's left, known limits, a **"Handoff"** section.

### 5.3 Checkpoint rule (cutoff-resilient)

Each of these moments is a *checkpoint*. At every checkpoint, do **three
things as one atomic unit**.

Triggers:
- A meaningful unit of code change is complete.
- A test newly passes.
- A dependency or migration is added.
- A roadmap checklist line completes.
- **The user says "checkpoint" or "pause".**

The three units:

1. **Commit code** — per CLAUDE.md §10.
2. **Update worklog** — append the new commit hash to "What was done", and
   rewrite "What's left / Handoff" as of *now*. Don't leave stale mid-work
   notes.
3. **Update STATUS.md** — refresh the timestamp, active worklog path, last
   3–5 commits, "Where we paused", and "Next single step".

If you don't bundle these three, the next session is lost.

### 5.4 ADR

- Path: `docs/decisions/NNNN-<slug>.md`
- Template: `docs/decisions/TEMPLATE.md`
- ADRs are for hard-to-reverse / wide-impact decisions. Smaller
  implementation choices belong in the worklog.

## 6. Pre-task checklist

1. Read `docs/STATUS.md`. Note the worklog it points to and the "Next single step".
2. Read that worklog's last "Handoff" section.
3. `git log -5 --oneline`. `git show` the latest if needed.
4. Re-read `docs/design.md` and `docs/roadmap.md`.
5. Check related ADRs in `docs/decisions/`.
6. Announce in one line: "Per STATUS.md the next step is X. Starting that now."
7. If unclear or architecture-touching, ask **before** starting.

### 6.1 Standard "resume" prompt

> Resume. Read STATUS.md → the worklog it points to → `git log -5`. Announce
> the next single step in one line, then execute it. Update per §5.3 along
> the way.

## 7. Code conventions

- Python 3.11+ syntax. Type hints encouraged; required on public functions
  and classes.
- Formatter/linter: `ruff` (format + lint). Run before every commit.
- Tests: `pytest`. Pure functions get unit tests; proxy behavior gets
  integration tests against a fake Anthropic server end-to-end.
- Async by default (`async def`). No blocking IO.
- Logging: `structlog`. No `print`.
- Configuration: `pydantic-settings`. Env var prefix `LLMTRACK_*`.
- Secrets/PII never appear in logs. Scrubbing happens only inside
  `llm_tracker.scrubbers`.
- Don't pile comments at the top of files. Module docstrings are fine.

## 8. Verification

Before reporting "done", have at least one **active verification**.

- Added/changed a function → test run output in worklog.
- Changed proxy behavior → local end-to-end logs/screenshots.
- Documentation only → confirm internal links resolve.
- Added a dependency → confirm install succeeds clean.

No "tests should pass" language. Either run them, or say you couldn't.

## 9. Public interfaces

Contracts — changes break downstream systems and plugins. Changes require an ADR.

- CLI command names and flags (`llm-tracker ...`).
- Environment variable names (`LLMTRACK_*`, `ANTHROPIC_BASE_URL`).
- The HTTP paths the proxy listens on (Anthropic Messages API shape).
- **Hook lifecycle** — names, timing, and meaning of return values for the
  8 hooks.
- **Capability vocabulary** — names and meaning of each capability.
- **Plugin manifest schema** — keys and validation in `plugin.toml`.
- **Content levels** — definitions of L0/L1/L2/L3.
- Core PostgreSQL schema (`exchanges`, `events`, `tool_calls`, `audit_log`).

## 10. Git commit rules (auto-commit on)

Claude Code **commits automatically** at every meaningful unit of change.
**Never push automatically** — humans push.

### When to commit

- A worklog work-unit completes.
- After dependency changes (`pyproject.toml` + lockfile updated).
- After adding an Alembic migration.
- Right after tests pass. **Never commit a failing state.**

If the tree is mid-broken (build broken, tests red), don't commit. Update
the worklog and proceed.

### Message format

```
<scope>: <one-line summary, ≤ 50 chars>

- key change 1
- key change 2

Refs: docs/worklog/YYYY-MM-DD-<slug>.md
ADR: docs/decisions/NNNN-<slug>.md     (when relevant)
```

`<scope>` examples: `proxy`, `server`, `scope-guard`, `storage`, `docs`,
`infra`, `deps`, `tests`.

**Do not include auto-generated meta** in commit messages (e.g.
"Generated with X", "Co-Authored-By: ..."). Keep it clean.

### Staging

- Stage only the files you intended. Prefer explicit paths over `git add -A`.
- Add generated/cache files to `.gitignore` immediately and exclude them.
- Before committing run `git diff --cached`. **Scan for secrets**:
  `Bearer `, `sk-`, `AKIA`, `ghp_`, `xoxb-`, `password=`, `LLMTRACK_*_TOKEN=`,
  email patterns, etc.

### Forbidden

- Auto-running `git push`.
- Auto-running `--force` / `--force-with-lease`.
- Auto-rewriting history (`rebase -i`, `commit --amend`).
- Mass-deletion commits without confirmation.
- Committing `.env`, keychain content, secret files.

### Worklog cross-reference

In the worklog "What was done" section, cite the short commit hash:

```
## What was done
- Created src/foo.py — handles bar (commit a1b2c3d)
- Modified tests/test_foo.py (commits a1b2c3d, e4f5g6h)
```

## 11. Common commands

```bash
# Install dependencies (uv workspace)
uv sync

# Format + lint
ruff format . && ruff check .

# Tests
pytest -q

# Run the proxy locally
python -m llm_tracker.proxy

# Run the central receiver app locally
python -m llm_tracker_server

# Alembic migrations (per package, via alembic.ini)
alembic revision -m "<message>"
alembic upgrade head
```

## 12. Where to find things

```
packages/llm_tracker/             # core framework (proxy + hook host)
  src/llm_tracker/
    proxy/        # FastAPI app, SSE forwarding, tee
    adapters/     # provider-specific parsing (anthropic only for now)
    extractors/   # SSE events → structured records
    scrubbers/    # PII / secret removal
    storage/      # PostgreSQL buffer
    config/       # pydantic-settings
    cli/          # Typer CLI
    plugin_host/  # plugin loader, hook dispatcher, capability registry
    egress_guard/ # single egress path with allowlist
    audit/        # audit log writers

packages/llm_tracker_server/      # central receiver app
  src/llm_tracker_server/
    api/          # HTTP routes
    domain/       # business logic (no DB)
    storage/      # SQLAlchemy + Alembic

packages/llm_tracker_agent/       # agent-side client / SDK

tests/          # pytest
docs/           # human-readable documents
  STATUS.md     # first entry point for any new session
  design.md     # full architecture
  roadmap.md    # phased plan
  plugins.md    # plugin authoring guide
  distribution.md
  worklog/      # per-session work logs
  decisions/    # ADRs
.claude/        # Claude Code-specific config (slash commands, hooks)
```
