"""LangGraph StateGraph orchestrator with conditional routing."""

import logging
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from pravni_kvalifikator.agents.activity import log_agent_activity
from pravni_kvalifikator.agents.head_classifier import head_classifier_node
from pravni_kvalifikator.agents.law_identifier import law_identifier_node
from pravni_kvalifikator.agents.paragraph_selector import paragraph_selector_node
from pravni_kvalifikator.agents.qualifier import qualifier_node
from pravni_kvalifikator.agents.reviewer import reviewer_node
from pravni_kvalifikator.agents.state import QualificationState

logger = logging.getLogger(__name__)


def route_by_type(state: QualificationState) -> Literal["law_identifier", "head_classifier"]:
    """Route: PR -> law_identifier, TC -> head_classifier."""
    if state.get("typ") == "PR":
        return "law_identifier"
    return "head_classifier"


async def _safe_node(state: QualificationState, agent_fn, agent_name: str) -> dict[str, Any]:
    """Wrap agent node with error handling."""
    try:
        return await agent_fn(state)
    except Exception as e:
        logger.exception("Agent %s failed", agent_name)
        await log_agent_activity(state.get("qualification_id", 0), agent_name, "error", str(e))
        # NOTE (P3-3): Return ONLY changed keys. LangGraph merges automatically.
        return {"error": f"Agent {agent_name} selhal: {e!s}"}


def _check_error(state: QualificationState) -> Literal["continue", "end"]:
    """If error occurred, skip to END."""
    if state.get("error"):
        return "end"
    return "continue"


def create_workflow() -> Any:
    """Build and compile the qualification workflow."""
    workflow = StateGraph(QualificationState)

    # Add nodes (wrapped with error handling)
    async def safe_law_id(state):
        return await _safe_node(state, law_identifier_node, "law_identifier")

    async def safe_head_cls(state):
        return await _safe_node(state, head_classifier_node, "head_classifier")

    async def safe_para_sel(state):
        return await _safe_node(state, paragraph_selector_node, "paragraph_selector")

    async def safe_qualifier(state):
        return await _safe_node(state, qualifier_node, "qualifier")

    async def safe_reviewer(state):
        return await _safe_node(state, reviewer_node, "reviewer")

    workflow.add_node("law_identifier", safe_law_id)
    workflow.add_node("head_classifier", safe_head_cls)
    workflow.add_node("paragraph_selector", safe_para_sel)
    workflow.add_node("qualifier", safe_qualifier)
    workflow.add_node("reviewer", safe_reviewer)

    # Routing
    workflow.add_conditional_edges(
        START,
        route_by_type,
        {"law_identifier": "law_identifier", "head_classifier": "head_classifier"},
    )
    workflow.add_edge("law_identifier", "head_classifier")
    workflow.add_conditional_edges(
        "head_classifier",
        _check_error,
        {"continue": "paragraph_selector", "end": END},
    )
    workflow.add_conditional_edges(
        "paragraph_selector",
        _check_error,
        {"continue": "qualifier", "end": END},
    )
    workflow.add_conditional_edges(
        "qualifier",
        _check_error,
        {"continue": "reviewer", "end": END},
    )
    workflow.add_edge("reviewer", END)

    return workflow.compile()


async def run_qualification(
    popis_skutku: str, typ: str, qualification_id: int
) -> QualificationState:
    """Main entry point: run the full qualification pipeline."""
    initial_state: QualificationState = {
        "popis_skutku": popis_skutku,
        "typ": typ,
        "qualification_id": qualification_id,
    }

    workflow = create_workflow()

    try:
        final_state = await workflow.ainvoke(initial_state)
        return final_state
    except Exception as e:
        logger.exception("Qualification pipeline failed")
        initial_state["error"] = str(e)
        return initial_state
