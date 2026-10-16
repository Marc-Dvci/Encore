"""SQLite storage: the care home's own records, the private Qloo cache and the request log.

Resident records (names, rooms, care notes) live only here. The Qloo cache is private server-side
storage, which Qloo's hackathon terms allow; it is never committed to the repository.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, first_name TEXT NOT NULL, last_initial TEXT,
  birth_year INTEGER NOT NULL, city TEXT, country TEXT, demonym TEXT, cuisine TEXT, music_genre TEXT, languages TEXT,
  room TEXT, present INTEGER NOT NULL DEFAULT 1, care_note TEXT, family_note TEXT, portrait TEXT, owner TEXT
);
CREATE TABLE IF NOT EXISTS favourites (
  id INTEGER PRIMARY KEY AUTOINCREMENT, person_id TEXT NOT NULL, label TEXT NOT NULL, kind TEXT NOT NULL,
  entity_id TEXT, entity_name TEXT, status TEXT NOT NULL DEFAULT 'pending', source TEXT NOT NULL DEFAULT 'family',
  added_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS avoid (
  id INTEGER PRIMARY KEY AUTOINCREMENT, person_id TEXT NOT NULL, tag_id TEXT, entity_id TEXT,
  label TEXT NOT NULL, source TEXT NOT NULL, added_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS reactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL DEFAULT (datetime('now')), person_id TEXT NOT NULL,
  carer_id TEXT, session_id TEXT, entity_id TEXT NOT NULL, entity_name TEXT NOT NULL, entity_type TEXT NOT NULL,
  reaction TEXT NOT NULL, note TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, at TEXT NOT NULL DEFAULT (datetime('now')), kind TEXT NOT NULL, carer_id TEXT,
  person_ids TEXT NOT NULL, plan TEXT NOT NULL, closed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS qloo_cache (
  key TEXT PRIMARY KEY, path TEXT NOT NULL, body TEXT NOT NULL, fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS qloo_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, purpose TEXT NOT NULL, path TEXT NOT NULL,
  params TEXT NOT NULL, status INTEGER, ms INTEGER, cached INTEGER NOT NULL, results INTEGER
);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""


class Store:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(people)")}
        if "owner" not in cols:  # databases created before visitors could add someone
            self.db.execute("ALTER TABLE people ADD COLUMN owner TEXT")

    def q(self, sql: str, args: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.db.execute(sql, tuple(args)).fetchall()]

    def one(self, sql: str, args: Iterable[Any] = ()) -> Optional[dict]:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def x(self, sql: str, args: Iterable[Any] = ()) -> int:
        with self._lock:
            cur = self.db.execute(sql, tuple(args))
            return cur.lastrowid or 0

    def kv_get(self, k: str) -> Optional[str]:
        r = self.one("SELECT v FROM kv WHERE k=?", (k,))
        return r["v"] if r else None

    def kv_set(self, k: str, v: str) -> None:
        self.x("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))

    def kv_json(self, k: str, default: Any = None) -> Any:
        v = self.kv_get(k)
        return json.loads(v) if v else default
