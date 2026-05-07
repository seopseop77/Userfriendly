"""Mode-R reference upload sink for llm-tracker (ADR-0007).

End-to-end: per-exchange the plugin
1. accumulates the streamed Anthropic response via `ResponseAssembler`,
2. on `on_response_complete` builds an `ExchangeRecord` from the cached
   request body + assembled response + usage, and enqueues it,
3. a background flusher batches up to N records (or T seconds) and
   POSTs them to PostgREST through `ctx.egress` (i.e. EgressGuard).

Consent stance (ADR-0006 + ADR-0016): the plugin uploads *only* when
`ctx.user_opted_in` is True. Without opt-in, the plugin loads but
silently no-ops on every exchange — explicit opt-in is required for
prompt/response text to leave the proxy.

Operator-facing config (env, prefix `LLMTRACK_PLUGIN_SUPABASE_SINK_`):
- `URL`: full PostgREST endpoint, e.g.
  `https://<project>.supabase.co/rest/v1/exchanges`
- `KEY`: Supabase service_role key. Read each call by the headers
  factory; never stored as a string on the client.

If either is missing at `on_init` time, the plugin loads but disables
itself. Audit log records this as a warning so the operator can spot
the misconfiguration.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import structlog
from llm_tracker_sdk import BasePlugin, HookContext, Pass

from .client import ExchangeRecord, SubmitOutcome, SupabaseSinkClient
from .parser import ResponseAssembler, extract_request_text

URL_ENV = "LLMTRACK_PLUGIN_SUPABASE_SINK_URL"
KEY_ENV = "LLMTRACK_PLUGIN_SUPABASE_SINK_KEY"

SOURCE = "supabase_sink/0.1.0"

# v0.1: Anthropic Messages API only. The `endpoint` column is mostly a
# forensics aid; expose via HookContext when a second adapter lands.
DEFAULT_ENDPOINT = "v1/messages"

# Flusher tunables — small enough to feel responsive in a CLI session,
# large enough to amortise HTTP overhead during a multi-turn chat.
DEFAULT_BATCH_SIZE = 8
DEFAULT_BATCH_INTERVAL_S = 2.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE_S = 0.5

_log = structlog.get_logger(__name__)


@dataclass
class _ExchangeState:
    """Per-exchange state captured at first chunk + needed at flush time."""

    session_id: str
    mode: str
    ts_started_ms: int
    request_text: str
    raw_request: dict[str, Any] | None
    assembler: ResponseAssembler


class SupabaseSinkPlugin(BasePlugin):
    """Phase-2 reference Mode-R sink.

    Tests inject a `client=` to bypass env wiring; production lets
    `on_init` build one from `URL_ENV` / `KEY_ENV`.
    """

    name = "supabase_sink"

    def __init__(
        self,
        *,
        client: SupabaseSinkClient | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        batch_interval_s: float = DEFAULT_BATCH_INTERVAL_S,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_base_s: float = DEFAULT_BACKOFF_BASE_S,
        sleep: Any = asyncio.sleep,
    ) -> None:
        self._client_override = client
        self._client: SupabaseSinkClient | None = client
        self._batch_size = batch_size
        self._batch_interval_s = batch_interval_s
        self._max_attempts = max_attempts
        self._backoff_base_s = backoff_base_s
        # Pluggable for tests so a fast-test doesn't actually sleep
        # 0.5/1/2 seconds during retry.
        self._sleep = sleep
        self._states: dict[str, _ExchangeState] = {}
        self._queue: asyncio.Queue[ExchangeRecord | None] = asyncio.Queue()
        self._flusher_task: asyncio.Task[None] | None = None
        self._enabled = False

    # -- lifecycle --------------------------------------------------------

    async def on_init(self) -> None:
        # If a test injected a client, trust it and skip env wiring.
        if self._client_override is not None:
            self._enabled = True
            self._flusher_task = asyncio.create_task(self._flusher())
            return

        url = os.environ.get(URL_ENV)
        key = os.environ.get(KEY_ENV)
        if not url or not key:
            _log.warning(
                "supabase_sink disabled: missing env",
                missing=[name for name, val in ((URL_ENV, url), (KEY_ENV, key)) if not val],
            )
            return
        if self.egress is None:
            _log.warning("supabase_sink disabled: no egress client wired by host")
            return

        self._client = SupabaseSinkClient(
            url=url,
            # Read the key fresh each call — never store it as a string
            # attribute on the client (CLAUDE.md §7 + ADR-0016 critic note).
            headers_factory=_make_headers_factory(),
            egress=self.egress,
        )
        self._enabled = True
        self._flusher_task = asyncio.create_task(self._flusher())

    async def on_shutdown(self) -> None:
        if self._flusher_task is None:
            return
        # Sentinel tells the flusher to drain and exit.
        await self._queue.put(None)
        try:
            await self._flusher_task
        except Exception as exc:
            _log.error("supabase_sink flusher exited with error", error=repr(exc))
        finally:
            self._flusher_task = None
            self._enabled = False
            self._states.clear()

    # -- per-exchange hooks ----------------------------------------------

    async def on_response_chunk(self, exchange_id: str, chunk: bytes, ctx: HookContext) -> Pass:
        if not self._enabled or not ctx.user_opted_in:
            return Pass()
        state = self._states.get(exchange_id)
        if state is None:
            request_text, raw_request = extract_request_text(ctx._raw_request_body)
            state = _ExchangeState(
                session_id=ctx.session_id,
                mode=ctx.mode,
                ts_started_ms=int(time.time() * 1000),
                request_text=request_text,
                raw_request=raw_request,
                assembler=ResponseAssembler(),
            )
            self._states[exchange_id] = state
        state.assembler.feed(chunk)
        return Pass()

    async def on_response_complete(self, exchange_id: str, ctx: HookContext) -> None:
        if not self._enabled:
            return
        state = self._states.pop(exchange_id, None)
        if state is None:
            # Either the exchange was opted-out (no state captured) or
            # no chunks ever arrived (Block / Abort path). Skip.
            return

        asm = state.assembler
        model_requested = (
            state.raw_request.get("model")
            if isinstance(state.raw_request, dict)
            and isinstance(state.raw_request.get("model"), str)
            else None
        )
        record = ExchangeRecord(
            exchange_id=exchange_id,
            session_id=state.session_id,
            ts_started_ms=state.ts_started_ms,
            mode=state.mode,
            endpoint=DEFAULT_ENDPOINT,
            source=SOURCE,
            model_requested=model_requested,
            model_served=asm.model,
            stop_reason=asm.stop_reason,
            input_tokens=asm.input_tokens or None,
            output_tokens=asm.output_tokens or None,
            cache_creation_input_tokens=asm.cache_creation_input_tokens or None,
            cache_read_input_tokens=asm.cache_read_input_tokens or None,
            request_text=state.request_text or None,
            response_text=asm.response_text or None,
            raw_request=state.raw_request,
            raw_response=asm.raw_response_summary(),
        )
        await self._queue.put(record)

    # -- background flusher ----------------------------------------------

    async def _flusher(self) -> None:
        while True:
            batch, shutdown = await self._collect_batch()
            if batch:
                await self._flush(batch)
            if shutdown:
                return

    async def _collect_batch(self) -> tuple[list[ExchangeRecord], bool]:
        """Wait for the first item, then top up the batch up to
        `batch_size` or until `batch_interval_s` elapses.

        Returns `(batch, shutdown)`. `shutdown` is True iff the sentinel
        appeared at any point — caller flushes the partial then exits.
        """
        first = await self._queue.get()
        if first is None:
            return [], True
        batch: list[ExchangeRecord] = [first]
        deadline = time.monotonic() + self._batch_interval_s
        while len(batch) < self._batch_size:
            timeout = max(0.0, deadline - time.monotonic())
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            except TimeoutError:
                break
            if item is None:
                return batch, True
            batch.append(item)
        return batch, False

    async def _flush(self, batch: list[ExchangeRecord]) -> None:
        if self._client is None:
            return
        for record in batch:
            outcome = SubmitOutcome.RETRY
            for attempt in range(self._max_attempts):
                outcome = await self._client.submit(record)
                if outcome in (SubmitOutcome.OK, SubmitOutcome.IDEMPOTENT_SKIP):
                    break
                if outcome is SubmitOutcome.TERMINAL_FAILURE:
                    _log.warning(
                        "supabase_sink dropping record (terminal failure)",
                        exchange_id=record.exchange_id,
                        attempt=attempt + 1,
                    )
                    break
                # RETRY — exp backoff
                await self._sleep(self._backoff_base_s * (2**attempt))
            else:
                _log.warning(
                    "supabase_sink dropping record (max attempts exceeded)",
                    exchange_id=record.exchange_id,
                    final_outcome=outcome.value,
                )


def _make_headers_factory():
    """Returns a callable that re-reads `KEY_ENV` on every call.

    Keeping the env read inside the closure means the key is never held
    as a string attribute on a long-lived object; if the operator
    rotates `LLMTRACK_PLUGIN_SUPABASE_SINK_KEY` and restarts the proxy,
    the new key flows through immediately.
    """

    def _factory() -> dict[str, str]:
        key = os.environ.get(KEY_ENV, "")
        return {"apikey": key, "Authorization": f"Bearer {key}"}

    return _factory


# structlog falls back to the stdlib logger if not configured; quiet it
# down so test runs don't spew warnings about a missing handler.
logging.getLogger(__name__).addHandler(logging.NullHandler())


__all__ = [
    "ExchangeRecord",
    "ResponseAssembler",
    "SubmitOutcome",
    "SupabaseSinkClient",
    "SupabaseSinkPlugin",
    "extract_request_text",
]
