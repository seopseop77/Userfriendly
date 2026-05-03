# 2026-05-03 · Phase 0 — Core framework skeleton

**Author**: Claude Code
**Session trigger**: First Claude Code session; execute Phase 0 per STATUS.md "Next single step".
**Related docs**: `docs/design.md §11`, `docs/roadmap.md Phase 0`, ADR-0001, ADR-0005

## Interpretation

STATUS.md listed four concrete steps for the first Phase 0 checkpoint:
1. Create this worklog.
2. Fill in `pyproject.toml` runtime dependencies (fastapi, uvicorn[standard], httpx[http2],
   pydantic, pydantic-settings, structlog, typer, sqlalchemy[asyncio], aiosqlite, alembic,
   python-ulid, keyring, pynacl) from design.md §11.
3. Verify `pip install -e ".[dev]"` succeeds.
4. Complete checkpoint: commit + worklog + STATUS update.

No architectural decisions required here — everything is prescribed.

## What was done

- Filled in `pyproject.toml` `dependencies` with all 13 runtime packages from design.md §11 (commit b43d82d)
- Created `.venv` using `/opt/homebrew/bin/python3.12` (system `python3` is 3.9.6, too old)
- Verified `pip install -e ".[dev]"` succeeds cleanly in `.venv`
- Created `src/llm_tracker/proxy/app.py` — FastAPI catch-all route (commit 453e590)
- Created `src/llm_tracker/proxy/forwarder.py` — httpx SSE forwarder + asyncio.Queue tee (commit 453e590)
- Created `tests/proxy/test_forwarder.py` — 3 tests via respx; all pass (commit 453e590)
- Created `src/llm_tracker/storage/models.py` — ORM models for exchanges, events, tool_calls, audit_log (commit 6ce1267)
- Configured `alembic/env.py` for async SQLAlchemy + aiosqlite (commit 6ce1267)
- Generated and applied initial Alembic migration; `alembic upgrade head` verified clean (commit 6ce1267)
- Created `src/llm_tracker/config.py` — pydantic-settings, Mode StrEnum (commit 0aaa698)
- Created `src/llm_tracker/cli/main.py` — Typer CLI: init, start, audit (commit 0aaa698)
- Created `src/llm_tracker/plugin_host/hooks.py` — Pass/Block/Transform/Abort types (commit 0aaa698)
- Created `src/llm_tracker/plugin_host/host.py` — PluginHost with 8 hooks + audit writes (commit 0aaa698)
- Created `src/llm_tracker/storage/audit.py` + `database.py` — write_audit(), session factory (commit 0aaa698)
- Updated `proxy/app.py` — FastAPI lifespan wires PluginHost; `proxy/forwarder.py` — all 8 hooks dispatched (commit 0aaa698)

## Decisions

- **python-ulid** used verbatim from design.md §11. Package name verified by install result.

## Verification

```
$ .venv/bin/pip install -e ".[dev]"
...
Successfully installed Mako-1.3.12 MarkupSafe-3.0.3 aiosqlite-0.22.1 alembic-1.18.4
  annotated-doc-0.0.4 annotated-types-0.7.0 anyio-4.13.0 certifi-2026.4.22 cffi-2.0.0
  click-8.3.3 fastapi-0.136.1 greenlet-3.5.0 h11-0.16.0 h2-4.3.0 hpack-4.1.0
  httpcore-1.0.9 httptools-0.7.1 httpx-0.28.1 hyperframe-6.1.0 idna-3.13
  iniconfig-2.3.0 jaraco.classes-3.4.0 jaraco.context-6.1.2 jaraco.functools-4.4.0
  keyring-25.7.0 librt-0.9.0 llm-tracker-0.0.1 markdown-it-py-4.0.0 mdurl-0.1.2
  more-itertools-11.0.2 mypy-1.20.2 mypy_extensions-1.1.0 packaging-26.2
  pathspec-1.1.1 pluggy-1.6.0 pycparser-3.0 pydantic-2.13.3 pydantic-core-2.46.3
  pydantic-settings-2.14.0 pygments-2.20.0 pynacl-1.6.2 pytest-9.0.3
  pytest-asyncio-1.3.0 python-dotenv-1.2.2 python-ulid-3.1.0 pyyaml-6.0.3
  respx-0.23.1 rich-15.0.0 ruff-0.15.12 shellingham-1.5.4 sqlalchemy-2.0.49
  starlette-1.0.0 structlog-25.5.0 typer-0.25.1 typing-extensions-4.15.0
  typing-inspection-0.4.2 uvicorn-0.46.0 uvloop-0.22.1 watchfiles-1.1.1 websockets-16.0
```

## What's left / known limits

- Dependencies installed; no source code yet.
- Remaining Phase 0 items (FastAPI proxy, SQLite schema, CLI, PluginHost, etc.) follow in
  subsequent sessions.

## Handoff

Checkpoint 4 complete: CLI + PluginHost + AuditLog wired. Remaining Phase 0 items:
EgressGuard skeleton, Mode configuration enforcement, hello_world sample plugin,
end-to-end latency test (roadmap.md Phase 0 checklist items 7–11).

## Suggestions (untouched)

- None at this stage.
