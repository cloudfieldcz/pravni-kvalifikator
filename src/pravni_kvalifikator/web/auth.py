"""Authentication — HMAC SHA-256 token validation and auth routes."""

import argparse
import hashlib
import hmac
import logging
import re
import sys
from datetime import date, datetime

from fastapi import APIRouter, Cookie, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from pravni_kvalifikator.shared.config import get_settings

logger = logging.getLogger(__name__)

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")
USERNAME_MAX_LEN = 64


class AuthRequired(Exception):
    """Raised when authentication is required — triggers redirect to /login."""

    pass


def parse_token(token: str) -> tuple[str, str, str]:
    """Parse 'USERNAME:YYYYMMDD:HEX' -> (username, platnost_do, hex_token).

    Raises ValueError if format is invalid.
    """
    parts = token.split(":")
    if len(parts) != 3:
        raise ValueError("Token musí mít formát USERNAME:YYYYMMDD:TOKEN")
    username, platnost_do, hex_token = parts
    if not USERNAME_PATTERN.match(username) or len(username) > USERNAME_MAX_LEN:
        raise ValueError("Neplatné uživatelské jméno")
    if len(platnost_do) != 8 or not platnost_do.isdigit():
        raise ValueError("Neplatné datum platnosti")
    return username, platnost_do, hex_token


def compute_hmac(username: str, platnost_do: str, key: str) -> str:
    """HMAC-SHA256(key, 'USERNAME:YYYYMMDD').hexdigest()"""
    msg = f"{username}:{platnost_do}".encode()
    return hmac.new(key.encode(), msg, hashlib.sha256).hexdigest()


def validate_token(token: str, key: str) -> str | None:
    """Validate token. Returns username if valid, None if invalid."""
    try:
        username, platnost_do, hex_token = parse_token(token)
    except ValueError:
        return None

    expected = compute_hmac(username, platnost_do, key)
    if not hmac.compare_digest(hex_token, expected):
        return None

    # Check expiry: platnost_do >= today
    try:
        expiry = datetime.strptime(platnost_do, "%Y%m%d").date()
    except ValueError:
        return None
    if expiry < date.today():
        return None

    return username


def generate_token(username: str, platnost_do: str, key: str) -> str:
    """Generate 'USERNAME:YYYYMMDD:HEX' token.

    Validates username format before generating.
    """
    if not USERNAME_PATTERN.match(username) or len(username) > USERNAME_MAX_LEN:
        raise ValueError(f"Neplatné uživatelské jméno: {username!r}")
    if len(platnost_do) != 8 or not platnost_do.isdigit():
        raise ValueError(f"Neplatné datum platnosti: {platnost_do!r}")
    # Validate date is parseable
    datetime.strptime(platnost_do, "%Y%m%d")

    hex_token = compute_hmac(username, platnost_do, key)
    return f"{username}:{platnost_do}:{hex_token}"


# ── FastAPI dependency ──


async def require_auth(request: Request, auth_token: str | None = Cookie(default=None)):
    """Dependency: validate auth token from cookie. Sets request.state.username."""
    settings = get_settings()
    if not settings.auth_hmac_key:
        return None  # Auth disabled
    if not auth_token:
        raise AuthRequired()
    username = validate_token(auth_token, settings.auth_hmac_key)
    if username is None:
        raise AuthRequired()
    request.state.username = username
    return username


# ── Auth router (login/logout — no auth dependency) ──

auth_router = APIRouter()


@auth_router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None):
    """Render login form."""
    from pravni_kvalifikator.web.main import templates

    settings = get_settings()
    if not settings.auth_hmac_key:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": error})


@auth_router.post("/login")
async def login_submit(request: Request, token: str = Form()):
    """Validate token, set cookie, redirect."""
    from pravni_kvalifikator.web.main import templates

    settings = get_settings()
    if not settings.auth_hmac_key:
        return RedirectResponse(url="/", status_code=303)

    username = validate_token(token.strip(), settings.auth_hmac_key)
    if username is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Neplatný nebo prošlý token."},
            status_code=401,
        )

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key="auth_token",
        value=token.strip(),
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=60 * 60 * 24 * settings.session_expiry_days,
        path="/",
    )
    return response


@auth_router.get("/logout")
async def logout():
    """Delete auth cookie, redirect to login."""
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("auth_token", path="/")
    return response


# ── CLI utility ──


def main_cli():
    """Entry point for pq-token command — generate auth tokens."""
    parser = argparse.ArgumentParser(description="Generate HMAC SHA-256 auth tokens")
    parser.add_argument("--username", required=True, help="Username (alphanumeric, dots, dashes)")
    parser.add_argument(
        "--valid-until", required=True, help="Expiry date in YYYYMMDD format (inclusive)"
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.auth_hmac_key:
        print("Error: AUTH_HMAC_KEY is not set in .env", file=sys.stderr)
        sys.exit(1)

    try:
        token = generate_token(args.username, args.valid_until, settings.auth_hmac_key)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Token: {token}")
