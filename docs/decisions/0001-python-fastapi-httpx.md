# ADR-0001 · Language and proxy framework: Python + FastAPI + httpx

- **Status**: Accepted
- **Date**: 2026-04-25
- **Author**: Claude Cowork (user-approved)
- **Related**: `docs/design.md §2, §6, §11`

## Context

This repository's role within the parent project is to build a local sidecar
that intercepts Claude Code's API traffic, observes it, and optionally
intervenes. The team prefers Python. The proxy must **forward HTTP SSE
streams with low latency while teeing concurrently**, and asyncio fits
naturally.

## Options considered

1. **Python + FastAPI + httpx**
   - Pros: team familiarity. `httpx.AsyncClient.stream()` works well for
     SSE tee. FastAPI's `StreamingResponse` for client-direction is
     straightforward. `respx` makes testing easy.
   - Cons: lower raw throughput than Node/Go. Not a problem for a
     single-user, single-agent local sidecar.

2. **Python + aiohttp (server + client in one)**
   - Pros: one dependency for both server and client.
   - Cons: less familiar than FastAPI in our team and the surrounding LLM
     ecosystem; weaker docs / typing story.

3. **Node/TypeScript + undici**
   - Pros: streaming/SSE is native; Anthropic's reference SDK is TS.
   - Cons: against the team's language preference; integration cost with
     metric-design teammate's stack.

4. **Go + net/http**
   - Pros: single binary deployment, low latency.
   - Cons: language preference; double stack with Python scrubbing/analytics
     code.

## Decision

**Option 1: Python 3.11+, FastAPI, httpx.**

- Aligns with team Python preference.
- httpx has clean stream support and a modern async model. `respx` covers
  unit and integration testing.
- For a research-scale local sidecar, throughput requirements are tiny;
  Python's overhead is negligible.
- Same language as the metric-design teammate's stack (pandas, sklearn).

## Consequences

- Official runtime: Python 3.11+.
- Server framework: FastAPI (+ uvicorn).
- Upstream HTTP: httpx (HTTP/2 enabled).
- CLI: Typer.
- Logging: structlog.
- Configuration: pydantic-settings.
- Local storage: SQLite (`sqlalchemy` + `aiosqlite` or `sqlite-utils`;
  re-decided in Phase 1).

### What we give up

- Whatever low-latency / single-binary advantages Node/Go would offer.
- We lose easy reuse of Anthropic's official TS SDK for parsing — but the
  wire format is JSON and re-implementing the parser is tractable.

### Reversibility

Medium. The proxy core itself is portable, but as the Python ecosystem
around scrub / upload / metrics grows in Phase 1+, swap cost rises sharply.
Therefore, **review one last time before Phase 1 closes**, and lock after
that.

## Open questions

None.
