import json

import pytest

from pravni_kvalifikator.mcp.db import LawsDB

SCHEMA_TABLES = ["laws", "chapters", "paragraphs", "damage_thresholds"]


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test_laws.db"
    db = LawsDB(db_path)
    db.create_tables()
    return db


def test_create_tables(db):
    """All expected tables exist after create_tables()."""
    with db._conn() as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row["name"] for row in cursor.fetchall()]
    for table in SCHEMA_TABLES:
        assert table in tables


def test_upsert_law(db):
    law_id = db.upsert_law(
        sbirkove_cislo="40/2009",
        nazev="Trestní zákoník",
        typ="TZ",
        oblasti=["majetkové TČ", "násilné TČ"],
        popis="Základní trestní zákon",
    )
    assert law_id is not None
    assert law_id > 0

    law = db.get_law(law_id)
    assert law["sbirkove_cislo"] == "40/2009"
    assert law["nazev"] == "Trestní zákoník"
    assert law["typ"] == "TZ"
    assert json.loads(law["oblasti"]) == ["majetkové TČ", "násilné TČ"]


def test_upsert_law_idempotent(db):
    """Second upsert with same sbirkove_cislo updates, not duplicates."""
    id1 = db.upsert_law("40/2009", "Trestní zákoník", "TZ")
    id2 = db.upsert_law("40/2009", "Trestní zákoník (aktualizovaný)", "TZ")
    assert id1 == id2

    law = db.get_law(id1)
    assert law["nazev"] == "Trestní zákoník (aktualizovaný)"


def test_upsert_chapter(db):
    law_id = db.upsert_law("40/2009", "TZ", "TZ")
    chapter_id = db.upsert_chapter(
        law_id=law_id,
        cast_cislo="2",
        cast_nazev="ZVLÁŠTNÍ ČÁST",
        hlava_cislo="V",
        hlava_nazev="TRESTNÉ ČINY PROTI MAJETKU",
    )
    assert chapter_id > 0

    chapters = db.list_chapters(law_id)
    assert len(chapters) == 1
    assert chapters[0]["hlava_nazev"] == "TRESTNÉ ČINY PROTI MAJETKU"


def test_upsert_paragraph(db):
    law_id = db.upsert_law("40/2009", "TZ", "TZ")
    chapter_id = db.upsert_chapter(law_id=law_id, hlava_cislo="V", hlava_nazev="TČ PROTI MAJETKU")
    paragraph_id = db.upsert_paragraph(
        chapter_id=chapter_id,
        cislo="205",
        nazev="Krádež",
        plne_zneni="(1) Kdo si přisvojí cizí věc...",
        metadata={"forma_zavineni": "úmysl"},
    )
    assert paragraph_id > 0

    para = db.get_paragraph(paragraph_id)
    assert para["cislo"] == "205"
    assert para["nazev"] == "Krádež"
    assert "přisvojí" in para["plne_zneni"]


def test_paragraph_string_cislo(db):
    """Paragraphs like '205a' must be stored as strings."""
    law_id = db.upsert_law("40/2009", "TZ", "TZ")
    ch_id = db.upsert_chapter(law_id=law_id, hlava_cislo="V", hlava_nazev="Majetkové")
    p_id = db.upsert_paragraph(ch_id, cislo="205a", nazev="Test", plne_zneni="Text")
    para = db.get_paragraph(p_id)
    assert para["cislo"] == "205a"


def test_damage_thresholds_seeded(db):
    thresholds = db.get_damage_thresholds()
    assert len(thresholds) == 5
    categories = [t["kategorie"] for t in thresholds]
    assert "nepatrná" in categories
    assert "nikoli nepatrná" in categories
    assert "větší" in categories
    assert "značná" in categories
    assert "velkého rozsahu" in categories


def test_damage_threshold_values(db):
    thresholds = db.get_damage_thresholds()
    by_cat = {t["kategorie"]: t for t in thresholds}
    assert by_cat["nepatrná"]["min_castka"] == 0
    assert by_cat["nepatrná"]["max_castka"] == 9999
    assert by_cat["nikoli nepatrná"]["min_castka"] == 10000
    assert by_cat["velkého rozsahu"]["max_castka"] is None  # unlimited


def test_list_laws(db):
    db.upsert_law("40/2009", "TZ", "TZ")
    db.upsert_law("251/2016", "Přestupkový zákon", "prestupkovy")
    all_laws = db.list_laws()
    assert len(all_laws) == 2

    tz_laws = db.list_laws(typ="TZ")
    assert len(tz_laws) == 1
    assert tz_laws[0]["nazev"] == "TZ"


def test_list_paragraphs(db):
    law_id = db.upsert_law("40/2009", "TZ", "TZ")
    ch_id = db.upsert_chapter(law_id=law_id, hlava_cislo="V", hlava_nazev="Majetkové")
    db.upsert_paragraph(ch_id, "205", "Krádež", "text1")
    db.upsert_paragraph(ch_id, "206", "Neoprávněné užívání", "text2")

    paragraphs = db.list_paragraphs(ch_id)
    assert len(paragraphs) == 2


def test_get_paragraph_by_law_and_cislo(db):
    law_id = db.upsert_law("40/2009", "TZ", "TZ")
    ch_id = db.upsert_chapter(law_id=law_id, hlava_cislo="V", hlava_nazev="Majetkové")
    db.upsert_paragraph(ch_id, "205", "Krádež", "plné znění krádeže")

    para = db.get_paragraph_by_law_and_cislo("40/2009", "205")
    assert para is not None
    assert para["nazev"] == "Krádež"
    assert para["plne_zneni"] == "plné znění krádeže"


def test_get_paragraph_by_law_and_cislo_not_found(db):
    para = db.get_paragraph_by_law_and_cislo("99/9999", "999")
    assert para is None


# ── content_hash ──


def test_upsert_law_with_content_hash(db):
    """content_hash is stored and retrievable."""
    law_id = db.upsert_law("40/2009", "TZ", "TZ", content_hash="abc123")
    law = db.get_law(law_id)
    assert law["content_hash"] == "abc123"


def test_upsert_law_updates_content_hash(db):
    """content_hash is updated on re-upsert."""
    law_id = db.upsert_law("40/2009", "TZ", "TZ", content_hash="hash_v1")
    db.upsert_law("40/2009", "TZ", "TZ", content_hash="hash_v2")
    law = db.get_law(law_id)
    assert law["content_hash"] == "hash_v2"


# ── get_law_by_sbirkove_cislo ──


def test_get_law_by_sbirkove_cislo(db):
    db.upsert_law("40/2009", "TZ", "TZ", content_hash="hash1")
    law = db.get_law_by_sbirkove_cislo("40/2009")
    assert law is not None
    assert law["nazev"] == "TZ"
    assert law["content_hash"] == "hash1"


def test_get_law_by_sbirkove_cislo_not_found(db):
    assert db.get_law_by_sbirkove_cislo("99/9999") is None


# ── delete_law_cascade ──


def _populate_law_with_embeddings(db):
    """Helper: create a law with chapters, paragraphs, and all embeddings."""
    law_id = db.upsert_law("40/2009", "TZ", "TZ", content_hash="h1")
    ch_id = db.upsert_chapter(law_id=law_id, hlava_cislo="V", hlava_nazev="Majetkové")
    p_id = db.upsert_paragraph(ch_id, "205", "Krádež", "text krádeže")

    fake_emb = [0.1] * 1536
    db.upsert_law_embedding(law_id, fake_emb)
    db.upsert_chapter_embedding(ch_id, fake_emb)
    db.upsert_paragraph_embedding(p_id, fake_emb)

    return law_id, ch_id, p_id


def test_delete_law_cascade_removes_chapters_and_paragraphs(db):
    law_id, ch_id, p_id = _populate_law_with_embeddings(db)

    db.delete_law_cascade(law_id)

    assert db.get_law(law_id) is None
    assert db.list_chapters(law_id) == []
    assert db.get_paragraph(p_id) is None


def test_delete_law_cascade_removes_embeddings(db):
    law_id, ch_id, p_id = _populate_law_with_embeddings(db)

    db.delete_law_cascade(law_id)

    assert db.get_law_ids_with_embeddings() == set()
    assert db.get_chapter_ids_with_embeddings() == set()
    assert db.get_paragraph_ids_with_embeddings() == set()


# ── get_*_ids_with_embeddings ──


def test_get_law_ids_with_embeddings(db):
    law_id = db.upsert_law("40/2009", "TZ", "TZ")
    assert db.get_law_ids_with_embeddings() == set()

    db.upsert_law_embedding(law_id, [0.1] * 1536)
    assert db.get_law_ids_with_embeddings() == {law_id}


def test_get_chapter_ids_with_embeddings(db):
    law_id = db.upsert_law("40/2009", "TZ", "TZ")
    ch_id = db.upsert_chapter(law_id=law_id, hlava_cislo="V", hlava_nazev="Majetkové")
    assert db.get_chapter_ids_with_embeddings() == set()

    db.upsert_chapter_embedding(ch_id, [0.1] * 1536)
    assert db.get_chapter_ids_with_embeddings() == {ch_id}


def test_get_paragraph_ids_with_embeddings(db):
    law_id = db.upsert_law("40/2009", "TZ", "TZ")
    ch_id = db.upsert_chapter(law_id=law_id, hlava_cislo="V", hlava_nazev="Majetkové")
    p_id = db.upsert_paragraph(ch_id, "205", "Krádež", "text")
    assert db.get_paragraph_ids_with_embeddings() == set()

    db.upsert_paragraph_embedding(p_id, [0.1] * 1536)
    assert db.get_paragraph_ids_with_embeddings() == {p_id}
