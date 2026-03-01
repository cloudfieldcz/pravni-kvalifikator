"""Session management — SQLite database for sessions, qualifications, and agent logs."""

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

SESSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS qualifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    popis_skutku    TEXT NOT NULL,
    typ             TEXT NOT NULL,
    stav            TEXT NOT NULL DEFAULT 'pending',
    vysledek        TEXT,
    error_message   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at    TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    qualification_id    INTEGER NOT NULL REFERENCES qualifications(id) ON DELETE CASCADE,
    agent_name          TEXT NOT NULL,
    stav                TEXT NOT NULL,
    zprava              TEXT,
    data                TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_qualifications_session ON qualifications(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_log_qualification ON agent_log(qualification_id);
"""


class SessionDB:
    """SQLite access layer for sessions database."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_tables(self) -> None:
        with self._conn() as conn:
            conn.executescript(SESSION_SCHEMA)

    # ── Sessions ──

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute("INSERT INTO sessions (id) VALUES (?)", (session_id,))
        return session_id

    def create_session_with_id(self, session_id: str) -> str:
        """Create session with explicit ID (for username-based sessions)."""
        with self._conn() as conn:
            conn.execute("INSERT OR IGNORE INTO sessions (id) VALUES (?)", (session_id,))
        return session_id

    def get_session(self, session_id: str) -> dict | None:
        with self._conn() as conn:
            cursor = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # ── Qualifications ──

    def create_qualification(self, session_id: str, popis_skutku: str, typ: str) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                "INSERT INTO qualifications (session_id, popis_skutku, typ) VALUES (?, ?, ?)",
                (session_id, popis_skutku, typ),
            )
            return cursor.lastrowid

    def get_qualification(self, qualification_id: int) -> dict | None:
        with self._conn() as conn:
            cursor = conn.execute("SELECT * FROM qualifications WHERE id = ?", (qualification_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_qualification(
        self,
        qualification_id: int,
        stav: str | None = None,
        vysledek: str | None = None,
        error_message: str | None = None,
    ) -> None:
        updates = []
        params = []
        if stav is not None:
            updates.append("stav = ?")
            params.append(stav)
            if stav in ("completed", "error"):
                updates.append("completed_at = CURRENT_TIMESTAMP")
        if vysledek is not None:
            updates.append("vysledek = ?")
            params.append(vysledek)
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)

        if not updates:
            return

        params.append(qualification_id)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE qualifications SET {', '.join(updates)} WHERE id = ?",
                params,
            )

    def list_qualifications(self, session_id: str) -> list[dict]:
        with self._conn() as conn:
            cursor = conn.execute(
                "SELECT * FROM qualifications WHERE session_id = ? ORDER BY created_at DESC",
                (session_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    # ── Agent Log ──

    def insert_agent_log(
        self,
        qualification_id: int,
        agent_name: str,
        stav: str,
        zprava: str,
        data: dict | None = None,
    ) -> int:
        data_json = json.dumps(data, ensure_ascii=False) if data else None
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO agent_log (qualification_id, agent_name, stav, zprava, data)
                   VALUES (?, ?, ?, ?, ?)""",
                (qualification_id, agent_name, stav, zprava, data_json),
            )
            return cursor.lastrowid

    def get_agent_logs(self, qualification_id: int) -> list[dict]:
        with self._conn() as conn:
            cursor = conn.execute(
                "SELECT * FROM agent_log WHERE qualification_id = ? ORDER BY created_at",
                (qualification_id,),
            )
            return [dict(row) for row in cursor.fetchall()]
