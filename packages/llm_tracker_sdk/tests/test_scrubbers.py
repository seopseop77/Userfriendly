"""Tests for `llm_tracker_sdk.scrubbers.scrub` (ADR-0029).

Pure string-in / string-out unit tests. The accessor-level wiring is
covered separately in :mod:`test_hook_context`.
"""

from __future__ import annotations

from llm_tracker_sdk.scrubbers import scrub

# -- no-op shapes --------------------------------------------------------


def test_empty_string_passes_through() -> None:
    assert scrub("") == ""


def test_text_without_patterns_unchanged() -> None:
    assert scrub("nothing sensitive here") == "nothing sensitive here"


def test_sk_after_dash_redacts_privacy_tilted() -> None:
    """Word boundary treats `-` as non-word, so `task-sk-abcdefgh` over-redacts.

    Documented privacy-tilted behaviour: false positives are preferred over
    leaking a real secret. The scrubber's docstring names this trade-off.
    """
    assert "[REDACTED:secret]" in scrub("task-sk-abcdefgh-not-a-key")


# -- sk- secrets ----------------------------------------------------------


def test_anthropic_api_key_redacted() -> None:
    out = scrub("key=sk-ant-api03-AbCdEfGhIjKlMnOpQrStUv-12345 trailing")
    assert "sk-ant" not in out
    assert "[REDACTED:secret]" in out
    assert out.endswith(" trailing")


def test_openai_style_sk_token_redacted() -> None:
    out = scrub("OPENAI_KEY=sk-proj-AbCdEfGhIjKlMnOp end")
    assert "sk-proj" not in out
    assert "[REDACTED:secret]" in out


def test_short_sk_value_below_min_length_not_redacted() -> None:
    """`sk-x` (1 char) is too short to be an API key -- avoids false positives."""
    assert scrub("sk-x and sk-abc") == "sk-x and sk-abc"


# -- lts_ tokens ----------------------------------------------------------


def test_lts_token_redacted() -> None:
    out = scrub("X-LLM-Tracker-Token: lts_test_token_abcdef")
    assert "lts_test_token" not in out
    assert "[REDACTED:token]" in out


def test_lts_token_with_dashes_redacted() -> None:
    out = scrub("token=lts_abcDEF12-34_56")
    assert "lts_abc" not in out
    assert "[REDACTED:token]" in out


# -- Bearer values --------------------------------------------------------


def test_bearer_value_redacted() -> None:
    out = scrub("Bearer abc.def-_+/=789")
    assert "abc.def" not in out
    assert "[REDACTED:bearer]" in out


def test_authorization_bearer_header_value_redacted_prefix_preserved() -> None:
    """The value half is replaced; the `Authorization:` prefix is kept intact."""
    out = scrub("Authorization: Bearer eyJhbGciOiJSUzI1NiIs")
    assert "eyJhbGci" not in out
    assert "Authorization: [REDACTED:bearer]" in out


def test_bearer_case_insensitive() -> None:
    assert "[REDACTED:bearer]" in scrub("BEARER ABC12345")
    assert "[REDACTED:bearer]" in scrub("bearer xyz09876")


def test_bearer_consumes_sk_value_inside() -> None:
    """A `Bearer sk-xxx` span becomes one bearer tag, not bearer + sk tag."""
    out = scrub("Authorization: Bearer sk-ant-api03-AbCdEfGhIj")
    assert out.count("[REDACTED:") == 1
    assert "[REDACTED:bearer]" in out


# -- emails ---------------------------------------------------------------


def test_email_redacted() -> None:
    out = scrub("Contact alice@example.com for details.")
    assert "alice@example" not in out
    assert "[REDACTED:email]" in out


def test_email_with_plus_and_dot() -> None:
    out = scrub("bob.smith+filter@sub.example.co.uk")
    assert "bob.smith" not in out
    assert "[REDACTED:email]" in out


# -- combined -------------------------------------------------------------


def test_multiple_patterns_in_one_string() -> None:
    raw = (
        "Authorization: Bearer eyJhbGci.AbC\n"
        "X-LLM-Tracker-Token: lts_abcDEF12345\n"
        "ANTHROPIC_API_KEY=sk-ant-api03-zzzAbCdEfGh\n"
        "Reply to ops@example.com."
    )
    out = scrub(raw)
    assert "eyJhbGci" not in out
    assert "lts_abc" not in out
    assert "sk-ant" not in out
    assert "ops@example" not in out
    assert out.count("[REDACTED:bearer]") == 1
    assert out.count("[REDACTED:token]") == 1
    assert out.count("[REDACTED:secret]") == 1
    assert out.count("[REDACTED:email]") == 1


def test_scrub_is_idempotent_on_already_scrubbed_text() -> None:
    once = scrub("Bearer abcdef12 + ops@example.com")
    twice = scrub(once)
    assert once == twice


# -- JSON-aware mode + orphan-backslash regression ------------------------


def test_scrub_json_body_remains_valid_json() -> None:
    """A JSON request body with an email inside a string value scrubs to
    valid JSON that still round-trips through json.loads."""
    import json as _json

    body = _json.dumps(
        {
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "email: alice@example.com"}],
                }
            ]
        }
    )
    out = scrub(body)
    # Output must be parseable JSON.
    parsed = _json.loads(out)
    assert parsed["messages"][0]["content"][0]["text"] == "email: [REDACTED:email]"


def test_scrub_json_orphan_backslash_regression() -> None:
    """Live 2026-05-19 bug: the email regex consumed the ``t`` of a ``\\t``
    JSON escape (word boundary between ``\\`` and ``t``), leaving the
    backslash orphaned in front of ``[REDACTED:email]`` -- producing the
    invalid JSON escape sequence ``\\[``. Operating on JSON-decoded values
    avoids the hazard entirely; the output must round-trip and must not
    contain a backslash followed immediately by ``[``.
    """
    import json as _json

    # Source line content after Read tool: literal tab then an email.
    raw_text = "77\ttest_user@example.com\n78\tasync def ..."
    body = _json.dumps({"messages": [{"role": "user", "content": raw_text}]})
    # Confirm the input has the hazardous shape (`\t` before the email).
    assert "\\ttest_user@example.com" in body
    out = scrub(body)
    # Must round-trip as JSON (the failure mode wrote `\[REDACTED:email]`
    # which fails any ::jsonb cast or strict json.loads in some runtimes).
    parsed = _json.loads(out)
    user_text = parsed["messages"][0]["content"]
    assert "[REDACTED:email]" in user_text
    assert "test_user@example.com" not in user_text
    # Defensive: there must be no `\[` substring (single-backslash-bracket)
    # anywhere in the serialised output.
    assert "\\[" not in out  # this checks the literal 2-char `\[`


def test_scrub_falls_back_to_text_for_non_json_input() -> None:
    """Plain text input (no JSON shape) still goes through the flat-text
    rules. Smoke-checks the fallback branch."""
    out = scrub("contact alice@example.com")
    assert "[REDACTED:email]" in out
    assert "alice@example" not in out
