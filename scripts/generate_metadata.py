"""Generate LLM-enriched metadata for chapters and paragraphs.

For chapters: 2-3 sentence description of what the chapter covers.
For paragraphs: structured metadata (znaky skutkové podstaty, kvalifikované podstaty,
forma zavinění, trestnost přípravy, trestní sazba).

IMPORTANT: Run this AFTER load_laws.py and BEFORE generate_embeddings.py.
The generated descriptions are used as input for embedding generation.
"""

import asyncio
import json
import logging
import warnings

from pydantic import BaseModel, Field

from pravni_kvalifikator.mcp.db import LawsDB
from pravni_kvalifikator.shared.config import get_settings, setup_logging
from pravni_kvalifikator.shared.llm import get_llm

# Suppress known Pydantic serialization warning from OpenAI SDK's `parsed` field
warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings",
    category=UserWarning,
    module="pydantic",
)


class ChapterDescription(BaseModel):
    """LLM-generated chapter description."""

    popis: str = Field(description="2-3 věty popisující co řeší tato hlava/díl zákona")


class KvalifikovanaPodstata(BaseModel):
    """Single qualified fact pattern (přitěžující okolnost)."""

    okolnost: str = Field(description="Přitěžující okolnost, e.g. 'organizovaná skupina'")
    odkaz: str = Field(description="Odkaz na odstavec/písmeno, e.g. 'odst. 3 písm. a)'")


class ParagraphMetadata(BaseModel):
    """LLM-generated structured paragraph metadata."""

    znaky_skutkove_podstaty: list[str] = Field(
        default_factory=list,
        description=(
            "Znaky skutkové podstaty (objekt, objektivní stránka, subjekt, subjektivní stránka)"
        ),
    )
    kvalifikovane_podstaty: list[KvalifikovanaPodstata] = Field(
        default_factory=list,
        description="Kvalifikované skutkové podstaty — přitěžující okolnosti z vyšších odstavců",
    )
    forma_zavineni: str = Field(default="", description="úmysl / nedbalost / obojí")
    priprava_trestna: bool = Field(default=False, description="Zda je příprava trestná")
    trestni_sazba: str = Field(default="", description="Rozsah trestní sazby")


CHAPTER_PROMPT = """Jsi právní expert. Popiš 2-3 větami co řeší tato hlava/díl zákona.
Zákon: {law_nazev}
Část: {cast_nazev}
Hlava: {hlava_cislo} — {hlava_nazev}
{dil_info}

Odpověz stručně a věcně."""

PARAGRAPH_PROMPT = """Jsi právní expert. Analyzuj tento paragraf a extrahuj strukturovaná metadata.

Zákon: {law_nazev}
§ {cislo} {nazev}

Plné znění:
{plne_zneni}

Extrahuj:
1. Znaky skutkové podstaty (objekt, objektivní stránka, subjekt, subjektivní stránka)
2. Kvalifikované skutkové podstaty (odstavce 2, 3, 4... — mapuj na přitěžující okolnosti)
3. Forma zavinění (úmysl/nedbalost)
4. Zda je příprava trestná
5. Trestní sazbu"""


CONCURRENCY = 10


async def generate_chapter_descriptions(db: LawsDB, llm) -> int:
    """Generate descriptions for chapters without popis (concurrent)."""
    logger = logging.getLogger(__name__)

    # Collect work items
    work_items: list[tuple[dict, dict]] = []
    for law in db.list_laws():
        for ch in db.list_chapters(law["id"]):
            if not ch.get("popis"):
                work_items.append((law, ch))

    if not work_items:
        return 0

    logger.info("Found %d chapters needing descriptions", len(work_items))
    sem = asyncio.Semaphore(CONCURRENCY)
    completed = 0

    async def process_one(law: dict, ch: dict) -> bool:
        nonlocal completed
        dil_info = f"Díl {ch['dil_cislo']}: {ch['dil_nazev']}" if ch.get("dil_nazev") else ""
        prompt = CHAPTER_PROMPT.format(
            law_nazev=law["nazev"],
            cast_nazev=ch.get("cast_nazev", ""),
            hlava_cislo=ch["hlava_cislo"],
            hlava_nazev=ch["hlava_nazev"],
            dil_info=dil_info,
        )
        async with sem:
            try:
                structured_llm = llm.with_structured_output(ChapterDescription)
                result = await structured_llm.ainvoke([{"role": "user", "content": prompt}])
                with db._conn() as conn:
                    conn.execute(
                        "UPDATE chapters SET popis = ? WHERE id = ?",
                        (result.popis, ch["id"]),
                    )
                completed += 1
                if completed % 50 == 0:
                    logger.info("Chapters progress: %d / %d", completed, len(work_items))
                return True
            except Exception as e:
                logger.warning("Failed to generate description for chapter %d: %s", ch["id"], e)
                return False

    results = await asyncio.gather(*(process_one(law, ch) for law, ch in work_items))
    return sum(1 for r in results if r)


async def generate_paragraph_metadata(db: LawsDB, llm) -> int:
    """Generate structured metadata for paragraphs without metadata (concurrent)."""
    logger = logging.getLogger(__name__)

    # Collect work items
    work_items: list[tuple[dict, dict]] = []
    for law in db.list_laws():
        for ch in db.list_chapters(law["id"]):
            for p in db.list_paragraphs(ch["id"]):
                if not p.get("metadata"):
                    work_items.append((law, p))

    if not work_items:
        return 0

    logger.info("Found %d paragraphs needing metadata", len(work_items))
    sem = asyncio.Semaphore(CONCURRENCY)
    completed = 0
    failed = 0

    async def process_one(law: dict, p: dict) -> bool:
        nonlocal completed, failed
        prompt = PARAGRAPH_PROMPT.format(
            law_nazev=law["nazev"],
            cislo=p["cislo"],
            nazev=p.get("nazev", ""),
            plne_zneni=p["plne_zneni"][:3000],
        )
        async with sem:
            try:
                structured_llm = llm.with_structured_output(ParagraphMetadata)
                result = await structured_llm.ainvoke([{"role": "user", "content": prompt}])
                metadata_json = json.dumps(result.model_dump(), ensure_ascii=False)
                with db._conn() as conn:
                    conn.execute(
                        "UPDATE paragraphs SET metadata = ? WHERE id = ?",
                        (metadata_json, p["id"]),
                    )
                completed += 1
                if completed % 100 == 0:
                    logger.info(
                        "Paragraphs progress: %d / %d (failed: %d)",
                        completed,
                        len(work_items),
                        failed,
                    )
                return True
            except Exception as e:
                failed += 1
                logger.warning("Failed to generate metadata for § %s: %s", p["cislo"], e)
                return False

    results = await asyncio.gather(*(process_one(law, p) for law, p in work_items))
    return sum(1 for r in results if r)


async def async_main():
    settings = get_settings()
    setup_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    db = LawsDB(settings.laws_db_path)
    llm = get_llm(temperature=0.0)

    logger.info("Generating chapter descriptions...")
    n_chapters = await generate_chapter_descriptions(db, llm)
    logger.info("Generated %d chapter descriptions", n_chapters)

    logger.info("Generating paragraph metadata...")
    n_paragraphs = await generate_paragraph_metadata(db, llm)
    logger.info("Generated %d paragraph metadata records", n_paragraphs)


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
