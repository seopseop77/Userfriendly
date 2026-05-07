"""PostgREST-backed sink client for the supabase_sink plugin.

This module is the *only* place the plugin knows about its concrete sink
shape. Swapping PostgREST → Edge Function or a self-hosted gateway later
means rewriting this file (URL + auth-header construction + idempotency
mapping + status-code interpretation), not the plugin core (parser,
queue, lifecycle).

The `service_role` key is read from env *each call* via the injected
`headers_factory` callable, so the key is never stored as a string
attribute on the client (CLAUDE.md §7 — secrets never appear in logs;
attribute storage would survive past needed scope).
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from llm_tracker_sdk.egress import EgressClient, EgressDenied


@dataclass(frozen=True)
class ExchangeRecord:
    """One row destined for `public.exchanges`. Mirrors the CP4 schema."""

    exchange_id: str
    session_id: str
    ts_started_ms: int
    mode: str
    endpoint: str
    source: str
    model_requested: str | None = None
    model_served: str | None = None
    stop_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    request_text: str | None = None
    response_text: str | None = None
    raw_request: dict[str, Any] | None = None
    raw_response: dict[str, Any] | None = None

    def to_postgrest_row(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class SubmitOutcome(Enum):
    """Result of a single `submit` call.

    - `OK`: row accepted (HTTP 201 Created from PostgREST).
    - `IDEMPOTENT_SKIP`: duplicate `exchange_id` (PK conflict, HTTP 409
      with `Prefer: resolution=ignore-duplicates` headers); safe to
      treat as success on retry.
    - `RETRY`: transient failure (5xx, network); caller should backoff.
    - `TERMINAL_FAILURE`: 4xx other than 409, or `EgressDenied`. Won't
      succeed on retry; drop and audit.
    """

    OK = "ok"
    IDEMPOTENT_SKIP = "idempotent_skip"
    RETRY = "retry"
    TERMINAL_FAILURE = "terminal_failure"


class SupabaseSinkClient:
    """PostgREST insertion client.

    Vendor coupling is confined to this class. The plugin core treats it
    as an opaque submitter that maps `ExchangeRecord` → `SubmitOutcome`.
    """

    def __init__(
        self,
        *,
        url: str,
        headers_factory: Callable[[], Mapping[str, str]],
        egress: EgressClient,
    ) -> None:
        self._url = url
        self._headers_factory = headers_factory
        self._egress = egress

    async def submit(self, record: ExchangeRecord) -> SubmitOutcome:
        # PostgREST accepts both single-object and array bodies; we use
        # the array form so a future batch-of-N variant is a one-line
        # change (`json.dumps([rec.to_row() for rec in batch])`).
        body = json.dumps([record.to_postgrest_row()], default=str).encode("utf-8")
        headers = {
            **dict(self._headers_factory()),
            "Content-Type": "application/json",
            "Prefer": "resolution=ignore-duplicates",
        }
        try:
            resp = await self._egress.fetch(self._url, method="POST", headers=headers, body=body)
        except EgressDenied:
            return SubmitOutcome.TERMINAL_FAILURE

        return _interpret_status(resp.status_code)


def _interpret_status(status: int) -> SubmitOutcome:
    if status in (200, 201):
        return SubmitOutcome.OK
    if status == 409:
        # PK conflict on `exchange_id`. With
        # `Prefer: resolution=ignore-duplicates` PostgREST may surface
        # this as 200/201, but a stricter server config can still emit
        # 409 — treat it as idempotent success either way.
        return SubmitOutcome.IDEMPOTENT_SKIP
    if 500 <= status < 600:
        return SubmitOutcome.RETRY
    # 4xx other than 409: schema mismatch, malformed body, auth failure.
    # Won't succeed on retry without operator action.
    return SubmitOutcome.TERMINAL_FAILURE
