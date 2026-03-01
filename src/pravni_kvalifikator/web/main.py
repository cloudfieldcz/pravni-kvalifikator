"""FastAPI web application entry point."""

import hashlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader

from pravni_kvalifikator.shared.config import get_settings, setup_logging
from pravni_kvalifikator.web.auth import AuthRequired
from pravni_kvalifikator.web.session import SessionDB

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"


def _static_hash() -> str:
    """Compute short hash from static files' mtimes for cache busting."""
    mtimes = sorted(f"{p.name}:{p.stat().st_mtime}" for p in STATIC_DIR.iterdir() if p.is_file())
    return hashlib.md5("|".join(mtimes).encode()).hexdigest()[:8]


def _format_datetime(value: str | None) -> str:
    """Format SQLite timestamp to Czech format: '1. 3. 2026 14:23'."""
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value)
        return f"{dt.day}. {dt.month}. {dt.year} {dt.hour}:{dt.minute:02d}"
    except (ValueError, TypeError):
        return str(value)


# Jinja2 templates — pre-configured Environment avoids Starlette deprecation warning
_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
_jinja_env.filters["format_datetime"] = _format_datetime
_jinja_env.globals["static_v"] = _static_hash()
templates = Jinja2Templates(env=_jinja_env)


# NOTE (P4-1): @app.on_event("startup") is deprecated since FastAPI 0.109+.
# Use lifespan context manager instead.
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown logic."""
    settings = get_settings()
    setup_logging(settings.log_level)

    # Initialize sessions database
    session_db = SessionDB(settings.sessions_db_path)
    session_db.create_tables()

    # Register DB logger callback for agent activity module (P3-2: avoids circular dependency)
    from pravni_kvalifikator.agents.activity import register_db_logger

    async def _db_log(qualification_id, agent_name, stav, zprava, data):
        db = SessionDB(settings.sessions_db_path)
        db.insert_agent_log(qualification_id, agent_name, stav, zprava, data)

    register_db_logger(_db_log)

    if not settings.auth_hmac_key:
        logger.warning("AUTH_HMAC_KEY is empty — authentication is DISABLED!")

    yield  # App is running

    # Shutdown: nothing to clean up currently


def create_app() -> FastAPI:
    """Factory function for the FastAPI app."""
    app = FastAPI(title="Právní Kvalifikátor", lifespan=lifespan)

    # Mount static files
    STATIC_DIR.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/health")
    async def health_check():
        return {"status": "healthy"}

    # Auth: exception handler for AuthRequired → redirect to /login
    @app.exception_handler(AuthRequired)
    async def auth_redirect(request: Request, exc: AuthRequired):
        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie("auth_token", path="/")
        return response

    # NOTE (P4-3): Import routes inside factory, not at module level.
    # Module-level imports of routes would trigger circular imports
    # (routes.py imports from main.py for templates).
    from pravni_kvalifikator.web.auth import auth_router
    from pravni_kvalifikator.web.routes import router

    app.include_router(auth_router)  # /login, /logout — no auth dependency
    app.include_router(router)  # All other routes — with auth dependency

    return app


# Module-level app instance for uvicorn reference ("pravni_kvalifikator.web.main:app")
app = create_app()


def main():
    """Entry point for pq-web command."""
    settings = get_settings()
    setup_logging(settings.log_level)
    uvicorn.run(
        "pravni_kvalifikator.web.main:app",
        host=settings.web_host,
        port=settings.web_port,
        reload=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
