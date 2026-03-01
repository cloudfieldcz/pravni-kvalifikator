"""Tests for Azure OpenAI embedding client."""

from unittest.mock import MagicMock, patch

from pravni_kvalifikator.mcp.embedder import EMBEDDING_TOKEN_BUDGET
from pravni_kvalifikator.shared.config import EMBEDDING_DIMENSIONS


def test_embed_text_returns_correct_dimensions():
    """embed_text returns a list of EMBEDDING_DIMENSIONS floats."""
    fake_embedding = [0.1] * EMBEDDING_DIMENSIONS
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=fake_embedding)]

    with patch("pravni_kvalifikator.mcp.embedder.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            azure_openai_endpoint="https://test.openai.azure.com/",
            azure_openai_api_key="test-key",
            azure_openai_embedding_deployment="text-embedding-3-large",
        )
        with patch("pravni_kvalifikator.mcp.embedder.AzureOpenAI") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.embeddings.create.return_value = mock_response
            mock_client_cls.return_value = mock_client

            from pravni_kvalifikator.mcp.embedder import EmbeddingClient

            client = EmbeddingClient()
            result = client.embed_text("test query")

            assert len(result) == EMBEDDING_DIMENSIONS
            mock_client.embeddings.create.assert_called_once()


def test_embed_batch_preserves_order():
    """embed_batch returns embeddings in the same order as inputs."""

    def make_response(texts):
        data = []
        for i, _ in enumerate(texts):
            entry = MagicMock()
            entry.embedding = [float(i)] * EMBEDDING_DIMENSIONS
            entry.index = i
            data.append(entry)
        response = MagicMock()
        response.data = data
        return response

    with patch("pravni_kvalifikator.mcp.embedder.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            azure_openai_endpoint="https://test.openai.azure.com/",
            azure_openai_api_key="test-key",
            azure_openai_embedding_deployment="text-embedding-3-large",
        )
        with patch("pravni_kvalifikator.mcp.embedder.AzureOpenAI") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.embeddings.create.side_effect = lambda **kwargs: make_response(
                kwargs["input"]
            )
            mock_client_cls.return_value = mock_client

            from pravni_kvalifikator.mcp.embedder import EmbeddingClient

            client = EmbeddingClient()
            results = client.embed_batch(["a", "b", "c"])

            assert len(results) == 3
            # First text should have embedding starting with 0.0
            assert results[0][0] == 0.0
            assert results[1][0] == 1.0
            assert results[2][0] == 2.0


def test_embed_batch_truncates_too_long_texts():
    """embed_batch truncates over-limit texts before API call."""

    class FakeEncoding:
        def encode(self, text: str) -> list[int]:
            return list(range(len(text)))

        def decode(self, token_ids: list[int]) -> str:
            return "x" * len(token_ids)

    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1] * EMBEDDING_DIMENSIONS, index=0)]

    with patch("pravni_kvalifikator.mcp.embedder.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            azure_openai_endpoint="https://test.openai.azure.com/",
            azure_openai_api_key="test-key",
            azure_openai_embedding_deployment="text-embedding-3-large",
        )
        with patch("pravni_kvalifikator.mcp.embedder.AzureOpenAI") as mock_client_cls:
            with patch("pravni_kvalifikator.mcp.embedder.tiktoken.get_encoding") as mock_encoding:
                mock_encoding.return_value = FakeEncoding()
                mock_client = MagicMock()
                mock_client.embeddings.create.return_value = mock_response
                mock_client_cls.return_value = mock_client

                from pravni_kvalifikator.mcp.embedder import EmbeddingClient

                client = EmbeddingClient()
                too_long = "a" * (EMBEDDING_TOKEN_BUDGET + 500)
                client.embed_batch([too_long])

                api_input = mock_client.embeddings.create.call_args.kwargs["input"][0]
                assert len(api_input) == EMBEDDING_TOKEN_BUDGET
