"""Mode-R reference upload sink for llm-tracker (ADR-0007).

CP5 ships only the parser; the live `SupabaseSinkPlugin` class (queue,
flusher, lifecycle hooks) lands in CP6. The placeholder class below
keeps the package importable so the entry point resolves at host load
time, even before CP6 fills in the behaviour.
"""

from __future__ import annotations

from llm_tracker_sdk import BasePlugin

from .parser import ResponseAssembler, extract_request_text


class SupabaseSinkPlugin(BasePlugin):
    """Reference Mode-R sink. Implementation pending (CP6)."""

    name = "supabase_sink"


__all__ = [
    "ResponseAssembler",
    "SupabaseSinkPlugin",
    "extract_request_text",
]
