"""Agent 1 — Head Classifier: classifies relevant heads (hlavy) of laws."""

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
Tvým úkolem je klasifikovat, do které hlavy (části) zákona spadá popsaný skutek.

Na základě popisu skutku a seznamu hlav nalezených v databázi:
1. Vyber hlavy, které jsou relevantní pro popis skutku
2. Přiřaď každé hlavě confidence score (0.0-1.0)
3. Stručně zdůvodni, proč je hlava relevantní
4. U trestných činů zvažuj i souběh (jednočinný i vícečinný) — skutek může spadat pod více hlav

Pro trestné činy (TC): Pracuj výhradně s hlavami Trestního zákoníku (40/2009 Sb.).
Pro přestupky (PR): Pracuj s hlavami zákonů identifikovaných v předchozím kroku.

Confidence score:
- 0.8-1.0: Hlava je vysoce relevantní (skutek jednoznačně spadá pod tuto hlavu)
- 0.5-0.8: Hlava je pravděpodobně relevantní (možný souběh nebo hraniční případ)
- 0.3-0.5: Hlava může být okrajově relevantní
- pod 0.3: Nezahrnuj
"""


class CandidateChapter(BaseModel):
    chapter_id: int
    hlava_nazev: str
    law_nazev: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class HeadClassifierOutput(BaseModel):
    chapters: list[CandidateChapter]


async def head_classifier_node(state: QualificationState) -> dict[str, Any]:
    """Agent 1: Classify relevant heads (hlavy) of laws."""
    qid = state.get("qualification_id", 0)
    await log_agent_activity(
        qid, "head_classifier", "started", "Klasifikuji relevantní hlavy zákonů"
    )

    popis = state["popis_skutku"]
    typ = state.get("typ", "TC")

    mcp = get_mcp_client()

    # For TC: search chapters of TZ. For PR: search chapters of each identified law.
    all_chapters = []
    if typ == "TC":
        raw = await mcp.search_chapters(query=popis, top_k=10)
        all_chapters = json.loads(raw)
    else:
        for law in state.get("identified_laws", []):
            raw = await mcp.search_chapters(query=popis, law_id=law["law_id"], top_k=5)
            all_chapters.extend(json.loads(raw))

    if not all_chapters:
        await log_agent_activity(
            qid, "head_classifier", "completed", "Nenalezeny žádné relevantní hlavy"
        )
        return {"candidate_chapters": []}

    llm = get_llm()
    user_message = f"""Popis skutku ({typ}):
\"{popis}\"

Nalezené hlavy zákonů v databázi:
{json.dumps(all_chapters, ensure_ascii=False, indent=2)}

Vyber relevantní hlavy a přiřaď jim confidence score."""

    result: HeadClassifierOutput = await call_llm_structured(
        llm,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        HeadClassifierOutput,
    )

    candidates = [ch.model_dump() for ch in result.chapters if ch.confidence > 0.3]

    await log_agent_activity(
        qid,
        "head_classifier",
        "completed",
        f"Klasifikováno {len(candidates)} hlav",
        {"candidate_chapters": candidates},
    )

    return {"candidate_chapters": candidates}
