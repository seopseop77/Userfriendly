"""Tests for the proxy's admin routes (ADR-0014)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from llm_tracker.proxy.app import admin_plugins, app


async def test_admin_plugins_returns_loaded_view():
    """Handler echoes whatever `plugin_host.loaded_plugins()` returns."""
    request = MagicMock()
    request.app.state.plugin_host = MagicMock()
    request.app.state.plugin_host.loaded_plugins.return_value = [
        {
            "name": "hello_world",
            "version": "0.0.1",
            "hooks": ["on_init"],
            "capabilities": [],
            "allowed_modes": ["L", "A", "R"],
        }
    ]

    response = await admin_plugins(request)

    assert response.status_code == 200
    body = json.loads(bytes(response.body))
    assert body == [
        {
            "name": "hello_world",
            "version": "0.0.1",
            "hooks": ["on_init"],
            "capabilities": [],
            "allowed_modes": ["L", "A", "R"],
        }
    ]


async def test_admin_plugins_empty_when_no_plugin_host():
    """If `plugin_host` is missing from app.state, the handler returns []."""
    request = MagicMock()
    # Replicate `getattr(state, "plugin_host", None)` returning None.
    delattr_target = MagicMock(spec=[])  # spec=[] means no attributes
    request.app.state = delattr_target

    response = await admin_plugins(request)

    assert response.status_code == 200
    assert json.loads(bytes(response.body)) == []


def test_admin_plugins_route_registered_before_catchall():
    """FastAPI dispatches in registration order; admin must precede catch-all.

    Pins ADR-0014's "register before catch-all" contract: if the catch-all
    were registered first, every `/admin/plugins` GET would be forwarded
    upstream as a passthrough request.
    """
    paths = [getattr(r, "path", None) for r in app.routes]
    admin_idx = paths.index("/admin/plugins")
    catchall_idx = paths.index("/{path:path}")
    assert admin_idx < catchall_idx
