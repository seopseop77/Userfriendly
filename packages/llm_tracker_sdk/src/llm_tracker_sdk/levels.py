"""Content-level ladder + per-mode ceiling policy (design.md §7.1, §8).

Public SDK primitive — plugins import `ContentLevel` from here when
they call `HookContext.request_text(level=...)`. The math
(`effective_ceiling`, `degrade`) is exposed for the host's use; a
well-behaved plugin shouldn't need to call it directly.

Lives in the SDK package (not the core) so plugin authors can import
levels without crossing the `llm_tracker.*` boundary the SDK
docstring forbids.
"""

from __future__ import annotations

from enum import IntEnum


class ContentLevel(IntEnum):
    """Ordered ladder L0 < L1 < L2 < L3.

    L0  metadata only (token counts, model name, latency, tool names, status)
    L1  L0 + SHA-256 hashes of bodies and their lengths
    L2  L0 + scrubbed body (secrets/PII/paths/emails/IPs removed)
    L3  raw body (still scrubber-passed)
    """

    L0 = 0
    L1 = 1
    L2 = 2
    L3 = 3


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
