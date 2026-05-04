"""Hook return types: every plugin hook must return one of these."""

from dataclasses import dataclass


@dataclass
class Pass:
    """Continue to the next hook or the default action."""


@dataclass
class Block:
    """Emit a synthetic block response and skip forwarding."""

    reason: str


@dataclass
class Transform:
    """Replace the request before forwarding (before_forward only)."""

    headers: dict[str, str] | None = None
    body: bytes | None = None


@dataclass
class Abort:
    """Terminate an in-progress response stream."""

    reason: str
