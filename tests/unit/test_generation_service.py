from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.generation.application.generation_service import GenerationService
from src.core.generation.domain.ports.providers import LLMProviderPort
from src.core.tenants.domain.ports.tenant_repository import TenantRepository
from src.shared.kernel.runtime import _reset_for_tests, configure_settings
from src.shared.model_registry import DEFAULT_LLM_MODEL


class DummySettings:
    default_llm_provider = "openai"
    default_llm_model = DEFAULT_LLM_MODEL["openai"]
    default_llm_temperature = 0.0
    seed = 42
    db = SimpleNamespace(redis_url="redis://test")


@pytest.fixture(autouse=True)
def configure_runtime_settings():
    configure_settings(DummySettings())
    yield
    _reset_for_tests()


@pytest.mark.asyncio
async def test_generate_uses_tenant_prompt_overrides():
    # Setup Mocks
    mock_tenant_repo = AsyncMock(spec=TenantRepository)
    mock_tenant = MagicMock()
    mock_tenant.config = {
        "rag_system_prompt": "CUSTOM_SYSTEM_PROMPT",
        "rag_user_prompt": "CUSTOM_USER_PROMPT: {query}",
    }
    mock_tenant_repo.get.return_value = mock_tenant

    mock_llm = AsyncMock(spec=LLMProviderPort)
    mock_llm.model_name = "mock-model"
    mock_usage = MagicMock()
    mock_usage.total_tokens = 100
    mock_usage.input_tokens = 50
    mock_usage.output_tokens = 50
    mock_response = MagicMock(
        content="Mock Response", text="Mock Response", usage=mock_usage, cost_estimate=0.001
    )
    mock_llm.generate.return_value = mock_response

    with (
        patch(
            "src.core.generation.application.generation_service.build_provider_factory"
        ) as mock_build,
        patch(
            "src.core.generation.application.generation_service.ContextBuilder"
        ) as MockContextBuilder,
    ):
        # Setup Factory Mock
        mock_factory = MagicMock()
        mock_build.return_value = mock_factory
        # The service calls factory.get_llm_provider(...) internally
        mock_factory.get_llm_provider.return_value = mock_llm

        # Service Init
        service = GenerationService(
            tenant_repository=mock_tenant_repo, default_llm_provider="mock_provider"
        )
        # Ensure LLM is set (though factory should have handled it)
        service.llm = mock_llm

        mock_ctx_builder_instance = MockContextBuilder.return_value
        mock_context_result = MagicMock()
        mock_context_result.content = "Mock Context"
        mock_ctx_builder_instance.build.return_value = mock_context_result

        # Execute
        await service.generate(
            query="Test Query", candidates=[MagicMock()], options={"tenant_id": "tenant-123"}
        )

    # Verify
    call_args = mock_llm.generate.call_args
    assert call_args is not None
    kwargs = call_args.kwargs

    assert kwargs.get("system_prompt").startswith("CUSTOM_SYSTEM_PROMPT")
    assert "CUSTOM_USER_PROMPT" in kwargs.get("prompt")
    assert "Test Query" in kwargs.get("prompt")
    assert kwargs.get("tenant_id") == "tenant-123"


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
    mock_response = MagicMock(
        content="Mock Response", text="Mock Response", usage=mock_usage, cost_estimate=0.0
    )
    mock_llm.generate.return_value = mock_response

    with (
        patch(
            "src.core.generation.application.generation_service.build_provider_factory"
        ) as mock_build,
        patch(
            "src.core.generation.application.generation_service.ContextBuilder"
        ) as MockContextBuilder,
    ):
        mock_factory = MagicMock()
        mock_build.return_value = mock_factory
        mock_factory.get_llm_provider.return_value = mock_llm

        service = GenerationService(
            tenant_repository=mock_tenant_repo, default_llm_provider="mock_provider"
        )
        service.llm = mock_llm

        mock_ctx_builder_instance = MockContextBuilder.return_value
        mock_context_result = MagicMock()
        mock_context_result.content = "Mock Context"
        mock_ctx_builder_instance.build.return_value = mock_context_result

        # Execute
        await service.generate(
            query="Test Query", candidates=[MagicMock()], options={"tenant_id": "tenant-123"}
        )

    # Verify
    call_args = mock_llm.generate.call_args
    assert call_args is not None
    kwargs = call_args.kwargs

    # Defaults should be used (we can't easily check the exact default string without importing it,
    # but we can check it's NOT the custom one)
    assert kwargs.get("system_prompt") != "CUSTOM_SYSTEM_PROMPT"
    assert "CUSTOM_USER_PROMPT" not in kwargs.get("prompt")


@pytest.mark.asyncio
async def test_generate_injects_global_rules_into_system_prompt():
    """Global rules from RulesService must be appended to the system prompt."""
    # Setup Mocks
    mock_tenant_repo = AsyncMock(spec=TenantRepository)
    mock_tenant = MagicMock()
    mock_tenant.config = {}
    mock_tenant_repo.get.return_value = mock_tenant

    mock_llm = AsyncMock(spec=LLMProviderPort)
    mock_llm.model_name = "mock-model"
    mock_usage = MagicMock()
    mock_usage.total_tokens = 100
    mock_usage.input_tokens = 50
    mock_usage.output_tokens = 50
    mock_response = MagicMock(
        content="Mock Response", text="Mock Response", usage=mock_usage, cost_estimate=0.0
    )
    mock_llm.generate.return_value = mock_response

    # Mock RulesService
    mock_rules_service = AsyncMock()
    mock_rules_service.get_active_rules.return_value = [
        "If the user does not specify CE or User Guide, treat the question as Admin Acme Mail Guide."
    ]
    mock_rules_service.build_system_prompt_addendum.return_value = (
        "\n\n## DOMAIN RULES\n"
        "The following rules MUST be considered when answering questions:\n"
        "- If the user does not specify CE or User Guide, treat the question as Admin Acme Mail Guide.\n"
    )

    with (
        patch(
            "src.core.generation.application.generation_service.build_provider_factory"
        ) as mock_build,
        patch(
            "src.core.generation.application.generation_service.ContextBuilder"
        ) as MockContextBuilder,
        patch(
            "src.core.admin_ops.application.rules_service.get_rules_service",
            return_value=mock_rules_service,
        ),
    ):
        mock_factory = MagicMock()
        mock_build.return_value = mock_factory
        mock_factory.get_llm_provider.return_value = mock_llm

        service = GenerationService(
            tenant_repository=mock_tenant_repo, default_llm_provider="mock_provider"
        )
        service.llm = mock_llm

        mock_ctx_builder_instance = MockContextBuilder.return_value
        mock_context_result = MagicMock()
        mock_context_result.content = "Mock Context"
        mock_ctx_builder_instance.build.return_value = mock_context_result

        # Execute
        await service.generate(
            query="How to configure mailstore?",
            candidates=[MagicMock()],
            options={"tenant_id": "tenant-123"},
        )

    # Verify: system prompt must contain the DOMAIN RULES section
    call_args = mock_llm.generate.call_args
    assert call_args is not None
    kwargs = call_args.kwargs

    system_prompt = kwargs.get("system_prompt")
    assert "## DOMAIN RULES" in system_prompt, "Global rules were not injected into system prompt"
    assert "Admin Acme Mail Guide" in system_prompt, "Rule content missing from system prompt"




@pytest.mark.asyncio
async def test_generate_inherits_default_tenant_prompt_overrides():
    mock_tenant_repo = AsyncMock(spec=TenantRepository)
    default_tenant = MagicMock()
    default_tenant.config = {
        'rag_system_prompt': 'DEFAULT_SYSTEM_PROMPT',
        'rag_user_prompt': 'DEFAULT_USER_PROMPT: {query}',
    }
    child_tenant = MagicMock()
    child_tenant.config = {
        'rag_user_prompt': 'TENANT_USER_PROMPT: {query}',
    }

    async def _get(tenant_id: str):
        if tenant_id == 'default':
            return default_tenant
        if tenant_id == 'tenant-123':
            return child_tenant
        return None

    mock_tenant_repo.get.side_effect = _get

    mock_llm = AsyncMock(spec=LLMProviderPort)
    mock_llm.model_name = 'mock-model'
    mock_usage = MagicMock()
    mock_usage.total_tokens = 100
    mock_response = MagicMock(
        content='Mock Response', text='Mock Response', usage=mock_usage, cost_estimate=0.0
    )
    mock_llm.generate.return_value = mock_response

    with (
        patch('src.core.generation.application.generation_service.build_provider_factory') as mock_build,
        patch('src.core.generation.application.generation_service.ContextBuilder') as MockContextBuilder,
    ):
        mock_factory = MagicMock()
        mock_build.return_value = mock_factory
        mock_factory.get_llm_provider.return_value = mock_llm

        service = GenerationService(
            tenant_repository=mock_tenant_repo, default_llm_provider='mock_provider'
        )
        service.llm = mock_llm

        mock_ctx_builder_instance = MockContextBuilder.return_value
        mock_context_result = MagicMock()
        mock_context_result.content = 'Mock Context'
        mock_ctx_builder_instance.build.return_value = mock_context_result

        await service.generate(
            query='Test Query', candidates=[MagicMock()], options={'tenant_id': 'tenant-123'}
        )

    kwargs = mock_llm.generate.call_args.kwargs
    assert kwargs.get('system_prompt').startswith('DEFAULT_SYSTEM_PROMPT')
    assert 'TENANT_USER_PROMPT' in kwargs.get('prompt')


@pytest.mark.asyncio
async def test_generate_keeps_domain_rules_with_tenant_system_prompt_override():
    mock_tenant_repo = AsyncMock(spec=TenantRepository)
    mock_tenant = MagicMock()
    mock_tenant.config = {
        'rag_system_prompt': 'CUSTOM_SYSTEM_PROMPT',
    }
    mock_tenant_repo.get.return_value = mock_tenant

    mock_llm = AsyncMock(spec=LLMProviderPort)
    mock_llm.model_name = 'mock-model'
    mock_usage = MagicMock()
    mock_usage.total_tokens = 100
    mock_usage.input_tokens = 50
    mock_usage.output_tokens = 50
    mock_response = MagicMock(
        content='Mock Response', text='Mock Response', usage=mock_usage, cost_estimate=0.0
    )
    mock_llm.generate.return_value = mock_response

    mock_rules_service = AsyncMock()
    mock_rules_service.get_active_rules.return_value = ['Always answer with domain context.']
    mock_rules_service.build_system_prompt_addendum.return_value = (
        '\n\n## DOMAIN RULES\n'
        'The following rules MUST be considered when answering questions:\n'
        '- Always answer with domain context.\n'
    )

    with (
        patch('src.core.generation.application.generation_service.build_provider_factory') as mock_build,
        patch('src.core.generation.application.generation_service.ContextBuilder') as MockContextBuilder,
        patch(
            'src.core.admin_ops.application.rules_service.get_rules_service',
            return_value=mock_rules_service,
        ),
    ):
        mock_factory = MagicMock()
        mock_build.return_value = mock_factory
        mock_factory.get_llm_provider.return_value = mock_llm

        service = GenerationService(
            tenant_repository=mock_tenant_repo, default_llm_provider='mock_provider'
        )
        service.llm = mock_llm

        mock_ctx_builder_instance = MockContextBuilder.return_value
        mock_context_result = MagicMock()
        mock_context_result.content = 'Mock Context'
        mock_ctx_builder_instance.build.return_value = mock_context_result

        await service.generate(
            query='How to configure mailstore?',
            candidates=[MagicMock()],
            options={'tenant_id': 'tenant-123'},
        )

    system_prompt = mock_llm.generate.call_args.kwargs.get('system_prompt')
    assert system_prompt.startswith('CUSTOM_SYSTEM_PROMPT')
    assert '## DOMAIN RULES' in system_prompt
    assert 'Always answer with domain context.' in system_prompt

def test_is_synthetic_candidate_true_for_dict_with_synthetic_flag():
    from src.core.generation.application.generation_service import _is_synthetic_candidate

    candidate = {"chunk_id": "global_rule_0", "metadata": {"synthetic": True}}
    assert _is_synthetic_candidate(candidate) is True


def test_is_synthetic_candidate_false_for_real_chunk_dict():
    from src.core.generation.application.generation_service import _is_synthetic_candidate

    candidate = {"chunk_id": "c1", "content": "text", "metadata": {"title": "Doc 1"}}
    assert _is_synthetic_candidate(candidate) is False


def test_is_synthetic_candidate_handles_missing_and_none_metadata():
    from src.core.generation.application.generation_service import _is_synthetic_candidate

    assert _is_synthetic_candidate({"chunk_id": "c1"}) is False
    assert _is_synthetic_candidate({"chunk_id": "c1", "metadata": None}) is False


def test_is_synthetic_candidate_false_for_candidate_dataclass_without_synthetic():
    from src.core.generation.application.generation_service import _is_synthetic_candidate
    from src.core.retrieval.domain.candidate import Candidate

    candidate = Candidate(chunk_id="c1", content="text")
    assert _is_synthetic_candidate(candidate) is False


@pytest.mark.asyncio
async def test_generate_excludes_injected_global_rules_from_chunks_used():
    """chunks_used must count only retrieval chunks, not injected rule
    pseudo-candidates -- see issue #91 (chunks_used > chunks_retrieved)."""
    mock_tenant_repo = AsyncMock(spec=TenantRepository)
    mock_tenant = MagicMock()
    mock_tenant.config = {}
    mock_tenant_repo.get.return_value = mock_tenant

    mock_llm = AsyncMock(spec=LLMProviderPort)
    mock_llm.model_name = "mock-model"
    mock_usage = MagicMock()
    mock_usage.total_tokens = 100
    mock_usage.input_tokens = 50
    mock_usage.output_tokens = 50
    mock_response = MagicMock(
        content="Mock Response", text="Mock Response", usage=mock_usage, cost_estimate=0.0
    )
    mock_llm.generate.return_value = mock_response

    mock_rules_service = AsyncMock()
    mock_rules_service.get_active_rules.return_value = ["Always cite sources."]
    mock_rules_service.build_system_prompt_addendum.return_value = "\n\n## DOMAIN RULES\n- Always cite sources.\n"

    retrieved_chunks = [
        {"chunk_id": "c1", "content": "chunk one", "document_id": "doc1", "score": 0.9},
        {"chunk_id": "c2", "content": "chunk two", "document_id": "doc2", "score": 0.8},
    ]

    with (
        patch(
            "src.core.generation.application.generation_service.build_provider_factory"
        ) as mock_build,
        patch(
            "src.core.generation.application.generation_service.ContextBuilder"
        ) as MockContextBuilder,
        patch(
            "src.core.admin_ops.application.rules_service.get_rules_service",
            return_value=mock_rules_service,
        ),
    ):
        mock_factory = MagicMock()
        mock_build.return_value = mock_factory
        mock_factory.get_llm_provider.return_value = mock_llm

        service = GenerationService(
            tenant_repository=mock_tenant_repo, default_llm_provider="mock_provider"
        )
        service.llm = mock_llm

        captured_candidates: list = []

        def fake_build(candidates, query=None):
            from src.core.generation.application.context_builder import ContextResult

            captured_candidates.extend(candidates)
            return ContextResult(
                content="Mock Context", tokens=10, used_candidates=list(candidates), dropped_candidates=[]
            )

        MockContextBuilder.return_value.build.side_effect = fake_build

        result = await service.generate(
            query="How to configure mailstore?",
            candidates=list(retrieved_chunks),
            options={"tenant_id": "tenant-123"},
        )

    # Sanity: confirm the 1 injected global-rule candidate really was packed
    # alongside the 2 real chunks (3 total) -- otherwise the chunks_used == 2
    # assertion below would pass by coincidence rather than by exclusion.
    assert len(captured_candidates) == 3
    assert result.chunks_used == 2
