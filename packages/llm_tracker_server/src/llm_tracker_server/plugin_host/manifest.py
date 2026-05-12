"""Plugin manifest discovery + validation.

Locates the plugin's ``plugin.toml`` via :mod:`importlib.resources` --
same shape as the local-sidecar host (the SDK owns the schema; the
server-side host only loads it).

The :data:`PluginManifest.allowed_modes` field is left on the SDK
schema but **ignored** by the server-side host. ADR-0019 retired the
L/A/R modes; future cleanup may remove the field from the schema
entirely, but until then the field passes validation and the host
treats it as a no-op so existing local-sidecar plugin manifests load
cleanly on the server.
"""

from __future__ import annotations

import importlib.resources
import tomllib

from llm_tracker_sdk.manifest import PluginManifest
from pydantic import ValidationError


def find_manifest(plugin_class: type) -> tuple[PluginManifest | None, str]:
    """Locate and parse ``plugin.toml`` from the plugin's top-level package.

    Returns ``(manifest, error_reason)``. ``error_reason`` is ``""`` on
    success.
    """
    pkg_name = plugin_class.__module__.split(".")[0]
    try:
        ref = importlib.resources.files(pkg_name) / "plugin.toml"
        with ref.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        return None, "plugin.toml not found"
    except Exception as exc:  # pragma: no cover - filesystem edge case
        return None, f"plugin.toml unreadable: {exc}"
    try:
        return PluginManifest.model_validate(data), ""
    except ValidationError as exc:
        return None, f"invalid manifest: {exc}"
