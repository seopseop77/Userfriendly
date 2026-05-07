"""llm-tracker-sdk — public plugin interface.

Plugin authors import from this package only; never from llm_tracker.*.
"""

from . import capabilities
from .egress import EgressClient, EgressDenied, EgressResponse
from .hook_context import HookContext
from .hooks import Abort, Block, Pass, Transform
from .levels import ContentLevel, degrade, effective_ceiling
from .manifest import PluginManifest
from .plugin import BasePlugin

__version__ = "0.0.1"
__all__ = [
    "Abort",
    "BasePlugin",
    "Block",
    "ContentLevel",
    "EgressClient",
    "EgressDenied",
    "EgressResponse",
    "HookContext",
    "Pass",
    "PluginManifest",
    "Transform",
    "capabilities",
    "degrade",
    "effective_ceiling",
]
