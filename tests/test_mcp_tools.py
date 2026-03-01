"""Tests for MCP server tools."""

import json
import math
from unittest.mock import MagicMock

import pytest

from pravni_kvalifikator.mcp.db import LawsDB
from pravni_kvalifikator.mcp.main import (
    get_damage_thresholds,
    get_paragraph_text,
    list_chapters,
    list_laws,
    list_paragraphs,
    search_chapters,
    search_laws,
    search_paragraphs,
    search_paragraphs_keyword,
)
from pravni_kvalifikator.shared.config import EMBEDDING_DIMENSIONS


def _fake_embedding(seed: float = 0.1) -> list[float]:
    return [math.sin(seed * (i + 1)) for i in range(EMBEDDING_DIMENSIONS)]


@pytest.fixture
def populated_db(tmp_path, monkeypatch):
    """Create and populate a test database, patch the MCP server to use it."""
    db_path = tmp_path / "test_laws.db"
    db = LawsDB(db_path)
    db.create_tables()

    # Populate with test data
    law_id = db.upsert_law("40/2009", "Trestní zákoník", "TZ")
    ch_id = db.upsert_chapter(
        law_id=law_id,
        cast_cislo="2",
        cast_nazev="ZVLÁŠTNÍ ČÁST",
        hlava_cislo="V",
        hlava_nazev="TRESTNÉ ČINY PROTI MAJETKU",
    )
    db.upsert_paragraph(ch_id, "205", "Krádež", "Kdo si přisvojí cizí věc tím, že se jí zmocní...")
    db.upsert_paragraph(ch_id, "206", "Neoprávněné užívání cizí věci", "Kdo se zmocní cizí věci...")

    db.upsert_law("251/2016", "Zákon o přestupcích", "prestupkovy")

    # Patch the _get_db function in main module
    monkeypatch.setattr("pravni_kvalifikator.mcp.main._get_db", lambda: db)

    return db


class TestNavigationTools:
    def test_list_laws_all(self, populated_db):
        result = list_laws()
        data = json.loads(result)
        assert len(data) == 2

    def test_list_laws_by_type(self, populated_db):
        result = list_laws(typ="TZ")
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["nazev"] == "Trestní zákoník"

    def test_list_chapters(self, populated_db):
        result = list_chapters(law_id=1)
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["hlava_nazev"] == "TRESTNÉ ČINY PROTI MAJETKU"

    def test_list_paragraphs(self, populated_db):
        result = list_paragraphs(chapter_id=1)
        data = json.loads(result)
        assert len(data) == 2

    def test_get_paragraph_text_by_id(self, populated_db):
        result = get_paragraph_text(paragraph_id=1)
        data = json.loads(result)
        assert data["cislo"] == "205"
        assert "přisvojí" in data["plne_zneni"]

    def test_get_paragraph_text_by_law_and_cislo(self, populated_db):
        result = get_paragraph_text(law_sbirkove_cislo="40/2009", paragraph_cislo="205")
        data = json.loads(result)
        assert data["cislo"] == "205"

    def test_get_damage_thresholds(self, populated_db):
        result = get_damage_thresholds()
        data = json.loads(result)
        assert len(data) == 5


class TestSemanticTools:
    def test_search_laws(self, populated_db, monkeypatch):
        """search_laws returns results when embeddings exist."""
        # Add embedding for the test law
        populated_db.upsert_law_embedding(1, _fake_embedding(0.1))

        # Mock the embedder
        mock_embedder = MagicMock()
        mock_embedder.embed_text.return_value = _fake_embedding(0.1)
        monkeypatch.setattr("pravni_kvalifikator.mcp.main._get_embedder", lambda: mock_embedder)

        result = search_laws(query="krádež", top_k=5)
        data = json.loads(result)
        assert len(data) >= 1

    def test_search_chapters(self, populated_db, monkeypatch):
        """search_chapters returns results."""
        populated_db.upsert_chapter_embedding(1, _fake_embedding(0.5))

        mock_embedder = MagicMock()
        mock_embedder.embed_text.return_value = _fake_embedding(0.5)
        monkeypatch.setattr("pravni_kvalifikator.mcp.main._get_embedder", lambda: mock_embedder)

        result = search_chapters(query="majetkové trestné činy", top_k=5)
        data = json.loads(result)
        assert len(data) >= 1

    def test_search_paragraphs(self, populated_db, monkeypatch):
        """search_paragraphs returns results."""
        populated_db.upsert_paragraph_embedding(1, _fake_embedding(0.7))

        mock_embedder = MagicMock()
        mock_embedder.embed_text.return_value = _fake_embedding(0.7)
        monkeypatch.setattr("pravni_kvalifikator.mcp.main._get_embedder", lambda: mock_embedder)

        result = search_paragraphs(query="krádež cizí věci", top_k=10)
        data = json.loads(result)
        assert len(data) >= 1

    def test_search_paragraphs_keyword(self, populated_db):
        result = search_paragraphs_keyword(keywords="přisvojí", top_k=10)
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["cislo"] == "205"
