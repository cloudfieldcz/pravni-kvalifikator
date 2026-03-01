"""Agent 4 — Reviewer: cross-checks qualification for consistency and completeness."""

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from pravni_kvalifikator.agents.activity import log_agent_activity
from pravni_kvalifikator.agents.state import QualificationState
from pravni_kvalifikator.shared.llm import call_llm_structured, get_llm

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Jsi senior právní expert provádějící revizi právní kvalifikace skutku.
Tvým úkolem je zkontrolovat kvalifikaci provedenou předchozím agentem a opravit chyby.

Zkontroluj následující aspekty:

1. SOUBĚH TRESTNÝCH ČINŮ:
   - Jednočinný souběh: Jeden skutek naplňuje znaky více TČ
     (např. vloupání do bytu = § 205 krádež + § 178 porušování domovní svobody)
   - Vícečinný souběh: Více skutků v jednom popisu
   - Pokud chybí kvalifikace pro zjevný souběh, přidej ji s poznámkou

2. SPRÁVNOST KVALIFIKACE:
   - Jsou odstavce a písmena správně přiřazeny?
   - Odpovídá forma zavinění popisu skutku?
   - Je stadium (dokonaný/pokus/příprava) správně určeno?
   - Odpovídá kategorie škody uvedené výši?

3. KONZISTENCE CONFIDENCE SCORES:
   - Jsou scores konzistentní napříč kvalifikacemi?
   - Odpovídá confidence počtu naplněných znaků?
   - Příliš vysoké scores pro neúplné kvalifikace → snížit
   - Příliš nízké scores pro jasné kvalifikace → zvýšit

4. TC vs PR KLASIFIKACE:
   - Odpovídá typ (TC/PR) popisu skutku?
   - Může být skutek kvalifikován opačně? (např. drobná krádež pod 10 000 Kč
     může být přestupek, ne TČ)

5. REVIEW NOTES:
   - Přidej poznámky ke každé úpravě
   - Uveď důvod změny confidence score
   - Zaznamenej chybějící informace důležité pro kvalifikaci

6. OKOLNOSTI VYLUČUJÍCÍ PROTIPRÁVNOST:
   Zkontroluj, zda identifikované okolnosti vylučující protiprávnost odpovídají
   popisu skutku. Pravidla pro úpravu confidence:
   - Pokud vylučující okolnost má aplikovatelnost="ano" a confidence >= 0.7:
     SNIŽ confidence dotčené kvalifikace na maximálně 0.5.
     Silná obrana (jasné splnění všech znaků § 28/29) → 0.3
     Částečná/kontextová obrana → 0.4-0.5
     Přidej review note: "Kvalifikace je podmíněná — uplatňuje se okolnost
     vylučující protiprávnost (§ XX). Skutek pravděpodobně není trestný/protiprávní."
   - Pokud aplikovatelnost="možná":
     Přidej review note s upozorněním, ale confidence nesnižuj výrazně
   - Pokud aplikovatelnost="překročení mezí":
     Kvalifikace zůstává, přidej note o překročení mezí (exces) —
     skutek je stále trestný, ale může být polehčující okolností
   - Pro každou dotčenou kvalifikaci vyplň vylucujici_okolnost_poznamka

Výstup: Upravená kvalifikace + review notes.
"""


class ReviewedKvalifikace(BaseModel):
    paragraf: str
    nazev: str
    confidence: float = Field(ge=0.0, le=1.0)
    duvod_jistoty: str
    chybejici_znaky: list[str]
    stadium: str
    forma_zavineni: str
    review_adjustment: str = Field(
        default="beze změny",
        description="Co bylo upraveno oproti původní kvalifikaci ('beze změny' pokud nic)",
    )
    vylucujici_okolnost_poznamka: str | None = Field(
        default=None,
        description="Poznámka k vylučující okolnosti vztahující se k této kvalifikaci",
    )


class ReviewerOutput(BaseModel):
    final_kvalifikace: list[ReviewedKvalifikace]
    review_notes: list[str] = Field(
        description="Poznámky reviewera — souběhy, chybějící kvalifikace, upozornění"
    )


async def reviewer_node(state: QualificationState) -> dict[str, Any]:
    """Agent 4: Review and cross-check qualification."""
    qid = state.get("qualification_id", 0)
    await log_agent_activity(qid, "reviewer", "started", "Provádím revizi kvalifikace")

    popis = state["popis_skutku"]
    kvalifikace = state.get("kvalifikace", [])
    skoda = state.get("skoda", {})
    okolnosti = state.get("okolnosti", {})
    candidate_paragraphs = state.get("candidate_paragraphs", [])

    llm = get_llm(max_tokens=8192)

    user_parts = [
        f'Popis skutku:\n"{popis}"',
        "Kvalifikace od předchozího agenta:\n"
        f"{json.dumps(kvalifikace, ensure_ascii=False, indent=2)}",
        f"Škoda: {json.dumps(skoda, ensure_ascii=False)}",
        f"Okolnosti: {json.dumps(okolnosti, ensure_ascii=False)}",
        f"Všechny kandidátní paragrafy (pro kontrolu souběhu):\n"
        f"{json.dumps(candidate_paragraphs, ensure_ascii=False, indent=2)}",
    ]

    # Pokud existují vylučující okolnosti, explicitně upozorni reviewera
    vylucujici = okolnosti.get("vylucujici_okolnosti", [])
    if vylucujici:
        user_parts.append(
            "DŮLEŽITÉ: Qualifier identifikoval okolnosti vylučující protiprávnost. "
            "Zkontroluj jejich oprávněnost a uprav confidence dotčených kvalifikací "
            "podle pravidel v bodu 6."
        )

    user_parts.append(
        "Zkontroluj kvalifikaci, oprav chyby, doplň chybějící souběhy a uprav confidence scores."
    )

    user_message = "\n\n".join(user_parts)

    result: ReviewerOutput = await call_llm_structured(
        llm,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        ReviewerOutput,
    )

    final = [k.model_dump() for k in result.final_kvalifikace]

    await log_agent_activity(
        qid,
        "reviewer",
        "completed",
        f"Revize dokončena: {len(final)} kvalifikací, {len(result.review_notes)} poznámek",
        {"final_kvalifikace": final, "review_notes": result.review_notes},
    )

    return {
        "final_kvalifikace": final,
        "review_notes": result.review_notes,
    }
