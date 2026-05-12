"""Request-scoped audit context (CP9 plumbing for ADR-0018 + ADR-0020).

CP8 lifted the :class:`~llm_tracker_server.plugin_host.host.PluginHost`'s
audit-row writer to an injected callable so storage could be decoupled
from the host. CP9 supplies the production writer: every audit row
needs ``org_id`` (CP4 NOT NULL constraint + CP5 RLS context), and that
identity lives on the per-request :class:`AsyncSession` opened by
:class:`~llm_tracker_server.auth.AuthMiddleware`.

The host is a single shared instance across the FastAPI app; we can't
construct a different writer per request without touching ``host.py``.
The :class:`contextvars.ContextVar` below threads the per-request
``(session, org_id)`` through any audit call made *within* the request
scope — and degrades to a silent no-op outside it so lifecycle audits
fired from :func:`PluginHost.on_init` / :func:`PluginHost.on_shutdown`
don't crash trying to write a row with no org. (Lifecycle audit
emission is a deferred Phase-3c carry-over; the call sites are still
in place so a later checkpoint can light them up.)

The :func:`bind_request_context` ``with`` block is entered twice per
request — once around the pre-streaming hook dispatches in
``forward_request`` and once at the top of the response generator,
because the outer block exits when ``forward_request`` returns the
:class:`StreamingResponse` but the generator runs after that. Sync
``with`` keeps the contextvar bound across the awaits inside.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class RequestAuditContext:
    session: AsyncSession
    org_id: uuid.UUID


_current: ContextVar[RequestAuditContext | None] = ContextVar(
    "llm_tracker_server.audit_context",
    default=None,
)


@contextmanager
def bind_request_context(session: AsyncSession, org_id: uuid.UUID) -> Iterator[None]:
    """Bind ``(session, org_id)`` for any audit call made inside the ``with``."""
    token = _current.set(RequestAuditContext(session=session, org_id=org_id))
    try:
        yield
    finally:
        _current.reset(token)


def get_request_context() -> RequestAuditContext | None:
    """Return the active context or ``None`` outside any request scope."""
    return _current.get()


async def session_bound_audit_writer(**kwargs: object) -> None:
    """Production audit writer for :class:`PluginHost` / :class:`EgressGuard`.

    Reads the request-scoped contextvar and writes an
    :class:`~llm_tracker_server.storage.AuditLog` row carrying
    ``org_id = ctx.org_id`` through ``ctx.session``. Silently skips
    when no request context is bound (lifecycle / background events
    fired outside a request).
    """
    ctx = _current.get()
    if ctx is None:
        return
    # Imported lazily so this module stays import-safe even if a test
    # mocks :mod:`llm_tracker_server.storage`.
    from llm_tracker_server.storage.audit import write_audit

    await write_audit(ctx.session, org_id=ctx.org_id, **kwargs)  # type: ignore[arg-type]
