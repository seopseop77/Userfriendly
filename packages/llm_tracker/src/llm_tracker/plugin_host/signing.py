"""Manifest signature verification (ADR-0008).

Pure verification primitive. The host hands in the bytes of
`plugin.toml`, the bytes of the sibling `.sig` blob, and a registry
of trusted public keys. The verifier returns a typed `VerifyResult`
and never raises on bad input — operator-controlled file content
must not crash the loader.

Sub-decisions locked here (ADR-0008 §"What is deferred"):

- **Canonicalization**: byte-exact contents of `plugin.toml`. No
  parse/re-serialize round trip — that would couple verification to
  the TOML library's whitespace/quote conventions.
- **Signature blob format**: TOML with two fields,
  `signer` (string, must match a `name` in the registry) and
  `signature` (hex-encoded 64-byte ed25519 signature). Carrying the
  signer name lets us tell `signing_key_not_in_registry` apart from
  `signature_invalid` (ADR-0008's three failure reasons).
- **Registry file format**: TOML `[[key]]` array, each entry with
  `name` and `public_key` (hex of 32-byte ed25519 public key).

Storage location of the `.sig` file (sibling vs embedded vs
separate manifest), the signing CLI, and reference-plugin signing
are still deferred to the host-wiring checkpoint.
"""

from __future__ import annotations

import tomllib
from enum import StrEnum

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey


class VerifyResult(StrEnum):
    """ADR-0008 §"Hard reject on failure" enumerates these reasons."""

    VERIFIED = "verified"
    SIGNATURE_MISSING = "signature_missing"
    SIGNATURE_INVALID = "signature_invalid"
    SIGNING_KEY_NOT_IN_REGISTRY = "signing_key_not_in_registry"


def load_registry(toml_bytes: bytes) -> dict[str, VerifyKey]:
    """Parse a `keys.toml` blob into `name -> VerifyKey`.

    Raises `ValueError` for an unparseable registry — the registry
    ships inside the core package, so a malformed file is a
    distribution bug, not a runtime fallback.
    """
    try:
        data = tomllib.loads(toml_bytes.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"trust registry is not valid UTF-8 TOML: {exc}") from exc

    out: dict[str, VerifyKey] = {}
    for entry in data.get("key", []):
        try:
            name = entry["name"]
            pubkey_hex = entry["public_key"]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"registry entry missing field: {exc}") from exc
        try:
            out[name] = VerifyKey(bytes.fromhex(pubkey_hex))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"registry entry {name!r} has bad public_key: {exc}") from exc
    return out


def verify_manifest_signature(
    manifest_bytes: bytes,
    sig_blob: bytes | None,
    registry: dict[str, VerifyKey],
) -> tuple[VerifyResult, str | None]:
    """Verify `manifest_bytes` against `sig_blob` using `registry`.

    Returns (result, signer_name). `signer_name` is the registry key
    that succeeded on `VERIFIED`, or the asserted-but-unknown signer
    on `SIGNING_KEY_NOT_IN_REGISTRY`, or `None` otherwise.
    """
    if sig_blob is None:
        return VerifyResult.SIGNATURE_MISSING, None

    try:
        sig_data = tomllib.loads(sig_blob.decode("utf-8"))
        signer = sig_data["signer"]
        sig_hex = sig_data["signature"]
        signature = bytes.fromhex(sig_hex)
        if len(signature) != 64:
            raise ValueError("ed25519 signature must be 64 bytes")
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, KeyError, ValueError, TypeError):
        return VerifyResult.SIGNATURE_INVALID, None

    key = registry.get(signer)
    if key is None:
        return VerifyResult.SIGNING_KEY_NOT_IN_REGISTRY, signer

    try:
        key.verify(manifest_bytes, signature)
    except BadSignatureError:
        return VerifyResult.SIGNATURE_INVALID, signer
    return VerifyResult.VERIFIED, signer
