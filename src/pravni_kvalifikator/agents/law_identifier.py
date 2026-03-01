"""Agent 0 — Law Identifier: identifies relevant laws for misdemeanor cases."""

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
Jsi právní expert specializovaný na české právo. Tvým úkolem je identifikovat \
relevantní zákony pro daný popis přestupku.

Na základě popisu skutku a seznamu nalezených zákonů z databáze:
1. Vyber zákony, které jsou relevantní pro popis skutku
2. Přiřaď každému zákonu confidence score (0.0-1.0)
3. Stručně zdůvodni, proč je zákon relevantní

Confidence score:
- 0.7-1.0: Zákon je vysoce relevantní
- 0.3-0.7: Zákon může být relevantní
- 0.0-0.3: Zákon pravděpodobně není relevantní (nezahrnuj)
"""


class IdentifiedLaw(BaseModel):
    law_id: int
    nazev: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class LawIdentifierOutput(BaseModel):
    laws: list[IdentifiedLaw]


async def law_identifier_node(state: QualificationState) -> dict[str, Any]:
    """Agent 0: Identify relevant laws for misdemeanor cases."""
    qid = state.get("qualification_id", 0)
    await log_agent_activity(qid, "law_identifier", "started", "Identifikuji relevantní zákony")

    popis = state["popis_skutku"]

    # Search for relevant laws via MCP
    mcp = get_mcp_client()
    search_results_raw = await mcp.search_laws(query=popis, top_k=10)
    search_results = json.loads(search_results_raw)

    if not search_results:
        await log_agent_activity(
            qid, "law_identifier", "completed", "Nepodařilo se identifikovat relevantní zákon"
        )
        # NOTE (P3-3): LangGraph nodes must return ONLY changed keys.
        return {"identified_laws": []}

    # Use LLM to filter and score
    llm = get_llm()
    user_message = f"""Popis skutku (přestupek):
\"{popis}\"

Nalezené zákony v databázi:
{json.dumps(search_results, ensure_ascii=False, indent=2)}

Vyber relevantní zákony a přiřaď jim confidence score."""

    result: LawIdentifierOutput = await call_llm_structured(
        llm,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        LawIdentifierOutput,
    )

    # Filter low-confidence results
    identified = [law.model_dump() for law in result.laws if law.confidence > 0.3]

    await log_agent_activity(
        qid,
        "law_identifier",
        "completed",
        f"Identifikováno {len(identified)} zákonů",
        {"identified_laws": identified},
    )

    return {"identified_laws": identified}
