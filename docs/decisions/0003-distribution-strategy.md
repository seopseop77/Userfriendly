# ADR-0003 · Distribution: monorepo + per-package pyproject + git URL install

- **Status**: Accepted (revised after the framework pivot in ADR-0005;
  supersedes the original `Proposed` version)
- **Date**: 2026-05-03
- **Author**: Claude Cowork (user-approved)
- **Related**: ADR-0005, `docs/distribution.md`, `docs/plugins.md`

## Context

After ADR-0005 split the world into a framework core plus plugins, the
original distribution proposal — a single `llm-tracker` PyPI package — no
longer fits. Phase 1a will materialize the SDK package and force this
decision into code, so we lock it now.

Three sub-decisions are coupled and decided together:
1. Package layout in the repository.
2. Distribution channel (where users `pip install` from).
3. The boundary between the SDK and the core.

## Options considered

### (1) Package layout

- **A. Monorepo with per-package `pyproject.toml`** (uv workspace +
  hatchling per package).
- **B. Separate git repos per package.**
- **C. Single root `pyproject.toml` listing multiple packages.** The
  current state.

### (2) Distribution channel

- **A. Git URL install** (`pip install
  "git+https://.../<repo>.git#subdirectory=packages/x"`).
- **B. PyPI / private index from day one.**
- **C. Both — PyPI primary with git URL fallback.**

### (3) SDK boundary

- **A. SDK is the public-interface package.** Plugins depend only on the
  SDK; core depends on the SDK; core does not re-export.
- **B. SDK is a "fat" bundle** including helpers, factories, common
  client code; core re-exports SDK symbols for convenience.
- **C. No SDK; plugins import directly from core.**

## Decision

### (1) Layout — Option A: uv workspace + per-package pyproject + hatchling

Phase 1a migrates the repository to:

```
Userfriendly/
├── pyproject.toml                   # workspace root: [tool.uv.workspace]
├── packages/
│   ├── llm_tracker/                 # core framework
│   │   ├── pyproject.toml
│   │   └── src/llm_tracker/...
│   ├── llm_tracker_sdk/             # plugin SDK (created in Phase 1a)
│   │   ├── pyproject.toml
│   │   └── src/llm_tracker_sdk/...
│   ├── llm_tracker_plugin_hello_world/
│   │   ├── pyproject.toml
│   │   └── src/llm_tracker_plugin_hello_world/...
│   ├── llm_tracker_plugin_scope_guard/      # arrives in Phase 1c
│   ├── llm_tracker_plugin_supabase_sink/    # arrives in Phase 2
│   └── llm_tracker_server/          # reference receiver app
│       └── pyproject.toml
└── docs/, tests/, alembic/ (per-package)
```

- Each package owns its `pyproject.toml`, runtime dependencies, version,
  and Alembic migrations.
- Build backend per package: `hatchling`.
- Workspace orchestration: `uv` (`[tool.uv.workspace.members]`). `uv sync`
  at the root creates one `.venv` with every package installed editable.
- `uv` becomes a dev-time tool; install via `pipx install uv` or
  Homebrew. Runtime users (researchers) do not need it — they `pip install`
  from git URL.

### (2) Distribution — Option A: git URL install, PyPI deferred

For demo and research scale:

```
pip install "git+https://github.com/<owner>/Userfriendly.git#subdirectory=packages/llm_tracker"
pip install "git+https://github.com/<owner>/Userfriendly.git#subdirectory=packages/llm_tracker_plugin_scope_guard"
```

PyPI publication is deferred until external usage demands it (Phase 2 or
later). The switch is mechanical and invisible to consumers other than the
URL change.

Why not PyPI from day one:
- Public name reservation overhead.
- Versioning ceremony adds friction during fast iteration.
- Research participants are a small known set; git URL is enough.

### (3) SDK boundary — Option A: SDK is the public interface

`llm_tracker_sdk` exposes:
- `BasePlugin` abstract class.
- `@hook("name")` decorator.
- Hook return types: `Pass`, `Block`, `Transform`, `Abort`.
- Capability symbols (the vocabulary frozen by `CLAUDE.md §10`).
- `plugin.toml` schema as a Pydantic model with a validator.
- A test harness: mock `HookContext`, in-memory mock `EgressGuard`, mock
  SQLite session.
- Public records used at the plugin/core boundary: `RequestRecord`,
  `ResponseEvent`, `Mode` enum.

`llm_tracker` (core) keeps:
- `PluginHost` implementation, `EgressGuard` implementation, `AuditLog`
  writer.
- The FastAPI proxy app (Router / Forwarder / Tee / Extractor / Scrubber).
- The CLI (`llm-tracker init/start/audit`).
- SQLAlchemy models for core tables, Alembic migrations, pydantic-settings.

**Both core and plugins depend on `llm_tracker_sdk`.** Core does not
re-export SDK symbols. Plugins must NOT import `llm_tracker.*` directly —
this is enforced by lint rule and code review.

## Consequences

- Phase 1a's first concrete task is the layout migration: create
  `packages/`, move existing source into `packages/llm_tracker/` and
  `packages/llm_tracker_plugin_hello_world/`, create
  `packages/llm_tracker_sdk/` as a fresh package, and add the workspace
  root `pyproject.toml`.
- `uv` joins the dev toolchain. Install instructions go in
  `docs/distribution.md` and the README quick-start.
- Editable dev install becomes `uv sync` (replaces
  `.venv/bin/pip install -e ".[dev]"`).
- Each package can be versioned and released independently when we move
  to PyPI later.
- External plugin authors have two options:
  1. Clone this repo, add a new package under `packages/`.
  2. Maintain their plugin in their own repo, depend on `llm_tracker_sdk`
     (git URL until PyPI).

### What we give up

- Single-command install — end users now install core + each plugin
  separately. Acceptable trade for clean independent versioning.
- Some short-term tooling friction during the layout migration in Phase 1a.

### Reversibility

Medium.
- Reverting to a single package is mechanical but undoes independent
  versioning.
- Switching from git URL to PyPI is mechanical and routine.
- Replacing `uv` with another workspace tool (hatch envs, rye, plain pip)
  is mechanical — packages themselves are standard PEP 621.

## Open questions

- CI release flow (versioning, tagging, who publishes) — Phase 2.
- Plugin discovery for end users — `docs/plugins.md` enumerates the
  official set for now; a proper plugin directory is Phase 3.
- Whether to keep `pyproject.toml` at the legacy repo root after migration
  for git-URL `pip install` shortcut against the old path. Phase 1a will
  decide; default is **remove** to avoid two install paths.
