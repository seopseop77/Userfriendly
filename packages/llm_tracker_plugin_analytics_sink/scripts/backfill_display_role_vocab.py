"""Backfill historic conversation_messages rows to the ADR-0037
display vocab.

Two changes per affected conversation:

1. **Reclassify `role`** from the ADR-0036 vocab to the ADR-0037
   vocab. Mapping (with idempotency guard):

   | Old role                | New role        | Note                                  |
   |-------------------------|-----------------|---------------------------------------|
   | `user_input_turn_start` | `user_input`    | Rename.                               |
   | `tool_continuation`     | `assistant`     | Folded into framework-sidecar bucket. |
   | `internal_subprompt`    | `title_gen`     | When content is `<session>…</session>`. |
   | `internal_subprompt`    | `assistant`     | Otherwise.                            |
   | `claude_manage_probe`   | `title_gen` / `assistant` | Same content-based split.   |
   | `assistant`             | `model_output`  | `role=assistant` upstream.            |

2. **Split `messages[0]`** when its stored content is a list with a
   leading wrapper block (`<system-reminder>`, `<command-name>`,
   `<local-command-*>`, post-`/compact` resume marker). The list peels
   into:
   - `msg_index = 0`, role=`system_prompt`, content = wrapper blocks.
   - `msg_index = 1`, role=`user_input`, content = remaining blocks
     (normalised — single bare text block collapses to a string).
   - Every other row in the same `conversation_id` shifts by +1.
   - The exchange's `plugin_analytics.n_messages_at_request` is bumped
     by +1 so the helper view's filter still captures every stored row.

Idempotency: a conversation is treated as already-migrated if any of
its rows carry a role in `{system_prompt, user_input, title_gen,
model_output}` (none of which existed in the ADR-0036 vocab). Such
conversations are skipped end-to-end.

Two execution modes (same as ADR-0036 backfill):

* ``--emit-sql`` (default) — print SQL to stdout, no DB connection.
  Pipe through `psql` / Supabase MCP / a SQL editor for review and
  manual apply.
* ``--apply`` — connect via ``LLMTRACK_DATABASE_URL`` and execute
  inside a single transaction.

Offline runs (`--from-json`) accept a JSON file with
`{pa_rows, cm_rows}` exported via Supabase MCP `execute_sql`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

_REPO_SRC = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, _REPO_SRC)
from llm_tracker_plugin_analytics_sink.classifier import (  # noqa: E402
    _SESSION_WRAP_RE,
    _SYNTHETIC_WRAPPER_PREFIXES,
)
from llm_tracker_plugin_analytics_sink.normalize import canonical_message  # noqa: E402

DATABASE_URL_ENV = "LLMTRACK_DATABASE_URL"

_NEW_VOCAB: frozenset[str] = frozenset(
    {"system_prompt", "user_input", "title_gen", "model_output", "assistant"}
)

# Old-vocab values that, if seen anywhere in a conversation, signal it
# has NOT been migrated yet. `assistant` is intentionally absent — it
# exists in both vocabs (model output in old, framework sidecar in new),
# so its presence alone is ambiguous.
_OLD_ONLY_ROLES: frozenset[str] = frozenset(
    {"user_input_turn_start", "tool_continuation", "internal_subprompt", "claude_manage_probe"}
)

# Roles that exist only in the new vocab. If a conv has any of these,
# it has already been migrated.
_NEW_ONLY_ROLES: frozenset[str] = frozenset(
    {"system_prompt", "user_input", "title_gen", "model_output"}
)


@dataclass
class CMRow:
    conversation_id: str
    msg_index: int
    role: str
    content_jsonb: Any  # python object after json.loads
    org_id: str


@dataclass
class PARow:
    conversation_id: str
    n_messages_at_request: int


# ---------------------------------------------------------------------
# Role remap.
# ---------------------------------------------------------------------


def _is_session_string(content: Any) -> bool:
    """True when content is a string wrapped in `<session>...</session>`."""
    if not isinstance(content, str):
        return False
    return bool(_SESSION_WRAP_RE.match(content))


def map_old_to_new_role(old_role: str, content: Any) -> str:
    """Translate an ADR-0036 vocab value to the ADR-0037 vocab.

    `system_prompt` is never the output here — it is only assigned by
    the splitter (`compute_split`). Rows already carrying a new-vocab
    role are returned unchanged (idempotency).

    Auto-correction: any user-role row whose content is a bare
    `<session>...</session>` string maps to `title_gen` regardless of
    its old role. This catches the historic mislabel (one production
    row carried `user_input_turn_start` for a session-classify
    sidecar payload). The old `assistant` value names a model output
    which we never auto-correct from content shape.
    """
    if old_role in _NEW_ONLY_ROLES:
        return old_role
    if old_role == "assistant":
        return "model_output"
    # All remaining old-vocab values mean `role=user` at the API layer.
    if _is_session_string(content):
        return "title_gen"
    if old_role == "user_input_turn_start":
        return "user_input"
    if old_role == "tool_continuation":
        return "assistant"
    if old_role in ("internal_subprompt", "claude_manage_probe"):
        return "assistant"
    return old_role  # unknown — preserve verbatim


# ---------------------------------------------------------------------
# Split detection for the stored msg_index=0 row.
# ---------------------------------------------------------------------


def _is_wrapper_text_block(block: Any) -> bool:
    if not isinstance(block, dict):
        return False
    if block.get("type") != "text":
        return False
    text = (block.get("text") or "").lstrip()
    return text.startswith(_SYNTHETIC_WRAPPER_PREFIXES)


def compute_split(
    msg0_content: Any,
) -> tuple[list[dict[str, Any]], Any] | None:
    """Return `(system_blocks, user_content_normalised)` or `None`.

    Mirrors `split_first_message` from the plugin but operates on
    already-stored (post-normalisation) content. A single non-wrapper
    text block stored as a bare string (Rule B collapse) means the
    original message had only the user's typed text — no split.
    """
    if not isinstance(msg0_content, list) or not msg0_content:
        return None
    # Walk forward; collect leading wrapper text blocks.
    split_point: int | None = None
    for idx, b in enumerate(msg0_content):
        if _is_wrapper_text_block(b):
            continue
        split_point = idx
        break

    if split_point is None or split_point == 0:
        # No wrappers, or every block was a wrapper.
        return None

    system_blocks = list(msg0_content[:split_point])
    user_blocks = list(msg0_content[split_point:])
    if not system_blocks or not user_blocks:
        return None

    # Normalise the user slice via canonical_message so Rule B
    # collapse mirrors the forward write path.
    user_norm = canonical_message({"role": "user", "content": user_blocks})
    return system_blocks, user_norm["content"]


def is_already_migrated(cm_rows_for_conv: list[CMRow]) -> bool:
    """True when any row in the conv carries a new-vocab-only role."""
    return any(r.role in _NEW_ONLY_ROLES for r in cm_rows_for_conv)


# ---------------------------------------------------------------------
# SQL emission.
# ---------------------------------------------------------------------


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _qj(obj: Any) -> str:
    return _q(json.dumps(obj, ensure_ascii=False))


def emit_statements(
    cm_rows: list[CMRow],
    pa_rows: list[PARow],
) -> tuple[list[str], dict[str, Any]]:
    """Return the SQL statement list + a stats dict for the report."""
    by_conv: dict[str, list[CMRow]] = defaultdict(list)
    for cm in cm_rows:
        by_conv[cm.conversation_id].append(cm)
    for rows in by_conv.values():
        rows.sort(key=lambda r: r.msg_index)

    stmts: list[str] = []
    stats: dict[str, Any] = {
        "convs_total": len(by_conv),
        "convs_skipped_migrated": 0,
        "convs_split": 0,
        "role_only_updates": 0,
        "rows_inserted": 0,
        "rows_deleted": 0,
        "pa_bumped": 0,
    }

    for conv_id, rows in by_conv.items():
        if is_already_migrated(rows):
            stats["convs_skipped_migrated"] += 1
            continue

        msg0 = next((r for r in rows if r.msg_index == 0), None)
        split = compute_split(msg0.content_jsonb) if msg0 is not None else None

        if split is None:
            # No structural change — just rewrite role values that drift.
            for r in rows:
                new_role = map_old_to_new_role(r.role, r.content_jsonb)
                if new_role != r.role:
                    stmts.append(
                        "UPDATE conversation_messages SET role = "
                        f"{_q(new_role)} WHERE conversation_id = "
                        f"{_q(conv_id)} AND msg_index = {r.msg_index};"
                    )
                    stats["role_only_updates"] += 1
            continue

        # Structural change. Rebuild the conv from scratch in one
        # DELETE + N INSERTs — avoids PK-collision footguns on
        # in-place shifts.
        system_blocks, user_content = split
        org_id = rows[0].org_id

        stmts.append(
            "DELETE FROM conversation_messages "
            f"WHERE conversation_id = {_q(conv_id)};"
        )
        stats["rows_deleted"] += len(rows)

        # New row 0: system_prompt.
        stmts.append(
            "INSERT INTO conversation_messages "
            "(conversation_id, msg_index, org_id, role, content_jsonb) "
            f"VALUES ({_q(conv_id)}, 0, {_q(org_id)}::uuid, "
            f"'system_prompt', CAST({_qj(system_blocks)} AS jsonb));"
        )
        stats["rows_inserted"] += 1

        # New row 1: user_input (Rule B-normalised content).
        stmts.append(
            "INSERT INTO conversation_messages "
            "(conversation_id, msg_index, org_id, role, content_jsonb) "
            f"VALUES ({_q(conv_id)}, 1, {_q(org_id)}::uuid, "
            f"'user_input', CAST({_qj(user_content)} AS jsonb));"
        )
        stats["rows_inserted"] += 1

        # Old rows 1..N shift to 2..N+1 with role remapped.
        for r in rows:
            if r.msg_index == 0:
                continue
            new_role = map_old_to_new_role(r.role, r.content_jsonb)
            stmts.append(
                "INSERT INTO conversation_messages "
                "(conversation_id, msg_index, org_id, role, content_jsonb) "
                f"VALUES ({_q(conv_id)}, {r.msg_index + 1}, "
                f"{_q(r.org_id)}::uuid, {_q(new_role)}, "
                f"CAST({_qj(r.content_jsonb)} AS jsonb));"
            )
            stats["rows_inserted"] += 1

        # Bump n_messages_at_request on every exchange in this conv.
        stmts.append(
            "UPDATE plugin_analytics SET "
            "n_messages_at_request = n_messages_at_request + 1 "
            f"WHERE conversation_id = {_q(conv_id)} "
            "AND n_messages_at_request IS NOT NULL;"
        )
        affected_pa = sum(1 for pa in pa_rows if pa.conversation_id == conv_id)
        stats["pa_bumped"] += affected_pa
        stats["convs_split"] += 1

    return stmts, stats


# ---------------------------------------------------------------------
# Report.
# ---------------------------------------------------------------------


def print_report(stats: dict[str, Any], stmt_count: int) -> None:
    print("=" * 60, file=sys.stderr)
    print("ADR-0037 backfill — dry-run report", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"conversations total:           {stats['convs_total']}", file=sys.stderr)
    print(f"  already-migrated (skipped):  {stats['convs_skipped_migrated']}", file=sys.stderr)
    print(f"  split applied:               {stats['convs_split']}", file=sys.stderr)
    print(f"role-only UPDATEs:             {stats['role_only_updates']}", file=sys.stderr)
    print(f"rows DELETEd (split-affected): {stats['rows_deleted']}", file=sys.stderr)
    print(f"rows INSERTed:                 {stats['rows_inserted']}", file=sys.stderr)
    print(f"plugin_analytics bumped (+1):  {stats['pa_bumped']}", file=sys.stderr)
    print(f"total SQL statements:          {stmt_count}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)


# ---------------------------------------------------------------------
# DB loader.
# ---------------------------------------------------------------------


async def _load_db(url: str) -> tuple[list[CMRow], list[PARow]]:
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    async with engine.begin() as conn:
        cm_result = await conn.execute(
            sa.text(
                "SELECT conversation_id, msg_index, role, content_jsonb, "
                "org_id::text AS org_id FROM conversation_messages"
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
        pa_result = await conn.execute(
            sa.text(
                "SELECT conversation_id, n_messages_at_request "
                "FROM plugin_analytics WHERE n_messages_at_request IS NOT NULL"
            )
        )
        pa_rows = [
            PARow(
                conversation_id=r.conversation_id,
                n_messages_at_request=r.n_messages_at_request,
            )
            for r in pa_result
        ]
    await engine.dispose()
    return cm_rows, pa_rows


# ---------------------------------------------------------------------
# Main.
# ---------------------------------------------------------------------


def _parse_content(raw: Any) -> Any:
    """Supabase MCP exports content_jsonb as a JSON string; parse if so."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw
    return raw


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
            "Path to a JSON file with {cm_rows: [...], pa_rows: [...]} for "
            "offline runs (e.g. exported via Supabase MCP execute_sql)."
        ),
    )
    args = parser.parse_args()

    if args.from_json:
        with open(args.from_json) as f:
            data = json.load(f)
        cm_rows = [
            CMRow(
                conversation_id=r["conversation_id"],
                msg_index=r["msg_index"],
                role=r["role"],
                content_jsonb=_parse_content(r["content_jsonb"]),
                org_id=r["org_id"],
            )
            for r in data["cm_rows"]
        ]
        pa_rows = [
            PARow(
                conversation_id=r["conversation_id"],
                n_messages_at_request=r["n_messages_at_request"],
            )
            for r in data["pa_rows"]
        ]
    else:
        url = os.environ.get(DATABASE_URL_ENV)
        if not url:
            print(
                f"error: {DATABASE_URL_ENV} not set, and no --from-json supplied.",
                file=sys.stderr,
            )
            return 2
        import asyncio

        cm_rows, pa_rows = asyncio.run(_load_db(url))

    stmts, stats = emit_statements(cm_rows, pa_rows)
    print_report(stats, len(stmts))

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

    print("BEGIN;")
    for stmt in stmts:
        print(stmt)
    print("COMMIT;")
    print(f"\n-- {len(stmts)} statements (dry-run; review then apply).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
