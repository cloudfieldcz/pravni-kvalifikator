"""Agent 4 — Special Law Checker: identifies additional qualifications from special laws."""

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
Jsi právní expert specializovaný na české právo. Tvým úkolem je zkontrolovat, zda popis \
skutku nezakládá porušení speciálních zákonů nad rámec Trestního zákoníku.

Hlavní TZ kvalifikace už byla provedena. Teď hledáš DODATEČNÉ kvalifikace ze speciálních \
zákonů, které hlavní pipeline nezachytil.

Typické případy:
- Nutná obrana se zbraní → zkontroluj zákon o zbraních (oprávněnost držení/nošení)
- Řízení pod vlivem alkoholu → dopravní zákon + zákon o návykových látkách
- Výroba/distribuce drog → zákon o návykových látkách + zákon o prekurzorech
- Nelegální podnikání → živnostenský zákon
- Znečištění životního prostředí → zákon o odpadech, vodní zákon, zákon o ochraně ovzduší

DŮLEŽITÉ:
- Okolnost vylučující protiprávnost (nutná obrana, krajní nouze) se vztahuje POUZE \
  na TZ kvalifikaci. Porušení speciálního zákona (např. nelegální držení zbraně) \
  je SAMOSTATNÝ skutek — nutná obrana ho nevylučuje.
- Nezahrnuj kvalifikace s confidence pod 0.3.
- Pokud popis skutku nenaznačuje žádné porušení speciálního zákona, vrať prázdné seznamy.
- Nezahrnuj kvalifikace, které už jsou v hlavní kvalifikaci (final_kvalifikace).
"""


class SpecialLawKvalifikace(BaseModel):
    paragraf: str = Field(description="Kvalifikace, např. '§ 58 zákona 90/2024 Sb.'")
    nazev: str = Field(description="Název skutkové podstaty")
    zakon: str = Field(description="Název speciálního zákona")
    confidence: float = Field(ge=0.0, le=1.0)
    duvod: str = Field(description="Zdůvodnění kvalifikace")
    chybejici_znaky: list[str] = Field(description="Co by se muselo prokázat")


class SpecialLawCheckerOutput(BaseModel):
    kvalifikace: list[SpecialLawKvalifikace]
    notes: list[str] = Field(
        description="Poznámky ke speciálním zákonům — proč je/není porušení relevantní"
    )


async def special_law_checker_node(state: QualificationState) -> dict[str, Any]:
    """Agent 4: Check for special law violations beyond TZ qualification."""
    qid = state.get("qualification_id", 0)
    await log_agent_activity(
        qid, "special_law_checker", "started", "Kontroluji porušení speciálních zákonů"
    )

    popis = state["popis_skutku"]
    kvalifikace = state.get("kvalifikace", [])
    okolnosti = state.get("okolnosti", {})

    mcp = get_mcp_client()

    # Search for relevant special laws based on popis skutku
    await log_agent_activity(
        qid, "special_law_checker", "working", "Vyhledávám relevantní speciální zákony"
    )
    search_results_raw = await mcp.search_laws(query=popis, top_k=10)
    search_results = json.loads(search_results_raw)

    # Filter out TZ and procedural laws — we only want special laws
    special_laws = [law for law in search_results if law.get("typ") == "specialni"]

    if not special_laws:
        await log_agent_activity(
            qid, "special_law_checker", "completed", "Žádné relevantní speciální zákony nenalezeny"
        )
        return {"special_law_kvalifikace": [], "special_law_notes": []}

    # For each special law, search for relevant paragraphs
    all_paragraphs = []
    for law in special_laws:
        law_id = law.get("law_id") or law.get("id")
        if not law_id:
            continue
        raw = await mcp.search_chapters(query=popis, law_id=law_id, top_k=3)
        chapters = json.loads(raw)
        for ch in chapters:
            ch_id = ch.get("chapter_id") or ch.get("id")
            if not ch_id:
                continue
            raw_para = await mcp.search_paragraphs(query=popis, chapter_id=ch_id, top_k=3)
            paras = json.loads(raw_para)
            for p in paras:
                pid = p.get("paragraph_id") or p.get("id")
                if pid:
                    p["law_nazev"] = law.get("nazev", "")
                    raw_text = await mcp.get_paragraph_text(paragraph_id=pid)
                    p["plne_zneni"] = raw_text
                    all_paragraphs.append(p)

    if not all_paragraphs:
        await log_agent_activity(
            qid, "special_law_checker", "completed", "Žádné relevantní paragrafy speciálních zákonů"
        )
        return {"special_law_kvalifikace": [], "special_law_notes": []}

    # LLM decides which special laws are actually violated
    llm = get_llm(max_tokens=4096)

    user_parts = [
        f'Popis skutku:\n"{popis}"',
        f"Kvalifikace (TZ):\n{json.dumps(kvalifikace, ensure_ascii=False, indent=2)}",
        f"Okolnosti: {json.dumps(okolnosti, ensure_ascii=False)}",
        "Kandidátní paragrafy speciálních zákonů:\n"
        f"{json.dumps(all_paragraphs, ensure_ascii=False, indent=2)}",
        "Identifikuj porušení speciálních zákonů, která jsou DODATEČNÁ k hlavní TZ kvalifikaci.",
    ]

    user_message = "\n\n".join(user_parts)

    result: SpecialLawCheckerOutput = await call_llm_structured(
        llm,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        SpecialLawCheckerOutput,
    )

    kvalifikace_list = [k.model_dump() for k in result.kvalifikace if k.confidence > 0.3]

    await log_agent_activity(
        qid,
        "special_law_checker",
        "completed",
        f"Identifikováno {len(kvalifikace_list)} porušení speciálních zákonů",
        {"special_law_kvalifikace": kvalifikace_list, "special_law_notes": result.notes},
    )

    return {
        "special_law_kvalifikace": kvalifikace_list,
        "special_law_notes": result.notes,
    }
