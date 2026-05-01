"""llm_tracker_server — central ingest/rule/auth API for the llm-tracker project.

Stack: FastAPI + SQLAlchemy 2.0 + Alembic. DB is plain Postgres (Supabase for the
demo, swappable via DATABASE_URL). Hosted on Fly.io. See ADR-0004 and
docs/design.md §11. See /CLAUDE.md for working conventions.
"""

__version__ = "0.0.1"
