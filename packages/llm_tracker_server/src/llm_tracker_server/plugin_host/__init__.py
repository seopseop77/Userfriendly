"""Server-side plugin host (ADR-0017 / ADR-0019).

Loads plugins via entry points, validates manifests, wires per-plugin
egress clients, and dispatches the 8 lifecycle hooks with timeout +
exception isolation. ADR-0019 retired the L/A/R deployment-mode
taxonomy; the host on this side no longer accepts ``mode=`` or
``user_opted_in=`` constructor parameters, and the previously
mode-keyed capability-denial logic (``policy.py``) is gone. CP10 will
introduce per-plugin clamping via the ``min_content_level`` manifest
field.
"""

from .context import make_hook_context
from .hooks import HOOK_TIMEOUT, SHUTDOWN_HOOK_TIMEOUT
from .host import AuditWriter, PluginHost

__all__ = [
    "HOOK_TIMEOUT",
    "SHUTDOWN_HOOK_TIMEOUT",
    "AuditWriter",
    "PluginHost",
    "make_hook_context",
]
