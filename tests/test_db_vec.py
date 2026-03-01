"""Tests for sqlite-vec vector search functionality."""

import math

import pytest

from pravni_kvalifikator.mcp.db import LawsDB
from pravni_kvalifikator.shared.config import EMBEDDING_DIMENSIONS


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test_vec.db"
    db = LawsDB(db_path)
    db.create_tables()
    return db


def _fake_embedding(seed: float = 0.1) -> list[float]:
    """Generate a deterministic fake embedding for testing."""
    return [math.sin(seed * (i + 1)) for i in range(EMBEDDING_DIMENSIONS)]


def test_vec_tables_created(db):
    """Vector tables should exist after create_tables()."""
    with db._conn() as conn:
        # sqlite-vec virtual tables show up in sqlite_master
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'vec_%'"
        )
        tables = [row["name"] for row in cursor.fetchall()]
    assert "vec_laws" in tables
    assert "vec_chapters" in tables
    assert "vec_paragraphs" in tables


def test_upsert_law_embedding(db):
    law_id = db.upsert_law("40/2009", "TZ", "TZ")
    embedding = _fake_embedding(0.1)
    db.upsert_law_embedding(law_id, embedding)

    # Verify we can search and find it
    results = db.search_laws_vec(_fake_embedding(0.1), top_k=1)
    assert len(results) == 1
    assert results[0]["law_id"] == law_id


def test_upsert_law_embedding_overwrites_existing(db):
    law_id = db.upsert_law("40/2009", "TZ", "TZ")

    db.upsert_law_embedding(law_id, _fake_embedding(0.1))
    db.upsert_law_embedding(law_id, _fake_embedding(0.2))

    with db._conn() as conn:
        cursor = conn.execute("SELECT COUNT(*) AS cnt FROM vec_laws WHERE law_id = ?", (law_id,))
        row = cursor.fetchone()

    assert row is not None
    assert row["cnt"] == 1


def test_search_laws_vec_returns_similar(db):
    """Similar embeddings should rank higher."""
    id1 = db.upsert_law("40/2009", "TZ", "TZ")
    id2 = db.upsert_law("251/2016", "PZ", "prestupkovy")

    emb1 = _fake_embedding(0.1)
    emb2 = _fake_embedding(0.9)  # Different embedding
    db.upsert_law_embedding(id1, emb1)
    db.upsert_law_embedding(id2, emb2)

    # Search with embedding similar to emb1
    results = db.search_laws_vec(_fake_embedding(0.1), top_k=2)
    assert results[0]["law_id"] == id1  # Most similar first


def test_search_chapters_vec(db):
    law_id = db.upsert_law("40/2009", "TZ", "TZ")
    ch_id = db.upsert_chapter(law_id=law_id, hlava_cislo="V", hlava_nazev="Majetkové")
    db.upsert_chapter_embedding(ch_id, _fake_embedding(0.5))

    results = db.search_chapters_vec(_fake_embedding(0.5), top_k=1)
    assert len(results) == 1
    assert results[0]["chapter_id"] == ch_id


def test_search_chapters_vec_filtered_by_law(db):
    """search_chapters_vec with law_id filter."""
    law1 = db.upsert_law("40/2009", "TZ", "TZ")
    law2 = db.upsert_law("251/2016", "PZ", "prestupkovy")
    ch1 = db.upsert_chapter(law_id=law1, hlava_cislo="V", hlava_nazev="Majetkové")
    ch2 = db.upsert_chapter(law_id=law2, hlava_cislo="I", hlava_nazev="Obecné")

    emb = _fake_embedding(0.3)
    db.upsert_chapter_embedding(ch1, emb)
    db.upsert_chapter_embedding(ch2, emb)

    results = db.search_chapters_vec(emb, law_id=law1, top_k=10)
    assert all(r["law_id"] == law1 for r in results)


def test_search_paragraphs_vec(db):
    law_id = db.upsert_law("40/2009", "TZ", "TZ")
    ch_id = db.upsert_chapter(law_id=law_id, hlava_cislo="V", hlava_nazev="Majetkové")
    p_id = db.upsert_paragraph(ch_id, "205", "Krádež", "text")
    db.upsert_paragraph_embedding(p_id, _fake_embedding(0.7))

    results = db.search_paragraphs_vec(_fake_embedding(0.7), top_k=1)
    assert len(results) == 1
    assert results[0]["paragraph_id"] == p_id


def test_search_paragraphs_keyword(db):
    law_id = db.upsert_law("40/2009", "TZ", "TZ")
    ch_id = db.upsert_chapter(law_id=law_id, hlava_cislo="V", hlava_nazev="Majetkové")
    db.upsert_paragraph(ch_id, "205", "Krádež", "Kdo si přisvojí cizí věc")
    db.upsert_paragraph(ch_id, "206", "Neoprávněné užívání", "Kdo neoprávněně užívá cizí věc")

    results = db.search_paragraphs_keyword("přisvojí", top_k=10)
    assert len(results) == 1
    assert results[0]["cislo"] == "205"


def test_search_paragraphs_keyword_filtered_by_chapter(db):
    law_id = db.upsert_law("40/2009", "TZ", "TZ")
    ch1 = db.upsert_chapter(law_id=law_id, hlava_cislo="V", hlava_nazev="Majetkové")
    ch2 = db.upsert_chapter(law_id=law_id, hlava_cislo="VI", hlava_nazev="Hospodářské")
    db.upsert_paragraph(ch1, "205", "Krádež", "Kdo si přisvojí cizí věc")
    db.upsert_paragraph(ch2, "240", "Zkrácení daně", "Kdo si přisvojí daňovou povinnost")

    results = db.search_paragraphs_keyword("přisvojí", chapter_id=ch1, top_k=10)
    assert len(results) == 1
    assert results[0]["cislo"] == "205"
