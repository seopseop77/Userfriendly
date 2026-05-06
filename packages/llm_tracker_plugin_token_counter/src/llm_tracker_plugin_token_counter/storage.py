"""Sidecar SQLite store for token-counter records (test-only).

Lives in its own file so the plugin doesn't reach into the core DB.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

DEFAULT_PATH = Path("var") / "plugin_token_counter.db"
DB_PATH_ENV = "LLMTRACK_PLUGIN_TOKEN_COUNTER_DB"

SCHEMA = """
CREATE TABLE IF NOT EXISTS exchange_usage (
    exchange_id                  TEXT PRIMARY KEY,
    recorded_at_ms               INTEGER NOT NULL,
    model                        TEXT,
    input_tokens                 INTEGER NOT NULL,
    output_tokens                INTEGER NOT NULL,
    cache_creation_input_tokens  INTEGER NOT NULL,
    cache_read_input_tokens      INTEGER NOT NULL
)
"""


@dataclass(frozen=True)
class UsageRecord:
    exchange_id: str
    model: str | None
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int


class UsageStore:
    """One aiosqlite connection per plugin instance."""

    def __init__(self, db_path: str | os.PathLike[str]) -> None:
        self._db_path = os.fspath(db_path)
        self._conn: aiosqlite.Connection | None = None

    @classmethod
    def default(cls) -> UsageStore:
        path = os.environ.get(DB_PATH_ENV) or str(DEFAULT_PATH)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return cls(path)

    async def init(self) -> None:
        if self._conn is not None:
            return
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute(SCHEMA)
        await self._conn.commit()

    async def write(self, record: UsageRecord) -> None:
        if self._conn is None:
            raise RuntimeError("UsageStore.write called before init")
        await self._conn.execute(
            """
            INSERT OR REPLACE INTO exchange_usage (
                exchange_id, recorded_at_ms, model,
                input_tokens, output_tokens,
                cache_creation_input_tokens, cache_read_input_tokens
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.exchange_id,
                int(time.time() * 1000),
                record.model,
                record.input_tokens,
                record.output_tokens,
                record.cache_creation_input_tokens,
                record.cache_read_input_tokens,
            ),
        )
        await self._conn.commit()

    async def fetch(self, exchange_id: str) -> UsageRecord | None:
        if self._conn is None:
            raise RuntimeError("UsageStore.fetch called before init")
        async with self._conn.execute(
            """
            SELECT model, input_tokens, output_tokens,
                   cache_creation_input_tokens, cache_read_input_tokens
            FROM exchange_usage WHERE exchange_id = ?
            """,
            (exchange_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return UsageRecord(
            exchange_id=exchange_id,
            model=row[0],
            input_tokens=row[1],
            output_tokens=row[2],
            cache_creation_input_tokens=row[3],
            cache_read_input_tokens=row[4],
        )

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None


__all__ = ["DB_PATH_ENV", "DEFAULT_PATH", "UsageRecord", "UsageStore"]
