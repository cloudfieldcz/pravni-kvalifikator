"""HTTP and SSE endpoints for the web application."""

import asyncio
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

from pravni_kvalifikator.agents.activity import register_sse_queue, unregister_sse_queue
from pravni_kvalifikator.agents.orchestrator import run_qualification
from pravni_kvalifikator.shared.config import get_settings
from pravni_kvalifikator.web.auth import require_auth
from pravni_kvalifikator.web.models import QualifyRequest, QualifyResponse
from pravni_kvalifikator.web.session import SessionDB

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_auth)])


def _get_session_db() -> SessionDB:
    settings = get_settings()
    return SessionDB(settings.sessions_db_path)


def _get_or_create_session(request: Request) -> str:
    """Get session ID from auth (username) or legacy cookie (UUID)."""
    settings = get_settings()

    # Auth enabled → session_id = username
    username = getattr(request.state, "username", None)
    if settings.auth_hmac_key and username:
        db = _get_session_db()
        if not db.get_session(username):
            db.create_session_with_id(username)
        return username

    # Auth disabled → legacy UUID from cookie
    session_id = request.cookies.get("session_id")
    db = _get_session_db()
    if session_id:
        session = db.get_session(session_id)
        if session:
            return session_id
    new_id = db.create_session()
    return new_id


def _check_qualification_access(qualification: dict, request: Request) -> bool:
    """Check that the qualification belongs to the current user's session."""
    settings = get_settings()
    if not settings.auth_hmac_key:
        return True  # Auth disabled — no access check
    username = getattr(request.state, "username", None)
    return qualification.get("session_id") == username


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, session_id: str | None = Cookie(default=None)):
    """Main page with textarea and history."""
    from pravni_kvalifikator.web.main import templates

    sid = _get_or_create_session(request)
    db = _get_session_db()
    history = db.list_qualifications(sid)

    response = templates.TemplateResponse(
        request,
        "index.html",
        {"history": history},
    )
    # Set session cookie only for auth-disabled mode (legacy UUID sessions)
    if not get_settings().auth_hmac_key and sid != (session_id or ""):
        response.set_cookie(
            key="session_id",
            value=sid,
            httponly=True,
            max_age=60 * 60 * 24 * get_settings().session_expiry_days,
        )
    return response


@router.post("/qualify")
async def qualify(
    req: QualifyRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session_id: str | None = Cookie(default=None),
):
    """Start a new qualification. Returns qualification_id."""
    sid = _get_or_create_session(request)
    db = _get_session_db()
    qid = db.create_qualification(sid, req.popis_skutku, req.typ)

    # Start pipeline in background
    background_tasks.add_task(_run_pipeline, qid, req.popis_skutku, req.typ)

    response = JSONResponse(content=QualifyResponse(qualification_id=qid).model_dump())
    # Set session cookie only for auth-disabled mode (legacy UUID sessions)
    if not get_settings().auth_hmac_key and sid != (session_id or ""):
        response.set_cookie(
            key="session_id",
            value=sid,
            httponly=True,
            max_age=60 * 60 * 24 * get_settings().session_expiry_days,
        )
    return response


async def _run_pipeline(qualification_id: int, popis_skutku: str, typ: str):
    """Background task: run the qualification pipeline."""
    db = _get_session_db()
    db.update_qualification(qualification_id, stav="processing")

    try:
        result = await run_qualification(popis_skutku, typ, qualification_id)

        if result.get("error"):
            db.update_qualification(
                qualification_id,
                stav="error",
                error_message=result["error"],
            )
        else:
            db.update_qualification(
                qualification_id,
                stav="completed",
                vysledek=json.dumps(
                    {
                        "final_kvalifikace": result.get("final_kvalifikace", []),
                        "review_notes": result.get("review_notes", []),
                        "skoda": result.get("skoda", {}),
                        "okolnosti": result.get("okolnosti", {}),
                        "special_law_kvalifikace": result.get(
                            "special_law_kvalifikace", []
                        ),
                        "special_law_notes": result.get("special_law_notes", []),
                    },
                    ensure_ascii=False,
                ),
            )
    except Exception as e:
        logger.exception("Pipeline failed for qualification %d", qualification_id)
        db.update_qualification(qualification_id, stav="error", error_message=str(e))


@router.get("/qualify/{qualification_id}/stream")
async def stream_progress(request: Request, qualification_id: int):
    """SSE stream of agent progress events."""
    # Access check
    db = _get_session_db()
    qual = db.get_qualification(qualification_id)
    if qual is None or not _check_qualification_access(dict(qual), request):
        return JSONResponse(status_code=404, content={"error": "Kvalifikace nenalezena"})

    queue = register_sse_queue(qualification_id)

    async def event_generator():
        # NOTE (P4-2): We must detect errors from ANY agent, not just reviewer.
        # If pipeline fails at head_classifier, the reviewer never runs and
        # SSE stream would hang until timeout (120s).
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=120.0)
                    yield {
                        "event": "agent_update",
                        "data": json.dumps(event, ensure_ascii=False),
                    }
                    # Pipeline finished: reviewer completed OR any agent errored
                    if event.get("stav") == "error":
                        yield {
                            "event": "done",
                            "data": json.dumps({"error": True}, ensure_ascii=False),
                        }
                        break
                    if event.get("stav") == "completed" and event.get("agent_name") == "reviewer":
                        yield {"event": "done", "data": "{}"}
                        break
                except asyncio.TimeoutError:
                    # Check DB for pipeline completion (in case events were missed)
                    db_check = _get_session_db()
                    qual_check = db_check.get_qualification(qualification_id)
                    if qual_check and qual_check.get("stav") in ("completed", "error"):
                        yield {"event": "done", "data": "{}"}
                        break
                    # Send keepalive
                    yield {"event": "ping", "data": "{}"}
        finally:
            unregister_sse_queue(qualification_id)

    return EventSourceResponse(event_generator())


@router.get("/qualify/{qualification_id}", response_class=HTMLResponse)
async def get_result_html(request: Request, qualification_id: int):
    """Render qualification result as HTML page."""
    from pravni_kvalifikator.web.main import templates

    db = _get_session_db()
    qual = db.get_qualification(qualification_id)
    if qual is None or not _check_qualification_access(dict(qual), request):
        return JSONResponse(status_code=404, content={"error": "Kvalifikace nenalezena"})

    result = dict(qual)
    if result.get("vysledek"):
        result["vysledek"] = json.loads(result["vysledek"])

    return templates.TemplateResponse(request, "result.html", {"qualification": result})


@router.get("/api/qualify/{qualification_id}")
async def get_result_json(request: Request, qualification_id: int):
    """Get qualification result as JSON (for JS client)."""
    db = _get_session_db()
    qual = db.get_qualification(qualification_id)
    if qual is None or not _check_qualification_access(dict(qual), request):
        return JSONResponse(status_code=404, content={"error": "Kvalifikace nenalezena"})

    result = dict(qual)
    if result.get("vysledek"):
        result["vysledek"] = json.loads(result["vysledek"])
    return JSONResponse(content=result)


@router.get("/history")
async def history(request: Request):
    """History of qualifications in this session."""
    from pravni_kvalifikator.web.main import templates

    sid = _get_or_create_session(request)
    db = _get_session_db()
    quals = db.list_qualifications(sid)

    return templates.TemplateResponse(
        request,
        "index.html",
        {"history": quals},
    )
