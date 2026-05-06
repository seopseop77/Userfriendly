"""Tests for llm_tracker_sdk.manifest (PluginManifest schema + validator)."""

import pytest
from llm_tracker_sdk.manifest import PluginManifest
from pydantic import ValidationError


def _minimal() -> dict:
    return {"name": "test_plugin", "version": "0.1.0", "allowed_modes": ["L"]}


def test_minimal_manifest_valid():
    m = PluginManifest.model_validate(_minimal())
    assert m.name == "test_plugin"
    assert m.version == "0.1.0"
    assert m.hooks == []
    assert m.capabilities == []
    assert m.egress_destinations == []
    assert m.allowed_modes == ["L"]


def test_full_manifest_valid():
    data = {
        **_minimal(),
        "description": "A test plugin.",
        "hooks": ["before_forward", "on_persisted"],
        "capabilities": ["read_request_content", "block_request", "egress_http"],
        "egress_destinations": ["https://api.example.com"],
        "allowed_modes": ["A", "R"],
        "db_namespace": "test_plugin",
    }
    m = PluginManifest.model_validate(data)
    assert "egress_http" in m.capabilities
    assert m.db_namespace == "test_plugin"


def test_unknown_hook_rejected():
    with pytest.raises(ValidationError, match="Unknown hooks"):
        PluginManifest.model_validate({**_minimal(), "hooks": ["on_fake_hook"]})


def test_unknown_capability_rejected():
    with pytest.raises(ValidationError, match="Unknown capabilities"):
        PluginManifest.model_validate({**_minimal(), "capabilities": ["fly"]})


def test_unknown_mode_rejected():
    with pytest.raises(ValidationError, match="Unknown modes"):
        PluginManifest.model_validate({**_minimal(), "allowed_modes": ["X"]})


def test_egress_destinations_requires_capability():
    with pytest.raises(ValidationError, match="egress_http"):
        PluginManifest.model_validate(
            {**_minimal(), "egress_destinations": ["https://api.example.com"]}
        )


def test_missing_name_rejected():
    with pytest.raises(ValidationError):
        PluginManifest.model_validate({"version": "0.1.0", "allowed_modes": ["L"]})


def test_missing_allowed_modes_rejected():
    """ADR-0009: allowed_modes is required (no implicit any-mode default)."""
    with pytest.raises(ValidationError):
        PluginManifest.model_validate({"name": "test_plugin", "version": "0.1.0"})


def test_empty_allowed_modes_rejected():
    """ADR-0009: allowed_modes must be non-empty."""
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(
            {"name": "test_plugin", "version": "0.1.0", "allowed_modes": []}
        )
