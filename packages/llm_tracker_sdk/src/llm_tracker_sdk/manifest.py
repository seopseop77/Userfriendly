"""plugin.toml schema and validator (design.md §6.3.1)."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

from .capabilities import ALL_CAPABILITIES

VALID_HOOKS: frozenset[str] = frozenset(
    {
        "on_init",
        "on_request_received",
        "before_forward",
        "on_upstream_response_start",
        "on_response_chunk",
        "on_response_complete",
        "on_persisted",
        "on_shutdown",
    }
)

VALID_MODES: frozenset[str] = frozenset({"L", "A", "R"})


class PluginManifest(BaseModel):
    name: str
    version: str
    description: str = ""
    hooks: list[str] = []
    capabilities: list[str] = []
    egress_destinations: list[Annotated[str, ...]] = []
    allowed_modes: list[str] = Field(..., min_length=1)
    db_namespace: str = ""

    @field_validator("hooks")
    @classmethod
    def _validate_hooks(cls, v: list[str]) -> list[str]:
        unknown = set(v) - VALID_HOOKS
        if unknown:
            raise ValueError(f"Unknown hooks: {sorted(unknown)}")
        return v

    @field_validator("capabilities")
    @classmethod
    def _validate_capabilities(cls, v: list[str]) -> list[str]:
        unknown = set(v) - ALL_CAPABILITIES
        if unknown:
            raise ValueError(f"Unknown capabilities: {sorted(unknown)}")
        return v

    @field_validator("allowed_modes")
    @classmethod
    def _validate_modes(cls, v: list[str]) -> list[str]:
        unknown = set(v) - VALID_MODES
        if unknown:
            raise ValueError(f"Unknown modes: {sorted(unknown)}")
        return v

    @model_validator(mode="after")
    def _egress_requires_capability(self) -> PluginManifest:
        if self.egress_destinations and "egress_http" not in self.capabilities:
            raise ValueError(
                "egress_destinations requires the 'egress_http' capability"
            )
        return self

    @classmethod
    def from_path(cls, path: Path) -> PluginManifest:
        """Load and validate a plugin.toml file."""
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        return cls.model_validate(data)
