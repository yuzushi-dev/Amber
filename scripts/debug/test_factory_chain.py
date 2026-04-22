import asyncio

from src.api.config import settings
from src.core.generation.domain.provider_models import ProviderTier
from src.core.generation.infrastructure.providers.factory import ProviderFactory


async def main():
    factory = ProviderFactory(
        openrouter_api_key=settings.openrouter_api_key,
        openrouter_base_url=settings.openrouter_base_url,
        nvidia_nim_api_key=settings.nvidia_nim_api_key,
        nvidia_nim_base_url=settings.nvidia_nim_base_url,
        llm_fallback_enabled=settings.llm_fallback_enabled,
    )
    provider = factory.get_llm_provider(
        provider_name="ollama",
        model="llama3",
        tier=ProviderTier.ECONOMY,
    )
    from src.core.generation.infrastructure.providers.failover import FailoverLLMProvider
    if isinstance(provider, FailoverLLMProvider):
        print("Failover Providers:")
        for p in provider.providers:
            print(f"- {p.provider_name} ({p.default_model})")
    else:
        print(f"Single provider: {provider.provider_name}")

asyncio.run(main())
