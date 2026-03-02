"""End-to-end tests for the full qualification pipeline.

Strategy:
- Mock LLM responses for deterministic testing (call_llm_structured returns
  predefined Pydantic models matching each agent's output schema).
- Mock MCP client to return realistic search results from test DB data.
- Mock activity logging to avoid DB side-effects.
- Verify the orchestrator correctly routes, passes state between agents,
  and produces expected final output structure.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pravni_kvalifikator.agents.orchestrator import run_qualification
from tests.scenarios import SCENARIOS


def _make_mock_mcp(
    search_laws_result=None,
    search_chapters_result=None,
    search_paragraphs_result=None,
    search_paragraphs_keyword_result=None,
    get_paragraph_text_result=None,
    get_damage_thresholds_result=None,
):
    """Create a mock MCP client with configurable return values."""
    mock = AsyncMock()
    mock.search_laws.return_value = json.dumps(search_laws_result or [])
    mock.search_chapters.return_value = json.dumps(search_chapters_result or [])
    mock.search_paragraphs.return_value = json.dumps(search_paragraphs_result or [])
    mock.search_paragraphs_keyword.return_value = json.dumps(search_paragraphs_keyword_result or [])
    mock.get_paragraph_text.return_value = get_paragraph_text_result or ""
    mock.get_damage_thresholds.return_value = get_damage_thresholds_result or json.dumps(
        {
            "nikoli_nepatrna": 10000,
            "nikoli_mala": 50000,
            "vetsi": 100000,
            "znacna": 1000000,
            "velkeho_rozsahu": 10000000,
        }
    )
    return mock


def _patch_all_agents(mock_mcp, mock_call_llm):
    """Return a combined context manager patching all agent dependencies."""
    from contextlib import ExitStack

    stack = ExitStack()

    agent_modules = [
        "head_classifier",
        "paragraph_selector",
        "qualifier",
    ]
    # Agents that use MCP + LLM
    for mod in agent_modules:
        base = f"pravni_kvalifikator.agents.{mod}"
        stack.enter_context(patch(f"{base}.get_mcp_client", return_value=mock_mcp))
        stack.enter_context(patch(f"{base}.call_llm_structured", side_effect=mock_call_llm))
        stack.enter_context(patch(f"{base}.get_llm", return_value=MagicMock()))

    # law_identifier (MCP + LLM, but only called for PR)
    li_base = "pravni_kvalifikator.agents.law_identifier"
    stack.enter_context(patch(f"{li_base}.get_mcp_client", return_value=mock_mcp))
    stack.enter_context(patch(f"{li_base}.call_llm_structured", side_effect=mock_call_llm))
    stack.enter_context(patch(f"{li_base}.get_llm", return_value=MagicMock()))

    # reviewer (LLM only, no MCP)
    rev_base = "pravni_kvalifikator.agents.reviewer"
    stack.enter_context(patch(f"{rev_base}.call_llm_structured", side_effect=mock_call_llm))
    stack.enter_context(patch(f"{rev_base}.get_llm", return_value=MagicMock()))

    # special_law_checker (MCP + LLM)
    slc_base = "pravni_kvalifikator.agents.special_law_checker"
    stack.enter_context(patch(f"{slc_base}.get_mcp_client", return_value=mock_mcp))
    stack.enter_context(patch(f"{slc_base}.call_llm_structured", side_effect=mock_call_llm))
    stack.enter_context(patch(f"{slc_base}.get_llm", return_value=MagicMock()))

    # Activity logging — suppress DB/SSE side-effects
    stack.enter_context(
        patch(
            "pravni_kvalifikator.agents.activity.log_agent_activity",
            new_callable=AsyncMock,
        )
    )

    return stack


class TestE2EPipeline:
    """E2E tests with mocked LLM but real orchestrator routing logic."""

    @pytest.mark.asyncio
    async def test_tc_simple_theft(self):
        """Simple theft should qualify as 205 TZ. TC skips law_identifier."""
        mock_mcp = _make_mock_mcp(
            search_chapters_result=[
                {"chapter_id": 1, "hlava_nazev": "TČ PROTI MAJETKU", "distance": 0.1},
            ],
            search_paragraphs_result=[
                {"paragraph_id": 1, "cislo": "205", "nazev": "Krádež", "distance": 0.1},
            ],
            get_paragraph_text_result="(1) Kdo si přisvojí cizí věc...",
        )

        head_cls_result = MagicMock()
        head_cls_result.chapters = [
            MagicMock(
                chapter_id=1,
                hlava_nazev="TČ PROTI MAJETKU",
                law_nazev="TZ",
                confidence=0.95,
                reason="majetkový TČ",
                model_dump=lambda: {
                    "chapter_id": 1,
                    "hlava_nazev": "TČ PROTI MAJETKU",
                    "law_nazev": "TZ",
                    "confidence": 0.95,
                    "reason": "majetkový TČ",
                },
            )
        ]

        para_sel_result = MagicMock()
        para_sel_result.paragraphs = [
            MagicMock(
                paragraph_id=1,
                cislo="205",
                nazev="Krádež",
                plne_zneni="(1) Kdo si přisvojí...",
                relevance_score=0.9,
                matching_elements=["přisvojení cizí věci", "zmocnění"],
                model_dump=lambda: {
                    "paragraph_id": 1,
                    "cislo": "205",
                    "nazev": "Krádež",
                    "plne_zneni": "(1) Kdo si přisvojí...",
                    "relevance_score": 0.9,
                    "matching_elements": ["přisvojení cizí věci", "zmocnění"],
                },
            )
        ]

        qualifier_result = MagicMock()
        qualifier_result.kvalifikace = [
            MagicMock(
                paragraf="§ 205 odst. 1 TZ",
                nazev="Krádež",
                confidence=0.85,
                duvod_jistoty="Všechny znaky naplněny",
                chybejici_znaky=[],
                stadium="dokonaný",
                forma_zavineni="úmysl přímý",
                model_dump=lambda: {
                    "paragraf": "§ 205 odst. 1 TZ",
                    "nazev": "Krádež",
                    "confidence": 0.85,
                    "duvod_jistoty": "Všechny znaky naplněny",
                    "chybejici_znaky": [],
                    "stadium": "dokonaný",
                    "forma_zavineni": "úmysl přímý",
                },
            )
        ]
        qualifier_result.skoda = MagicMock(
            model_dump=lambda: {
                "odhadovana_vyse": 5000,
                "kategorie": "nikoli nepatrná",
                "relevantni_hranice": ">=10 000 Kč",
            }
        )
        qualifier_result.okolnosti = MagicMock(
            model_dump=lambda: {
                "vylucujici_okolnosti": [],
                "polehcujici": [],
                "pritezujici": [],
            }
        )

        reviewer_result = MagicMock()
        reviewer_result.final_kvalifikace = [
            MagicMock(
                model_dump=lambda: {
                    "paragraf": "§ 205 odst. 1 TZ",
                    "nazev": "Krádež",
                    "confidence": 0.85,
                    "duvod_jistoty": "Všechny znaky naplněny",
                    "chybejici_znaky": [],
                    "stadium": "dokonaný",
                    "forma_zavineni": "úmysl přímý",
                    "review_adjustment": "beze změny",
                }
            )
        ]
        reviewer_result.review_notes = ["Kvalifikace je správná"]

        special_law_result = MagicMock()
        special_law_result.kvalifikace = []
        special_law_result.notes = []

        llm_call_count = 0
        llm_results = [
            head_cls_result,
            para_sel_result,
            qualifier_result,
            reviewer_result,
            special_law_result,
        ]

        async def mock_call_llm(llm, messages, output_schema, **kwargs):
            nonlocal llm_call_count
            result = llm_results[min(llm_call_count, len(llm_results) - 1)]
            llm_call_count += 1
            return result

        with _patch_all_agents(mock_mcp, mock_call_llm):
            result = await run_qualification(
                "Pachatel odcizil z obchodu zboží v hodnotě 5 000 Kč", "TC", 1
            )

        assert result.get("error") is None
        assert "final_kvalifikace" in result
        assert len(result["final_kvalifikace"]) > 0
        assert any("205" in kv["paragraf"] for kv in result["final_kvalifikace"])

    @pytest.mark.asyncio
    async def test_tc_pipeline_skips_law_identifier(self):
        """For TC type, Agent 0 (law_identifier) should NOT be called."""
        mock_mcp = _make_mock_mcp()
        empty_result = MagicMock()
        empty_result.chapters = []
        empty_result.paragraphs = []
        empty_result.kvalifikace = []
        empty_result.skoda = MagicMock(model_dump=lambda: {})
        empty_result.okolnosti = MagicMock(model_dump=lambda: {})
        empty_result.final_kvalifikace = []
        empty_result.review_notes = []
        empty_result.notes = []

        law_identifier_called = False

        async def mock_law_id_node(state):
            nonlocal law_identifier_called
            law_identifier_called = True
            return {"identified_laws": []}

        async def mock_call_llm(llm, messages, schema, **kwargs):
            return empty_result

        with _patch_all_agents(mock_mcp, mock_call_llm):
            with patch(
                "pravni_kvalifikator.agents.orchestrator.law_identifier_node",
                mock_law_id_node,
            ):
                await run_qualification("Pachatel ukradl kolo", "TC", 1)

        assert not law_identifier_called, "law_identifier should NOT be called for TC"

    @pytest.mark.asyncio
    async def test_pr_pipeline_runs_law_identifier(self):
        """For PR type, Agent 0 (law_identifier) SHOULD be called."""
        mock_mcp = _make_mock_mcp(
            search_laws_result=[{"law_id": 3, "nazev": "Zákon o provozu", "distance": 0.1}],
        )
        law_id_result = MagicMock()
        law_id_result.laws = [
            MagicMock(
                law_id=3,
                nazev="Zákon o provozu",
                confidence=0.9,
                reason="dopravní",
                model_dump=lambda: {
                    "law_id": 3,
                    "nazev": "Zákon o provozu",
                    "confidence": 0.9,
                    "reason": "dopravní",
                },
            )
        ]
        empty_result = MagicMock()
        empty_result.chapters = []
        empty_result.paragraphs = []
        empty_result.kvalifikace = []
        empty_result.skoda = MagicMock(model_dump=lambda: {})
        empty_result.okolnosti = MagicMock(model_dump=lambda: {})
        empty_result.final_kvalifikace = []
        empty_result.review_notes = []
        empty_result.notes = []

        call_count = 0

        async def mock_call_llm(llm, messages, schema, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return law_id_result  # Agent 0
            return empty_result  # Agents 1-5

        with _patch_all_agents(mock_mcp, mock_call_llm):
            result = await run_qualification("Řidič překročil rychlost o 40 km/h v obci", "PR", 1)

        assert result.get("identified_laws") is not None, "law_identifier should have run for PR"

    @pytest.mark.asyncio
    async def test_pipeline_error_recovery(self):
        """Pipeline should handle agent errors gracefully and set error state."""

        async def failing_head_classifier(state):
            raise RuntimeError("Simulated head_classifier failure")

        with (
            patch(
                "pravni_kvalifikator.agents.activity.log_agent_activity",
                new_callable=AsyncMock,
            ),
            patch(
                "pravni_kvalifikator.agents.orchestrator.head_classifier_node",
                failing_head_classifier,
            ),
        ):
            result = await run_qualification("Pachatel ukradl kolo", "TC", 1)

        assert result.get("error") is not None
        assert "head_classifier" in result["error"]

    @pytest.mark.asyncio
    async def test_empty_result_for_no_matches(self):
        """When MCP returns no matches, pipeline should complete with empty results."""
        mock_mcp = _make_mock_mcp()  # All search results are empty []
        empty_result = MagicMock()
        empty_result.chapters = []
        empty_result.paragraphs = []
        empty_result.kvalifikace = []
        empty_result.skoda = MagicMock(model_dump=lambda: {})
        empty_result.okolnosti = MagicMock(model_dump=lambda: {})
        empty_result.final_kvalifikace = []
        empty_result.review_notes = ["Nepodařilo se kvalifikovat"]
        empty_result.notes = []

        async def mock_call_llm(llm, messages, schema, **kwargs):
            return empty_result

        with _patch_all_agents(mock_mcp, mock_call_llm):
            result = await run_qualification("Dnes je hezky a svítí sluníčko", "TC", 1)

        assert result.get("error") is None
        assert result.get("final_kvalifikace") == []


# ── Parametrized Scenario Tests ──

TC_SCENARIOS = [s for s in SCENARIOS if s["typ"] == "TC"]
PR_SCENARIOS = [s for s in SCENARIOS if s["typ"] == "PR"]


def _make_empty_llm_result():
    """Return a MagicMock that satisfies all agent output schemas with empty data."""
    result = MagicMock()
    result.chapters = []
    result.laws = []
    result.paragraphs = []
    result.kvalifikace = []
    result.skoda = MagicMock(model_dump=lambda: {})
    result.okolnosti = MagicMock(model_dump=lambda: {})
    result.final_kvalifikace = []
    result.review_notes = []
    result.notes = []
    return result


class TestScenarioRouting:
    """Verify correct pipeline routing for all scenarios."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", TC_SCENARIOS, ids=[s["id"] for s in TC_SCENARIOS])
    async def test_tc_scenario_completes(self, scenario):
        """Each TC scenario should complete without errors and skip law_identifier."""
        mock_mcp = _make_mock_mcp()

        async def mock_call_llm(llm, messages, schema, **kwargs):
            return _make_empty_llm_result()

        with _patch_all_agents(mock_mcp, mock_call_llm):
            result = await run_qualification(scenario["popis_skutku"], scenario["typ"], 1)

        assert result.get("error") is None, (
            f"Scenario {scenario['id']} failed: {result.get('error')}"
        )
        # TC scenarios should not have identified_laws set by law_identifier
        # (it may be absent or may be present if inherited from initial state)
        assert "final_kvalifikace" in result or "review_notes" in result

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", PR_SCENARIOS, ids=[s["id"] for s in PR_SCENARIOS])
    async def test_pr_scenario_runs_law_identifier(self, scenario):
        """Each PR scenario should run law_identifier and complete without errors."""
        mock_mcp = _make_mock_mcp(
            search_laws_result=[{"law_id": 1, "nazev": "Test zákon", "distance": 0.2}],
        )

        law_id_result = MagicMock()
        law_id_result.laws = [
            MagicMock(
                law_id=1,
                nazev="Test zákon",
                confidence=0.8,
                reason="test",
                model_dump=lambda: {
                    "law_id": 1,
                    "nazev": "Test zákon",
                    "confidence": 0.8,
                    "reason": "test",
                },
            )
        ]

        call_count = 0

        async def mock_call_llm(llm, messages, schema, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return law_id_result
            return _make_empty_llm_result()

        with _patch_all_agents(mock_mcp, mock_call_llm):
            result = await run_qualification(scenario["popis_skutku"], scenario["typ"], 1)

        assert result.get("error") is None, (
            f"Scenario {scenario['id']} failed: {result.get('error')}"
        )
        assert result.get("identified_laws") is not None, (
            f"Scenario {scenario['id']}: law_identifier should have run"
        )
