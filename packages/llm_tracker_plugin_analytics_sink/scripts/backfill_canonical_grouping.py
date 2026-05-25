"""Backfill historic plugin_analytics + conversation_messages rows to
ADR-0036 canonical grouping (canonical user-text hash, per-message
origin role, priority UPSERT semantics).

Two execution modes:

* ``--emit-sql`` (default) — print the SQL UPDATE/INSERT/DELETE
  statements that *would* run, no DB connection required. Pipe the
  output through `psql` / Supabase MCP / a SQL editor for review and
  manual apply. Safe by construction (no writes from this process).
* ``--apply`` — connect via ``LLMTRACK_DATABASE_URL`` and execute
  the same statements in a single transaction. Aborts loudly if the
  env var is unset.

The script reads from ``plugin_analytics`` and
``plugin_analytics_with_messages`` (the helper view introduced by
migration 0015) so it does not depend on the dropped
``messages_json`` column. ``messages_jsonb`` exposes the canonical
``messages[0].content`` we need to recompute ``first_msg_hash``.

What the script does (in the order it emits SQL):

1. **Reclassify `conversation_messages.role` in-place.** Maps the
   stored API protocol role (``user`` / ``assistant``) plus content
   shape onto the per-message origin vocabulary (ADR-0036 V): one of
   ``user_input_turn_start``, ``tool_continuation``,
   ``internal_subprompt``, ``assistant``. The string-content case
   uses pattern matching (SUGGESTION MODE, ``<session>``,
   step-away recap, ``/compact`` summarize) to distinguish
   framework sub-prompts from real user turns that collapsed under
   normalisation Rule B. (Forward writes use ``classify_message``
   on the raw message — pattern matching is needed here only because
   normalised content lost the original shape.)
2. **Recompute `plugin_analytics.first_msg_hash`** from each
   exchange's ``messages[0]`` canonical content using
   ``_canonical_user_text`` (the same helper the plugin uses
   forward).
3. **Remap `plugin_analytics.conversation_id`** by re-running the
   (B) chain-lookup over the new hashes in ``created_at`` order:
   the first row with a given ``(org_id, new_hash)`` defines the
   conversation; all later rows with the same key inherit.
4. **Move `conversation_messages` rows to their new
   `conversation_id`.** When the same ``(new_conversation_id,
   msg_index)`` is contested by multiple old rows, the priority
   rule applies: real-content rows (``user_input_turn_start`` /
   ``tool_continuation`` / ``assistant``) win over
   ``internal_subprompt`` placeholders. Same as the forward UPSERT.

The script is idempotent against itself when re-run: rows already
holding the post-fix values produce no-op UPDATEs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

# Import package helpers (single source of truth — never re-implement here).
_REPO_SRC = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, _REPO_SRC)
from llm_tracker_plugin_analytics_sink.classifier import (  # noqa: E402
    _canonical_user_text,
    classify_message,
)

DATABASE_URL_ENV = "LLMTRACK_DATABASE_URL"


# ---------------------------------------------------------------------
# Data classes (mirror the relevant columns).
# ---------------------------------------------------------------------


@dataclass
class PARow:
    id: str
    conversation_id: str
    org_id: str
    created_at: str  # ISO string
    n_messages_at_request: int
    first_msg_hash: str
    turn_kind: str


@dataclass
class CMRow:
    conversation_id: str
    msg_index: int
    role: str
    content_jsonb: Any  # python object after json.loads
    org_id: str


# ---------------------------------------------------------------------
# Forward-classifier shim — applies pattern matching for the
# normalised string case that `classify_message` cannot disambiguate.
# ---------------------------------------------------------------------

_KNOWN_SUBPROMPT_MARKERS: tuple[str, ...] = (
    "[SUGGESTION MODE:",
    "The user stepped away",
    "CRITICAL: Respond with TEXT ONLY",
    "Your job is to summarise the conversation",
)


def reclassify_role(cm: CMRow) -> str:
    """Per-message origin for a stored conversation_messages row.

    Pre-condition: ``content_jsonb`` has already been normalised by
    ``canonical_message`` (Rule B may have collapsed a single bare
    text block to a string). This function infers the original
    shape using known sub-prompt markers and a `<session>`
    wrapper test before falling back to ``classify_message``.
    """
    if cm.role == "assistant":
        return "assistant"

    # Reconstruct a synthetic message dict for the per-message classifier
    # in the unambiguous cases. The string-content branch needs more
    # context: a normalised single-block array collapses to the same
    # shape as a true sub-prompt. Use marker matching for the latter.
    if isinstance(cm.content_jsonb, str):
        text = cm.content_jsonb
        stripped = text.lstrip()
        if stripped.startswith("<session>"):
            return "internal_subprompt"
        if any(stripped.startswith(m) for m in _KNOWN_SUBPROMPT_MARKERS):
            return "internal_subprompt"
        # No sub-prompt marker — assume it's a collapsed real user
        # turn. Forward writes never reach this branch (the plugin
        # classifies the raw message before normalisation), so the
        # heuristic only matters for backfill.
        return "user_input_turn_start"

    # Array / other shapes: defer to the canonical classifier.
    msg = {"role": cm.role, "content": cm.content_jsonb}
    return classify_message(msg)


# ---------------------------------------------------------------------
# Hash recompute + (B) chain-lookup remap.
# ---------------------------------------------------------------------


def compute_new_hash(msg0_content: Any) -> str:
    canonical = _canonical_user_text(msg0_content)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def remap_conversations(
    pa_rows: list[PARow],
    new_hash_by_conv: dict[str, str],
) -> dict[str, str]:
    """Return ``{old_conv_id: new_conv_id}`` after re-running B-rule.

    Iterates plugin_analytics rows in ``created_at`` order. The
    first row to claim a given ``(org_id, new_hash)`` defines the
    conversation; all subsequent rows with the same key inherit.
    Conversations that don't collide stay at their original id.
    """
    head_by_key: dict[tuple[str, str], str] = {}
    remap: dict[str, str] = {}

    for pa in sorted(pa_rows, key=lambda r: r.created_at):
        new_hash = new_hash_by_conv.get(pa.conversation_id)
        if new_hash is None:
            # No msg_index=0 row available — keep original.
            remap.setdefault(pa.conversation_id, pa.conversation_id)
            continue
        key = (pa.org_id, new_hash)
        head = head_by_key.get(key)
        if head is None:
            head_by_key[key] = pa.conversation_id
            remap.setdefault(pa.conversation_id, pa.conversation_id)
        else:
            remap[pa.conversation_id] = head

    return remap


# ---------------------------------------------------------------------
# SQL emission.
# ---------------------------------------------------------------------


def _q(s: str) -> str:
    """Single-quote a string for SQL (basic escape)."""
    return "'" + s.replace("'", "''") + "'"


def emit_role_updates(cm_rows: list[CMRow]) -> list[str]:
    """One UPDATE per conversation_messages row whose role changes."""
    stmts: list[str] = []
    for cm in cm_rows:
        new_role = reclassify_role(cm)
        if new_role != cm.role:
            stmts.append(
                "UPDATE conversation_messages SET role = "
                f"{_q(new_role)} WHERE conversation_id = "
                f"{_q(cm.conversation_id)} AND msg_index = {cm.msg_index};"
            )
    return stmts


def emit_conv_moves(
    cm_rows: list[CMRow],
    remap: dict[str, str],
) -> list[str]:
    """Move conversation_messages rows whose conv_id changes.

    For each (old_conv, msg_index) row whose old_conv != new_conv:
    - INSERT into the new conv with priority UPSERT (same WHERE
      clause the plugin's runtime UPSERT uses).
    - DELETE the old conv's row.

    Rows whose conv_id doesn't change get no statements (they
    already carry the post-backfill role from step 1).
    """
    stmts: list[str] = []
    for cm in cm_rows:
        new_conv = remap.get(cm.conversation_id, cm.conversation_id)
        if new_conv == cm.conversation_id:
            continue
        # The new role is reclassify_role(cm) — same value that step 1
        # already wrote in-place. We read it back from the (already
        # updated) row by emitting an INSERT that pulls role from the
        # current row. Using a SELECT subquery keeps the DDL minimal
        # and matches step-1 results even if reclassify_role's logic
        # changes between runs.
        stmts.append(
            "INSERT INTO conversation_messages "
            "(conversation_id, msg_index, org_id, role, content_jsonb) "
            f"SELECT {_q(new_conv)}, msg_index, org_id, role, content_jsonb "
            "FROM conversation_messages "
            f"WHERE conversation_id = {_q(cm.conversation_id)} "
            f"AND msg_index = {cm.msg_index} "
            "ON CONFLICT (conversation_id, msg_index) DO UPDATE "
            "SET role = EXCLUDED.role, content_jsonb = EXCLUDED.content_jsonb "
            "WHERE conversation_messages.role IN "
            "('internal_subprompt', 'claude_manage_probe') "
            "AND EXCLUDED.role IN "
            "('user_input_turn_start', 'tool_continuation', 'assistant');"
        )
        stmts.append(
            "DELETE FROM conversation_messages "
            f"WHERE conversation_id = {_q(cm.conversation_id)} "
            f"AND msg_index = {cm.msg_index};"
        )
    return stmts


def emit_pa_updates(
    pa_rows: list[PARow],
    new_hash_by_conv: dict[str, str],
    remap: dict[str, str],
) -> list[str]:
    """UPDATE each plugin_analytics row whose hash/conv_id changes."""
    stmts: list[str] = []
    for pa in pa_rows:
        new_hash = new_hash_by_conv.get(pa.conversation_id, pa.first_msg_hash)
        new_conv = remap.get(pa.conversation_id, pa.conversation_id)
        if new_hash == pa.first_msg_hash and new_conv == pa.conversation_id:
            continue
        stmts.append(
            "UPDATE plugin_analytics SET "
            f"first_msg_hash = {_q(new_hash)}, "
            f"conversation_id = {_q(new_conv)} "
            f"WHERE id = {_q(pa.id)};"
        )
    return stmts


# ---------------------------------------------------------------------
# Reporting (dry-run summary).
# ---------------------------------------------------------------------


def print_report(
    pa_rows: list[PARow],
    cm_rows: list[CMRow],
    new_hash_by_conv: dict[str, str],
    remap: dict[str, str],
) -> None:
    """Human-readable summary of the changes — what would shift if applied."""
    role_changes = 0
    for cm in cm_rows:
        if reclassify_role(cm) != cm.role:
            role_changes += 1

    hash_changes = sum(
        1
        for pa in pa_rows
        if new_hash_by_conv.get(pa.conversation_id, pa.first_msg_hash) != pa.first_msg_hash
    )
    conv_id_changes = sum(
        1 for pa in pa_rows if remap.get(pa.conversation_id) != pa.conversation_id
    )
    unique_old_convs = len({pa.conversation_id for pa in pa_rows})
    unique_new_convs = len({remap.get(pa.conversation_id, pa.conversation_id) for pa in pa_rows})

    # Collapse groups (where two or more old convs merge into one new conv).
    groups: dict[str, list[str]] = defaultdict(list)
    for old_id in {pa.conversation_id for pa in pa_rows}:
        groups[remap.get(old_id, old_id)].append(old_id)
    collapses = {k: v for k, v in groups.items() if len(v) > 1}

    print("=" * 60, file=sys.stderr)
    print("ADR-0036 backfill — dry-run report", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"plugin_analytics rows:        {len(pa_rows)}", file=sys.stderr)
    print(f"conversation_messages rows:   {len(cm_rows)}", file=sys.stderr)
    print(f"role changes:                 {role_changes}", file=sys.stderr)
    print(f"first_msg_hash changes:       {hash_changes}", file=sys.stderr)
    print(f"conversation_id changes:      {conv_id_changes}", file=sys.stderr)
    print(
        f"unique conversations:         {unique_old_convs} -> {unique_new_convs}",
        file=sys.stderr,
    )
    print(f"collapse groups:              {len(collapses)}", file=sys.stderr)
    for new_conv, old_convs in sorted(collapses.items()):
        print(f"  new={new_conv}", file=sys.stderr)
        for old in old_convs:
            print(f"    <- {old}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)


# ---------------------------------------------------------------------
# DB loaders.
# ---------------------------------------------------------------------


async def _load_db(url: str) -> tuple[list[PARow], list[CMRow], dict[str, Any]]:
    """Load plugin_analytics + conversation_messages from the DB.

    Returns:
        pa_rows: every plugin_analytics row, ordered by created_at.
        cm_rows: every conversation_messages row.
        msg0_content_by_conv: ``{conversation_id: messages[0].content}``
            sourced from conversation_messages msg_index=0 — the same
            value the plugin would canonicalise at write time.
    """
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    async with engine.begin() as conn:
        pa_result = await conn.execute(
            sa.text(
                "SELECT id, conversation_id, org_id::text as org_id, "
                "to_char(created_at, 'YYYY-MM-DD HH24:MI:SS.US') as created_at, "
                "n_messages_at_request, first_msg_hash, turn_kind "
                "FROM plugin_analytics ORDER BY created_at ASC"
            )
        )
        pa_rows = [
            PARow(
                id=r.id,
                conversation_id=r.conversation_id,
                org_id=r.org_id,
                created_at=r.created_at,
                n_messages_at_request=r.n_messages_at_request,
                first_msg_hash=r.first_msg_hash,
                turn_kind=r.turn_kind,
            )
            for r in pa_result
        ]
        cm_result = await conn.execute(
            sa.text(
                "SELECT conversation_id, msg_index, role, content_jsonb, "
                "org_id::text as org_id FROM conversation_messages"
            )
        )
        cm_rows = [
            CMRow(
                conversation_id=r.conversation_id,
                msg_index=r.msg_index,
                role=r.role,
                content_jsonb=r.content_jsonb,
                org_id=r.org_id,
            )
            for r in cm_result
        ]
    await engine.dispose()

    msg0_by_conv: dict[str, Any] = {}
    for cm in cm_rows:
        if cm.msg_index == 0:
            msg0_by_conv[cm.conversation_id] = cm.content_jsonb
    return pa_rows, cm_rows, msg0_by_conv


# ---------------------------------------------------------------------
# Main.
# ---------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--emit-sql",
        action="store_true",
        default=True,
        help="Print SQL to stdout, no DB connection. Default mode.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Connect via LLMTRACK_DATABASE_URL and execute in a single transaction.",
    )
    parser.add_argument(
        "--from-json",
        type=str,
        default=None,
        help=(
            "Path to a JSON file with {pa_rows: [...], cm_rows: [...]} for "
            "offline runs (e.g. data exported via Supabase MCP execute_sql)."
        ),
    )
    args = parser.parse_args()

    if args.from_json:
        with open(args.from_json) as f:
            data = json.load(f)
        pa_rows = [PARow(**r) for r in data["pa_rows"]]
        cm_rows = [
            CMRow(
                conversation_id=r["conversation_id"],
                msg_index=r["msg_index"],
                role=r["role"],
                content_jsonb=r["content_jsonb"],
                org_id=r["org_id"],
            )
            for r in data["cm_rows"]
        ]
        msg0_by_conv = {cm.conversation_id: cm.content_jsonb for cm in cm_rows if cm.msg_index == 0}
    else:
        url = os.environ.get(DATABASE_URL_ENV)
        if not url:
            print(
                f"error: {DATABASE_URL_ENV} not set, and no --from-json supplied.",
                file=sys.stderr,
            )
            return 2
        import asyncio

        pa_rows, cm_rows, msg0_by_conv = asyncio.run(_load_db(url))

    new_hash_by_conv = {
        conv_id: compute_new_hash(content) for conv_id, content in msg0_by_conv.items()
    }
    remap = remap_conversations(pa_rows, new_hash_by_conv)

    print_report(pa_rows, cm_rows, new_hash_by_conv, remap)

    stmts = (
        emit_role_updates(cm_rows)
        + emit_conv_moves(cm_rows, remap)
        + emit_pa_updates(pa_rows, new_hash_by_conv, remap)
    )

    if args.apply:
        url = os.environ.get(DATABASE_URL_ENV)
        if not url:
            print(f"error: --apply requires {DATABASE_URL_ENV}.", file=sys.stderr)
            return 2
        import asyncio

        import sqlalchemy as sa
        from sqlalchemy.ext.asyncio import create_async_engine

        async def _apply() -> None:
            engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
            async with engine.begin() as conn:
                for stmt in stmts:
                    await conn.execute(sa.text(stmt))
            await engine.dispose()

        asyncio.run(_apply())
        print(f"\napplied {len(stmts)} statements in one transaction.", file=sys.stderr)
        return 0

    # Default: --emit-sql. Wrap in a transaction for safe paste-and-run.
    print("BEGIN;")
    for stmt in stmts:
        print(stmt)
    print("COMMIT;")
    print(f"\n-- {len(stmts)} statements (dry-run; review then apply).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
