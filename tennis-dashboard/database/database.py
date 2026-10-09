"""SQLite access layer (thin wrapper, raw SQL, one connection per thread)."""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterable, Iterator

from database.models import SCHEMA

_LOCAL = threading.local()


class Database:
    def __init__(self, path: str):
        self.path = path
        self._init_lock = threading.Lock()
        self.ensure_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(_LOCAL, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            _LOCAL.conn = conn
        return conn

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        conn = self._conn()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    def ensure_schema(self) -> None:
        with self._init_lock:
            conn = self._conn()
            conn.executescript(SCHEMA)
            conn.commit()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self.cursor() as cur:
            cur.execute(sql, tuple(params))

    def executemany(self, sql: str, seq: Iterable[Iterable[Any]]) -> None:
        with self.cursor() as cur:
            cur.executemany(sql, [tuple(p) for p in seq])

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self.cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.fetchall()

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self.cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.fetchone()

    def upsert(self, table: str, data: dict[str, Any], conflict_keys: list[str]) -> None:
        cols = list(data.keys())
        placeholders = ",".join("?" for _ in cols)
        updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in conflict_keys)
        conflict = ",".join(conflict_keys)
        sql = (
            f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT({conflict}) DO UPDATE SET {updates}"
        )
        self.execute(sql, [data[c] for c in cols])

    def get_setting(self, key: str) -> str | None:
        row = self.query_one("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        self.upsert("settings", {"key": key, "value": value}, ["key"])

    def all_settings(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self.query("SELECT key, value FROM settings")}


_DB: Database | None = None


def get_db(path: str | None = None) -> Database:
    global _DB
    if _DB is None:
        from config import DB_PATH

        _DB = Database(path or DB_PATH)
    return _DB


def reset_db_for_tests(path: str) -> Database:
    global _DB
    if os.path.exists(path):
        os.remove(path)
    _LOCAL.__dict__.pop("conn", None)
    _DB = Database(path)
    return _DB
