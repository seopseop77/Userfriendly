"""llm_tracker_server — reference receiver app for Mode R deployments.

This is NOT a core component. The core framework (`llm_tracker`) does not depend
on this package. This app is the receiving side that pairs with the
`supabase_sink` reference plugin (Mode R only). It exposes ingest/auth APIs,
backed by Supabase Postgres, deployable to Fly.io.

See ADR-0007 (supersedes ADR-0004) and docs/design.md §13.1.
See /CLAUDE.md for working conventions.
"""

__version__ = "0.0.1"
