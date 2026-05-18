"""Stage-2 LLM judge — Gemini ``gemini-2.5-flash`` (ADR-0031 §D2).

Egress flows through the same :class:`llm_tracker_sdk.egress.EgressClient`
as :mod:`.embeddings`, targeting
``https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent``.

ADR-0030 §Q4 — the prompt template is pinned as a module-top frozen
string so future tweaks are diff-visible. The judge instructs
``gemini-2.5-flash`` to emit
``{"verdict": "in_scope" | "out_of_scope", "reason": "<one sentence>"}``;
the parser tolerates whitespace / trailing newlines and falls back to a
degraded verdict on malformed JSON. The fallback exists because the
``on_persisted`` path is observe-only (ADR-0030 §D1): better to record
an alert with a degraded verdict than to crash the host.

Supersedes the OpenAI ``gpt-4o-mini`` client picked in ADR-0030 §D4.
"""

from __future__ import annotations

import json
from typing import Literal

from llm_tracker_sdk.egress import EgressClient, EgressResponse

_MODEL = "gemini-2.5-flash"
_CHAT_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{_MODEL}:generateContent"

Verdict = Literal["in_scope", "out_of_scope"]
_DEFAULT_VERDICT: Verdict = "in_scope"
_MALFORMED_REASON = "stage2_malformed_response"


# ADR-0030 §Q4 — frozen Stage-2 prompt template.
#
# Pinning rationale:
# - Strict JSON shape lets the parser fail closed to a fixed default verdict
#   without ad-hoc string scraping. ``gemini-2.5-flash`` reliably honours the
#   shape when the instruction is first in the system instruction and
#   ``responseMimeType=application/json`` is set.
# - Numbered chunks ground the model's "reason" against a specific scope
#   citation (operator-debuggable in ``scope_alerts.stage2_reason``).
# - One-sentence reason budget keeps ``scope_alerts.stage2_reason`` short and
#   storage-cost-bounded; ADR-0030 §D8 doesn't cap the column, but cheap is
#   cheap.
# - "in_scope" / "out_of_scope" mirror the literal values in the
#   ``scope_alerts.verdict`` column (ADR-0030 §D8) so the judge output drops
#   straight into the row.
#
# DO NOT edit casually — the exact wording is the unit under test in
# ``tests/test_judge.py``. ADR-0031 keeps the wording identical to the OpenAI
# era so a future provider swap doesn't break the contract.
_SYSTEM_PROMPT = (
    "You are a scope-monitoring judge. The operator has registered scope "
    "documents describing what their AI assistant is permitted to help with. "
    "Decide whether the user message is in_scope or out_of_scope.\n\n"
    "Respond with strict JSON only, no markdown, no commentary, in this exact "
    'shape: {"verdict": "in_scope" | "out_of_scope", '
    '"reason": "<one short sentence>"}\n'
    "Choose in_scope when the user message is plausibly served by at least one "
    "of the scope chunks below. Choose out_of_scope when the message is clearly "
    "unrelated to all of them. Keep the reason under 200 characters."
)

_USER_PROMPT_TEMPLATE = (
    "User message:\n<<<\n{message_text}\n>>>\n\nScope chunks (numbered):\n{numbered_chunks}\n"
)


def _build_user_prompt(message_text: str, chunks: list[str]) -> str:
    if chunks:
        numbered = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(chunks))
    else:
        numbered = "(no scope chunks supplied)"
    return _USER_PROMPT_TEMPLATE.format(
        message_text=message_text,
        numbered_chunks=numbered,
    )


def _parse_verdict(content: str) -> tuple[Verdict, str]:
    """Parse the model's JSON content. Fall back to the default on any error."""
    try:
        payload = json.loads(content.strip())
        verdict_raw = payload["verdict"]
        reason = payload["reason"]
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        return _DEFAULT_VERDICT, _MALFORMED_REASON
    if verdict_raw not in ("in_scope", "out_of_scope") or not isinstance(reason, str):
        return _DEFAULT_VERDICT, _MALFORMED_REASON
    return verdict_raw, reason


class JudgeError(RuntimeError):
    """Raised when the generateContent endpoint returns a non-2xx response.

    Distinct from a malformed-but-200 body — the latter falls back to a
    degraded verdict in-band per ADR-0030 §D1 (observe-only) rather than
    raising. Transport failures still raise so the caller can log + skip.
    """


class JudgeClient:
    """Thin wrapper over :class:`EgressClient` for ``gemini-2.5-flash``."""

    def __init__(self, *, api_key: str, egress: EgressClient, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._egress = egress
        self._timeout = timeout

    async def judge(self, message_text: str, chunks: list[str]) -> tuple[Verdict, str]:
        """Run the Stage-2 judge.

        Returns ``(verdict, reason)``. On a 2xx response with malformed JSON
        body the result is ``(_DEFAULT_VERDICT, _MALFORMED_REASON)``; non-2xx
        responses raise :class:`JudgeError`. :class:`EgressDenied` from the
        guard is allowed to propagate.
        """
        body = json.dumps(
            {
                "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": _build_user_prompt(message_text, chunks)}],
                    }
                ],
                "generationConfig": {
                    "temperature": 0.0,
                    "responseMimeType": "application/json",
                },
            }
        ).encode("utf-8")
        resp: EgressResponse = await self._egress.fetch(
            _CHAT_URL,
            method="POST",
            headers={
                "x-goog-api-key": self._api_key,
                "Content-Type": "application/json",
            },
            body=body,
            timeout=self._timeout,
        )
        if resp.status_code < 200 or resp.status_code >= 300:
            raise JudgeError(
                f"gemini generateContent returned status {resp.status_code}: {resp.body[:200]!r}"
            )
        try:
            payload = json.loads(resp.body)
            content = payload["candidates"][0]["content"]["parts"][0]["text"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            return _DEFAULT_VERDICT, _MALFORMED_REASON
        return _parse_verdict(content)
