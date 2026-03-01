"""Agent 3 — Qualifier: core qualification agent matching znaky skutkové podstaty."""

import asyncio
import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from pravni_kvalifikator.agents.activity import log_agent_activity
from pravni_kvalifikator.agents.state import QualificationState
from pravni_kvalifikator.shared.llm import call_llm_structured, get_llm
from pravni_kvalifikator.shared.mcp_client import MCPClient, get_mcp_client

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Jsi právní expert specializovaný na kvalifikaci trestných činů a přestupků
podle českého práva. Tvým úkolem je provést právní kvalifikaci skutku.

Pro každý kandidátní paragraf proveď analýzu:

1. ZNAKY SKUTKOVÉ PODSTATY:
   - Objekt (chráněný zájem — např. majetek, zdraví, svoboda)
   - Objektivní stránka (jednání, následek, příčinná souvislost)
   - Subjekt (kdo může být pachatelem — obecný vs. speciální)
   - Subjektivní stránka (forma zavinění — úmysl přímý/nepřímý, nedbalost vědomá/nevědomá)

2. KVALIFIKOVANÉ SKUTKOVÉ PODSTATY:
   - Ověř vyšší odstavce (odst. 2, 3, 4...) — přitěžující okolnosti
   - Zkontroluj konkrétní písmena (písm. a), b), c)...)
   - Formát: "§ 205 odst. 1 písm. b), odst. 3 písm. a)"

3. ŠKODA (pro majetkové TČ):
   - Odhadni výši škody z popisu skutku
   - Klasifikuj dle hranic: nikoli nepatrná (≥10 000), nikoli malá (≥50 000),
     větší (≥100 000), značná (≥1 000 000), velkého rozsahu (≥10 000 000)
   - Použij hranice z MCP nástroje get_damage_thresholds

4. STADIUM:
   - Dokonaný trestný čin (všechny znaky naplněny)
   - Pokus (§ 21 TZ) — jednání směřující k dokonání, k dokonání nedošlo
   - Příprava (§ 20 TZ) — jen u zvlášť závažných zločinů (sazba ≥10 let)

5. FORMA ÚČASTENSTVÍ (§ 24 TZ):
   - Pachatel (§ 22), spolupachatel (§ 23)
   - Organizátor, návodce, pomocník (§ 24)

6. CONFIDENCE SCORE:
   - 0.9-1.0: Všechny znaky skutkové podstaty jsou naplněny
   - 0.7-0.9: Většina znaků naplněna, drobné pochybnosti
   - 0.5-0.7: Některé znaky chybějí, ale kvalifikace je pravděpodobná
   - 0.3-0.5: Hraniční případ, výrazné pochybnosti
   - pod 0.3: Nezahrnuj

7. OKOLNOSTI VYLUČUJÍCÍ PROTIPRÁVNOST (§ 28-32 TZ):
   Na základě přiložených textů § 28-32 vyhodnoť, zda se na popsaný skutek
   vztahuje některá okolnost vylučující protiprávnost.
   - Pro každou relevantní okolnost uveď:
     - Na kterou kvalifikaci se vztahuje (vztahuje_se_na)
     - Aplikovatelnost: "ano" (jasně splněny znaky), "ne" (nesplněny),
       "možná" (částečně splněny / putativní obrana), "překročení mezí" (exces)
   - U přestupků (PR) se § 28-32 TZ použijí obdobně (§ 5 zákona 250/2016 Sb.)
   - Pokud popis naznačuje domněle ohrožení (putativní obrana),
     nastav aplikovatelnost="možná" s odkazem na § 18 TZ v duvod
   - Neidentifikuj okolnost, pokud popis jasně neukazuje na obrannou situaci
   - Příklady obranných situací:
     - "Útočník na něj šel s nožem, bránil se" → § 29 nutná obrana
     - "Při požáru vyrazil dveře, aby zachránil dítě" → § 28 krajní nouze
     - "Bránil se, ale pak útočníka pronásledoval a zbil" → § 29 překročení mezí

8. POLEHČUJÍCÍ A PŘITĚŽUJÍCÍ OKOLNOSTI (§ 41-42 TZ):
   Jen pro trestné činy (TC), NE pro přestupky.
   Na základě přiložených textů § 41 a § 42 identifikuj relevantní okolnosti.
   Pro každou uveď přesný odkaz (paragraf + písmeno), např. "§ 41 písm. g) TZ".

Vždy uveď chybějící znaky (co by se muselo prokázat) a důvod confidence score.
"""


class Kvalifikace(BaseModel):
    paragraf: str = Field(
        description="Plná kvalifikace, např. '§ 205 odst. 1 písm. b), odst. 3 písm. a) TZ'"
    )
    nazev: str = Field(description="Název TČ/přestupku, např. 'Krádež'")
    confidence: float = Field(ge=0.0, le=1.0)
    duvod_jistoty: str = Field(description="Proč je confidence na dané úrovni")
    chybejici_znaky: list[str] = Field(description="Co by se muselo prokázat / co chybí")
    stadium: str = Field(description="'dokonaný' | 'pokus' | 'příprava'")
    forma_zavineni: str = Field(
        description=("'úmysl přímý' | 'úmysl nepřímý' | 'nedbalost vědomá' | 'nedbalost nevědomá'")
    )


class SkodaInfo(BaseModel):
    odhadovana_vyse: int | None = Field(
        description="Odhadovaná výše škody v Kč (None pokud nelze určit)"
    )
    kategorie: str | None = Field(
        description=(
            "'nikoli nepatrná' | 'nikoli malá' | 'větší' | 'značná' | 'velkého rozsahu' | None"
        )
    )
    relevantni_hranice: str | None = Field(description="Textový popis relevantní hranice")


class VylucujiciOkolnost(BaseModel):
    paragraf: str = Field(description="'§ 28' | '§ 29' | '§ 30' | '§ 31' | '§ 32'")
    nazev: str = Field(description="'Krajní nouze' | 'Nutná obrana' | ...")
    aplikovatelnost: str = Field(description="'ano' | 'ne' | 'možná' | 'překročení mezí'")
    vztahuje_se_na: list[str] = Field(
        description="Na které kvalifikace se vztahuje, např. ['§ 146']"
    )
    duvod: str = Field(description="Zdůvodnění")
    confidence: float = Field(ge=0.0, le=1.0)


class PolehcujiciPritezujici(BaseModel):
    popis: str = Field(description="Popis okolnosti")
    paragraf_pismeno: str = Field(description="Odkaz na zákon, např. '§ 41 písm. n) TZ'")


class OkolnostiInfo(BaseModel):
    vylucujici_okolnosti: list[VylucujiciOkolnost] = Field(
        default_factory=list, description="Okolnosti vylučující protiprávnost (§ 28-32 TZ)"
    )
    polehcujici: list[PolehcujiciPritezujici] = Field(
        default_factory=list, description="Polehčující okolnosti dle § 41 TZ (jen pro TC)"
    )
    pritezujici: list[PolehcujiciPritezujici] = Field(
        default_factory=list, description="Přitěžující okolnosti dle § 42 TZ (jen pro TC)"
    )


class QualifierOutput(BaseModel):
    kvalifikace: list[Kvalifikace]
    skoda: SkodaInfo
    okolnosti: OkolnostiInfo


# Module-level cache pro statické texty zákonů
_cached_okolnosti_texts: dict[str, str] | None = None
_cache_lock = asyncio.Lock()


async def _fetch_okolnosti_texts(mcp: MCPClient) -> dict[str, str]:
    """Načti texty § 28-32, § 41, § 42 TZ. Cached po prvním úspěšném volání."""
    global _cached_okolnosti_texts
    if _cached_okolnosti_texts is not None:
        return _cached_okolnosti_texts

    async with _cache_lock:
        if _cached_okolnosti_texts is not None:
            return _cached_okolnosti_texts

        paragraphs = ["28", "29", "30", "31", "32", "41", "42"]
        texts: dict[str, str] = {}
        for cislo in paragraphs:
            try:
                raw = await mcp.get_paragraph_text(
                    law_sbirkove_cislo="40/2009", paragraph_cislo=cislo
                )
                texts[f"§ {cislo}"] = raw
            except Exception:
                logger.warning("Nepodařilo se načíst § %s TZ, pokračuji bez něj", cislo)

        if len(texts) == len(paragraphs):
            _cached_okolnosti_texts = texts
        return texts


async def qualifier_node(state: QualificationState) -> dict[str, Any]:
    """Agent 3: Qualify the act — match znaky skutkové podstaty."""
    qid = state.get("qualification_id", 0)
    await log_agent_activity(qid, "qualifier", "started", "Provádím právní kvalifikaci skutku")

    popis = state["popis_skutku"]
    typ = state.get("typ", "TC")
    paragraphs = state.get("candidate_paragraphs", [])

    mcp = get_mcp_client()

    # Get damage thresholds for context
    damage_thresholds_raw = await mcp.get_damage_thresholds()

    # Načti texty okolností vylučujících protiprávnost
    await log_agent_activity(
        qid, "qualifier", "working", "Načítám okolnosti vylučující protiprávnost"
    )
    okolnosti_texts = await _fetch_okolnosti_texts(mcp)

    # Sestav blok textů pro LLM kontext
    okolnosti_context_parts = []
    if okolnosti_texts:
        # § 28-32 se načítají vždy (pro TC i PR)
        vylucujici_parts = []
        for par in ["§ 28", "§ 29", "§ 30", "§ 31", "§ 32"]:
            if par in okolnosti_texts:
                vylucujici_parts.append(f"{par}:\n{okolnosti_texts[par]}")
        if vylucujici_parts:
            okolnosti_context_parts.append(
                "Okolnosti vylučující protiprávnost (§ 28-32 TZ):\n" + "\n\n".join(vylucujici_parts)
            )

        # § 41-42 jen pro TC
        if typ == "TC":
            polehc_parts = []
            for par in ["§ 41", "§ 42"]:
                if par in okolnosti_texts:
                    polehc_parts.append(f"{par}:\n{okolnosti_texts[par]}")
            if polehc_parts:
                okolnosti_context_parts.append(
                    "Polehčující a přitěžující okolnosti (§ 41-42 TZ):\n"
                    + "\n\n".join(polehc_parts)
                )

    okolnosti_context = "\n\n".join(okolnosti_context_parts)

    llm = get_llm(max_tokens=8192)

    user_parts = [
        f'Popis skutku:\n"{popis}"',
        f"Typ kvalifikace: {typ}",
        "Kandidátní paragrafy (s plným zněním):\n"
        f"{json.dumps(paragraphs, ensure_ascii=False, indent=2)}",
        f"Hranice výše škody:\n{damage_thresholds_raw}",
    ]

    if okolnosti_context:
        user_parts.append(okolnosti_context)

    if typ == "PR":
        user_parts.append(
            "POZNÁMKA: Jde o přestupek (PR). § 28-32 TZ se použijí obdobně "
            "(§ 5 zákona 250/2016 Sb.). § 41-42 TZ (polehčující/přitěžující) "
            "se pro přestupky NEPOUŽIJÍ — vrať prázdné seznamy polehcujici a pritezujici."
        )

    user_parts.append(
        "Proveď kvalifikaci skutku — urči přesnou právní kvalifikaci včetně odstavců a písmen, "
        "formu zavinění, stadium, výši škody, okolnosti vylučující protiprávnost"
        + (" a polehčující/přitěžující okolnosti." if typ == "TC" else ".")
    )

    user_message = "\n\n".join(user_parts)

    result: QualifierOutput = await call_llm_structured(
        llm,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        QualifierOutput,
    )

    kvalifikace_list = [k.model_dump() for k in result.kvalifikace if k.confidence > 0.3]

    await log_agent_activity(
        qid,
        "qualifier",
        "completed",
        f"Kvalifikováno {len(kvalifikace_list)} skutkových podstat",
        {"kvalifikace": kvalifikace_list},
    )

    return {
        "kvalifikace": kvalifikace_list,
        "skoda": result.skoda.model_dump(),
        "okolnosti": result.okolnosti.model_dump(),
    }
