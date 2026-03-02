"""QualificationState — the state that flows through the agent pipeline."""

from typing import TypedDict


class QualificationState(TypedDict, total=False):
    # -- Input --
    popis_skutku: str
    typ: str  # "TC" | "PR"
    qualification_id: int  # ID in sessions.db

    # -- Agent 0: Law Identifier (only for PR) --
    identified_laws: list[dict]  # [{law_id, nazev, confidence, reason}]

    # -- Agent 1: Head Classifier --
    candidate_chapters: list[dict]  # [{chapter_id, hlava_nazev, law_nazev, confidence, reason}]

    # -- Agent 2: Paragraph Selector --
    # [{paragraph_id, cislo, nazev, plne_zneni, relevance_score, matching_elements}]
    candidate_paragraphs: list[dict]

    # -- Agent 3: Qualifier --
    # [{paragraf, nazev, confidence, duvod_jistoty, chybejici_znaky, stadium, forma_zavineni}]
    kvalifikace: list[dict]
    skoda: dict  # {odhadovana_vyse, kategorie, relevantni_hranice}
    okolnosti: dict  # {vylucujici_okolnosti, polehcujici, pritezujici}

    # -- Agent 4: Reviewer --
    final_kvalifikace: list[dict]  # adjusted kvalifikace after review
    review_notes: list[str]  # reviewer notes (souběhy, missing qualifications)

    # -- Agent 5: Special Law Checker --
    # [{paragraf, nazev, zakon, confidence, duvod, chybejici_znaky}]
    special_law_kvalifikace: list[dict]
    special_law_notes: list[str]

    # -- Status --
    error: str | None
