import os
import sqlite3
from typing import Optional

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except Exception:  # psycopg2 is optional if using SQLite
    psycopg2 = None


POSTGRES_DSN = os.getenv("POSTGRES_DSN")
SQLITE_PATH = os.getenv("VISITED_DB", "/data/visited.sqlite3")


def _initialize_sqlite_table(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS visited (url TEXT PRIMARY KEY)")


def record_url_sqlite(url: str) -> bool:
    _initialize_sqlite_table(SQLITE_PATH)
    with sqlite3.connect(SQLITE_PATH) as conn:
        cur = conn.execute("INSERT OR IGNORE INTO visited(url) VALUES (?)", (url,))
        return cur.rowcount == 1


def contains_url_sqlite(url: str) -> bool:
    _initialize_sqlite_table(SQLITE_PATH)
    with sqlite3.connect(SQLITE_PATH) as conn:
        cur = conn.execute("SELECT 1 FROM visited WHERE url = ? LIMIT 1", (url,))
        return cur.fetchone() is not None


def record_url_postgres(url: str) -> bool:
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required for Postgres support")
    with psycopg2.connect(POSTGRES_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS visited (url TEXT PRIMARY KEY)"
            )
            cur.execute(
                "INSERT INTO visited(url) VALUES (%s) ON CONFLICT DO NOTHING RETURNING url",
                (url,),
            )
            row = cur.fetchone()
            return row is not None


def contains_url_postgres(url: str) -> bool:
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required for Postgres support")
    with psycopg2.connect(POSTGRES_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM visited WHERE url = %s LIMIT 1", (url,))
            return cur.fetchone() is not None


def record_url(url: str) -> bool:
    """Save `url` to the visited store. Return True if it was newly added."""
    if POSTGRES_DSN:
        return record_url_postgres(url)
    return record_url_sqlite(url)


def contains_url(url: str) -> bool:
    if POSTGRES_DSN:
        return contains_url_postgres(url)
    return contains_url_sqlite(url)


# Backwards-compatible name used previously
def record_first_visit(url: str) -> bool:
    return record_url(url)
