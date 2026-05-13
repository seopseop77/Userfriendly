# ADR-0025 · Thin local agent — language & distribution: Python CLI

- **Status**: Accepted
- **Date**: 2026-05-13
- **Author**: Claude Cowork (decision) / Claude Code (drafting)
- **Related**: ADR-0017 §Open questions (Phase-3a item #4),
  ADR-0024 (fallback policy), `docs/roadmap.md#3b`,
  `docs/worklog/2026-05-13-phase3b-agent.md`

## Context

The thin local agent (Phase 3b deliverable) must be installed on every
team member's machine. Its single job is to set
`ANTHROPIC_BASE_URL=http://127.0.0.1:<local_port>` and run a tiny
local proxy that forwards Claude Code's requests to the central
server with the org's `X-LLM-Tracker-Token` injected.

Language and distribution channel together determine install friction
and maintenance overhead. Options span a familiar trade space:

- **Python CLI on PyPI** — same language as the server codebase.
  Requires Python 3.11+ on the user's machine; everyone on the team
  already has that for the server work.
- **Go single binary** — zero runtime dependency, smallest install
  friction, biggest *build* overhead. Cross-compile for macOS/Linux,
  ship via GitHub Releases or Homebrew. Implies a second language in
  the codebase.
- **Shell wrapper** — `bash` script that `curl`s a forwarder. Smallest
  shipping artefact, but actually proxying SSE streaming bytes from
  bash means re-implementing the streaming forwarder in a non-async
  language. Quickly becomes worse than either alternative.

For the current team-demo phase the user count is single digits and
the deployment story is "internal-only, source available". External
distribution friction (PyPI cold install, Homebrew tap) is not the
binding constraint; *maintenance* and *consistency with the rest of
the codebase* are.

## Options considered

1. **Python CLI** packaged as `llm-tracker-agent`, installed via
   `pip install -e packages/llm_tracker_agent` (during development) or
   `pip install llm-tracker-agent` from PyPI (future). Entry point
   `claude-manage`. Reuses FastAPI + httpx + Typer already known by
   the team.
2. **Go binary** distributed via GitHub Releases / Homebrew. Single
   static binary, no runtime. Requires a Go build pipeline and a
   second-language port of the small forwarder.
3. **Shell wrapper** (`bash` + `curl`). Cheapest to ship, expensive to
   maintain once SSE streaming and error handling get involved.

## Decision

**Pick option 1 — Python CLI.** Three reasons:

1. **Language consistency.** The server is Python/FastAPI; the agent
   is a 100-line local proxy of the same shape. Keeping both in
   Python means one toolchain, one test framework, one set of patterns
   for HTTP/SSE handling. ADR-0024's fail-closed contract is trivial
   to implement with httpx exceptions; harder to keep aligned across
   two languages.
2. **Install path is acceptable for the audience.** Every team member
   already installs the server packages via `uv` / `pip`. Adding one
   more `pip install -e packages/llm_tracker_agent` is in the workflow
   they already run. PyPI publication is deferred until external
   users appear.
3. **Maintenance budget.** A Go port would carry its own dependency
   graph, build pipeline, release process, and security surface, all
   to save a `pip install` step that current users already perform
   weekly.

The entry point is `claude-manage` (not `llm-tracker-agent`), exposed
through `[project.scripts]` in the package's `pyproject.toml`. The
short name is intentional: users type it after `claude` and the verb
form ("manage") signals that it is the managed wrapper, not a
replacement.

## Consequences

- **Enables**: a Phase 3b deliverable shipped in days, not weeks; tests
  that share fixtures with the server suite; a single language story
  for the project.
- **Forecloses**: zero-dependency installation. Users without Python
  3.11+ cannot run the agent; for the team-demo audience this is not
  a real constraint.
- **Reversibility**: medium. A Go rewrite later is mechanically
  straightforward — the agent stays under ~200 lines — but does
  require a new release pipeline. The public CLI surface
  (`claude-manage setup` + default command) is the contract that must
  be preserved across any rewrite; ADR.

## Open questions

- **Future distribution channel** (PyPI vs. internal index vs.
  Homebrew tap) when external users arrive. Out of scope until that
  audience exists.

## Settles

Phase-3a item #4 (local agent language / distribution) from ADR-0017
§Open questions and `docs/roadmap.md#3a`.
