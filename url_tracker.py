import os
import sqlite3
from typing import Optional

try:
    import psycopg2
except Exception:  # pragma: no cover - optional dependency
    psycopg2 = None


POSTGRES_DSN = os.getenv("POSTGRES_DSN")
VISITED_DB = os.getenv("VISITED_DB", "/data/visited.sqlite3")


def _record_sqlite(url: str) -> bool:
    db_path = VISITED_DB
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path) as database:
        database.execute("CREATE TABLE IF NOT EXISTS visited (url TEXT PRIMARY KEY)")
        cursor = database.execute("INSERT OR IGNORE INTO visited(url) VALUES (?)", (url,))
        return cursor.rowcount == 1


def _record_postgres(url: str) -> bool:
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed")
    with psycopg2.connect(POSTGRES_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS visited (url TEXT PRIMARY KEY)"
            )
            cur.execute(
                "INSERT INTO visited(url) VALUES (%s) ON CONFLICT DO NOTHING",
                (url,),
            )
            return cur.rowcount == 1


def record_first_visit(url: str) -> bool:
    """Return True if url was not previously seen and is now recorded.

    Uses Postgres when POSTGRES_DSN is set, otherwise falls back to SQLite.
    """
    if POSTGRES_DSN:
        return _record_postgres(url)
    return _record_sqlite(url)
