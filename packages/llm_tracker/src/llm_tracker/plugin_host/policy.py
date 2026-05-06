"""Mode-by-mode capability policy (design.md §6.3.3, §8).

Per design.md §8, the operator-selected mode constrains which
capabilities a plugin may declare. Today the design only mode-gates
`egress_http` (denied in Mode L); the rest of the §6.3.3 vocabulary
is allowed in every mode. The table below is the single source of
truth for that policy and is consulted at plugin load time so a
denied plugin never reaches hook dispatch.

Runtime egress restrictions (Mode A's single-destination rule,
Mode R's manifest-driven allowlist) live in EgressGuard, not here —
this module is purely about *declaration-time* rejection.
"""

from __future__ import annotations

from llm_tracker_sdk.capabilities import EGRESS_HTTP

MODE_DENIED_CAPABILITIES: dict[str, frozenset[str]] = {
    "L": frozenset({EGRESS_HTTP}),
    "A": frozenset(),
    "R": frozenset(),
}


def denied_capabilities(mode: str, declared: list[str]) -> frozenset[str]:
    """Return the subset of `declared` that is forbidden under `mode`.

    Empty result means the plugin's declared capabilities are
    acceptable for this mode. An unknown mode raises `ValueError` —
    modes are a closed L/A/R enumeration, not a runtime fallback.
    """
    try:
        denied = MODE_DENIED_CAPABILITIES[mode]
    except KeyError as exc:
        raise ValueError(f"unknown mode: {mode!r}") from exc
    return frozenset(declared) & denied
