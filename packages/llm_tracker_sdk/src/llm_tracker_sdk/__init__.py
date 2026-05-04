"""llm-tracker-sdk — public plugin interface.

Plugin authors import from this package only; never from llm_tracker.*.
"""

from .hooks import Abort, Block, Pass, Transform
from .plugin import BasePlugin

__version__ = "0.0.1"
__all__ = ["Abort", "BasePlugin", "Block", "Pass", "Transform"]
