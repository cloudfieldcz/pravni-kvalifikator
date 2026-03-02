"""Download and index all laws from zakonyprolidi.cz into SQLite."""

import asyncio
import logging
import sys

from pravni_kvalifikator.mcp.db import LawsDB
from pravni_kvalifikator.mcp.indexer import LawIndexer
from pravni_kvalifikator.mcp.registry import LAW_REGISTRY
from pravni_kvalifikator.shared.config import get_settings, setup_logging


async def main():
    settings = get_settings()
    setup_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    db = LawsDB(settings.laws_db_path)
    db.create_tables()

    indexer = LawIndexer(db)

    logger.info("Starting law indexing: %d laws", len(LAW_REGISTRY))
    stats = await indexer.index_all(LAW_REGISTRY)

    # Delete laws no longer in registry (with all chapters, paragraphs, embeddings)
    registry_cisla = {law["sbirkove_cislo"] for law in LAW_REGISTRY}
    for db_law in db.list_laws():
        if db_law["sbirkove_cislo"] not in registry_cisla:
            logger.warning(
                "Removing %s (%s) — no longer in registry",
                db_law["sbirkove_cislo"],
                db_law["nazev"],
            )
            db.delete_law_cascade(db_law["id"])
            stats["removed"] = stats.get("removed", 0) + 1

    logger.info(
        "Indexing complete: %d laws, %d chapters, %d paragraphs, %d removed, %d errors",
        stats["laws"],
        stats["chapters"],
        stats["paragraphs"],
        stats.get("removed", 0),
        len(stats["errors"]),
    )

    if stats["errors"]:
        logger.warning("Errors:")
        for err in stats["errors"]:
            logger.warning("  %s: %s", err["sbirkove_cislo"], err["error"])
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
