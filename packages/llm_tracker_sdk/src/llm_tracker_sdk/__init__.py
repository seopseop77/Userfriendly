"""llm-tracker-sdk — public plugin interface.

Phase 1a will populate this package with:
- BasePlugin abstract class
- @hook("name") decorator
- Hook return types: Pass, Block, Transform, Abort
- Capability token vocabulary
- plugin.toml Pydantic schema + validator
- Test harness: mock HookContext, mock EgressGuard, mock SQLite session
"""

__version__ = "0.0.1"
