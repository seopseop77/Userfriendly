"""End-to-end integration test for the supabase_sink plugin.

Wires `PluginHost` + `EgressGuard` + `HostEgressClient` + the live
`SupabaseSinkPlugin` together against a stubbed Anthropic upstream
(provided by feeding SSE chunks straight into the host's
`on_response_chunk` dispatcher) and a stubbed Supabase upstream
(`httpx.MockTransport`). Pins three end-to-end shapes:

1. Happy path (Mode R + opted_in) — record arrives at PostgREST with
   the expected URL/headers/body and the audit log shows
   `egress_attempt outcome=ok`.
2. Negative — the manifest's `egress_destinations` doesn't list the
   env URL, EgressGuard denies, no POST is made, `egress_blocked`
   audit row appears with the right reason.
3. Mode L safety — the manifest declares `egress_http`, which Mode L
   denies at load time, so the plugin never appears in
   `loaded_plugins()` and a `capability_denied` audit row is written.
"""

from __future__ import annotations

import json

import httpx
import llm_tracker.plugin_host.host as host_mod
import pytest
from llm_tracker.egress_guard.guard import EgressGuard
from llm_tracker.plugin_host.host import PluginHost
from llm_tracker.storage.models import AuditLog, Base
from llm_tracker_plugin_supabase_sink import SupabaseSinkPlugin
from llm_tracker_sdk.manifest import PluginManifest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

URL = "https://qdcixbwwlsnkekabavmj.supabase.co/rest/v1/exchanges"
SUPABASE_KEY_ENV = "LLMTRACK_PLUGIN_SUPABASE_SINK_KEY"
SUPABASE_URL_ENV = "LLMTRACK_PLUGIN_SUPABASE_SINK_URL"


# -- fixtures --------------------------------------------------------------


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _supabase_sink_manifest(*, destinations: list[str] | None = None) -> PluginManifest:
    return PluginManifest(
        name="supabase_sink",
        version="0.1.0",
        hooks=[
            "on_init",
            "on_response_chunk",
            "on_response_complete",
            "on_shutdown",
        ],
        capabilities=[
            "read_request_metadata",
            "read_request_content",
            "read_response_metadata",
            "read_response_content",
            "egress_http",
        ],
        egress_destinations=destinations or [URL],
        allowed_modes=["R"],
        db_namespace="supabase_sink",
    )


class _StubEP:
    """Single-plugin entry-point stub so the test sees only supabase_sink."""

    name = "supabase_sink"

    def load(self):
        return SupabaseSinkPlugin


def _wire_supabase_sink_only(monkeypatch, *, destinations: list[str] | None = None) -> None:
    """Monkey-patch entry_points + manifest so only the supabase_sink
    class loads, with the manifest we control."""
    monkeypatch.setattr(host_mod, "entry_points", lambda **_kw: [_StubEP()])
    manifest = _supabase_sink_manifest(destinations=destinations)
    monkeypatch.setattr(
        PluginHost,
        "_find_manifest",
        staticmethod(lambda _cls: (manifest, "")),
    )


def _request_body() -> bytes:
    return json.dumps(
        {
            "model": "claude-test",
            "messages": [{"role": "user", "content": "Hi"}],
        }
    ).encode("utf-8")


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


def _full_response_chunks() -> list[bytes]:
    return [
        _sse(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "m1",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-test",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": 11,
                        "output_tokens": 0,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
            },
        ),
        _sse(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        _sse(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hello!"},
            },
        ),
        _sse("content_block_stop", {"type": "content_block_stop", "index": 0}),
        _sse(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 1},
            },
        ),
        _sse("message_stop", {"type": "message_stop"}),
    ]


async def _audit(factory) -> list[AuditLog]:
    async with factory() as session:
        return list((await session.execute(select(AuditLog))).scalars())


# -- 1) happy path ---------------------------------------------------------


async def test_e2e_happy_path_records_a_postgrest_insert(monkeypatch, session_factory):
    """An exchange flows through the host into PostgREST, and the
    audit log records the egress attempt as `outcome=ok`."""
    _wire_supabase_sink_only(monkeypatch)
    monkeypatch.setenv(SUPABASE_URL_ENV, URL)
    monkeypatch.setenv(SUPABASE_KEY_ENV, "fake-service-role")

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(201, headers={}, content=b"")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        guard = EgressGuard(mode="R", session_factory=session_factory)
        host = PluginHost(
            mode="R",
            session_factory=session_factory,
            egress_guard=guard,
            http_client=http_client,
            user_opted_in=True,
        )
        await host.on_init()

        # Plugin loaded.
        assert {p["name"] for p in host.loaded_plugins()} == {"supabase_sink"}

        host.begin_exchange("ex-e2e", request_body=_request_body())
        for chunk in _full_response_chunks():
            await host.on_response_chunk("ex-e2e", chunk)
        await host.on_response_complete("ex-e2e")

        # Shutdown drains the flusher's queue (CP7's longer timeout
        # gives it the headroom it needs).
        await host.on_shutdown()

    # The HTTP transport saw one POST; verify URL/headers/body.
    assert len(captured) == 1
    req = captured[0]
    assert str(req.url) == URL
    assert req.method == "POST"
    assert req.headers["apikey"] == "fake-service-role"
    assert req.headers["Authorization"] == "Bearer fake-service-role"
    assert req.headers["Content-Type"] == "application/json"
    assert req.headers["Prefer"] == "resolution=ignore-duplicates"

    body = json.loads(req.content)
    assert isinstance(body, list) and len(body) == 1
    row = body[0]
    assert row["exchange_id"] == "ex-e2e"
    assert row["mode"] == "R"
    assert row["endpoint"] == "v1/messages"
    assert row["source"] == "supabase_sink/0.1.0"
    assert row["model_requested"] == "claude-test"
    assert row["model_served"] == "claude-test"
    assert row["stop_reason"] == "end_turn"
    assert row["input_tokens"] == 11
    assert row["output_tokens"] == 1
    assert row["request_text"] and "Hi" in row["request_text"]
    assert row["response_text"] == "Hello!"
    assert isinstance(row["raw_request"], dict)
    assert row["raw_request"]["model"] == "claude-test"
    assert isinstance(row["raw_response"], dict)
    assert row["raw_response"]["stop_reason"] == "end_turn"

    # Audit log: `egress_attempt outcome=ok` for plugin=supabase_sink.
    rows = await _audit(session_factory)
    egress_attempts = [r for r in rows if r.kind == "egress_attempt"]
    assert len(egress_attempts) == 1
    assert egress_attempts[0].outcome == "ok"
    assert egress_attempts[0].plugin == "supabase_sink"
    assert egress_attempts[0].destination == URL


# -- 2) negative — destination not in allowlist ----------------------------


async def test_e2e_destination_not_in_allowlist_blocks_post(monkeypatch, session_factory):
    """Manifest's `egress_destinations` does NOT list the env URL —
    EgressGuard denies, no POST is made, `egress_blocked` audit row
    is written with `reason=destination_not_in_allowlist`."""
    bad_destination = "https://wrong-host.test/rest/v1/exchanges"
    _wire_supabase_sink_only(monkeypatch, destinations=[bad_destination])
    # Env points at the *real* URL, but the manifest only allows the bad one.
    monkeypatch.setenv(SUPABASE_URL_ENV, URL)
    monkeypatch.setenv(SUPABASE_KEY_ENV, "fake-service-role")

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        guard = EgressGuard(mode="R", session_factory=session_factory)
        host = PluginHost(
            mode="R",
            session_factory=session_factory,
            egress_guard=guard,
            http_client=http_client,
            user_opted_in=True,
        )
        await host.on_init()

        host.begin_exchange("ex-blocked", request_body=_request_body())
        for chunk in _full_response_chunks():
            await host.on_response_chunk("ex-blocked", chunk)
        await host.on_response_complete("ex-blocked")
        await host.on_shutdown()

    # No POST hit the http transport — the guard denied first.
    assert captured == []

    rows = await _audit(session_factory)
    blocked = [r for r in rows if r.kind == "egress_blocked"]
    # The plugin's flusher exhausted its retry budget against the same
    # denial — accept >=1 row.
    assert len(blocked) >= 1
    assert blocked[0].plugin == "supabase_sink"
    assert blocked[0].destination == URL
    assert "destination_not_in_allowlist" in (blocked[0].detail_json or "")


# -- 3) Mode L safety ------------------------------------------------------


async def test_e2e_mode_l_rejects_plugin_at_load_time(monkeypatch, session_factory):
    """Mode L denies the `egress_http` capability at *load time*, so the
    plugin never reaches hook dispatch. Pinned by `loaded_plugins()`
    being empty + a `capability_denied` audit row."""
    _wire_supabase_sink_only(monkeypatch)
    monkeypatch.setenv(SUPABASE_URL_ENV, URL)
    monkeypatch.setenv(SUPABASE_KEY_ENV, "fake-service-role")

    # The transport must never be touched — assert below.
    transport = httpx.MockTransport(lambda _r: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as http_client:
        guard = EgressGuard(mode="L", session_factory=session_factory)
        host = PluginHost(
            mode="L",
            session_factory=session_factory,
            egress_guard=guard,
            http_client=http_client,
            user_opted_in=True,  # irrelevant in Mode L
        )
        await host.on_init()

        # Critical: plugin not loaded.
        assert host.loaded_plugins() == []

        # Even pretending to drive an exchange must not produce egress.
        host.begin_exchange("ex-modeL", request_body=_request_body())
        for chunk in _full_response_chunks():
            await host.on_response_chunk("ex-modeL", chunk)
        await host.on_response_complete("ex-modeL")
        await host.on_shutdown()

    rows = await _audit(session_factory)
    capability_denied = [r for r in rows if r.kind == "capability_denied"]
    assert len(capability_denied) == 1
    assert capability_denied[0].plugin == "supabase_sink"
    assert capability_denied[0].outcome == "denied"
    # And no `egress_attempt` rows at all — the plugin never got to call out.
    assert [r for r in rows if r.kind == "egress_attempt"] == []
