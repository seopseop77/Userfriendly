"""Hook return types: every plugin hook must return one of these."""

from dataclasses import dataclass


@dataclass
class Pass:
    """Continue to the next hook or the default action."""


@dataclass
class Block:
    """Emit a synthetic block response and skip forwarding.

    `plugin` is set by the host to the name of the plugin whose hook
    returned this Block; plugins should leave it at the default. The
    forwarder uses it to populate the `exchanges.blocked_by` column.
    """

    reason: str
    plugin: str = ""


@dataclass
class Transform:
    """Replace the request before forwarding (before_forward only)."""

    headers: dict[str, str] | None = None
    body: bytes | None = None


@dataclass
class Abort:
    """Terminate an in-progress response stream.

    `plugin` is set by the host to the name of the plugin whose hook
    returned this Abort; plugins should leave it at the default.
    """

    reason: str
    plugin: str = ""
