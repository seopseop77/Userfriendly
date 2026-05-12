"""Server-side egress allowlist + per-plugin HTTP client (ADR-0015).

ADR-0019 retired the L/A/R deployment-mode taxonomy: the guard no
longer mode-gates anything. The enforcement surface that remains is
the per-plugin manifest allowlist (capability declaration + exact-URL
match) plus the audit-log trail. Plugin host wires a per-plugin
:class:`HostEgressClient` over this guard at load time so background
tasks can call ``fetch`` outside any hook with stable attribution.
"""

from .client import HostEgressClient
from .guard import AuditWriter, EgressGuard

__all__ = ["AuditWriter", "EgressGuard", "HostEgressClient"]
