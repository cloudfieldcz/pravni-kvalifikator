"""Uvicorn SSE/HTTP transport for the MCP server.

NOTE: Avoid module-level side effects (get_settings, setup_logging) here.
Uvicorn imports this module to get the `app` object — any module-level
code that requires .env will break test imports.
"""

import logging
import os

from mcp.server.transport_security import TransportSecuritySettings

from pravni_kvalifikator.mcp.main import mcp

logger = logging.getLogger(__name__)


def _get_transport_security() -> TransportSecuritySettings:
    """Build transport security settings.

    In Docker, the web container connects via hostname 'mcp:8001' which fails
    the default DNS rebinding protection. Allow it explicitly.
    """
    allowed_hosts = ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*"]
    # MCP_ALLOWED_HOSTS can add extra hosts (e.g. Docker service names)
    extra = os.environ.get("MCP_ALLOWED_HOSTS", "")
    if extra:
        allowed_hosts.extend(h.strip() for h in extra.split(",") if h.strip())
    return TransportSecuritySettings(allowed_hosts=allowed_hosts)


def create_sse_app():
    """Create the SSE ASGI app. Called by uvicorn."""
    from pravni_kvalifikator.shared.config import get_settings, setup_logging

    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("Starting MCP server SSE transport")
    mcp.settings.transport_security = _get_transport_security()
    return mcp.sse_app()


# For uvicorn: pravni_kvalifikator.mcp.server:app
mcp.settings.transport_security = _get_transport_security()
app = mcp.sse_app()
