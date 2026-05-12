"""Per-plugin ``min_content_level`` clamp (ADR-0019 §Open questions / CP10).

Pins the manifest-driven shape of plugin visibility:

- A plugin declaring ``min_content_level = "L1"`` reads
  :meth:`HookContext.request_hash` / :meth:`request_length` but
  :meth:`request_text` returns ``None`` regardless of the level the
  plugin asks for.
- A plugin declaring ``min_content_level = "L3"`` sees the full body.

The clamp is bound per plugin inside the dispatch loop (same pattern
as ``ctx.egress``), so two plugins sharing one exchange context still
see different ceilings.
"""

from __future__ import annotations

import hashlib
from typing import Any

import llm_tracker_server.plugin_host.host as host_mod
import pytest
from llm_tracker_sdk import BasePlugin, Block, ContentLevel, HookContext, Pass
from llm_tracker_sdk.manifest import PluginManifest
from llm_tracker_server.plugin_host.host import PluginHost


@pytest.fixture
def captured_audit():
    rows: list[dict[str, Any]] = []

    async def writer(**kwargs: Any) -> None:
        rows.append(kwargs)

    writer.rows = rows  # type: ignore[attr-defined]
    return writer


class _L1Plugin(BasePlugin):
    """Declared at L1: should never see ``request_text``."""

    name = "plugin_l1"
    seen_text: str | None | object = "UNSET"
    seen_hash: str | None | object = "UNSET"
    seen_length: int | None | object = "UNSET"

    async def on_request_received(self, exchange_id: str, ctx: HookContext) -> Pass | Block:
        type(self).seen_text = ctx.request_text(ContentLevel.L3)
        type(self).seen_hash = ctx.request_hash()
        type(self).seen_length = ctx.request_length()
        return Pass()


class _L3Plugin(BasePlugin):
    """Declared at L3: should see the full body."""

    name = "plugin_l3"
    seen_text: str | None | object = "UNSET"

    async def on_request_received(self, exchange_id: str, ctx: HookContext) -> Pass | Block:
        type(self).seen_text = ctx.request_text(ContentLevel.L3)
        return Pass()


class _L1EP:
    name = "plugin_l1"

    def load(self) -> type[BasePlugin]:
        return _L1Plugin


class _L3EP:
    name = "plugin_l3"

    def load(self) -> type[BasePlugin]:
        return _L3Plugin


def _reset_captures() -> None:
    _L1Plugin.seen_text = "UNSET"
    _L1Plugin.seen_hash = "UNSET"
    _L1Plugin.seen_length = "UNSET"
    _L3Plugin.seen_text = "UNSET"


def _patch_load(monkeypatch: pytest.MonkeyPatch, manifests: dict[type, PluginManifest]) -> None:
    monkeypatch.setattr(host_mod, "entry_points", lambda **_kw: [_L1EP(), _L3EP()])
    monkeypatch.setattr(
        host_mod,
        "find_manifest",
        staticmethod(lambda cls: (manifests[cls], "")),
    )


async def test_l1_plugin_cannot_read_request_text(monkeypatch, captured_audit):
    """L1 plugin sees ``request_text() is None`` and the L1 hash/length escape hatch."""
    _reset_captures()
    body = b"sensitive prompt body"
    _patch_load(
        monkeypatch,
        {
            _L1Plugin: PluginManifest(
                name="plugin_l1",
                version="0.1.0",
                allowed_modes=["L", "A", "R"],
                min_content_level="L1",
            ),
            _L3Plugin: PluginManifest(
                name="plugin_l3",
                version="0.1.0",
                allowed_modes=["L", "A", "R"],
                min_content_level="L3",
            ),
        },
    )

    host = PluginHost(audit_writer=captured_audit)
    await host.load_plugins()
    host.begin_exchange("ex-clamp-l1", request_body=body)
    await host.on_request_received("ex-clamp-l1")

    assert _L1Plugin.seen_text is None
    assert _L1Plugin.seen_hash == hashlib.sha256(body).hexdigest()
    assert _L1Plugin.seen_length == len(body)


async def test_l3_plugin_sees_request_text(monkeypatch, captured_audit):
    """L3 plugin sees the full decoded body."""
    _reset_captures()
    body = b"sensitive prompt body"
    _patch_load(
        monkeypatch,
        {
            _L1Plugin: PluginManifest(
                name="plugin_l1",
                version="0.1.0",
                allowed_modes=["L", "A", "R"],
                min_content_level="L1",
            ),
            _L3Plugin: PluginManifest(
                name="plugin_l3",
                version="0.1.0",
                allowed_modes=["L", "A", "R"],
                min_content_level="L3",
            ),
        },
    )

    host = PluginHost(audit_writer=captured_audit)
    await host.load_plugins()
    host.begin_exchange("ex-clamp-l3", request_body=body)
    await host.on_request_received("ex-clamp-l3")

    assert _L3Plugin.seen_text == body.decode()


async def test_loaded_plugins_payload_reports_min_content_level(monkeypatch, captured_audit):
    """ADR-0014 introspection exposes each plugin's declared level."""
    _reset_captures()
    _patch_load(
        monkeypatch,
        {
            _L1Plugin: PluginManifest(
                name="plugin_l1",
                version="0.1.0",
                allowed_modes=["L", "A", "R"],
                min_content_level="L1",
            ),
            _L3Plugin: PluginManifest(
                name="plugin_l3",
                version="0.1.0",
                allowed_modes=["L", "A", "R"],
                min_content_level="L3",
            ),
        },
    )

    host = PluginHost(audit_writer=captured_audit)
    await host.load_plugins()

    view = host.loaded_plugins()
    by_name = {row["name"]: row for row in view}
    assert by_name["plugin_l1"]["min_content_level"] == "L1"
    assert by_name["plugin_l3"]["min_content_level"] == "L3"


def test_manifest_min_content_level_defaults_to_l3():
    """Pre-CP10 manifests (no field declared) inherit the L3 default."""
    manifest = PluginManifest(
        name="legacy",
        version="0.1.0",
        allowed_modes=["L", "A", "R"],
    )
    assert manifest.min_content_level == ContentLevel.L3


def test_manifest_min_content_level_rejects_unknown_string():
    """Typos in ``min_content_level`` fail manifest validation, not at runtime."""
    with pytest.raises(ValueError, match="Unknown min_content_level"):
        PluginManifest(
            name="bad",
            version="0.1.0",
            allowed_modes=["L", "A", "R"],
            min_content_level="L4",
        )
