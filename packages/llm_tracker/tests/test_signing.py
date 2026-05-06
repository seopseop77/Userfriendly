"""Unit tests for the manifest signature verifier (ADR-0008)."""

import pytest
from llm_tracker.plugin_host.signing import (
    VerifyResult,
    load_registry,
    verify_manifest_signature,
)
from nacl.signing import SigningKey

# -- helpers --------------------------------------------------------------


def _make_signer(name: str = "dev"):
    """Return (signer_name, signing_key, registry)."""
    sk = SigningKey.generate()
    registry = {name: sk.verify_key}
    return name, sk, registry


def _make_sig_blob(signer: str, signing_key: SigningKey, manifest_bytes: bytes) -> bytes:
    sig = signing_key.sign(manifest_bytes).signature
    return f'signer = "{signer}"\nsignature = "{sig.hex()}"\n'.encode()


# -- verifier outcomes -----------------------------------------------------


def test_verified_round_trip():
    name, sk, registry = _make_signer()
    manifest = b'name = "p"\nversion = "0.1.0"\n'
    sig_blob = _make_sig_blob(name, sk, manifest)

    result, signer = verify_manifest_signature(manifest, sig_blob, registry)

    assert result == VerifyResult.VERIFIED
    assert signer == name


def test_signature_missing_returns_missing():
    _, _, registry = _make_signer()
    manifest = b'name = "p"\n'

    result, signer = verify_manifest_signature(manifest, None, registry)

    assert result == VerifyResult.SIGNATURE_MISSING
    assert signer is None


def test_tampered_manifest_returns_invalid():
    name, sk, registry = _make_signer()
    manifest = b'name = "p"\nversion = "0.1.0"\n'
    sig_blob = _make_sig_blob(name, sk, manifest)

    tampered = manifest + b'capabilities = ["egress_http"]\n'
    result, signer = verify_manifest_signature(tampered, sig_blob, registry)

    assert result == VerifyResult.SIGNATURE_INVALID
    assert signer == name


def test_corrupted_signature_returns_invalid():
    name, _sk, registry = _make_signer()
    manifest = b'name = "p"\n'
    bad_sig_blob = (
        f'signer = "{name}"\n'
        f'signature = "{"00" * 64}"\n'  # well-formed hex, wrong content
    ).encode()

    result, _ = verify_manifest_signature(manifest, bad_sig_blob, registry)

    assert result == VerifyResult.SIGNATURE_INVALID


def test_unknown_signer_returns_key_not_in_registry():
    _, sk, _ = _make_signer("alice")
    manifest = b'name = "p"\n'
    # signer claims to be "bob"; alice's key signs but registry only knows "carol".
    foreign_registry = {"carol": SigningKey.generate().verify_key}
    sig_blob = _make_sig_blob("bob", sk, manifest)

    result, signer = verify_manifest_signature(manifest, sig_blob, foreign_registry)

    assert result == VerifyResult.SIGNING_KEY_NOT_IN_REGISTRY
    assert signer == "bob"


@pytest.mark.parametrize(
    "blob",
    [
        b"this is not toml [",  # malformed TOML
        b'signer = "dev"\n',  # missing signature field
        b'signature = "deadbeef"\n',  # missing signer field
        b'signer = "dev"\nsignature = "not hex"\n',  # bad hex
        b'signer = "dev"\nsignature = "abcd"\n',  # hex but not 64 bytes
        b"\xff\xfe\x00\x00",  # not utf-8
    ],
)
def test_malformed_sig_blob_returns_invalid(blob):
    _, _, registry = _make_signer()
    manifest = b'name = "p"\n'

    result, _ = verify_manifest_signature(manifest, blob, registry)

    assert result == VerifyResult.SIGNATURE_INVALID


# -- registry parsing -----------------------------------------------------


def test_load_registry_round_trip():
    sk = SigningKey.generate()
    pubkey_hex = bytes(sk.verify_key).hex()
    toml_bytes = (
        "[[key]]\n"
        f'name = "alice"\n'
        f'public_key = "{pubkey_hex}"\n'
    ).encode()

    registry = load_registry(toml_bytes)

    assert set(registry.keys()) == {"alice"}
    # The parsed VerifyKey must verify what alice signs.
    msg = b"hello"
    sig = sk.sign(msg).signature
    registry["alice"].verify(msg, sig)


def test_load_registry_empty_when_no_keys():
    assert load_registry(b"") == {}


def test_load_registry_rejects_non_utf8():
    with pytest.raises(ValueError, match="not valid UTF-8 TOML"):
        load_registry(b"\xff\xfe\x00\x00")


def test_load_registry_rejects_missing_field():
    toml_bytes = b'[[key]]\nname = "alice"\n'
    with pytest.raises(ValueError, match="missing field"):
        load_registry(toml_bytes)


def test_load_registry_rejects_bad_pubkey():
    toml_bytes = b'[[key]]\nname = "alice"\npublic_key = "not-hex"\n'
    with pytest.raises(ValueError, match="bad public_key"):
        load_registry(toml_bytes)
