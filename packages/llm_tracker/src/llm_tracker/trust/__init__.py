"""Bundled trust registry for plugin manifest signature verification.

Per ADR-0008, the set of public keys trusted to sign plugin manifests
ships *inside* this core package as a frozen TOML at
`trust/keys.toml`. Updating the trust set (add/remove a developer) is
a core release operation, not a runtime config change.

`load_bundled_registry()` is the only public surface here. It reads
`keys.toml` from the package via `importlib.resources` so the lookup
works under both editable and installed layouts.
"""

from __future__ import annotations

import importlib.resources

from nacl.signing import VerifyKey

from ..plugin_host.signing import load_registry


def load_bundled_registry() -> dict[str, VerifyKey]:
    """Read `keys.toml` from this package and return `name -> VerifyKey`.

    Raises `ValueError` for an unparseable registry — the file ships
    inside the core package, so a malformed version is a distribution
    bug, not a runtime fallback (mirrors `signing.load_registry`).
    """
    keys_toml = importlib.resources.files(__package__).joinpath("keys.toml").read_bytes()
    return load_registry(keys_toml)
