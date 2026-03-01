"""LLM client — Azure OpenAI via LangChain with retry and semaphore."""

import asyncio
import logging
import warnings

import httpx

# LangChain's with_structured_output() interně serializuje přes Pydantic wrapper
# s polem parsed: OutputModel | None, což generuje neškodné warningy.
warnings.filterwarnings("ignore", category=UserWarning, message=".*Pydantic serializer warnings.*")
from langchain_openai import AzureChatOpenAI

from pravni_kvalifikator.shared.config import get_settings

logger = logging.getLogger(__name__)

# Limit concurrent LLM calls to avoid rate-limiting
_semaphore = asyncio.Semaphore(5)


def get_llm(
    temperature: float = 0.0,
    max_tokens: int = 4096,
    deployment: str | None = None,
) -> AzureChatOpenAI:
    """Create an AzureChatOpenAI client.

    Args:
        temperature: Sampling temperature (0.0-1.0).
        max_tokens: Maximum tokens in response.
        deployment: Override deployment name (default: from settings).
    """
    settings = get_settings()
    timeout = httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=10.0)
    return AzureChatOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        azure_deployment=deployment or settings.azure_openai_chat_deployment,
        api_version="2024-08-01-preview",
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=3,
    )


async def invoke_with_semaphore(llm: AzureChatOpenAI, messages: list[dict]) -> str:
    """Invoke LLM with concurrency semaphore to avoid rate-limiting."""
    async with _semaphore:
        response = await llm.ainvoke(messages)
        return response.content


# Alias for agent code consistency
call_llm = invoke_with_semaphore


async def call_llm_structured(
    llm: AzureChatOpenAI,
    messages: list[dict],
    output_schema: type,
    max_tokens: int | None = None,
):
    """Call LLM with structured output (Pydantic model).

    Args:
        llm: The AzureChatOpenAI instance.
        messages: List of message dicts with "role" and "content" keys.
        output_schema: Pydantic model class for structured output.
        max_tokens: Override max_tokens for this call (e.g. for large outputs).
    """
    if max_tokens is not None:
        llm = llm.bind(max_tokens=max_tokens)
    async with _semaphore:
        structured_llm = llm.with_structured_output(output_schema)
        return await structured_llm.ainvoke(messages)
