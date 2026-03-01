"""Shared test fixtures for all test modules."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from pravni_kvalifikator.mcp.db import LawsDB
from pravni_kvalifikator.web.session import SessionDB


@pytest.fixture
def laws_db(tmp_path):
    """Create a test laws database with tables and seed data."""
    db_path = tmp_path / "test_laws.db"
    db = LawsDB(db_path)
    db.create_tables()
    return db


@pytest.fixture
def session_db(tmp_path):
    """Create a test sessions database."""
    db_path = tmp_path / "test_sessions.db"
    db = SessionDB(db_path)
    db.create_tables()
    return db


# ── E2E Test Fixtures ──


@pytest.fixture
def mock_llm():
    """Mock LLM that returns predefined structured outputs."""
    mock = MagicMock()
    mock.ainvoke = AsyncMock()
    return mock


@pytest.fixture
def e2e_laws_db(laws_db):
    """Extended laws_db with additional test data for E2E scenarios.

    Extends the base laws_db fixture (Phase 1) with chapters and paragraphs
    needed for E2E test scenarios (theft, assault, fraud, drugs, etc.).
    """
    # Create TZ law (upsert_law returns the ID)
    law_id = laws_db.upsert_law("40/2009", "Trestní zákoník", "TZ")

    # Chapter: TČ proti majetku (Hlava V)
    ch_majetkove = laws_db.upsert_chapter(
        law_id=law_id,
        cast_cislo="2",
        cast_nazev="ZVLÁŠTNÍ ČÁST",
        hlava_cislo="V",
        hlava_nazev="TRESTNÉ ČINY PROTI MAJETKU",
    )
    laws_db.upsert_paragraph(
        ch_majetkove,
        "205",
        "Krádež",
        "(1) Kdo si přisvojí cizí věc tím, že se jí zmocní, a způsobí tak na cizím "
        "majetku škodu nikoli nepatrnou, bude potrestán odnětím svobody až na dvě léta, "
        "zákazem činnosti nebo propadnutím věci.",
        metadata={"forma_zavineni": "úmysl"},
    )
    laws_db.upsert_paragraph(
        ch_majetkove,
        "209",
        "Podvod",
        "(1) Kdo sebe nebo jiného obohatí tím, že uvede někoho v omyl, využije "
        "něčího omylu nebo zamlčí podstatné skutečnosti, a způsobí tak na cizím "
        "majetku škodu nikoli nepatrnou, bude potrestán odnětím svobody až na dvě léta.",
        metadata={"forma_zavineni": "úmysl"},
    )

    # Chapter: TČ proti životu a zdraví (Hlava I)
    ch_zdravi = laws_db.upsert_chapter(
        law_id=law_id,
        cast_cislo="2",
        cast_nazev="ZVLÁŠTNÍ ČÁST",
        hlava_cislo="I",
        hlava_nazev="TRESTNÉ ČINY PROTI ŽIVOTU A ZDRAVÍ",
    )
    laws_db.upsert_paragraph(
        ch_zdravi,
        "146",
        "Ublížení na zdraví",
        "(1) Kdo jinému úmyslně ublíží na zdraví, bude potrestán odnětím svobody "
        "na šest měsíců až tři léta.",
        metadata={"forma_zavineni": "úmysl"},
    )

    # Chapter: TČ proti pořádku ve věcech veřejných — porušování domovní svobody
    ch_svobody = laws_db.upsert_chapter(
        law_id=law_id,
        cast_cislo="2",
        cast_nazev="ZVLÁŠTNÍ ČÁST",
        hlava_cislo="II",
        hlava_nazev="TRESTNÉ ČINY PROTI SVOBODĚ A PRÁVŮM NA OCHRANU OSOBNOSTI",
    )
    laws_db.upsert_paragraph(
        ch_svobody,
        "178",
        "Porušování domovní svobody",
        "(1) Kdo neoprávněně vnikne do obydlí jiného nebo tam neoprávněně setrvá, "
        "bude potrestán odnětím svobody až na dvě léta.",
    )

    # Chapter: TČ obecně nebezpečné (Hlava VII) — OPL
    ch_opl = laws_db.upsert_chapter(
        law_id=law_id,
        cast_cislo="2",
        cast_nazev="ZVLÁŠTNÍ ČÁST",
        hlava_cislo="VII",
        hlava_nazev="TRESTNÉ ČINY OBECNĚ NEBEZPEČNÉ",
    )
    laws_db.upsert_paragraph(
        ch_opl,
        "283",
        "Nedovolená výroba a jiné nakládání s OPL",
        "(1) Kdo neoprávněně vyrobí, doveze, vyveze, proveze, nabídne, zprostředkuje, "
        "prodá nebo jinak jinému opatří nebo pro jiného přechovává omamnou nebo "
        "psychotropní látku, bude potrestán odnětím svobody na jeden rok až pět let.",
    )

    return laws_db
