"""Agent 2 — Paragraph Selector: selects candidate paragraphs from classified heads."""

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from pravni_kvalifikator.agents.activity import log_agent_activity
from pravni_kvalifikator.agents.state import QualificationState
from pravni_kvalifikator.shared.llm import call_llm_structured, get_llm
from pravni_kvalifikator.shared.mcp_client import get_mcp_client

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Jsi právní expert specializovaný na české trestní a přestupkové právo.
Tvým úkolem je vybrat konkrétní paragrafy, které nejlépe odpovídají popsanému skutku.

Dostal jsi popis skutku a seznam kandidátních paragrafů nalezených sémantickým
a klíčovým vyhledáváním. Pro každý relevantní paragraf:
1. Ověř, že skutková podstata odpovídá popisu skutku
2. Přiřaď relevance_score (0.0-1.0)
3. Uveď, které znaky skutkové podstaty odpovídají popisu
4. Zvažuj i kvalifikované skutkové podstaty (vyšší odstavce)

DŮLEŽITÉ: Zahrň i paragrafy pro souběh (pokud skutek naplňuje více skutkových podstat).
Nezahrnuj paragrafy s relevance_score pod 0.3.
"""


class LLMCandidateParagraph(BaseModel):
    """LLM output model — no plne_zneni (we already have it from DB)."""

    paragraph_id: int
    cislo: str  # e.g. "205"
    nazev: str  # e.g. "Krádež"
    relevance_score: float = Field(ge=0.0, le=1.0)
    matching_elements: list[str]  # which znaky match


class ParagraphSelectorOutput(BaseModel):
    paragraphs: list[LLMCandidateParagraph]


async def paragraph_selector_node(state: QualificationState) -> dict[str, Any]:
    """Agent 2: Select candidate paragraphs using semantic + keyword search."""
    qid = state.get("qualification_id", 0)
    await log_agent_activity(
        qid, "paragraph_selector", "started", "Vyhledávám kandidátní paragrafy"
    )

    popis = state["popis_skutku"]
    chapters = state.get("candidate_chapters", [])

    mcp = get_mcp_client()

    # For each candidate chapter: semantic search + keyword search, merge results
    all_paragraphs = []
    seen_ids: set[int] = set()

    for ch in chapters:
        ch_id = ch["chapter_id"]

        # Semantic search
        raw_semantic = await mcp.search_paragraphs(query=popis, chapter_id=ch_id, top_k=5)
        semantic_results = json.loads(raw_semantic)

        # Keyword search
        raw_keyword = await mcp.search_paragraphs_keyword(keywords=popis, chapter_id=ch_id, top_k=5)
        keyword_results = json.loads(raw_keyword)

        # Merge and deduplicate
        for p in semantic_results + keyword_results:
            pid = p.get("paragraph_id") or p.get("id")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                all_paragraphs.append(p)

    if not all_paragraphs:
        await log_agent_activity(
            qid, "paragraph_selector", "completed", "Nenalezeny žádné paragrafy"
        )
        return {"candidate_paragraphs": []}

    # Fetch full text for top candidates
    for p in all_paragraphs:
        pid = p.get("paragraph_id") or p.get("id")
        if pid:
            raw_text = await mcp.get_paragraph_text(paragraph_id=pid)
            p["plne_zneni"] = raw_text

    # LLM selects and scores
    llm = get_llm()
    user_message = f"""Popis skutku:
\"{popis}\"

Kandidátní paragrafy nalezené v databázi:
{json.dumps(all_paragraphs, ensure_ascii=False, indent=2)}

Vyber nejrelevantnější paragrafy a ohodnoť je."""

    result: ParagraphSelectorOutput = await call_llm_structured(
        llm,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        ParagraphSelectorOutput,
        max_tokens=8192,
    )

    # Build lookup: paragraph_id -> plne_zneni from DB-fetched data
    text_lookup = {
        (p.get("paragraph_id") or p.get("id")): p.get("plne_zneni", "")
        for p in all_paragraphs
    }

    candidates = []
    for p in result.paragraphs:
        if p.relevance_score > 0.3:
            d = p.model_dump()
            d["plne_zneni"] = text_lookup.get(p.paragraph_id, "")
            candidates.append(d)

    await log_agent_activity(
        qid,
        "paragraph_selector",
        "completed",
        f"Vybráno {len(candidates)} paragrafů",
        {"candidate_paragraphs": candidates},
    )

    return {"candidate_paragraphs": candidates}
