"""Pipeline: scrape → parse → store in SQLite."""

import hashlib
import logging

from pravni_kvalifikator.mcp.db import LawsDB
from pravni_kvalifikator.mcp.parser import LawParser, ParsedLaw
from pravni_kvalifikator.mcp.scraper import LawScraper

logger = logging.getLogger(__name__)


class LawIndexer:
    """Indexes laws from zakonyprolidi.cz into SQLite."""

    def __init__(self, db: LawsDB, scraper: LawScraper | None = None):
        self.db = db
        self.scraper = scraper or LawScraper()
        self.parser = LawParser()

    @staticmethod
    def _hash_parsed(parsed: ParsedLaw) -> str:
        """Compute SHA-256 hash of parsed law content.

        Hashes paragraph numbers and full text, ignoring HTML template changes.
        """
        h = hashlib.sha256()
        for para in parsed.all_paragraphs():
            h.update(para.cislo.encode())
            h.update(b"\x00")
            h.update((para.nazev or "").encode())
            h.update(b"\x00")
            h.update(para.plne_zneni.encode())
            h.update(b"\x01")
        return h.hexdigest()

    def index_from_html(
        self,
        sbirkove_cislo: str,
        nazev: str,
        typ: str,
        html: str,
        oblasti: list[str] | None = None,
        popis: str | None = None,
    ) -> dict:
        """Parse HTML and store into DB. Returns stats.

        Compares SHA-256 hash of parsed content with stored content_hash.
        Hashing parsed content (not raw HTML) avoids false changes from
        dynamic page elements (ads, navigation, timestamps).
        If unchanged, skips re-indexing.
        If changed or new, deletes old data (including embeddings) and re-imports.
        """
        parsed = self.parser.parse(html)
        content_hash = self._hash_parsed(parsed)

        existing = self.db.get_law_by_sbirkove_cislo(sbirkove_cislo)
        if existing and existing.get("content_hash") == content_hash:
            logger.info("Skipping %s — unchanged (hash match)", sbirkove_cislo)
            return {
                "law_id": existing["id"],
                "chapters": 0,
                "paragraphs": 0,
                "skipped": True,
            }

        # Changed or new law — delete old data if exists
        if existing:
            logger.warning("Law %s changed — deleting old data and re-indexing", sbirkove_cislo)
            self.db.delete_law_cascade(existing["id"])

        law_id = self.db.upsert_law(
            sbirkove_cislo, nazev, typ, oblasti, popis, content_hash=content_hash
        )

        chapter_count = 0
        paragraph_count = 0

        for cast in parsed.casti:
            for hlava in cast.hlavy:
                # Store hlavy with paragraphs directly under them
                chapter_id = self.db.upsert_chapter(
                    law_id=law_id,
                    cast_cislo=cast.cislo if cast.nazev else None,
                    cast_nazev=cast.nazev or None,
                    hlava_cislo=hlava.cislo,
                    hlava_nazev=hlava.nazev,
                )
                chapter_count += 1

                for para in hlava.paragraphs:
                    self.db.upsert_paragraph(
                        chapter_id=chapter_id,
                        cislo=para.cislo,
                        nazev=para.nazev,
                        plne_zneni=para.plne_zneni,
                    )
                    paragraph_count += 1

                # Store díly as separate chapters
                for dil in hlava.dily:
                    dil_chapter_id = self.db.upsert_chapter(
                        law_id=law_id,
                        cast_cislo=cast.cislo if cast.nazev else None,
                        cast_nazev=cast.nazev or None,
                        hlava_cislo=hlava.cislo,
                        hlava_nazev=hlava.nazev,
                        dil_cislo=dil.cislo,
                        dil_nazev=dil.nazev,
                    )
                    chapter_count += 1

                    for para in dil.paragraphs:
                        self.db.upsert_paragraph(
                            chapter_id=dil_chapter_id,
                            cislo=para.cislo,
                            nazev=para.nazev,
                            plne_zneni=para.plne_zneni,
                        )
                        paragraph_count += 1

        stats = {
            "law_id": law_id,
            "chapters": chapter_count,
            "paragraphs": paragraph_count,
            "skipped": False,
        }
        logger.info(
            "Indexed %s: %d chapters, %d paragraphs",
            sbirkove_cislo,
            chapter_count,
            paragraph_count,
        )
        return stats

    async def index_law(
        self,
        sbirkove_cislo: str,
        nazev: str,
        typ: str,
        oblasti: list[str] | None = None,
        popis: str | None = None,
    ) -> dict:
        """Fetch law from web and index into DB."""
        html = await self.scraper.fetch(sbirkove_cislo)
        return self.index_from_html(sbirkove_cislo, nazev, typ, html, oblasti, popis)

    async def index_all(self, laws: list[dict]) -> dict:
        """Index multiple laws. Each dict has: sbirkove_cislo, nazev, typ, oblasti?, popis?."""
        total_stats = {
            "laws": 0,
            "skipped": 0,
            "chapters": 0,
            "paragraphs": 0,
            "errors": [],
        }
        for law in laws:
            try:
                stats = await self.index_law(**law)
                if stats.get("skipped"):
                    total_stats["skipped"] += 1
                else:
                    total_stats["laws"] += 1
                    total_stats["chapters"] += stats["chapters"]
                    total_stats["paragraphs"] += stats["paragraphs"]
            except Exception as e:
                logger.error("Failed to index %s: %s", law["sbirkove_cislo"], e)
                total_stats["errors"].append(
                    {"sbirkove_cislo": law["sbirkove_cislo"], "error": str(e)}
                )
        return total_stats
