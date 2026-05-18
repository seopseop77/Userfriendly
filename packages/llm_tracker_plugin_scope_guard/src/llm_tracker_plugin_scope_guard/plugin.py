"""scope_guard entry point — async monitor on ``on_persisted`` (ADR-0030 §D1).

This module is the entry point referenced from ``pyproject.toml``. CP2
ships the class skeleton so the host can load the manifest and stamp
``llm_tracker_plugin_scope_guard`` into the audit-log row at startup.
The real pipeline (semantic chunker, OpenAI clients, max-cosine query,
``scope_alerts`` writer) lands across CP3..CP6.
"""

from __future__ import annotations

import structlog
from llm_tracker_sdk import BasePlugin, HookContext


class ScopeGuard(BasePlugin):
    """ADR-0030 §D1 — observe-only ``on_persisted`` monitor."""

    name = "scope_guard"

    def __init__(self) -> None:
        self._log = structlog.get_logger("scope_guard")

    async def on_persisted(self, exchange_id: str, ctx: HookContext) -> None:
        # CP3..CP6 wire in chunker, embedding, pipeline, and storage.
        # CP2's skeleton no-ops so the host's load + audit path can be
        # exercised before the runtime infrastructure exists.
        return None
