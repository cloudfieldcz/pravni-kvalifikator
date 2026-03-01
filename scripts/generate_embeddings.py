"""Generate embeddings for all laws, chapters, and paragraphs in the database."""

import logging
import sys
from collections.abc import Callable

from pravni_kvalifikator.mcp.db import LawsDB
from pravni_kvalifikator.mcp.embedder import EmbeddingClient
from pravni_kvalifikator.shared.config import get_settings, setup_logging

logger = logging.getLogger(__name__)

BATCH_SIZE = 100


def _embed_and_save(
    texts: list[str],
    ids: list[int],
    embedder: EmbeddingClient,
    save_fn: Callable[[int, list[float]], None],
) -> int:
    """Embed texts in batches and save each batch to DB immediately.

    Returns count of saved embeddings.
    """
    saved = 0
    for i in range(0, len(texts), BATCH_SIZE):
        batch_texts = texts[i : i + BATCH_SIZE]
        batch_ids = ids[i : i + BATCH_SIZE]
        embeddings = embedder.embed_batch(batch_texts)
        for entity_id, emb in zip(batch_ids, embeddings):
            save_fn(entity_id, emb)
        saved += len(embeddings)
        logger.info("Saved batch %d/%d to DB", saved, len(texts))
    return saved


def generate_law_embeddings(db: LawsDB, embedder: EmbeddingClient) -> int:
    """Generate embeddings for laws. Returns count of new embeddings."""
    existing_ids = db.get_law_ids_with_embeddings()
    laws = db.list_laws()
    texts = []
    ids = []
    skipped = 0
    for law in laws:
        if law["id"] in existing_ids:
            skipped += 1
            continue
        text = law.get("popis") or f"{law['nazev']}. Oblasti: {law.get('oblasti', '')}"
        texts.append(text)
        ids.append(law["id"])

    if skipped:
        logger.info("Skipping %d laws with existing embeddings", skipped)

    if not texts:
        return 0

    return _embed_and_save(texts, ids, embedder, db.upsert_law_embedding)


def generate_chapter_embeddings(db: LawsDB, embedder: EmbeddingClient) -> int:
    """Generate embeddings for chapters. Returns count of new embeddings."""
    existing_ids = db.get_chapter_ids_with_embeddings()
    laws = db.list_laws()
    texts = []
    ids = []
    skipped = 0
    for law in laws:
        chapters = db.list_chapters(law["id"])
        law_skipped = 0
        law_new = 0
        for ch in chapters:
            if ch["id"] in existing_ids:
                law_skipped += 1
                skipped += 1
                continue
            dil_part = f", Díl {ch['dil_cislo']}: {ch['dil_nazev']}" if ch.get("dil_nazev") else ""
            text = ch.get("popis") or (
                f"{law['nazev']}, {ch.get('cast_nazev', '')} "
                f"Hlava {ch['hlava_cislo']}: {ch['hlava_nazev']}{dil_part}"
            )
            texts.append(text)
            ids.append(ch["id"])
            law_new += 1
        if law_new:
            logger.info(
                "Embedding %d chapters for %s (%d skipped)",
                law_new,
                law["sbirkove_cislo"],
                law_skipped,
            )

    if skipped:
        logger.info("Skipping %d chapters with existing embeddings total", skipped)

    if not texts:
        return 0

    return _embed_and_save(texts, ids, embedder, db.upsert_chapter_embedding)


def generate_paragraph_embeddings(db: LawsDB, embedder: EmbeddingClient) -> int:
    """Generate embeddings for paragraphs. Returns count of new embeddings."""
    existing_ids = db.get_paragraph_ids_with_embeddings()
    laws = db.list_laws()
    texts = []
    ids = []
    skipped = 0
    for law in laws:
        chapters = db.list_chapters(law["id"])
        law_skipped = 0
        law_new = 0
        for ch in chapters:
            paragraphs = db.list_paragraphs(ch["id"])
            for p in paragraphs:
                if p["id"] in existing_ids:
                    law_skipped += 1
                    skipped += 1
                    continue
                text = f"§ {p['cislo']} {p.get('nazev', '')} - {p['plne_zneni']}"
                if len(text) > 20000:
                    text = text[:20000]
                texts.append(text)
                ids.append(p["id"])
                law_new += 1
        if law_new:
            logger.info(
                "Embedding %d paragraphs for %s (%d skipped)",
                law_new,
                law["sbirkove_cislo"],
                law_skipped,
            )

    if skipped:
        logger.info("Skipping %d paragraphs with existing embeddings total", skipped)

    if not texts:
        return 0

    return _embed_and_save(texts, ids, embedder, db.upsert_paragraph_embedding)


def main():
    settings = get_settings()
    setup_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    db = LawsDB(settings.laws_db_path)
    try:
        embedder = EmbeddingClient()
    except ValueError as e:
        logger.error("Cannot create embedding client: %s", e)
        logger.error("Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY in .env")
        sys.exit(1)

    logger.info("Generating law embeddings...")
    n_laws = generate_law_embeddings(db, embedder)
    logger.info("Generated %d law embeddings", n_laws)

    logger.info("Generating chapter embeddings...")
    n_chapters = generate_chapter_embeddings(db, embedder)
    logger.info("Generated %d chapter embeddings", n_chapters)

    logger.info("Generating paragraph embeddings...")
    n_paragraphs = generate_paragraph_embeddings(db, embedder)
    logger.info("Generated %d paragraph embeddings", n_paragraphs)

    logger.info(
        "Done! Total: %d laws, %d chapters, %d paragraphs", n_laws, n_chapters, n_paragraphs
    )


if __name__ == "__main__":
    main()
