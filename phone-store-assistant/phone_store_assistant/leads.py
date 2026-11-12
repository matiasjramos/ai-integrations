"""Lead persistence port and SQLite adapter (stdlib only, parameterized queries)."""

import sqlite3
from datetime import datetime, timezone
from typing import Protocol

from .models import Lead


class LeadRepository(Protocol):
    def save(self, lead: Lead) -> Lead: ...
    def list_recent(self, limit: int = 20) -> list[Lead]: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    contact TEXT NOT NULL,
    product_id TEXT NOT NULL,
    intent_summary TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""


class SqliteLeadRepository:
    def __init__(self, db_path: str = "leads.db"):
        self.db_path = db_path
        # ":memory:" is per-connection, so keep a single connection for the object's life.
        # check_same_thread=False: Streamlit may run reruns on different threads.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute(_SCHEMA)

    def save(self, lead: Lead) -> Lead:
        created_at = datetime.now(timezone.utc)
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO leads (name, contact, product_id, intent_summary, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (lead.name, lead.contact, lead.product_id, lead.intent_summary,
                 created_at.isoformat()),
            )
        return Lead(lead.name, lead.contact, lead.product_id, lead.intent_summary,
                    created_at=created_at, id=cur.lastrowid)

    def list_recent(self, limit: int = 20) -> list[Lead]:
        rows = self._conn.execute(
            "SELECT * FROM leads ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            Lead(r["name"], r["contact"], r["product_id"], r["intent_summary"],
                 created_at=datetime.fromisoformat(r["created_at"]), id=r["id"])
            for r in rows
        ]
