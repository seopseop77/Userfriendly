"""Read timing data from the local SQLite DB and report first-token latency stats."""

import sqlite3
import statistics
import sys
from pathlib import Path

DB_PATH = Path(__file__).parents[2] / "var" / "llm_tracker.db"


def main() -> None:
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        """
        SELECT t_upstream_first_byte_ms, t_client_first_byte_ms
        FROM exchanges
        WHERE t_upstream_first_byte_ms IS NOT NULL
          AND t_client_first_byte_ms IS NOT NULL
        ORDER BY started_at DESC
        LIMIT 20
        """
    ).fetchall()
    conn.close()

    if not rows:
        print("No timing data found. Run prompts through the proxy first.")
        sys.exit(1)

    overheads = [row[1] - row[0] for row in rows]
    n = len(overheads)
    overheads_sorted = sorted(overheads)
    p95 = overheads_sorted[min(int(n * 0.95), n - 1)]

    print(f"Exchanges with timing data : {n}")
    print(f"proxy_overhead_ms (t_client_first_byte - t_upstream_first_byte):")
    print(f"  min    : {min(overheads):.1f} ms")
    print(f"  median : {statistics.median(overheads):.1f} ms")
    print(f"  p95    : {p95:.1f} ms")
    print(f"  max    : {max(overheads):.1f} ms")

    median = statistics.median(overheads)
    if median <= 50:
        print(f"\nRESULT: PASS  (median {median:.1f} ms ≤ 50 ms target)")
    else:
        print(f"\nRESULT: FAIL  (median {median:.1f} ms > 50 ms target — known limit, flag to owner)")


if __name__ == "__main__":
    main()
