from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.core.generation.application.intelligence.document_summarizer import (
    DocumentSummarizer,
)


def test_get_llm_forwards_ollama_cloud_settings():
    """Regression: _get_llm must forward ollama_cloud_* to build_provider_factory,
    otherwise the factory always sees an empty key list regardless of .env
    (prod incident: 523 docs failed enrichment with "OLLAMA_CLOUD_API_KEYS is empty"
    while the env var was correctly populated end-to-end)."""
    settings = SimpleNamespace(
        openai_api_key="",
        anthropic_api_key="",
        ollama_base_url="http://ollama:11434",
        ollama_cloud_base_url="https://ollama.com/v1",
        ollama_cloud_api_keys=["key1", "key2"],
    )

    with (
        patch(
            "src.core.generation.application.intelligence.document_summarizer.build_provider_factory"
        ) as mock_build,
        patch(
            "src.shared.kernel.runtime.get_settings", return_value=settings
        ),
    ):
        mock_factory = MagicMock()
        mock_build.return_value = mock_factory

        DocumentSummarizer()._get_llm()

        mock_build.assert_called_once()
        kwargs = mock_build.call_args.kwargs
        assert kwargs["ollama_cloud_base_url"] == "https://ollama.com/v1"
        assert kwargs["ollama_cloud_api_keys"] == ["key1", "key2"]
