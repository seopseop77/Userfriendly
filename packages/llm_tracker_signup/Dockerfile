# Public-facing signup app image.
#
# Two-stage build, same shape as the proxy server's root-level
# Dockerfile but trimmed: signup pulls no SDK / plugin packages and
# does NOT need alembic shipped inside the image (the migration
# schema is owned by `llm_tracker_server`, applied via Supabase MCP).
#
# Build context: this directory (packages/llm_tracker_signup/), set
# by fly.toml's [build] block. The signup package has no
# cross-package import from the rest of the uv workspace, so the
# narrow context is sufficient.
#
# Build:   docker build -t llm-tracker-signup .
# Run:     docker run -e LLMTRACK_DATABASE_URL=postgresql+asyncpg://... \
#                    -e LLMTRACK_PROXY_SERVER_URL=https://... \
#                    -p 8000:8000 llm-tracker-signup

# ---------- builder ---------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml /build/pyproject.toml
COPY src            /build/src

RUN pip install /build

# ---------- runtime ---------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Non-root user, same convention as the proxy server image.
RUN groupadd --system app && useradd --system --gid app --no-create-home app

COPY --from=builder /opt/venv /opt/venv

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; \
sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "llm_tracker_signup.app:app", "--host", "0.0.0.0", "--port", "8000"]
