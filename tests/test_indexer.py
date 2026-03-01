from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from pravni_kvalifikator.mcp.db import LawsDB
from pravni_kvalifikator.mcp.indexer import LawIndexer

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test_laws.db"
    db = LawsDB(db_path)
    db.create_tables()
    return db


@pytest.fixture
def tz_html():
    path = FIXTURES / "zakon_40_2009_sample.html"
    if not path.exists():
        pytest.skip("Fixture not found")
    return path.read_text(encoding="utf-8")


@pytest.fixture
def indexer(db):
    return LawIndexer(db)


class TestLawIndexer:
    def test_index_from_html(self, indexer, db, tz_html):
        """Index a law from already-fetched HTML."""
        stats = indexer.index_from_html(
            sbirkove_cislo="40/2009",
            nazev="Trestní zákoník",
            typ="TZ",
            html=tz_html,
        )
        assert stats["paragraphs"] > 100  # TZ has ~420 paragraphs
        assert stats["chapters"] > 0

        # Verify data in DB
        laws = db.list_laws()
        assert len(laws) == 1
        assert laws[0]["sbirkove_cislo"] == "40/2009"

    def test_index_is_idempotent(self, indexer, db, tz_html):
        """Running index twice doesn't duplicate data."""
        indexer.index_from_html("40/2009", "TZ", "TZ", tz_html)
        indexer.index_from_html("40/2009", "TZ", "TZ", tz_html)

        laws = db.list_laws()
        assert len(laws) == 1

    def test_index_skips_unchanged_law(self, indexer, db, tz_html):
        """Second index with same HTML is skipped (hash match)."""
        stats1 = indexer.index_from_html("40/2009", "TZ", "TZ", tz_html)
        assert stats1["skipped"] is False
        assert stats1["paragraphs"] > 0

        stats2 = indexer.index_from_html("40/2009", "TZ", "TZ", tz_html)
        assert stats2["skipped"] is True
        assert stats2["chapters"] == 0
        assert stats2["paragraphs"] == 0

        # Data still present in DB
        laws = db.list_laws()
        assert len(laws) == 1

    def test_index_reindexes_changed_law(self, indexer, db, tz_html):
        """Changed parsed content triggers delete + re-index."""
        stats1 = indexer.index_from_html("40/2009", "TZ", "TZ", tz_html)
        original_paragraphs = stats1["paragraphs"]

        # Add embeddings so we can verify they get cleaned up
        law = db.get_law_by_sbirkove_cislo("40/2009")
        db.upsert_law_embedding(law["id"], [0.1] * 1536)

        # Modify actual law content (change paragraph text) — this changes the parsed hash
        modified_html = tz_html.replace("přisvojí cizí věc", "přisvojí cizí movitou věc")
        stats2 = indexer.index_from_html("40/2009", "TZ", "TZ", modified_html)
        assert stats2["skipped"] is False
        assert stats2["paragraphs"] == original_paragraphs

        # Law embedding should be gone (cascade cleanup)
        assert db.get_law_ids_with_embeddings() == set()

    def test_index_skips_when_only_html_template_changes(self, indexer, db, tz_html):
        """HTML-only changes (comments, template) don't trigger re-index."""
        indexer.index_from_html("40/2009", "TZ", "TZ", tz_html)

        modified_html = tz_html + "<!-- dynamic ad content -->"
        stats = indexer.index_from_html("40/2009", "TZ", "TZ", modified_html)
        assert stats["skipped"] is True

    def test_index_stores_content_hash(self, indexer, db, tz_html):
        """content_hash is stored in DB after indexing."""
        indexer.index_from_html("40/2009", "TZ", "TZ", tz_html)
        law = db.get_law_by_sbirkove_cislo("40/2009")
        assert law["content_hash"] is not None
        assert len(law["content_hash"]) == 64  # SHA-256 hex

    @pytest.mark.asyncio
    async def test_index_law_fetches_and_stores(self, indexer, tz_html):
        """index_law() fetches from web and stores in DB."""
        with patch.object(indexer.scraper, "fetch", new_callable=AsyncMock, return_value=tz_html):
            stats = await indexer.index_law(
                sbirkove_cislo="40/2009",
                nazev="Trestní zákoník",
                typ="TZ",
            )
            assert stats["paragraphs"] > 0
