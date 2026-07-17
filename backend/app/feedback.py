"""Persistent thumbs-up/down vote store backed by SQLite."""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager

_db_path: str = "feedback.db"


def init_db(path: str = "feedback.db") -> None:
    global _db_path
    _db_path = path
    with _connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                place_id TEXT NOT NULL,
                vote     INTEGER NOT NULL,  -- +1 or -1
                ts       REAL NOT NULL
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_place ON feedback(place_id)")


@contextmanager
def _connect():
    con = sqlite3.connect(_db_path)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def record_vote(place_id: str, vote: int) -> None:
    with _connect() as con:
        con.execute(
            "INSERT INTO feedback (place_id, vote, ts) VALUES (?, ?, ?)",
            (place_id, vote, time.time()),
        )


def get_biases(place_ids: list[str]) -> dict[str, float]:
    """Return a score bias in [-1, 1] for each place_id that has votes."""
    if not place_ids:
        return {}
    placeholders = ",".join("?" * len(place_ids))
    with _connect() as con:
        rows = con.execute(
            f"SELECT place_id, SUM(vote), COUNT(*) FROM feedback "
            f"WHERE place_id IN ({placeholders}) GROUP BY place_id",
            place_ids,
        ).fetchall()
    result = {}
    for place_id, total, count in rows:
        # Dampen small samples; clamp to [-1, 1].
        raw = total / (count + 1)
        result[place_id] = max(-1.0, min(1.0, raw))
    return result
