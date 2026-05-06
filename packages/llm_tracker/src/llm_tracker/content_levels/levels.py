"""Content-level ladder + per-mode ceiling policy.

Encodes the four levels from design.md §7.1 and the per-mode default /
opt-in ceilings. The ladder is comparable so callers can express
"degrade to at most X" as `min(level, ceiling)`.

This module is a pure primitive: it does not transform payloads, does
not consult plugin manifests, and is not yet wired into hook dispatch.
The hook-dispatch integration is a separate checkpoint (the payload
shape it must degrade is not yet modeled in the codebase).
"""

from __future__ import annotations

from enum import IntEnum


class ContentLevel(IntEnum):
    """Ordered ladder L0 < L1 < L2 < L3 (design.md §7.1).

    L0  metadata only (token counts, model name, latency, tool names, status)
    L1  L0 + SHA-256 hashes of bodies and their lengths
    L2  L0 + scrubbed body (secrets/PII/paths/emails/IPs removed)
    L3  raw body (still scrubber-passed)
    """

    L0 = 0
    L1 = 1
    L2 = 2
    L3 = 3


# Per-mode plugin-visible ceilings (design.md §7.1, §8).
#
# DEFAULT is what plugins see absent any per-task user consent.
# OPT_IN  is the elevated ceiling once the user opts a task in.
# In Modes L and A the user has no opt-in path, so OPT_IN == DEFAULT.

_DEFAULT_CEILING: dict[str, ContentLevel] = {
    "L": ContentLevel.L1,
    "A": ContentLevel.L0,
    "R": ContentLevel.L1,
}

_OPT_IN_CEILING: dict[str, ContentLevel] = {
    "L": ContentLevel.L1,
    "A": ContentLevel.L0,
    "R": ContentLevel.L3,
}


def effective_ceiling(mode: str, *, user_opted_in: bool = False) -> ContentLevel:
    """Highest content level a plugin may see in `mode`.

    Raises `ValueError` for an unknown mode — modes are a closed
    enumeration (L/A/R) and a typo is a programming error, not a
    runtime condition to silently fall back from.
    """
    table = _OPT_IN_CEILING if user_opted_in else _DEFAULT_CEILING
    try:
        return table[mode]
    except KeyError as exc:
        raise ValueError(f"unknown mode: {mode!r}") from exc


def degrade(level: ContentLevel, ceiling: ContentLevel) -> ContentLevel:
    """Return the lower of `level` and `ceiling` — never elevates."""
    return min(level, ceiling)
