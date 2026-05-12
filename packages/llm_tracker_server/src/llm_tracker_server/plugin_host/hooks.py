"""Hook dispatch constants.

Two budgets are exposed:

* :data:`HOOK_TIMEOUT` -- per-exchange hook budget. A plugin exceeding
  this is treated as a fault, audit-logged, and the safe default is
  returned so the core pipeline is never interrupted.
* :data:`SHUTDOWN_HOOK_TIMEOUT` -- a longer budget for
  ``on_shutdown``. Sink plugins legitimately need more than 5 s to
  drain queues + retry backoffs; clipping shutdown to the
  per-exchange budget would silently drop records and audit
  ``plugin_fault timeout`` misleadingly. Inherited from the
  local-sidecar host (supabase_sink prerequisite, CP9 of the prior
  workstream).
"""

from __future__ import annotations

HOOK_TIMEOUT = 5.0
SHUTDOWN_HOOK_TIMEOUT = 30.0
