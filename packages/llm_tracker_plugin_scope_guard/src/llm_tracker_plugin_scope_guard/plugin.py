"""scope_guard entry point — async monitor on ``on_persisted`` (ADR-0030 §D1).

Wiring (CP5; provider rev ADR-0031):

* ``on_init`` reads ``GEMINI_API_KEY`` + the plugin's env-tunable knobs
  (``LLMTRACK_PLUGIN_SCOPE_GUARD_*``), constructs the two Gemini clients
  on top of the host-injected :class:`EgressClient`, and opens an
  ``AsyncEngine`` against ``LLMTRACK_DATABASE_URL``. Anything missing
  → ``structlog.warning`` + the plugin disables itself for this process
  (ADR-0030 §D1 is observe-only; "do nothing" is the right degraded
  state, and ADR-0030 §D9 — as amended by ADR-0031 §D4 — mandates the
  silent no-op when ``GEMINI_API_KEY`` is unset).
* ``on_persisted`` extracts the user-initiated message text per ADR-0030
  §D6, runs :func:`.pipeline.evaluate` over the org's ``scope_chunks``
  corpus, and writes one row to ``scope_alerts``.

Constructor injection (``session_factory``, ``embed_client``,
``judge_client``, ``thresholds``, ``window``) lets the integration test
swap in a role-wrapped factory plus deterministic embedding / judge
stubs without touching the network. ``on_init`` only fills in fields
that were not injected, so a fully-injected plugin (test path) ignores
env vars entirely.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import structlog
from llm_tracker_sdk import BasePlugin, HookContext
from llm_tracker_sdk.egress import EgressDenied
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from .embeddings import EmbeddingClient, EmbeddingError
from .judge import JudgeClient, JudgeError
from .pipeline import ScopeEvaluation, Thresholds, evaluate
from .storage import SessionFactory, insert_alert, select_top_chunks_by_cosine

DATABASE_URL_ENV = "LLMTRACK_DATABASE_URL"
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
THRESHOLD_ENV = "LLMTRACK_PLUGIN_SCOPE_GUARD_THRESHOLD"
BAND_ENV = "LLMTRACK_PLUGIN_SCOPE_GUARD_AMBIGUOUS_BAND"
WINDOW_ENV = "LLMTRACK_PLUGIN_SCOPE_GUARD_WINDOW"
JUDGE_TOP_K_ENV = "LLMTRACK_PLUGIN_SCOPE_GUARD_JUDGE_TOP_K"


def _build_message_text(request_json: str, window: int) -> str | None:
    """ADR-0030 §D6 message-input construction.

    1. system-reminder text from the *first* user turn only (subsequent
       turns repeat the same Claude Code project context; one copy is
       signal-bearing, more would just inflate token count).
    2. User-initiated text from every user turn — content blocks with
       ``type="text"`` whose text does *not* start with
       ``<system-reminder>`` or ``<system>``. Turns whose content is only
       ``tool_result`` blocks contribute nothing (internal tool-use, not
       user intent).
    3. Assistant text excluded; top-level ``system`` field excluded.
    4. Keep at most the most recent ``window`` user-initiated turns,
       time-ordered, joined with ``\\n\\n`` (after the first-turn
       system-reminder is prepended once).

    Returns ``None`` when the request body is unparseable or contains no
    user-initiated text after the rules above.
    """
    try:
        data = json.loads(request_json)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    messages = data.get("messages")
    if not isinstance(messages, list):
        return None

    system_reminder_parts: list[str] = []
    user_turn_texts: list[str] = []
    first_user_seen = False

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            blocks: list[Any] = [{"type": "text", "text": content}]
        elif isinstance(content, list):
            blocks = content
        else:
            continue

        is_first_user = not first_user_seen
        first_user_seen = True

        text_parts: list[str] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "text":
                continue
            text = block.get("text")
            if not isinstance(text, str):
                continue
            if text.startswith("<system-reminder>") or text.startswith("<system>"):
                if is_first_user:
                    system_reminder_parts.append(text)
                continue
            text_parts.append(text)

        if text_parts:
            user_turn_texts.append("\n\n".join(text_parts))

    user_turn_texts = user_turn_texts[-window:]
    pieces = system_reminder_parts + user_turn_texts
    if not pieces:
        return None
    return "\n\n".join(pieces)


class _EmbeddingProtocol:
    """Structural type the plugin needs from :class:`EmbeddingClient`."""

    async def embed(self, text: str) -> list[float]: ...  # pragma: no cover


class _JudgeProtocol:
    """Structural type the plugin needs from :class:`JudgeClient`."""

    async def judge(
        self, message_text: str, chunks: list[str]
    ) -> tuple[str, str]: ...  # pragma: no cover


class ScopeGuard(BasePlugin):
    """ADR-0030 §D1 — observe-only ``on_persisted`` monitor."""

    name = "scope_guard"

    def __init__(
        self,
        *,
        session_factory: SessionFactory | None = None,
        embed_client: _EmbeddingProtocol | None = None,
        judge_client: _JudgeProtocol | None = None,
        thresholds: Thresholds | None = None,
        window: int | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._embed_client = embed_client
        self._judge_client = judge_client
        # Any field left ``None`` at construction time is filled from env by
        # ``on_init``. Tests typically inject everything; the host wires the
        # Gemini clients + DB engine through ``on_init`` in production.
        self._thresholds: Thresholds | None = thresholds
        self._window: int | None = window
        self._engine: AsyncEngine | None = None
        self._engine_owned: bool = False
        self._log = structlog.get_logger("scope_guard")

    def _ready(self) -> bool:
        return (
            self._embed_client is not None
            and self._judge_client is not None
            and self._session_factory is not None
            and self._thresholds is not None
            and self._window is not None
        )

    async def on_init(self) -> None:
        if self._embed_client is None or self._judge_client is None:
            api_key = os.environ.get(GEMINI_API_KEY_ENV)
            if not api_key:
                self._log.warning("scope_guard.disabled", reason=f"{GEMINI_API_KEY_ENV} not set")
                return
            if self.egress is None:
                self._log.warning("scope_guard.disabled", reason="egress client not wired by host")
                return
            if self._embed_client is None:
                self._embed_client = EmbeddingClient(api_key=api_key, egress=self.egress)
            if self._judge_client is None:
                self._judge_client = JudgeClient(api_key=api_key, egress=self.egress)

        if self._session_factory is None:
            url = os.environ.get(DATABASE_URL_ENV)
            if not url:
                self._log.warning("scope_guard.disabled", reason=f"{DATABASE_URL_ENV} not set")
                return
            # Match ``llm_tracker_server.storage.make_engine`` semantics for
            # the Supabase pgbouncer transaction-mode pool (CP13-b).
            self._engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
            self._engine_owned = True
            self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

        if self._thresholds is None:
            self._thresholds = Thresholds(
                threshold=float(os.environ.get(THRESHOLD_ENV, "0.6")),
                band=float(os.environ.get(BAND_ENV, "0.1")),
                judge_top_k=int(os.environ.get(JUDGE_TOP_K_ENV, "3")),
            )
        if self._window is None:
            self._window = int(os.environ.get(WINDOW_ENV, "5"))

    async def on_shutdown(self) -> None:
        if self._engine_owned and self._engine is not None:
            await self._engine.dispose()

    async def on_persisted(self, exchange_id: str, ctx: HookContext) -> None:
        if not self._ready():
            return
        if ctx.org_id is None:
            self._log.warning(
                "scope_guard.skip",
                reason="ctx.org_id missing",
                exchange_id=exchange_id,
            )
            return
        request_text = ctx.request_text()
        if request_text is None:
            self._log.warning(
                "scope_guard.skip",
                reason="request_text unavailable",
                exchange_id=exchange_id,
            )
            return
        assert self._window is not None
        message_text = _build_message_text(request_text, window=self._window)
        if not message_text:
            self._log.info(
                "scope_guard.skip",
                reason="no user-initiated text in window",
                exchange_id=exchange_id,
            )
            return

        evaluation = await self._evaluate(message_text, ctx.org_id, exchange_id)
        if evaluation is None:
            return

        assert self._session_factory is not None
        try:
            await insert_alert(
                self._session_factory,
                exchange_id=exchange_id,
                org_id=ctx.org_id,
                stage=evaluation.stage,
                flagged=evaluation.flagged,
                max_similarity=evaluation.max_similarity,
                matched_chunk_id=evaluation.matched_chunk_id,
                stage2_verdict=evaluation.stage2_verdict,
                stage2_reason=evaluation.stage2_reason,
            )
        except Exception as exc:  # pragma: no cover — defensive
            self._log.warning(
                "scope_guard.insert_failed",
                error=str(exc),
                exchange_id=exchange_id,
            )

    async def _evaluate(
        self,
        message_text: str,
        org_id: uuid.UUID,
        exchange_id: str,
    ) -> ScopeEvaluation | None:
        """Wrap :func:`pipeline.evaluate` with failure-mode logging.

        Gemini failures (network / non-2xx / EgressDenied) degrade to "no
        alert this exchange" rather than crashing the host — ADR-0030 §D1
        observe-only contract.
        """
        assert self._embed_client is not None
        assert self._judge_client is not None
        assert self._session_factory is not None
        assert self._thresholds is not None

        async def _lookup(vec: list[float], k: int):
            return await select_top_chunks_by_cosine(
                self._session_factory,  # type: ignore[arg-type]
                org_id=org_id,
                vector=vec,
                k=k,
            )

        async def _embed(text: str) -> list[float]:
            return await self._embed_client.embed(text)  # type: ignore[union-attr]

        async def _judge(text: str, chunks: list[str]) -> tuple[str, str]:
            return await self._judge_client.judge(text, chunks)  # type: ignore[union-attr]

        try:
            result = await evaluate(
                message_text,
                embed=_embed,
                judge=_judge,  # type: ignore[arg-type]
                max_cosine_lookup=_lookup,
                thresholds=self._thresholds,
            )
        except (EmbeddingError, JudgeError) as exc:
            self._log.warning(
                "scope_guard.gemini_failure",
                error=str(exc),
                exchange_id=exchange_id,
            )
            return None
        except EgressDenied as exc:
            self._log.warning(
                "scope_guard.egress_denied",
                error=str(exc),
                exchange_id=exchange_id,
            )
            return None

        if result is None:
            self._log.info(
                "scope_guard.no_corpus",
                org_id=str(org_id),
                exchange_id=exchange_id,
            )
        return result
