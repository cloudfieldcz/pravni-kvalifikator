"""Tests for individual agents."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pravni_kvalifikator.agents.state import QualificationState


class TestState:
    def test_state_has_special_law_keys(self):
        """QualificationState should have special_law_kvalifikace and special_law_notes."""
        hints = QualificationState.__annotations__
        assert "special_law_kvalifikace" in hints
        assert "special_law_notes" in hints


class TestLawIdentifier:
    @pytest.mark.asyncio
    async def test_identifies_relevant_laws(self):
        """Agent 0 should identify relevant laws for přestupek."""
        from pravni_kvalifikator.agents.law_identifier import law_identifier_node

        state: QualificationState = {
            "popis_skutku": "Řidič překročil povolenou rychlost o 40 km/h v obci",
            "typ": "PR",
            "qualification_id": 1,
        }

        mock_mcp = AsyncMock()
        mock_mcp.search_laws.return_value = json.dumps(
            [
                {
                    "law_id": 5,
                    "nazev": "Zákon o provozu na pozemních komunikacích",
                    "distance": 0.1,
                },
            ]
        )

        mock_llm_result = MagicMock()
        mock_llm_result.laws = [
            MagicMock(
                law_id=5,
                nazev="Zákon o provozu",
                confidence=0.9,
                reason="dopravní přestupek",
            )
        ]
        mock_llm_result.laws[0].model_dump.return_value = {
            "law_id": 5,
            "nazev": "Zákon o provozu",
            "confidence": 0.9,
            "reason": "dopravní přestupek",
        }

        with (
            patch(
                "pravni_kvalifikator.agents.law_identifier.get_mcp_client",
                return_value=mock_mcp,
            ),
            patch(
                "pravni_kvalifikator.agents.law_identifier.call_llm_structured",
                new_callable=AsyncMock,
                return_value=mock_llm_result,
            ),
            patch(
                "pravni_kvalifikator.agents.law_identifier.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            result = await law_identifier_node(state)

        assert "identified_laws" in result
        assert len(result["identified_laws"]) > 0

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_search_results(self):
        """Agent 0 should return empty list when no laws found."""
        from pravni_kvalifikator.agents.law_identifier import law_identifier_node

        state: QualificationState = {
            "popis_skutku": "Neexistující skutek",
            "typ": "PR",
            "qualification_id": 1,
        }

        mock_mcp = AsyncMock()
        mock_mcp.search_laws.return_value = "[]"

        with (
            patch(
                "pravni_kvalifikator.agents.law_identifier.get_mcp_client",
                return_value=mock_mcp,
            ),
            patch(
                "pravni_kvalifikator.agents.law_identifier.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            result = await law_identifier_node(state)

        assert result == {"identified_laws": []}


class TestHeadClassifier:
    @pytest.mark.asyncio
    async def test_classifies_heads(self):
        from pravni_kvalifikator.agents.head_classifier import head_classifier_node

        state: QualificationState = {
            "popis_skutku": "Pachatel odcizil z obchodu zboží v hodnotě 5 000 Kč",
            "typ": "TC",
            "qualification_id": 1,
        }

        mock_mcp = AsyncMock()
        mock_mcp.search_chapters.return_value = json.dumps(
            [
                {"chapter_id": 10, "hlava_nazev": "TČ PROTI MAJETKU", "distance": 0.1},
            ]
        )

        mock_llm_result = MagicMock()
        mock_llm_result.chapters = [
            MagicMock(
                chapter_id=10,
                hlava_nazev="TČ PROTI MAJETKU",
                law_nazev="TZ",
                confidence=0.95,
                reason="majetkový TČ",
            )
        ]
        mock_llm_result.chapters[0].model_dump.return_value = {
            "chapter_id": 10,
            "hlava_nazev": "TČ PROTI MAJETKU",
            "law_nazev": "TZ",
            "confidence": 0.95,
            "reason": "majetkový TČ",
        }

        with (
            patch(
                "pravni_kvalifikator.agents.head_classifier.get_mcp_client",
                return_value=mock_mcp,
            ),
            patch(
                "pravni_kvalifikator.agents.head_classifier.call_llm_structured",
                new_callable=AsyncMock,
                return_value=mock_llm_result,
            ),
            patch(
                "pravni_kvalifikator.agents.head_classifier.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            result = await head_classifier_node(state)

        assert "candidate_chapters" in result
        assert len(result["candidate_chapters"]) > 0

    @pytest.mark.asyncio
    async def test_pr_searches_identified_laws(self):
        """For PR, should search chapters of each identified law."""
        from pravni_kvalifikator.agents.head_classifier import head_classifier_node

        state: QualificationState = {
            "popis_skutku": "Řidič překročil rychlost",
            "typ": "PR",
            "qualification_id": 1,
            "identified_laws": [{"law_id": 5, "nazev": "Zákon o provozu"}],
        }

        mock_mcp = AsyncMock()
        mock_mcp.search_chapters.return_value = json.dumps(
            [
                {"chapter_id": 20, "hlava_nazev": "Přestupky", "distance": 0.2},
            ]
        )

        mock_llm_result = MagicMock()
        mock_llm_result.chapters = [
            MagicMock(
                chapter_id=20,
                hlava_nazev="Přestupky",
                law_nazev="Zákon o provozu",
                confidence=0.8,
                reason="dopravní přestupek",
            )
        ]
        mock_llm_result.chapters[0].model_dump.return_value = {
            "chapter_id": 20,
            "hlava_nazev": "Přestupky",
            "law_nazev": "Zákon o provozu",
            "confidence": 0.8,
            "reason": "dopravní přestupek",
        }

        with (
            patch(
                "pravni_kvalifikator.agents.head_classifier.get_mcp_client",
                return_value=mock_mcp,
            ),
            patch(
                "pravni_kvalifikator.agents.head_classifier.call_llm_structured",
                new_callable=AsyncMock,
                return_value=mock_llm_result,
            ),
            patch(
                "pravni_kvalifikator.agents.head_classifier.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            result = await head_classifier_node(state)

        # Should have searched with law_id=5
        mock_mcp.search_chapters.assert_called_once_with(
            query="Řidič překročil rychlost", law_id=5, top_k=5
        )
        assert len(result["candidate_chapters"]) > 0


class TestParagraphSelector:
    @pytest.mark.asyncio
    async def test_selects_paragraphs(self):
        from pravni_kvalifikator.agents.paragraph_selector import paragraph_selector_node

        state: QualificationState = {
            "popis_skutku": "Pachatel odcizil z obchodu zboží v hodnotě 5 000 Kč",
            "typ": "TC",
            "qualification_id": 1,
            "candidate_chapters": [{"chapter_id": 10, "hlava_nazev": "TČ PROTI MAJETKU"}],
        }

        mock_mcp = AsyncMock()
        mock_mcp.search_paragraphs.return_value = json.dumps(
            [{"paragraph_id": 100, "cislo": "205", "nazev": "Krádež", "distance": 0.1}]
        )
        mock_mcp.search_paragraphs_keyword.return_value = "[]"
        mock_mcp.get_paragraph_text.return_value = "Kdo si přisvojí cizí věc..."

        mock_llm_result = MagicMock()
        mock_llm_result.paragraphs = [
            MagicMock(
                paragraph_id=100,
                cislo="205",
                nazev="Krádež",
                plne_zneni="Kdo si přisvojí cizí věc...",
                relevance_score=0.95,
                matching_elements=["přisvojení cizí věci"],
            )
        ]
        mock_llm_result.paragraphs[0].model_dump.return_value = {
            "paragraph_id": 100,
            "cislo": "205",
            "nazev": "Krádež",
            "plne_zneni": "Kdo si přisvojí cizí věc...",
            "relevance_score": 0.95,
            "matching_elements": ["přisvojení cizí věci"],
        }

        with (
            patch(
                "pravni_kvalifikator.agents.paragraph_selector.get_mcp_client",
                return_value=mock_mcp,
            ),
            patch(
                "pravni_kvalifikator.agents.paragraph_selector.call_llm_structured",
                new_callable=AsyncMock,
                return_value=mock_llm_result,
            ),
            patch(
                "pravni_kvalifikator.agents.paragraph_selector.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            result = await paragraph_selector_node(state)

        assert "candidate_paragraphs" in result
        assert len(result["candidate_paragraphs"]) > 0
        assert result["candidate_paragraphs"][0]["cislo"] == "205"


def _make_qualifier_okolnosti_mock(vylucujici=None, polehcujici=None, pritezujici=None):
    """Helper: create a mock okolnosti with new format."""
    mock = MagicMock()
    mock.model_dump.return_value = {
        "vylucujici_okolnosti": vylucujici or [],
        "polehcujici": polehcujici or [],
        "pritezujici": pritezujici or [],
    }
    return mock


class TestQualifier:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        """Reset module-level okolnosti cache between tests."""
        import pravni_kvalifikator.agents.qualifier as q

        q._cached_okolnosti_texts = None
        yield
        q._cached_okolnosti_texts = None

    def _make_mcp_mock(self):
        mock_mcp = AsyncMock()
        mock_mcp.get_damage_thresholds.return_value = json.dumps(
            [{"kategorie": "nikoli nepatrná", "min_castka": 10000}]
        )
        mock_mcp.get_paragraph_text.return_value = "Text paragrafu..."
        return mock_mcp

    def _make_theft_llm_result(self):
        mock_llm_result = MagicMock()
        mock_llm_result.kvalifikace = [
            MagicMock(
                paragraf="§ 205 odst. 1 písm. a) TZ",
                nazev="Krádež",
                confidence=0.85,
                duvod_jistoty="Naplněny znaky přisvojení cizí věci",
                chybejici_znaky=["prokázání úmyslu"],
                stadium="dokonaný",
                forma_zavineni="úmysl přímý",
            )
        ]
        mock_llm_result.kvalifikace[0].model_dump.return_value = {
            "paragraf": "§ 205 odst. 1 písm. a) TZ",
            "nazev": "Krádež",
            "confidence": 0.85,
            "duvod_jistoty": "Naplněny znaky přisvojení cizí věci",
            "chybejici_znaky": ["prokázání úmyslu"],
            "stadium": "dokonaný",
            "forma_zavineni": "úmysl přímý",
        }
        mock_llm_result.skoda = MagicMock()
        mock_llm_result.skoda.model_dump.return_value = {
            "odhadovana_vyse": 5000,
            "kategorie": None,
            "relevantni_hranice": "Pod hranicí nikoli nepatrné škody (10 000 Kč)",
        }
        mock_llm_result.okolnosti = _make_qualifier_okolnosti_mock()
        return mock_llm_result

    @pytest.mark.asyncio
    async def test_qualifies_theft(self):
        from pravni_kvalifikator.agents.qualifier import qualifier_node

        state: QualificationState = {
            "popis_skutku": "Pachatel odcizil z obchodu zboží v hodnotě 5 000 Kč",
            "typ": "TC",
            "qualification_id": 1,
            "candidate_paragraphs": [
                {
                    "paragraph_id": 100,
                    "cislo": "205",
                    "nazev": "Krádež",
                    "plne_zneni": "Kdo si přisvojí cizí věc...",
                    "relevance_score": 0.95,
                    "matching_elements": ["přisvojení cizí věci"],
                }
            ],
        }

        mock_mcp = self._make_mcp_mock()
        mock_llm_result = self._make_theft_llm_result()

        with (
            patch(
                "pravni_kvalifikator.agents.qualifier.get_mcp_client",
                return_value=mock_mcp,
            ),
            patch(
                "pravni_kvalifikator.agents.qualifier.call_llm_structured",
                new_callable=AsyncMock,
                return_value=mock_llm_result,
            ),
            patch(
                "pravni_kvalifikator.agents.qualifier.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            result = await qualifier_node(state)

        assert "kvalifikace" in result
        assert "skoda" in result
        assert "okolnosti" in result
        assert len(result["kvalifikace"]) > 0
        # New okolnosti format
        assert "vylucujici_okolnosti" in result["okolnosti"]
        assert "polehcujici" in result["okolnosti"]
        assert "pritezujici" in result["okolnosti"]

    @pytest.mark.asyncio
    async def test_qualifies_with_self_defense(self):
        """Popis s nutnou obranou → vylucujici_okolnosti contains § 29."""
        from pravni_kvalifikator.agents.qualifier import qualifier_node

        state: QualificationState = {
            "popis_skutku": ("Muž na mě zaútočil nožem, bránil jsem se a zlomil mu ruku"),
            "typ": "TC",
            "qualification_id": 2,
            "candidate_paragraphs": [
                {
                    "paragraph_id": 200,
                    "cislo": "146",
                    "nazev": "Ublížení na zdraví",
                    "plne_zneni": "Kdo jinému úmyslně ublíží na zdraví...",
                    "relevance_score": 0.9,
                    "matching_elements": ["ublížení na zdraví"],
                }
            ],
        }

        mock_mcp = self._make_mcp_mock()
        mock_llm_result = MagicMock()
        mock_llm_result.kvalifikace = [
            MagicMock(
                paragraf="§ 146 odst. 1 TZ",
                nazev="Ublížení na zdraví",
                confidence=0.8,
                duvod_jistoty="Zlomenina ruky = ublížení na zdraví",
                chybejici_znaky=[],
                stadium="dokonaný",
                forma_zavineni="úmysl přímý",
            )
        ]
        mock_llm_result.kvalifikace[0].model_dump.return_value = {
            "paragraf": "§ 146 odst. 1 TZ",
            "nazev": "Ublížení na zdraví",
            "confidence": 0.8,
            "duvod_jistoty": "Zlomenina ruky = ublížení na zdraví",
            "chybejici_znaky": [],
            "stadium": "dokonaný",
            "forma_zavineni": "úmysl přímý",
        }
        mock_llm_result.skoda = MagicMock()
        mock_llm_result.skoda.model_dump.return_value = {
            "odhadovana_vyse": None,
            "kategorie": None,
            "relevantni_hranice": None,
        }
        mock_llm_result.okolnosti = _make_qualifier_okolnosti_mock(
            vylucujici=[
                {
                    "paragraf": "§ 29",
                    "nazev": "Nutná obrana",
                    "aplikovatelnost": "ano",
                    "vztahuje_se_na": ["§ 146"],
                    "duvod": "Obránce reagoval na útok nožem",
                    "confidence": 0.9,
                }
            ]
        )

        with (
            patch(
                "pravni_kvalifikator.agents.qualifier.get_mcp_client",
                return_value=mock_mcp,
            ),
            patch(
                "pravni_kvalifikator.agents.qualifier.call_llm_structured",
                new_callable=AsyncMock,
                return_value=mock_llm_result,
            ),
            patch(
                "pravni_kvalifikator.agents.qualifier.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            result = await qualifier_node(state)

        okolnosti = result["okolnosti"]
        assert len(okolnosti["vylucujici_okolnosti"]) == 1
        vo = okolnosti["vylucujici_okolnosti"][0]
        assert vo["paragraf"] == "§ 29"
        assert vo["aplikovatelnost"] == "ano"
        assert "§ 146" in vo["vztahuje_se_na"]

    @pytest.mark.asyncio
    async def test_qualifies_without_defense(self):
        """Běžná krádež → vylucujici_okolnosti is empty."""
        from pravni_kvalifikator.agents.qualifier import qualifier_node

        state: QualificationState = {
            "popis_skutku": "Pachatel odcizil z obchodu zboží v hodnotě 5 000 Kč",
            "typ": "TC",
            "qualification_id": 3,
            "candidate_paragraphs": [
                {
                    "paragraph_id": 100,
                    "cislo": "205",
                    "nazev": "Krádež",
                    "plne_zneni": "Kdo si přisvojí cizí věc...",
                    "relevance_score": 0.95,
                    "matching_elements": ["přisvojení cizí věci"],
                }
            ],
        }

        mock_mcp = self._make_mcp_mock()
        mock_llm_result = self._make_theft_llm_result()

        with (
            patch(
                "pravni_kvalifikator.agents.qualifier.get_mcp_client",
                return_value=mock_mcp,
            ),
            patch(
                "pravni_kvalifikator.agents.qualifier.call_llm_structured",
                new_callable=AsyncMock,
                return_value=mock_llm_result,
            ),
            patch(
                "pravni_kvalifikator.agents.qualifier.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            result = await qualifier_node(state)

        assert result["okolnosti"]["vylucujici_okolnosti"] == []

    @pytest.mark.asyncio
    async def test_exceeded_defense(self):
        """Exces nutné obrany → aplikovatelnost='překročení mezí'."""
        from pravni_kvalifikator.agents.qualifier import qualifier_node

        state: QualificationState = {
            "popis_skutku": ("Muž na mě zaútočil, já ho pronásledoval 500 metrů a zbil ho"),
            "typ": "TC",
            "qualification_id": 4,
            "candidate_paragraphs": [
                {
                    "paragraph_id": 200,
                    "cislo": "146",
                    "nazev": "Ublížení na zdraví",
                    "plne_zneni": "Kdo jinému úmyslně ublíží na zdraví...",
                    "relevance_score": 0.85,
                    "matching_elements": ["ublížení na zdraví"],
                }
            ],
        }

        mock_mcp = self._make_mcp_mock()
        mock_llm_result = MagicMock()
        mock_llm_result.kvalifikace = [
            MagicMock(
                paragraf="§ 146 odst. 1 TZ",
                nazev="Ublížení na zdraví",
                confidence=0.85,
                duvod_jistoty="Zbití poškozeného",
                chybejici_znaky=[],
                stadium="dokonaný",
                forma_zavineni="úmysl přímý",
            )
        ]
        mock_llm_result.kvalifikace[0].model_dump.return_value = {
            "paragraf": "§ 146 odst. 1 TZ",
            "nazev": "Ublížení na zdraví",
            "confidence": 0.85,
            "duvod_jistoty": "Zbití poškozeného",
            "chybejici_znaky": [],
            "stadium": "dokonaný",
            "forma_zavineni": "úmysl přímý",
        }
        mock_llm_result.skoda = MagicMock()
        mock_llm_result.skoda.model_dump.return_value = {
            "odhadovana_vyse": None,
            "kategorie": None,
            "relevantni_hranice": None,
        }
        mock_llm_result.okolnosti = _make_qualifier_okolnosti_mock(
            vylucujici=[
                {
                    "paragraf": "§ 29",
                    "nazev": "Nutná obrana",
                    "aplikovatelnost": "překročení mezí",
                    "vztahuje_se_na": ["§ 146"],
                    "duvod": "Obránce pronásledoval útočníka — exces",
                    "confidence": 0.8,
                }
            ]
        )

        with (
            patch(
                "pravni_kvalifikator.agents.qualifier.get_mcp_client",
                return_value=mock_mcp,
            ),
            patch(
                "pravni_kvalifikator.agents.qualifier.call_llm_structured",
                new_callable=AsyncMock,
                return_value=mock_llm_result,
            ),
            patch(
                "pravni_kvalifikator.agents.qualifier.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            result = await qualifier_node(state)

        vo = result["okolnosti"]["vylucujici_okolnosti"][0]
        assert vo["aplikovatelnost"] == "překročení mezí"

    @pytest.mark.asyncio
    async def test_polehcujici_pritezujici(self):
        """TC → polehčující i přitěžující okolnosti s paragraf_pismeno."""
        from pravni_kvalifikator.agents.qualifier import qualifier_node

        state: QualificationState = {
            "popis_skutku": "Pachatel recidivista ukradl v obchodě",
            "typ": "TC",
            "qualification_id": 5,
            "candidate_paragraphs": [
                {
                    "paragraph_id": 100,
                    "cislo": "205",
                    "nazev": "Krádež",
                    "plne_zneni": "Kdo si přisvojí cizí věc...",
                    "relevance_score": 0.9,
                    "matching_elements": ["přisvojení cizí věci"],
                }
            ],
        }

        mock_mcp = self._make_mcp_mock()
        mock_llm_result = self._make_theft_llm_result()
        mock_llm_result.okolnosti = _make_qualifier_okolnosti_mock(
            polehcujici=[
                {
                    "popis": "Pachatel se přiznal",
                    "paragraf_pismeno": "§ 41 písm. n) TZ",
                }
            ],
            pritezujici=[
                {
                    "popis": "Recidiva — byl již odsouzen",
                    "paragraf_pismeno": "§ 42 písm. p) TZ",
                }
            ],
        )

        with (
            patch(
                "pravni_kvalifikator.agents.qualifier.get_mcp_client",
                return_value=mock_mcp,
            ),
            patch(
                "pravni_kvalifikator.agents.qualifier.call_llm_structured",
                new_callable=AsyncMock,
                return_value=mock_llm_result,
            ),
            patch(
                "pravni_kvalifikator.agents.qualifier.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            result = await qualifier_node(state)

        assert len(result["okolnosti"]["polehcujici"]) == 1
        assert result["okolnosti"]["polehcujici"][0]["paragraf_pismeno"] == "§ 41 písm. n) TZ"
        assert len(result["okolnosti"]["pritezujici"]) == 1
        assert result["okolnosti"]["pritezujici"][0]["paragraf_pismeno"] == "§ 42 písm. p) TZ"

    @pytest.mark.asyncio
    async def test_pr_skips_polehcujici(self):
        """For PR, § 41-42 are not loaded — user message omits polehčující/přitěžující."""
        from pravni_kvalifikator.agents.qualifier import qualifier_node

        state: QualificationState = {
            "popis_skutku": "Řidič překročil rychlost o 40 km/h",
            "typ": "PR",
            "qualification_id": 6,
            "candidate_paragraphs": [],
        }

        mock_mcp = self._make_mcp_mock()
        mock_llm_result = MagicMock()
        mock_llm_result.kvalifikace = []
        mock_llm_result.skoda = MagicMock()
        mock_llm_result.skoda.model_dump.return_value = {
            "odhadovana_vyse": None,
            "kategorie": None,
            "relevantni_hranice": None,
        }
        mock_llm_result.okolnosti = _make_qualifier_okolnosti_mock()

        with (
            patch(
                "pravni_kvalifikator.agents.qualifier.get_mcp_client",
                return_value=mock_mcp,
            ),
            patch(
                "pravni_kvalifikator.agents.qualifier.call_llm_structured",
                new_callable=AsyncMock,
                return_value=mock_llm_result,
            ) as mock_llm_call,
            patch(
                "pravni_kvalifikator.agents.qualifier.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            result = await qualifier_node(state)

        # Verify user message does NOT contain § 41 / § 42 text section
        call_args = mock_llm_call.call_args
        user_msg = call_args[0][1][1]["content"]
        assert "Polehčující a přitěžující okolnosti" not in user_msg
        assert result["okolnosti"]["polehcujici"] == []
        assert result["okolnosti"]["pritezujici"] == []


class TestReviewer:
    @pytest.mark.asyncio
    async def test_reviews_qualification(self):
        from pravni_kvalifikator.agents.reviewer import reviewer_node

        state: QualificationState = {
            "popis_skutku": "Pachatel vloupáním vnikl do bytu a odcizil peněženku",
            "typ": "TC",
            "qualification_id": 1,
            "kvalifikace": [
                {
                    "paragraf": "§ 205 odst. 1 písm. b) TZ",
                    "nazev": "Krádež",
                    "confidence": 0.9,
                    "duvod_jistoty": "Vloupání + odcizení",
                    "chybejici_znaky": [],
                    "stadium": "dokonaný",
                    "forma_zavineni": "úmysl přímý",
                }
            ],
            "skoda": {"odhadovana_vyse": None, "kategorie": None},
            "okolnosti": {
                "vylucujici_okolnosti": [],
                "polehcujici": [],
                "pritezujici": [],
            },
            "candidate_paragraphs": [],
        }

        mock_llm_result = MagicMock()
        mock_llm_result.final_kvalifikace = [
            MagicMock(
                paragraf="§ 205 odst. 1 písm. b) TZ",
                nazev="Krádež",
                confidence=0.9,
                duvod_jistoty="Vloupání + odcizení",
                chybejici_znaky=[],
                stadium="dokonaný",
                forma_zavineni="úmysl přímý",
                review_adjustment="beze změny",
            ),
            MagicMock(
                paragraf="§ 178 odst. 1 TZ",
                nazev="Porušování domovní svobody",
                confidence=0.85,
                duvod_jistoty="Vniknutí do bytu",
                chybejici_znaky=[],
                stadium="dokonaný",
                forma_zavineni="úmysl přímý",
                review_adjustment="přidáno — jednočinný souběh",
            ),
        ]
        for kv in mock_llm_result.final_kvalifikace:
            kv.model_dump.return_value = {
                "paragraf": kv.paragraf,
                "nazev": kv.nazev,
                "confidence": kv.confidence,
                "duvod_jistoty": kv.duvod_jistoty,
                "chybejici_znaky": kv.chybejici_znaky,
                "stadium": kv.stadium,
                "forma_zavineni": kv.forma_zavineni,
                "review_adjustment": kv.review_adjustment,
                "vylucujici_okolnost_poznamka": None,
            }
        mock_llm_result.review_notes = [
            "Doplněn § 178 — jednočinný souběh s § 205 (vloupání do bytu)"
        ]

        with (
            patch(
                "pravni_kvalifikator.agents.reviewer.call_llm_structured",
                new_callable=AsyncMock,
                return_value=mock_llm_result,
            ),
            patch(
                "pravni_kvalifikator.agents.reviewer.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            result = await reviewer_node(state)

        assert "final_kvalifikace" in result
        assert "review_notes" in result
        # Reviewer should have added souběh — 2 kvalifikace
        assert len(result["final_kvalifikace"]) == 2
        assert len(result["review_notes"]) > 0

    @pytest.mark.asyncio
    async def test_reviews_defense_lowers_confidence(self):
        """Reviewer should lower confidence when vylučující okolnost has aplikovatelnost=ano."""
        from pravni_kvalifikator.agents.reviewer import reviewer_node

        state: QualificationState = {
            "popis_skutku": "Muž na mě zaútočil nožem, bránil jsem se a zlomil mu ruku",
            "typ": "TC",
            "qualification_id": 2,
            "kvalifikace": [
                {
                    "paragraf": "§ 146 odst. 1 TZ",
                    "nazev": "Ublížení na zdraví",
                    "confidence": 0.8,
                    "duvod_jistoty": "Zlomenina ruky",
                    "chybejici_znaky": [],
                    "stadium": "dokonaný",
                    "forma_zavineni": "úmysl přímý",
                }
            ],
            "skoda": {"odhadovana_vyse": None, "kategorie": None},
            "okolnosti": {
                "vylucujici_okolnosti": [
                    {
                        "paragraf": "§ 29",
                        "nazev": "Nutná obrana",
                        "aplikovatelnost": "ano",
                        "vztahuje_se_na": ["§ 146"],
                        "duvod": "Obránce reagoval na útok nožem",
                        "confidence": 0.9,
                    }
                ],
                "polehcujici": [],
                "pritezujici": [],
            },
            "candidate_paragraphs": [],
        }

        mock_llm_result = MagicMock()
        mock_llm_result.final_kvalifikace = [
            MagicMock(
                paragraf="§ 146 odst. 1 TZ",
                nazev="Ublížení na zdraví",
                confidence=0.3,
                duvod_jistoty="Zlomenina ruky",
                chybejici_znaky=[],
                stadium="dokonaný",
                forma_zavineni="úmysl přímý",
                review_adjustment="confidence snížen kvůli nutné obraně",
                vylucujici_okolnost_poznamka=(
                    "Uplatňuje se nutná obrana (§ 29 TZ). Skutek pravděpodobně není trestný."
                ),
            )
        ]
        mock_llm_result.final_kvalifikace[0].model_dump.return_value = {
            "paragraf": "§ 146 odst. 1 TZ",
            "nazev": "Ublížení na zdraví",
            "confidence": 0.3,
            "duvod_jistoty": "Zlomenina ruky",
            "chybejici_znaky": [],
            "stadium": "dokonaný",
            "forma_zavineni": "úmysl přímý",
            "review_adjustment": "confidence snížen kvůli nutné obraně",
            "vylucujici_okolnost_poznamka": (
                "Uplatňuje se nutná obrana (§ 29 TZ). Skutek pravděpodobně není trestný."
            ),
        }
        mock_llm_result.review_notes = [
            "Kvalifikace je podmíněná — uplatňuje se okolnost vylučující "
            "protiprávnost (§ 29). Skutek pravděpodobně není trestný."
        ]

        with (
            patch(
                "pravni_kvalifikator.agents.reviewer.call_llm_structured",
                new_callable=AsyncMock,
                return_value=mock_llm_result,
            ),
            patch(
                "pravni_kvalifikator.agents.reviewer.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            result = await reviewer_node(state)

        kv = result["final_kvalifikace"][0]
        assert kv["confidence"] <= 0.5
        assert kv["vylucujici_okolnost_poznamka"] is not None
        assert "§ 29" in kv["vylucujici_okolnost_poznamka"]
        assert len(result["review_notes"]) > 0

    @pytest.mark.asyncio
    async def test_reviews_exces_keeps_confidence(self):
        """Reviewer should keep confidence for překročení mezí, but add note."""
        from pravni_kvalifikator.agents.reviewer import reviewer_node

        state: QualificationState = {
            "popis_skutku": "Muž na mě zaútočil, já ho pronásledoval a zbil",
            "typ": "TC",
            "qualification_id": 3,
            "kvalifikace": [
                {
                    "paragraf": "§ 146 odst. 1 TZ",
                    "nazev": "Ublížení na zdraví",
                    "confidence": 0.85,
                    "duvod_jistoty": "Zbití poškozeného",
                    "chybejici_znaky": [],
                    "stadium": "dokonaný",
                    "forma_zavineni": "úmysl přímý",
                }
            ],
            "skoda": {"odhadovana_vyse": None, "kategorie": None},
            "okolnosti": {
                "vylucujici_okolnosti": [
                    {
                        "paragraf": "§ 29",
                        "nazev": "Nutná obrana",
                        "aplikovatelnost": "překročení mezí",
                        "vztahuje_se_na": ["§ 146"],
                        "duvod": "Obránce pronásledoval útočníka — exces",
                        "confidence": 0.8,
                    }
                ],
                "polehcujici": [],
                "pritezujici": [],
            },
            "candidate_paragraphs": [],
        }

        mock_llm_result = MagicMock()
        mock_llm_result.final_kvalifikace = [
            MagicMock(
                paragraf="§ 146 odst. 1 TZ",
                nazev="Ublížení na zdraví",
                confidence=0.85,
                duvod_jistoty="Zbití poškozeného",
                chybejici_znaky=[],
                stadium="dokonaný",
                forma_zavineni="úmysl přímý",
                review_adjustment="beze změny — exces nutné obrany",
                vylucujici_okolnost_poznamka=(
                    "Překročení mezí nutné obrany (§ 29 TZ) — "
                    "skutek je stále trestný, ale exces může být polehčující okolností."
                ),
            )
        ]
        mock_llm_result.final_kvalifikace[0].model_dump.return_value = {
            "paragraf": "§ 146 odst. 1 TZ",
            "nazev": "Ublížení na zdraví",
            "confidence": 0.85,
            "duvod_jistoty": "Zbití poškozeného",
            "chybejici_znaky": [],
            "stadium": "dokonaný",
            "forma_zavineni": "úmysl přímý",
            "review_adjustment": "beze změny — exces nutné obrany",
            "vylucujici_okolnost_poznamka": (
                "Překročení mezí nutné obrany (§ 29 TZ) — "
                "skutek je stále trestný, ale exces může být polehčující okolností."
            ),
        }
        mock_llm_result.review_notes = [
            "Překročení mezí nutné obrany — skutek zůstává trestný, "
            "ale exces může být polehčující okolností dle § 41 písm. g) TZ"
        ]

        with (
            patch(
                "pravni_kvalifikator.agents.reviewer.call_llm_structured",
                new_callable=AsyncMock,
                return_value=mock_llm_result,
            ),
            patch(
                "pravni_kvalifikator.agents.reviewer.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            result = await reviewer_node(state)

        kv = result["final_kvalifikace"][0]
        # Exces — confidence stays high
        assert kv["confidence"] >= 0.7
        assert kv["vylucujici_okolnost_poznamka"] is not None
        assert "překročení" in kv["vylucujici_okolnost_poznamka"].lower()
        assert len(result["review_notes"]) > 0


class TestSpecialLawChecker:
    @pytest.mark.asyncio
    async def test_identifies_weapon_law(self):
        """When popis mentions a weapon, agent should check zákon o zbraních."""
        from pravni_kvalifikator.agents.special_law_checker import special_law_checker_node

        state: QualificationState = {
            "popis_skutku": (
                "Muž na mě zaútočil nožem, vytáhl jsem nelegálně drženou pistoli a bránil se"
            ),
            "typ": "TC",
            "qualification_id": 1,
            "kvalifikace": [
                {
                    "paragraf": "§ 146 odst. 1 TZ",
                    "nazev": "Ublížení na zdraví",
                    "confidence": 0.8,
                    "duvod_jistoty": "Zlomenina ruky",
                }
            ],
            "okolnosti": {
                "vylucujici_okolnosti": [
                    {
                        "paragraf": "§ 29",
                        "nazev": "Nutná obrana",
                        "aplikovatelnost": "ano",
                        "vztahuje_se_na": ["§ 146"],
                        "duvod": "Obrana proti útoku nožem",
                        "confidence": 0.9,
                    }
                ],
                "polehcujici": [],
                "pritezujici": [],
            },
        }

        mock_mcp = AsyncMock()
        mock_mcp.search_laws.return_value = json.dumps(
            [
                {
                    "law_id": 6,
                    "nazev": "Zákon o zbraních a střelivu",
                    "typ": "specialni",
                    "distance": 0.1,
                },
            ]
        )
        mock_mcp.search_chapters.return_value = json.dumps(
            [
                {"chapter_id": 60, "hlava_nazev": "Přestupky", "distance": 0.2},
            ]
        )
        mock_mcp.search_paragraphs.return_value = json.dumps(
            [
                {
                    "paragraph_id": 600,
                    "cislo": "58",
                    "nazev": "Neoprávněné držení zbraně",
                    "distance": 0.1,
                },
            ]
        )
        mock_mcp.get_paragraph_text.return_value = "Kdo bez povolení drží zbraň..."

        mock_llm_result = MagicMock()
        mock_llm_result.kvalifikace = [
            MagicMock(
                paragraf="§ 58 zákona 90/2024 Sb.",
                nazev="Neoprávněné držení zbraně",
                zakon="Zákon o zbraních a střelivu",
                confidence=0.8,
                duvod="Pachatel držel pistoli bez povolení",
                chybejici_znaky=["potvrzení absence zbrojního průkazu"],
            )
        ]
        mock_llm_result.kvalifikace[0].model_dump.return_value = {
            "paragraf": "§ 58 zákona 90/2024 Sb.",
            "nazev": "Neoprávněné držení zbraně",
            "zakon": "Zákon o zbraních a střelivu",
            "confidence": 0.8,
            "duvod": "Pachatel držel pistoli bez povolení",
            "chybejici_znaky": ["potvrzení absence zbrojního průkazu"],
        }
        mock_llm_result.notes = ["Nutná obrana nevylučuje přestupek neoprávněného držení zbraně"]

        with (
            patch(
                "pravni_kvalifikator.agents.special_law_checker.get_mcp_client",
                return_value=mock_mcp,
            ),
            patch(
                "pravni_kvalifikator.agents.special_law_checker.call_llm_structured",
                new_callable=AsyncMock,
                return_value=mock_llm_result,
            ),
            patch(
                "pravni_kvalifikator.agents.special_law_checker.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            result = await special_law_checker_node(state)

        assert "special_law_kvalifikace" in result
        assert len(result["special_law_kvalifikace"]) > 0
        assert result["special_law_kvalifikace"][0]["zakon"] == "Zákon o zbraních a střelivu"
        assert "special_law_notes" in result

    @pytest.mark.asyncio
    async def test_no_special_laws_when_irrelevant(self):
        """For a simple theft, no special law should be flagged."""
        from pravni_kvalifikator.agents.special_law_checker import special_law_checker_node

        state: QualificationState = {
            "popis_skutku": "Pachatel odcizil z obchodu zboží v hodnotě 5 000 Kč",
            "typ": "TC",
            "qualification_id": 2,
            "kvalifikace": [
                {
                    "paragraf": "§ 205 odst. 1 písm. a) TZ",
                    "nazev": "Krádež",
                    "confidence": 0.85,
                }
            ],
            "okolnosti": {
                "vylucujici_okolnosti": [],
                "polehcujici": [],
                "pritezujici": [],
            },
        }

        mock_mcp = AsyncMock()
        mock_mcp.search_laws.return_value = "[]"

        mock_llm_result = MagicMock()
        mock_llm_result.kvalifikace = []
        mock_llm_result.notes = []

        with (
            patch(
                "pravni_kvalifikator.agents.special_law_checker.get_mcp_client",
                return_value=mock_mcp,
            ),
            patch(
                "pravni_kvalifikator.agents.special_law_checker.call_llm_structured",
                new_callable=AsyncMock,
                return_value=mock_llm_result,
            ),
            patch(
                "pravni_kvalifikator.agents.special_law_checker.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            result = await special_law_checker_node(state)

        assert result["special_law_kvalifikace"] == []
        assert result["special_law_notes"] == []


class TestOrchestrator:
    @pytest.mark.asyncio
    async def test_tc_pipeline_skips_law_identifier(self):
        """For TC, Agent 0 (law_identifier) should be skipped."""
        from pravni_kvalifikator.agents.orchestrator import create_workflow

        law_id_called = False
        head_cls_called = False

        async def mock_law_id(state):
            nonlocal law_id_called
            law_id_called = True
            return {"identified_laws": []}

        async def mock_head_cls(state):
            nonlocal head_cls_called
            head_cls_called = True
            return {"candidate_chapters": []}

        async def mock_para_sel(state):
            return {"candidate_paragraphs": []}

        async def mock_qualifier(state):
            return {"kvalifikace": [], "skoda": {}, "okolnosti": {}}

        async def mock_reviewer(state):
            return {"final_kvalifikace": [], "review_notes": []}

        with (
            patch(
                "pravni_kvalifikator.agents.orchestrator.law_identifier_node",
                side_effect=mock_law_id,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.head_classifier_node",
                side_effect=mock_head_cls,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.paragraph_selector_node",
                side_effect=mock_para_sel,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.qualifier_node",
                side_effect=mock_qualifier,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.reviewer_node",
                side_effect=mock_reviewer,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.special_law_checker_node",
                new_callable=AsyncMock,
                return_value={"special_law_kvalifikace": [], "special_law_notes": []},
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            workflow = create_workflow()
            await workflow.ainvoke(
                {
                    "popis_skutku": "Pachatel ukradl kolo",
                    "typ": "TC",
                    "qualification_id": 1,
                }
            )

        assert not law_id_called, "law_identifier should NOT be called for TC"
        assert head_cls_called, "head_classifier should be called for TC"

    @pytest.mark.asyncio
    async def test_pr_pipeline_includes_law_identifier(self):
        """For PR, Agent 0 (law_identifier) should be called."""
        from pravni_kvalifikator.agents.orchestrator import create_workflow

        law_id_called = False

        async def mock_law_id(state):
            nonlocal law_id_called
            law_id_called = True
            return {"identified_laws": [{"law_id": 5}]}

        async def mock_head_cls(state):
            return {"candidate_chapters": []}

        async def mock_para_sel(state):
            return {"candidate_paragraphs": []}

        async def mock_qualifier(state):
            return {"kvalifikace": [], "skoda": {}, "okolnosti": {}}

        async def mock_reviewer(state):
            return {"final_kvalifikace": [], "review_notes": []}

        with (
            patch(
                "pravni_kvalifikator.agents.orchestrator.law_identifier_node",
                side_effect=mock_law_id,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.head_classifier_node",
                side_effect=mock_head_cls,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.paragraph_selector_node",
                side_effect=mock_para_sel,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.qualifier_node",
                side_effect=mock_qualifier,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.reviewer_node",
                side_effect=mock_reviewer,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.special_law_checker_node",
                new_callable=AsyncMock,
                return_value={"special_law_kvalifikace": [], "special_law_notes": []},
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            workflow = create_workflow()
            await workflow.ainvoke(
                {
                    "popis_skutku": "Řidič překročil rychlost",
                    "typ": "PR",
                    "qualification_id": 1,
                }
            )

        assert law_id_called, "law_identifier SHOULD be called for PR"

    @pytest.mark.asyncio
    async def test_error_stops_pipeline(self):
        """If an agent errors, pipeline should stop and set error."""
        from pravni_kvalifikator.agents.orchestrator import create_workflow

        reviewer_called = False

        async def mock_head_cls(state):
            raise RuntimeError("Test error")

        async def mock_reviewer(state):
            nonlocal reviewer_called
            reviewer_called = True
            return {"final_kvalifikace": [], "review_notes": []}

        with (
            patch(
                "pravni_kvalifikator.agents.orchestrator.head_classifier_node",
                side_effect=mock_head_cls,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.paragraph_selector_node",
                new_callable=AsyncMock,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.qualifier_node",
                new_callable=AsyncMock,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.reviewer_node",
                side_effect=mock_reviewer,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.special_law_checker_node",
                new_callable=AsyncMock,
                return_value={"special_law_kvalifikace": [], "special_law_notes": []},
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            workflow = create_workflow()
            result = await workflow.ainvoke(
                {
                    "popis_skutku": "Test",
                    "typ": "TC",
                    "qualification_id": 1,
                }
            )

        assert "error" in result
        assert not reviewer_called, "reviewer should NOT be called after error"

    @pytest.mark.asyncio
    async def test_tc_pipeline_includes_special_law_checker(self):
        """For TC, special_law_checker should run after qualifier and before reviewer."""
        from pravni_kvalifikator.agents.orchestrator import create_workflow

        special_law_called = False

        async def mock_head_cls(state):
            return {"candidate_chapters": []}

        async def mock_para_sel(state):
            return {"candidate_paragraphs": []}

        async def mock_qualifier(state):
            return {"kvalifikace": [], "skoda": {}, "okolnosti": {}}

        async def mock_reviewer(state):
            return {"final_kvalifikace": [], "review_notes": []}

        async def mock_special_law(state):
            nonlocal special_law_called
            special_law_called = True
            return {"special_law_kvalifikace": [], "special_law_notes": []}

        with (
            patch(
                "pravni_kvalifikator.agents.orchestrator.head_classifier_node",
                side_effect=mock_head_cls,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.paragraph_selector_node",
                side_effect=mock_para_sel,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.qualifier_node",
                side_effect=mock_qualifier,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.reviewer_node",
                side_effect=mock_reviewer,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.special_law_checker_node",
                side_effect=mock_special_law,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            workflow = create_workflow()
            await workflow.ainvoke(
                {
                    "popis_skutku": "Střelil na útočníka nelegální zbraní",
                    "typ": "TC",
                    "qualification_id": 1,
                }
            )

        assert special_law_called, "special_law_checker should be called for TC"

    @pytest.mark.asyncio
    async def test_pr_pipeline_includes_special_law_checker(self):
        """For PR, special_law_checker should also run after qualifier and before reviewer."""
        from pravni_kvalifikator.agents.orchestrator import create_workflow

        special_law_called = False

        async def mock_law_id(state):
            return {"identified_laws": [{"law_id": 5}]}

        async def mock_head_cls(state):
            return {"candidate_chapters": []}

        async def mock_para_sel(state):
            return {"candidate_paragraphs": []}

        async def mock_qualifier(state):
            return {"kvalifikace": [], "skoda": {}, "okolnosti": {}}

        async def mock_reviewer(state):
            return {"final_kvalifikace": [], "review_notes": []}

        async def mock_special_law(state):
            nonlocal special_law_called
            special_law_called = True
            return {"special_law_kvalifikace": [], "special_law_notes": []}

        with (
            patch(
                "pravni_kvalifikator.agents.orchestrator.law_identifier_node",
                side_effect=mock_law_id,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.head_classifier_node",
                side_effect=mock_head_cls,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.paragraph_selector_node",
                side_effect=mock_para_sel,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.qualifier_node",
                side_effect=mock_qualifier,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.reviewer_node",
                side_effect=mock_reviewer,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.special_law_checker_node",
                side_effect=mock_special_law,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.log_agent_activity",
                new_callable=AsyncMock,
            ),
        ):
            workflow = create_workflow()
            await workflow.ainvoke(
                {
                    "popis_skutku": "Řidič pod vlivem alkoholu srazil chodce",
                    "typ": "PR",
                    "qualification_id": 1,
                }
            )

        assert special_law_called, "special_law_checker should be called for PR"
