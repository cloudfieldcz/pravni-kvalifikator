"""Tests for shared LLM client."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pravni_kvalifikator.shared.llm import (
    _semaphore,
    call_llm,
    call_llm_structured,
    get_llm,
    invoke_with_semaphore,
)


def test_get_llm_returns_azure_chat():
    with patch("pravni_kvalifikator.shared.llm.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            azure_openai_endpoint="https://test.openai.azure.com/",
            azure_openai_api_key="test-key",
            azure_openai_chat_deployment="gpt-5.2",
        )
        with patch("pravni_kvalifikator.shared.llm.AzureChatOpenAI") as mock_cls:
            mock_cls.return_value = MagicMock()
            llm = get_llm()
            mock_cls.assert_called_once()
            assert llm is not None


def test_semaphore_has_correct_limit():
    """Semaphore should limit to 5 concurrent calls."""
    assert _semaphore._value == 5


def test_call_llm_is_alias_for_invoke_with_semaphore():
    """call_llm should be the same function as invoke_with_semaphore."""
    assert call_llm is invoke_with_semaphore


@pytest.mark.asyncio
async def test_call_llm_structured_uses_structured_output():
    """call_llm_structured should use with_structured_output."""
    mock_llm = MagicMock()
    mock_structured = AsyncMock()
    mock_structured.ainvoke.return_value = MagicMock(value="result")
    mock_llm.with_structured_output.return_value = mock_structured

    class FakeSchema:
        pass

    await call_llm_structured(mock_llm, [{"role": "user", "content": "test"}], FakeSchema)

    mock_llm.with_structured_output.assert_called_once_with(FakeSchema)
    mock_structured.ainvoke.assert_called_once_with([{"role": "user", "content": "test"}])
