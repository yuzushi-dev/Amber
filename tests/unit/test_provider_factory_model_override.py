from src.core.generation.infrastructure.providers.factory import ProviderFactory


def test_get_llm_provider_with_model_override():
    factory = ProviderFactory(
        openai_api_key="test",
        anthropic_api_key=None,
        ollama_base_url=None,
        default_llm_provider=None,
        default_llm_model=None,
    )

    llm = factory.get_llm_provider(provider_name="openai", model="gpt-4o")

    assert llm.default_model == "gpt-4o"
