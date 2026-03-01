"""SQLite access layer for the laws database."""

import json
import logging
import sqlite3
import struct
from contextlib import contextmanager
from pathlib import Path

import sqlite_vec

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS laws (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sbirkove_cislo TEXT NOT NULL UNIQUE,
    nazev       TEXT NOT NULL,
    typ         TEXT NOT NULL,
    oblasti     TEXT,
    popis       TEXT,
    content_hash TEXT,
    scraped_at  TIMESTAMP,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chapters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    law_id      INTEGER NOT NULL REFERENCES laws(id) ON DELETE CASCADE,
    cast_cislo  TEXT,
    cast_nazev  TEXT,
    hlava_cislo TEXT NOT NULL,
    hlava_nazev TEXT NOT NULL,
    dil_cislo   TEXT,
    dil_nazev   TEXT,
    popis       TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(law_id, cast_cislo, hlava_cislo, dil_cislo)
);

CREATE TABLE IF NOT EXISTS paragraphs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id      INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    cislo           TEXT NOT NULL,
    nazev           TEXT,
    plne_zneni      TEXT NOT NULL,
    metadata        TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chapter_id, cislo)
);

CREATE TABLE IF NOT EXISTS damage_thresholds (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kategorie   TEXT NOT NULL UNIQUE,
    min_castka  INTEGER NOT NULL,
    max_castka  INTEGER,
    paragraf    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chapters_law_id ON chapters(law_id);
CREATE INDEX IF NOT EXISTS idx_paragraphs_chapter_id ON paragraphs(chapter_id);
CREATE INDEX IF NOT EXISTS idx_laws_typ ON laws(typ);
"""

VEC_SCHEMA_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS vec_laws USING vec0(
    law_id INTEGER PRIMARY KEY,
    embedding float[1536]
);

CREATE VIRTUAL TABLE IF NOT EXISTS vec_chapters USING vec0(
    chapter_id INTEGER PRIMARY KEY,
    embedding float[1536]
);

CREATE VIRTUAL TABLE IF NOT EXISTS vec_paragraphs USING vec0(
    paragraph_id INTEGER PRIMARY KEY,
    embedding float[1536]
);
"""

SEED_DAMAGE_THRESHOLDS = """
INSERT OR IGNORE INTO damage_thresholds (kategorie, min_castka, max_castka, paragraf) VALUES
    ('nepatrná',            0,       9999, '§ 138 odst. 1 TZ'),
    ('nikoli nepatrná',     10000,  49999, '§ 138 odst. 1 TZ'),
    ('větší',               50000,  99999, '§ 138 odst. 1 TZ'),
    ('značná',              100000, 999999, '§ 138 odst. 1 TZ'),
    ('velkého rozsahu',     1000000, NULL, '§ 138 odst. 1 TZ');
"""


class LawsDB:
    """SQLite access layer for the laws database."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
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
        """Create all tables, vector tables, and seed damage thresholds."""
        with self._conn() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.executescript(VEC_SCHEMA_SQL)
            conn.executescript(SEED_DAMAGE_THRESHOLDS)

    # ── Laws ──

    def upsert_law(
        self,
        sbirkove_cislo: str,
        nazev: str,
        typ: str,
        oblasti: list[str] | None = None,
        popis: str | None = None,
        content_hash: str | None = None,
    ) -> int:
        """Insert or update a law. Returns law ID."""
        oblasti_json = json.dumps(oblasti, ensure_ascii=False) if oblasti else None
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO laws (sbirkove_cislo, nazev, typ, oblasti, popis, content_hash)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(sbirkove_cislo) DO UPDATE SET
                    nazev = excluded.nazev,
                    typ = excluded.typ,
                    oblasti = excluded.oblasti,
                    popis = excluded.popis,
                    content_hash = excluded.content_hash,
                    scraped_at = CURRENT_TIMESTAMP
                """,
                (sbirkove_cislo, nazev, typ, oblasti_json, popis, content_hash),
            )
            cursor = conn.execute("SELECT id FROM laws WHERE sbirkove_cislo = ?", (sbirkove_cislo,))
            return cursor.fetchone()["id"]

    def get_law(self, law_id: int) -> dict | None:
        with self._conn() as conn:
            cursor = conn.execute("SELECT * FROM laws WHERE id = ?", (law_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_laws(self, typ: str | None = None) -> list[dict]:
        with self._conn() as conn:
            if typ:
                cursor = conn.execute("SELECT * FROM laws WHERE typ = ? ORDER BY id", (typ,))
            else:
                cursor = conn.execute("SELECT * FROM laws ORDER BY id")
            return [dict(row) for row in cursor.fetchall()]

    def get_law_by_sbirkove_cislo(self, sbirkove_cislo: str) -> dict | None:
        """Get a law by its sbírkové číslo."""
        with self._conn() as conn:
            cursor = conn.execute("SELECT * FROM laws WHERE sbirkove_cislo = ?", (sbirkove_cislo,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_law_cascade(self, law_id: int) -> None:
        """Delete law with all chapters, paragraphs, and their embeddings.

        Vec0 virtual tables don't support CASCADE, so we manually clean them up.
        """
        with self._conn() as conn:
            # Delete paragraph embeddings
            conn.execute(
                """
                DELETE FROM vec_paragraphs WHERE paragraph_id IN (
                    SELECT p.id FROM paragraphs p
                    JOIN chapters c ON p.chapter_id = c.id
                    WHERE c.law_id = ?
                )
                """,
                (law_id,),
            )
            # Delete chapter embeddings
            conn.execute(
                "DELETE FROM vec_chapters WHERE chapter_id IN "
                "(SELECT id FROM chapters WHERE law_id = ?)",
                (law_id,),
            )
            # Delete law embedding
            conn.execute("DELETE FROM vec_laws WHERE law_id = ?", (law_id,))
            # Delete law — CASCADE handles chapters + paragraphs
            conn.execute("DELETE FROM laws WHERE id = ?", (law_id,))

    # ── Chapters ──

    def upsert_chapter(
        self,
        law_id: int,
        hlava_cislo: str,
        hlava_nazev: str,
        cast_cislo: str | None = None,
        cast_nazev: str | None = None,
        dil_cislo: str | None = None,
        dil_nazev: str | None = None,
        popis: str | None = None,
    ) -> int:
        """Insert or update a chapter. Returns chapter ID."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO chapters (law_id, cast_cislo, cast_nazev, hlava_cislo,
                                      hlava_nazev, dil_cislo, dil_nazev, popis)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(law_id, cast_cislo, hlava_cislo, dil_cislo) DO UPDATE SET
                    cast_nazev = excluded.cast_nazev,
                    hlava_nazev = excluded.hlava_nazev,
                    dil_nazev = excluded.dil_nazev,
                    popis = excluded.popis
                """,
                (
                    law_id,
                    cast_cislo,
                    cast_nazev,
                    hlava_cislo,
                    hlava_nazev,
                    dil_cislo,
                    dil_nazev,
                    popis,
                ),
            )
            cursor = conn.execute(
                """SELECT id FROM chapters
                   WHERE law_id = ? AND cast_cislo IS ? AND hlava_cislo = ? AND dil_cislo IS ?""",
                (law_id, cast_cislo, hlava_cislo, dil_cislo),
            )
            return cursor.fetchone()["id"]

    def list_chapters(self, law_id: int) -> list[dict]:
        with self._conn() as conn:
            cursor = conn.execute("SELECT * FROM chapters WHERE law_id = ? ORDER BY id", (law_id,))
            return [dict(row) for row in cursor.fetchall()]

    # ── Paragraphs ──

    def upsert_paragraph(
        self,
        chapter_id: int,
        cislo: str,
        nazev: str | None,
        plne_zneni: str,
        metadata: dict | None = None,
    ) -> int:
        """Insert or update a paragraph. Returns paragraph ID."""
        metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO paragraphs (chapter_id, cislo, nazev, plne_zneni, metadata)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chapter_id, cislo) DO UPDATE SET
                    nazev = excluded.nazev,
                    plne_zneni = excluded.plne_zneni,
                    metadata = excluded.metadata
                """,
                (chapter_id, cislo, nazev, plne_zneni, metadata_json),
            )
            cursor = conn.execute(
                "SELECT id FROM paragraphs WHERE chapter_id = ? AND cislo = ?",
                (chapter_id, cislo),
            )
            return cursor.fetchone()["id"]

    def get_paragraph(self, paragraph_id: int) -> dict | None:
        with self._conn() as conn:
            cursor = conn.execute("SELECT * FROM paragraphs WHERE id = ?", (paragraph_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_paragraphs(self, chapter_id: int) -> list[dict]:
        with self._conn() as conn:
            cursor = conn.execute(
                "SELECT * FROM paragraphs WHERE chapter_id = ? ORDER BY id", (chapter_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_paragraph_by_law_and_cislo(
        self, law_sbirkove_cislo: str, paragraph_cislo: str
    ) -> dict | None:
        """Get paragraph by law sbírkové číslo and paragraph number."""
        with self._conn() as conn:
            cursor = conn.execute(
                """
                SELECT p.* FROM paragraphs p
                JOIN chapters c ON p.chapter_id = c.id
                JOIN laws l ON c.law_id = l.id
                WHERE l.sbirkove_cislo = ? AND p.cislo = ?
                """,
                (law_sbirkove_cislo, paragraph_cislo),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    # ── Damage Thresholds ──

    def get_damage_thresholds(self) -> list[dict]:
        with self._conn() as conn:
            cursor = conn.execute("SELECT * FROM damage_thresholds ORDER BY min_castka")
            return [dict(row) for row in cursor.fetchall()]

    # ── Vector Embeddings ──

    def _pack_embedding(self, embedding: list[float]) -> bytes:
        return struct.pack(f"{len(embedding)}f", *embedding)

    def upsert_law_embedding(self, law_id: int, embedding: list[float]) -> None:
        blob = self._pack_embedding(embedding)
        with self._conn() as conn:
            conn.execute("DELETE FROM vec_laws WHERE law_id = ?", (law_id,))
            conn.execute(
                "INSERT INTO vec_laws (law_id, embedding) VALUES (?, ?)",
                (law_id, blob),
            )

    def upsert_chapter_embedding(self, chapter_id: int, embedding: list[float]) -> None:
        blob = self._pack_embedding(embedding)
        with self._conn() as conn:
            conn.execute("DELETE FROM vec_chapters WHERE chapter_id = ?", (chapter_id,))
            conn.execute(
                "INSERT INTO vec_chapters (chapter_id, embedding) VALUES (?, ?)",
                (chapter_id, blob),
            )

    def upsert_paragraph_embedding(self, paragraph_id: int, embedding: list[float]) -> None:
        blob = self._pack_embedding(embedding)
        with self._conn() as conn:
            conn.execute("DELETE FROM vec_paragraphs WHERE paragraph_id = ?", (paragraph_id,))
            conn.execute(
                "INSERT INTO vec_paragraphs (paragraph_id, embedding) VALUES (?, ?)",
                (paragraph_id, blob),
            )

    # ── Embedding existence checks ──

    def get_law_ids_with_embeddings(self) -> set[int]:
        """Return IDs of laws that already have embeddings."""
        with self._conn() as conn:
            cursor = conn.execute("SELECT law_id FROM vec_laws")
            return {row["law_id"] for row in cursor.fetchall()}

    def get_chapter_ids_with_embeddings(self) -> set[int]:
        """Return IDs of chapters that already have embeddings."""
        with self._conn() as conn:
            cursor = conn.execute("SELECT chapter_id FROM vec_chapters")
            return {row["chapter_id"] for row in cursor.fetchall()}

    def get_paragraph_ids_with_embeddings(self) -> set[int]:
        """Return IDs of paragraphs that already have embeddings."""
        with self._conn() as conn:
            cursor = conn.execute("SELECT paragraph_id FROM vec_paragraphs")
            return {row["paragraph_id"] for row in cursor.fetchall()}

    # ── Vector Search ──

    def search_laws_vec(self, query_embedding: list[float], top_k: int = 5) -> list[dict]:
        blob = self._pack_embedding(query_embedding)
        with self._conn() as conn:
            cursor = conn.execute(
                """
                SELECT v.law_id, v.distance, l.*
                FROM vec_laws v
                JOIN laws l ON v.law_id = l.id
                WHERE v.embedding MATCH ? AND k = ?
                ORDER BY v.distance
                """,
                (blob, top_k),
            )
            return [dict(row) for row in cursor.fetchall()]

    def search_chapters_vec(
        self, query_embedding: list[float], law_id: int | None = None, top_k: int = 5
    ) -> list[dict]:
        blob = self._pack_embedding(query_embedding)
        with self._conn() as conn:
            if law_id is not None:
                cursor = conn.execute(
                    """
                    SELECT v.chapter_id, v.distance, c.*, c.law_id
                    FROM vec_chapters v
                    JOIN chapters c ON v.chapter_id = c.id
                    WHERE v.embedding MATCH ? AND k = ?
                    ORDER BY v.distance
                    """,
                    (blob, top_k * 3),
                )
                results = [dict(row) for row in cursor.fetchall() if row["law_id"] == law_id]
                return results[:top_k]
            else:
                cursor = conn.execute(
                    """
                    SELECT v.chapter_id, v.distance, c.*
                    FROM vec_chapters v
                    JOIN chapters c ON v.chapter_id = c.id
                    WHERE v.embedding MATCH ? AND k = ?
                    ORDER BY v.distance
                    """,
                    (blob, top_k),
                )
                return [dict(row) for row in cursor.fetchall()]

    def search_paragraphs_vec(
        self, query_embedding: list[float], chapter_id: int | None = None, top_k: int = 10
    ) -> list[dict]:
        blob = self._pack_embedding(query_embedding)
        with self._conn() as conn:
            if chapter_id is not None:
                cursor = conn.execute(
                    """
                    SELECT v.paragraph_id, v.distance, p.*
                    FROM vec_paragraphs v
                    JOIN paragraphs p ON v.paragraph_id = p.id
                    WHERE v.embedding MATCH ? AND k = ?
                    ORDER BY v.distance
                    """,
                    (blob, top_k * 3),
                )
                results = [
                    dict(row) for row in cursor.fetchall() if row["chapter_id"] == chapter_id
                ]
                return results[:top_k]
            else:
                cursor = conn.execute(
                    """
                    SELECT v.paragraph_id, v.distance, p.*
                    FROM vec_paragraphs v
                    JOIN paragraphs p ON v.paragraph_id = p.id
                    WHERE v.embedding MATCH ? AND k = ?
                    ORDER BY v.distance
                    """,
                    (blob, top_k),
                )
                return [dict(row) for row in cursor.fetchall()]

    # ── Keyword Search ──

    def search_paragraphs_keyword(
        self, keywords: str, chapter_id: int | None = None, top_k: int = 10
    ) -> list[dict]:
        """Full-text search using SQL LIKE on paragraph text."""
        like_pattern = f"%{keywords}%"
        with self._conn() as conn:
            if chapter_id is not None:
                cursor = conn.execute(
                    """
                    SELECT * FROM paragraphs
                    WHERE chapter_id = ? AND plne_zneni LIKE ?
                    LIMIT ?
                    """,
                    (chapter_id, like_pattern, top_k),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM paragraphs
                    WHERE plne_zneni LIKE ?
                    LIMIT ?
                    """,
                    (like_pattern, top_k),
                )
            return [dict(row) for row in cursor.fetchall()]
