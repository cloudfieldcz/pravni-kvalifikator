"""Tests for MCP SSE client."""

from unittest.mock import AsyncMock, patch

import pytest

from pravni_kvalifikator.shared.mcp_client import MCPClient


@pytest.fixture
def client():
    return MCPClient(base_url="http://localhost:8001")


class TestMCPClient:
    def test_client_creation(self, client):
        assert client.base_url == "http://localhost:8001"

    @pytest.mark.asyncio
    async def test_list_laws_calls_tool(self, client):
        """list_laws() should call the MCP list_laws tool."""
        with patch.object(client, "_call_tool", new_callable=AsyncMock, return_value='[{"id": 1}]'):
            await client.list_laws()
            client._call_tool.assert_called_once_with("list_laws", {})

    @pytest.mark.asyncio
    async def test_list_laws_with_typ(self, client):
        """list_laws(typ=...) should pass typ argument."""
        with patch.object(client, "_call_tool", new_callable=AsyncMock, return_value="[]"):
            await client.list_laws(typ="TZ")
            client._call_tool.assert_called_once_with("list_laws", {"typ": "TZ"})

    @pytest.mark.asyncio
    async def test_search_paragraphs_passes_args(self, client):
        with patch.object(client, "_call_tool", new_callable=AsyncMock, return_value="[]"):
            await client.search_paragraphs(query="krádež", chapter_id=5, top_k=3)
            client._call_tool.assert_called_once_with(
                "search_paragraphs",
                {"query": "krádež", "chapter_id": 5, "top_k": 3},
            )

    @pytest.mark.asyncio
    async def test_get_paragraph_text_by_id(self, client):
        with patch.object(client, "_call_tool", new_callable=AsyncMock, return_value="text"):
            await client.get_paragraph_text(paragraph_id=42)
            client._call_tool.assert_called_once_with("get_paragraph_text", {"paragraph_id": 42})

    @pytest.mark.asyncio
    async def test_get_paragraph_text_by_law_and_cislo(self, client):
        with patch.object(client, "_call_tool", new_callable=AsyncMock, return_value="text"):
            await client.get_paragraph_text(law_sbirkove_cislo="40/2009", paragraph_cislo="205")
            client._call_tool.assert_called_once_with(
                "get_paragraph_text",
                {"law_sbirkove_cislo": "40/2009", "paragraph_cislo": "205"},
            )

    @pytest.mark.asyncio
    async def test_search_chapters_passes_args(self, client):
        with patch.object(client, "_call_tool", new_callable=AsyncMock, return_value="[]"):
            await client.search_chapters(query="majetek", law_id=1, top_k=5)
            client._call_tool.assert_called_once_with(
                "search_chapters", {"query": "majetek", "law_id": 1, "top_k": 5}
            )

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with MCPClient("http://localhost:8001") as client:
            assert client is not None
