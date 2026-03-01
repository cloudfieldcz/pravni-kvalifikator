"""MCP SSE client for agent-to-MCP-server communication.

Connects to MCP server via SSE transport, sends JSON-RPC messages, receives results.
"""

import json
import logging
from typing import Any

import httpx

from pravni_kvalifikator.shared.config import get_settings

logger = logging.getLogger(__name__)


class MCPClient:
    """HTTP client for MCP server communication via SSE transport."""

    def __init__(self, base_url: str | None = None):
        settings = get_settings()
        self.base_url = (base_url or settings.mcp_server_url).rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def _call_tool(self, tool_name: str, arguments: dict) -> Any:
        """Call an MCP tool via SSE transport. Returns the tool result."""
        client = await self._get_client()

        init_message = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pravni-kvalifikator-agent", "version": "1.0.0"},
            },
        }
        tool_message = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        session_url = None

        async with client.stream("GET", f"{self.base_url}/sse") as sse_response:
            async for line in sse_response.aiter_lines():
                line = line.strip()
                if not line:
                    continue

                if line.startswith("data:"):
                    data = line[5:].strip()

                    # First data message: session URL
                    if session_url is None:
                        session_url = f"{self.base_url}{data}" if data.startswith("/") else data
                        await client.post(
                            session_url,
                            json=init_message,
                            headers={"Content-Type": "application/json"},
                        )
                        continue

                    try:
                        response_data = json.loads(data)

                        # Initialize response (id=1)
                        if response_data.get("id") == 1:
                            if "error" in response_data:
                                raise RuntimeError(f"MCP init error: {response_data['error']}")
                            await client.post(
                                session_url,
                                json=tool_message,
                                headers={"Content-Type": "application/json"},
                            )
                            continue

                        # Tool response (id=2)
                        if response_data.get("id") == 2:
                            if "error" in response_data:
                                raise RuntimeError(f"MCP tool error: {response_data['error']}")
                            result = response_data.get("result", {})
                            if "content" in result:
                                contents = result["content"]
                                if contents:
                                    return contents[0].get("text", "")
                            return result

                    except json.JSONDecodeError:
                        logger.warning("Failed to parse SSE data: %s", data[:100])
                        continue

        raise RuntimeError(f"No response received for tool {tool_name}")

    # -- High-Level Tool Methods --

    async def list_laws(self, typ: str | None = None) -> str:
        args = {}
        if typ:
            args["typ"] = typ
        return await self._call_tool("list_laws", args)

    async def list_chapters(self, law_id: int) -> str:
        return await self._call_tool("list_chapters", {"law_id": law_id})

    async def list_paragraphs(self, chapter_id: int) -> str:
        return await self._call_tool("list_paragraphs", {"chapter_id": chapter_id})

    async def get_paragraph_text(
        self,
        paragraph_id: int | None = None,
        law_sbirkove_cislo: str | None = None,
        paragraph_cislo: str | None = None,
    ) -> str:
        args = {}
        if paragraph_id is not None:
            args["paragraph_id"] = paragraph_id
        if law_sbirkove_cislo:
            args["law_sbirkove_cislo"] = law_sbirkove_cislo
        if paragraph_cislo:
            args["paragraph_cislo"] = paragraph_cislo
        return await self._call_tool("get_paragraph_text", args)

    async def get_damage_thresholds(self) -> str:
        return await self._call_tool("get_damage_thresholds", {})

    async def search_laws(self, query: str, top_k: int = 5) -> str:
        return await self._call_tool("search_laws", {"query": query, "top_k": top_k})

    async def search_chapters(self, query: str, law_id: int | None = None, top_k: int = 5) -> str:
        args = {"query": query, "top_k": top_k}
        if law_id is not None:
            args["law_id"] = law_id
        return await self._call_tool("search_chapters", args)

    async def search_paragraphs(
        self, query: str, chapter_id: int | None = None, top_k: int = 10
    ) -> str:
        args = {"query": query, "top_k": top_k}
        if chapter_id is not None:
            args["chapter_id"] = chapter_id
        return await self._call_tool("search_paragraphs", args)

    async def search_paragraphs_keyword(
        self, keywords: str, chapter_id: int | None = None, top_k: int = 10
    ) -> str:
        args = {"keywords": keywords, "top_k": top_k}
        if chapter_id is not None:
            args["chapter_id"] = chapter_id
        return await self._call_tool("search_paragraphs_keyword", args)

    # -- Lifecycle --

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# Singleton
_mcp_client: MCPClient | None = None


def get_mcp_client() -> MCPClient:
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient()
    return _mcp_client
