"""FastMCP server with tools for law database access."""

import json
import logging

from mcp.server.fastmcp import FastMCP

from pravni_kvalifikator.mcp.db import LawsDB
from pravni_kvalifikator.shared.config import get_settings

logger = logging.getLogger(__name__)

mcp = FastMCP("pravni-kvalifikator-mcp")

# Lazy-loaded database instance
_db: LawsDB | None = None


def _get_db() -> LawsDB:
    global _db
    if _db is None:
        settings = get_settings()
        _db = LawsDB(settings.laws_db_path)
    return _db


# ── Navigation Tools ──


@mcp.tool()
def list_laws(typ: str | None = None) -> str:
    """Seznam zákonů v databázi. Volitelně filtrovaný podle typu.

    Args:
        typ: Typ zákona - "TZ" (trestní zákoník), "prestupkovy", "specialni". Bez filtru = všechny.
    """
    db = _get_db()
    laws = db.list_laws(typ=typ)
    return json.dumps(laws, ensure_ascii=False, indent=2)


@mcp.tool()
def list_chapters(law_id: int) -> str:
    """Hlavy (kapitoly) daného zákona.

    Args:
        law_id: ID zákona z tabulky laws.
    """
    db = _get_db()
    chapters = db.list_chapters(law_id)
    return json.dumps(chapters, ensure_ascii=False, indent=2)


@mcp.tool()
def list_paragraphs(chapter_id: int) -> str:
    """Paragrafy dané hlavy/dílu.

    Args:
        chapter_id: ID hlavy z tabulky chapters.
    """
    db = _get_db()
    paragraphs = db.list_paragraphs(chapter_id)
    return json.dumps(paragraphs, ensure_ascii=False, indent=2)


@mcp.tool()
def get_paragraph_text(
    paragraph_id: int | None = None,
    law_sbirkove_cislo: str | None = None,
    paragraph_cislo: str | None = None,
) -> str:
    """Plné znění paragrafu — přístup přes ID nebo sbírkové číslo + § číslo.

    Args:
        paragraph_id: Přímé ID paragrafu.
        law_sbirkove_cislo: Sbírkové číslo zákona (např. "40/2009").
        paragraph_cislo: Číslo paragrafu (např. "205", "205a").
    """
    db = _get_db()
    if paragraph_id is not None:
        para = db.get_paragraph(paragraph_id)
    elif law_sbirkove_cislo and paragraph_cislo:
        para = db.get_paragraph_by_law_and_cislo(law_sbirkove_cislo, paragraph_cislo)
    else:
        return json.dumps(
            {"error": "Zadejte paragraph_id nebo law_sbirkove_cislo + paragraph_cislo"},
            ensure_ascii=False,
        )

    if para is None:
        return json.dumps({"error": "Paragraf nenalezen"}, ensure_ascii=False)

    return json.dumps(para, ensure_ascii=False, indent=2)


@mcp.tool()
def get_damage_thresholds() -> str:
    """Tabulka hranic škod podle § 138 TZ."""
    db = _get_db()
    thresholds = db.get_damage_thresholds()
    return json.dumps(thresholds, ensure_ascii=False, indent=2)


# Lazy-loaded embedder
_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from pravni_kvalifikator.mcp.embedder import EmbeddingClient

        _embedder = EmbeddingClient()
    return _embedder


# ── Semantic Tools ──


@mcp.tool()
def search_laws(query: str, top_k: int = 5) -> str:
    """Sémantické vyhledávání zákonů podle popisu.

    Args:
        query: Textový popis skutku nebo oblasti práva.
        top_k: Maximální počet výsledků (výchozí 5).
    """
    embedder = _get_embedder()
    db = _get_db()
    query_embedding = embedder.embed_text(query)
    results = db.search_laws_vec(query_embedding, top_k=top_k)
    return json.dumps(results, ensure_ascii=False, indent=2)


@mcp.tool()
def search_chapters(query: str, law_id: int | None = None, top_k: int = 5) -> str:
    """Sémantické vyhledávání hlav zákona.

    Args:
        query: Textový popis skutku.
        law_id: Omezit hledání na konkrétní zákon (volitelné).
        top_k: Maximální počet výsledků (výchozí 5).
    """
    embedder = _get_embedder()
    db = _get_db()
    query_embedding = embedder.embed_text(query)
    results = db.search_chapters_vec(query_embedding, law_id=law_id, top_k=top_k)
    return json.dumps(results, ensure_ascii=False, indent=2)


@mcp.tool()
def search_paragraphs(query: str, chapter_id: int | None = None, top_k: int = 10) -> str:
    """Sémantické vyhledávání paragrafů.

    Args:
        query: Textový popis skutku.
        chapter_id: Omezit hledání na konkrétní hlavu (volitelné).
        top_k: Maximální počet výsledků (výchozí 10).
    """
    embedder = _get_embedder()
    db = _get_db()
    query_embedding = embedder.embed_text(query)
    results = db.search_paragraphs_vec(query_embedding, chapter_id=chapter_id, top_k=top_k)
    return json.dumps(results, ensure_ascii=False, indent=2)


# ── Keyword Tool ──


@mcp.tool()
def search_paragraphs_keyword(keywords: str, chapter_id: int | None = None, top_k: int = 10) -> str:
    """Full-text hledání klíčových slov v textu paragrafů.

    Args:
        keywords: Klíčová slova pro hledání (SQL LIKE).
        chapter_id: Omezit hledání na konkrétní hlavu (volitelné).
        top_k: Maximální počet výsledků (výchozí 10).
    """
    db = _get_db()
    results = db.search_paragraphs_keyword(keywords, chapter_id=chapter_id, top_k=top_k)
    return json.dumps(results, ensure_ascii=False, indent=2)


def main():
    """Entry point for STDIO transport."""
    mcp.run()


if __name__ == "__main__":
    main()
