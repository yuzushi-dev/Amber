import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.generation.application.prompts.community_summary import (
    COMMUNITY_SUMMARY_SYSTEM_PROMPT,
)
from src.core.graph.application.communities.lifecycle import CommunityLifecycleManager
from src.core.graph.application.communities.summarizer import (
    CommunitySummarizer,
)
from src.core.utils.tokenizer import Tokenizer
from src.shared.model_registry import llm_context_window


@pytest.fixture
def mock_neo4j():
    return AsyncMock()


@pytest.fixture
def mock_factory():
    factory = MagicMock()
    factory.get_llm_provider.return_value = AsyncMock()
    return factory


@pytest.fixture
def mock_embedding_service():
    service = AsyncMock()
    service.embed_single.return_value = [0.1] * 1536
    return service


def test_local_ollama_context_uses_runtime_num_ctx():
    with patch.dict("os.environ", {"OLLAMA_NUM_CTX": "65536"}):
        assert llm_context_window("ollama", "llama3") == 65_536
    assert llm_context_window("ollama_cloud_0", "gpt-oss:120b") == 131_072


def test_cloud_model_proxied_through_local_ollama_keeps_its_context_window():
    """Tenants route *-cloud models through the local `ollama` provider; the model's
    real window must win over the local daemon's OLLAMA_NUM_CTX default."""
    with patch.dict("os.environ", {"OLLAMA_NUM_CTX": "32768"}):
        assert llm_context_window("ollama", "gemma4:31b-cloud") == 131_072


class TestCommunitySummarizer:
    @pytest.mark.asyncio
    async def test_summarize_community_success(self, mock_neo4j, mock_factory):
        # Setup
        summarizer = CommunitySummarizer(mock_neo4j, mock_factory)

        # Mock data fetch
        mock_neo4j.execute_read.side_effect = [
            [{"name": "Entity A", "type": "Person", "description": "Desc A"}],  # entities
            [
                {
                    "source": "Entity A",
                    "target": "Entity B",
                    "type": "WORKS_WITH",
                    "description": "Rel Desc",
                }
            ],  # relationships
            [],  # child summaries
            [{"id": "chunk_1", "content": "Sample text unit content"}],  # text_units
        ]

        # Mock LLM response
        llm_result = MagicMock()
        llm_result.text = json.dumps(
            {
                "title": "Test Community",
                "summary": "This is a test summary.",
                "rating": 8,
                "key_entities": ["Entity A"],
                "findings": ["Finding 1"],
            }
        )
        budget_provider = MagicMock()
        budget_provider.provider_name = "ollama_cloud_0"
        budget_provider.default_model = "gpt-oss:120b"
        budget_llm = MagicMock(spec=["providers"])
        budget_llm.providers = [budget_provider]
        generation_llm = MagicMock(spec=[])
        generation_llm.generate = AsyncMock(return_value=llm_result)
        mock_factory.get_llm_provider.side_effect = lambda **kwargs: (
            budget_llm if kwargs.get("with_failover") is False else generation_llm
        )

        # The provider factory must resolve its fallback before prompt budgeting.
        llm_config = SimpleNamespace(
            provider=None,
            model=None,
            temperature=0,
            seed=None,
        )
        with (
            patch("src.shared.kernel.runtime.get_settings"),
            patch(
                "src.core.generation.application.llm_steps.resolve_llm_step_config",
                return_value=llm_config,
            ),
        ):
            result = await summarizer.summarize_community("comm_0_123", "tenant_1")

        # Verify
        assert result["title"] == "Test Community"
        assert mock_neo4j.execute_write.called
        assert "SET c.title = $title" in mock_neo4j.execute_write.call_args[0][0]

    @pytest.mark.asyncio
    async def test_summarize_community_no_data(self, mock_neo4j, mock_factory):
        summarizer = CommunitySummarizer(mock_neo4j, mock_factory)
        mock_neo4j.execute_read.return_value = []

        with patch("src.shared.kernel.runtime.get_settings"):
            result = await summarizer.summarize_community("comm_0_empty", "tenant_1")
        assert result == {}

    @pytest.mark.asyncio
    async def test_summarize_community_failure_keeps_ready_summary_available(
        self, mock_neo4j, mock_factory
    ):
        summarizer = CommunitySummarizer(mock_neo4j, mock_factory)
        mock_neo4j.execute_read.side_effect = [
            [{"name": "Entity A", "type": "Person", "description": "Desc A"}],
            [],
            [],
            [],
        ]
        mock_factory.get_llm_provider.return_value.generate.side_effect = RuntimeError(
            "provider down"
        )

        llm_config = SimpleNamespace(
            provider="ollama_cloud",
            model="gpt-oss:120b",
            temperature=0,
            seed=None,
        )
        with (
            patch("src.shared.kernel.runtime.get_settings"),
            patch(
                "src.core.generation.application.llm_steps.resolve_llm_step_config",
                return_value=llm_config,
            ),
        ):
            result = await summarizer.summarize_community("comm_0_existing", "tenant_1")

        assert result == {}
        query = mock_neo4j.execute_write.await_args.args[0]
        assert "CASE WHEN c.summary IS NOT NULL" in query
        assert "c.status = 'ready'" in query

    @pytest.mark.asyncio
    async def test_summarize_community_keeps_oversized_entity_prompt_within_context(
        self, mock_neo4j, mock_factory
    ):
        model = "gpt-oss:120b"
        context_window = 131_072
        completion_tokens = 800
        provider_overhead_tokens = 512
        entities = [
            {
                "name": f"Entity {index}",
                "type": "Concept",
                "description": "description " * 500,
            }
            for index in range(300)
        ]
        mock_neo4j.execute_read.side_effect = [entities, [], [], []]
        llm_result = MagicMock()
        llm_result.text = json.dumps({"title": "Community", "summary": "Summary"})
        mock_factory.get_llm_provider.return_value.generate.return_value = llm_result
        llm_config = SimpleNamespace(
            provider="ollama_cloud",
            model=model,
            temperature=0,
            seed=None,
        )

        with (
            patch("src.shared.kernel.runtime.get_settings"),
            patch(
                "src.core.generation.application.llm_steps.resolve_llm_step_config",
                return_value=llm_config,
            ),
        ):
            await CommunitySummarizer(mock_neo4j, mock_factory).summarize_community(
                "comm_0_oversized", "tenant_1"
            )

        prompt = mock_factory.get_llm_provider.return_value.generate.await_args.kwargs["prompt"]
        total_tokens = (
            Tokenizer.count_tokens(f"{COMMUNITY_SUMMARY_SYSTEM_PROMPT}\n{prompt}", model)
            + completion_tokens
            + provider_overhead_tokens
        )
        assert total_tokens <= context_window

    def test_build_prompt_budgets_and_orders_oversized_relationships(self):
        summarizer = CommunitySummarizer(MagicMock(), MagicMock())
        relationships = [
            {
                "source": f"Source {index}",
                "target": f"Target {index}",
                "type": "RELATED_TO",
                "description": "relationship " * 300,
            }
            for index in range(2_000)
        ]
        prompt = summarizer._build_prompt(
            {
                "entities": [{"name": "Entity", "type": "Concept", "description": ""}],
                "relationships": relationships,
                "child_summaries": [],
                "text_units": [],
            },
            provider="ollama_cloud",
            model="gpt-oss:120b",
        )
        reversed_prompt = summarizer._build_prompt(
            {
                "entities": [{"name": "Entity", "type": "Concept", "description": ""}],
                "relationships": list(reversed(relationships)),
                "child_summaries": [],
                "text_units": [],
            },
            provider="ollama_cloud",
            model="gpt-oss:120b",
        )

        assert prompt == reversed_prompt
        assert (
            Tokenizer.count_tokens(f"{COMMUNITY_SUMMARY_SYSTEM_PROMPT}\n{prompt}", "gpt-oss:120b")
            + 1_312
            <= 131_072
        )

    def test_build_prompt_budgets_oversized_child_summaries_and_text_units(self):
        summarizer = CommunitySummarizer(MagicMock(), MagicMock())
        prompt = summarizer._build_prompt(
            {
                "entities": [],
                "relationships": [],
                "child_summaries": [
                    {"id": f"child-{index}", "title": f"Child {index}", "summary": "summary " * 500}
                    for index in range(1_000)
                ],
                "text_units": [
                    {"id": f"chunk-{index}", "content": "source " * 2_000} for index in range(3)
                ],
            },
            provider="ollama_cloud",
            model="gpt-oss:120b",
        )

        assert (
            Tokenizer.count_tokens(f"{COMMUNITY_SUMMARY_SYSTEM_PROMPT}\n{prompt}", "gpt-oss:120b")
            + 1_312
            <= 131_072
        )

    def test_build_prompt_degrades_instead_of_failing_on_huge_entity_set(self):
        summarizer = CommunitySummarizer(MagicMock(), MagicMock())
        entities = [
            {"name": f"Entity number {index} with a fairly long name", "type": "Concept"}
            for index in range(4_000)
        ]

        with patch.dict("os.environ", {"OLLAMA_NUM_CTX": "32768"}):
            prompt = summarizer._build_prompt(
                {
                    "entities": entities,
                    "relationships": [],
                    "child_summaries": [],
                    "text_units": [],
                },
                provider="ollama",
                model="llama3",
            )

        assert (
            Tokenizer.count_tokens(f"{COMMUNITY_SUMMARY_SYSTEM_PROMPT}\n{prompt}", "llama3") + 1_312
            <= 32_768
        )
        assert "Entity number 0 " in prompt

    def test_unknown_configured_provider_model_uses_default_context_budget(self):
        assert llm_context_window("ollama_cloud", "custom-model") == 32_768


class TestCommunityLifecycle:
    @pytest.mark.asyncio
    async def test_mark_stale_by_entities(self, mock_neo4j):
        manager = CommunityLifecycleManager(mock_neo4j)
        mock_neo4j.execute_write.return_value = [{"count": 2}]

        await manager.mark_stale_by_entities(["EntityA", "EntityB"], "tenant_1")

        assert mock_neo4j.execute_write.called
        query = mock_neo4j.execute_write.call_args[0][0]
        assert "WHERE e.name IN $names" in query

    @pytest.mark.asyncio
    async def test_cleanup_orphans(self, mock_neo4j):
        manager = CommunityLifecycleManager(mock_neo4j)
        mock_neo4j.execute_read.return_value = [{"name": "OrphanEntity"}]

        await manager.cleanup_orphans("tenant_1")

        assert mock_neo4j.execute_read.called
        query = mock_neo4j.execute_read.call_args[0][0]
        assert "RETURN e.name as name" in query
        # Check that it tried to create misc community and link orphans
        assert mock_neo4j.execute_write.call_count == 2
        link_query = mock_neo4j.execute_write.call_args[0][0]
        assert "e.name IN $entity_names" in link_query
