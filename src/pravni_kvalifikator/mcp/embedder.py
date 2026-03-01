"""Azure OpenAI embedding client."""

import logging
from collections.abc import Sequence

import tiktoken
from openai import AzureOpenAI

from pravni_kvalifikator.shared.config import EMBEDDING_DIMENSIONS, get_settings

logger = logging.getLogger(__name__)

EMBEDDING_MAX_TOKENS = 8192
# Keep a small safety margin to avoid model-side accounting differences.
EMBEDDING_TOKEN_BUDGET = EMBEDDING_MAX_TOKENS - 64


class EmbeddingClient:
    """Azure OpenAI embedding client with batch support."""

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        deployment: str | None = None,
    ):
        settings = get_settings()
        self.endpoint = endpoint or settings.azure_openai_endpoint
        self.api_key = api_key or settings.azure_openai_api_key
        self.deployment = deployment or settings.azure_openai_embedding_deployment

        if not self.endpoint or not self.api_key:
            raise ValueError(
                "Azure OpenAI endpoint a API key musí být nastaveny. "
                "Nastavte AZURE_OPENAI_ENDPOINT a AZURE_OPENAI_API_KEY v .env"
            )

        self.client = AzureOpenAI(
            azure_endpoint=self.endpoint,
            api_key=self.api_key,
            api_version="2024-06-01",
        )
        self._encoding = tiktoken.get_encoding("cl100k_base")

    def _sanitize_text(self, text: str) -> str:
        """Ensure text fits within embedding token budget."""
        token_ids = self._encoding.encode(text)
        if len(token_ids) <= EMBEDDING_TOKEN_BUDGET:
            return text

        logger.warning(
            "Text too long for embedding (%d tokens), truncating to %d tokens",
            len(token_ids),
            EMBEDDING_TOKEN_BUDGET,
        )
        truncated_ids = token_ids[:EMBEDDING_TOKEN_BUDGET]
        return self._encoding.decode(truncated_ids)

    def embed_text(self, text: str) -> list[float]:
        """Embed a single text. Returns list of EMBEDDING_DIMENSIONS floats."""
        safe_text = self._sanitize_text(text)
        response = self.client.embeddings.create(
            model=self.deployment,
            input=safe_text,
            dimensions=EMBEDDING_DIMENSIONS,
        )
        return response.data[0].embedding

    def embed_batch(self, texts: Sequence[str], batch_size: int = 100) -> list[list[float]]:
        """Embed multiple texts in batches. Returns embeddings in input order."""
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            safe_batch = [self._sanitize_text(text) for text in batch]
            logger.info(
                "Embedding batch %d/%d (%d texts)",
                i // batch_size + 1,
                (len(texts) + batch_size - 1) // batch_size,
                len(batch),
            )
            response = self.client.embeddings.create(
                model=self.deployment,
                input=safe_batch,
                dimensions=EMBEDDING_DIMENSIONS,
            )
            # Sort by index to preserve input order
            batch_embeddings = sorted(response.data, key=lambda x: x.index)
            all_embeddings.extend([e.embedding for e in batch_embeddings])
        return all_embeddings


# Singleton
_client: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    """Return singleton EmbeddingClient instance."""
    global _client
    if _client is None:
        _client = EmbeddingClient()
    return _client
