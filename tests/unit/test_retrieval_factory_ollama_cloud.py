"""RetrievalService's shared provider factory (used by the query rewriter) must
carry the ollama_cloud credentials, so a tenant llm_steps override routing
retrieval.query_rewrite to ollama_cloud works in the API request path."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.core.retrieval.application.retrieval_service import RetrievalService
from src.shared.kernel.runtime import _reset_for_tests, configure_settings


def test_shared_factory_gets_ollama_cloud_keys_from_settings():
    configure_settings(
        SimpleNamespace(
            ollama_cloud_base_url="https://cloud.example.com",
            ollama_cloud_api_keys=["k1", "k2"],
        )
    )
    mock_factory = MagicMock()
    try:
        with (
            patch(
                "src.core.retrieval.application.retrieval_service.build_provider_factory",
                return_value=mock_factory,
            ) as build,
            patch("src.core.retrieval.application.retrieval_service.SemanticCache"),
            patch("src.core.retrieval.application.retrieval_service.ResultCache"),
        ):
            service = RetrievalService(
                document_repository=MagicMock(),
                vector_store=MagicMock(),
                neo4j_client=MagicMock(),
                ollama_base_url="http://ollama.example.com:11434",
            )
    finally:
        _reset_for_tests()

    kwargs = build.call_args_list[0].kwargs
    assert kwargs["ollama_cloud_api_keys"] == ["k1", "k2"]
    assert kwargs["ollama_cloud_base_url"] == "https://cloud.example.com"
    assert service.rewriter.factory is mock_factory
