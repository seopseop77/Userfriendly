# Central llm-tracker server image (Phase 3c CP12 / ADR-0022).
#
# Two-stage build:
#   1. builder  — pip-installs llm_tracker_sdk + llm_tracker_server into a
#                 dedicated venv at /opt/venv.
#   2. runtime  — copies the venv and the alembic assets into a slim image,
#                 runs uvicorn on :8080.
#
# Build:   docker build -t llm-tracker-server .
# Run:     docker run -e LLMTRACK_DATABASE_URL=postgresql+asyncpg://... \
#                     -p 8080:8080 llm-tracker-server
# Migrate: docker run --rm -e LLMTRACK_DATABASE_URL=... \
#                     llm-tracker-server alembic upgrade head

# ---------- builder ----------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install both workspace packages plus runtime deps that the server's
# pyproject.toml does not yet declare:
#   - `llm-tracker-sdk` — workspace member; the server imports from it
#     (forwarder.py, content_levels/levels.py) but the dep is implicit
#     via the uv workspace.
#   - `python-ulid` — used by storage/audit.py and proxy/forwarder.py;
#     present in dev because the local-sidecar `llm_tracker` package
#     provides it transitively, but absent in a server-only install.
# Both are tracked as worklog Suggestions for a proper pyproject fix.
COPY packages/llm_tracker_sdk    /build/packages/llm_tracker_sdk
COPY packages/llm_tracker_server /build/packages/llm_tracker_server

RUN pip install \
    python-ulid \
    /build/packages/llm_tracker_sdk \
    /build/packages/llm_tracker_server

# ---------- runtime ---------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    LLMTRACK_LOG_LEVEL=INFO

# Non-root user.
RUN groupadd --system app && useradd --system --gid app --no-create-home app

COPY --from=builder /opt/venv /opt/venv

# Alembic config + migration scripts must travel with the image so CP13's
# release-command migration runner can call `alembic upgrade head`. The
# script_location in alembic.ini is `%(here)s/alembic`, so they sit
# side-by-side under /app.
WORKDIR /app
COPY packages/llm_tracker_server/alembic.ini /app/alembic.ini
COPY packages/llm_tracker_server/alembic     /app/alembic

USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; \
sys.exit(0 if urllib.request.urlopen('http://localhost:8080/healthz', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "llm_tracker_server.app:app", "--host", "0.0.0.0", "--port", "8080"]
