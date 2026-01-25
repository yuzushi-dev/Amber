import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from src.core.generation.application.generation_service import GenerationService
from src.core.tenants.domain.ports.tenant_repository import TenantRepository
from src.core.generation.domain.ports.providers import LLMProviderPort

@pytest.mark.asyncio
async def test_generate_uses_tenant_prompt_overrides():
    # Setup Mocks
    mock_tenant_repo = AsyncMock(spec=TenantRepository)
    mock_tenant = MagicMock()
    mock_tenant.config = {
        "rag_system_prompt": "CUSTOM_SYSTEM_PROMPT",
        "rag_user_prompt": "CUSTOM_USER_PROMPT: {query}"
    }
    mock_tenant_repo.get.return_value = mock_tenant

    mock_llm = AsyncMock(spec=LLMProviderPort)
    mock_llm.model_name = "mock-model"
    mock_usage = MagicMock()
    mock_usage.total_tokens = 100
    mock_usage.input_tokens = 50
    mock_usage.output_tokens = 50
    mock_response = MagicMock(content="Mock Response", text="Mock Response", usage=mock_usage, cost_estimate=0.001)
    mock_llm.generate.return_value = mock_response

    with patch("src.core.generation.application.generation_service.build_provider_factory") as mock_build, \
         patch("src.core.generation.application.generation_service.ContextBuilder") as MockContextBuilder:
        
        # Setup Factory Mock
        mock_factory = MagicMock()
        mock_build.return_value = mock_factory
        # The service calls factory.get_llm_provider(...) internally
        mock_factory.get_llm_provider.return_value = mock_llm

        # Service Init
        service = GenerationService(
            tenant_repository=mock_tenant_repo,
            default_llm_provider="mock_provider"
        )
        # Ensure LLM is set (though factory should have handled it)
        service.llm = mock_llm

        mock_ctx_builder_instance = MockContextBuilder.return_value
        mock_context_result = MagicMock()
        mock_context_result.content = "Mock Context"
        mock_ctx_builder_instance.build.return_value = mock_context_result

        # Execute
        await service.generate(
            query="Test Query",
            candidates=[MagicMock()],
            options={"tenant_id": "tenant-123"}
        )

    # Verify
    call_args = mock_llm.generate.call_args
    assert call_args is not None
    kwargs = call_args.kwargs
    
    assert kwargs.get("system_prompt") == "CUSTOM_SYSTEM_PROMPT"
    assert "CUSTOM_USER_PROMPT" in kwargs.get("prompt")
    assert "Test Query" in kwargs.get("prompt")

@pytest.mark.asyncio
async def test_generate_uses_default_prompts_when_no_override():
    # Setup Mocks
    mock_tenant_repo = AsyncMock(spec=TenantRepository)
    # Tenant exists but has no config overrides
    mock_tenant = MagicMock()
    mock_tenant.config = {} 
    mock_tenant_repo.get.return_value = mock_tenant

    mock_llm = AsyncMock(spec=LLMProviderPort)
    mock_llm.model_name = "mock-model"
    mock_usage = MagicMock()
    mock_usage.total_tokens = 100
    mock_response = MagicMock(content="Mock Response", text="Mock Response", usage=mock_usage, cost_estimate=0.0)
    mock_llm.generate.return_value = mock_response

    with patch("src.core.generation.application.generation_service.build_provider_factory") as mock_build, \
         patch("src.core.generation.application.generation_service.ContextBuilder") as MockContextBuilder:

        mock_factory = MagicMock()
        mock_build.return_value = mock_factory
        mock_factory.get_llm_provider.return_value = mock_llm

        service = GenerationService(
            tenant_repository=mock_tenant_repo,
            default_llm_provider="mock_provider"
        )
        service.llm = mock_llm

        mock_ctx_builder_instance = MockContextBuilder.return_value
        mock_context_result = MagicMock()
        mock_context_result.content = "Mock Context"
        mock_ctx_builder_instance.build.return_value = mock_context_result

        # Execute
        await service.generate(
            query="Test Query",
            candidates=[MagicMock()],
            options={"tenant_id": "tenant-123"}
        )

    # Verify
    call_args = mock_llm.generate.call_args
    assert call_args is not None
    kwargs = call_args.kwargs
    
    # Defaults should be used (we can't easily check the exact default string without importing it, 
    # but we can check it's NOT the custom one)
    assert kwargs.get("system_prompt") != "CUSTOM_SYSTEM_PROMPT"
    assert "CUSTOM_USER_PROMPT" not in kwargs.get("prompt")
