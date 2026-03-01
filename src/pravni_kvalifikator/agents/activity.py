"""Agent activity logging — broadcasts via SSE queues + optional DB callback.

IMPORTANT: This file is named activity.py, NOT logging.py.
A file named logging.py in this package would shadow Python's built-in
logging module, causing ImportError across the agents package.

IMPORTANT: This module must NOT import from pravni_kvalifikator.web
to avoid circular dependency (agents -> web, but web -> agents).
DB persistence is handled via a registered callback from the web layer.
"""

import asyncio
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# SSE broadcast: dict[qualification_id, asyncio.Queue]
_sse_queues: dict[int, asyncio.Queue] = {}

# Optional DB persistence callback — registered by web layer at startup
_db_logger: Callable[[int, str, str, str, dict[str, Any] | None], Awaitable[None]] | None = None


def register_db_logger(
    fn: Callable[[int, str, str, str, dict[str, Any] | None], Awaitable[None]],
) -> None:
    """Register DB persistence callback. Called by web layer at startup.

    The callback signature: (qualification_id, agent_name, stav, zprava, data) -> None
    """
    global _db_logger
    _db_logger = fn


def register_sse_queue(qualification_id: int) -> asyncio.Queue:
    """Register an SSE queue for a qualification. Returns the queue."""
    queue: asyncio.Queue = asyncio.Queue()
    _sse_queues[qualification_id] = queue
    return queue


def unregister_sse_queue(qualification_id: int) -> None:
    """Remove the SSE queue for a qualification."""
    _sse_queues.pop(qualification_id, None)


async def log_agent_activity(
    qualification_id: int,
    agent_name: str,
    stav: str,
    zprava: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Log agent activity and broadcast via SSE.

    Args:
        qualification_id: Qualification being processed.
        agent_name: Name of the agent ("law_identifier", "head_classifier", etc.).
        stav: Status ("started", "working", "completed", "error").
        zprava: Human-readable message.
        data: Optional structured data (found chapters, paragraphs, etc.).
    """
    # 1. Persist to DB via registered callback (if available)
    if _db_logger is not None:
        await _db_logger(qualification_id, agent_name, stav, zprava, data)

    # 2. Broadcast via SSE queue
    if qualification_id in _sse_queues:
        await _sse_queues[qualification_id].put(
            {
                "agent_name": agent_name,
                "stav": stav,
                "zprava": zprava,
            }
        )

    logger.info("[%s] %s: %s", agent_name, stav, zprava)
