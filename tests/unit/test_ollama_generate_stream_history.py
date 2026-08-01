"""
Ollama Provider - generate_stream history support
==================================================

`generate_stream` must honor the `history` kwarg the same way the OpenAI
provider does: system prompt first, then the history messages in order,
then the current user prompt last. Previously `history` was silently
dropped via `kwargs.pop("history", None)`.
"""

from contextlib import asynccontextmanager

import pytest

from src.core.generation.infrastructure.providers.base import ProviderConfig
from src.core.generation.infrastructure.providers.ollama import OllamaLLMProvider
from src.shared.model_registry import llm_context_window


class _NoOpLimiter:
    """A no-op capacity limiter for unit tests (no Redis needed)."""

    @asynccontextmanager
    async def hold(self, *, work_class="chat"):
        yield


class _FakeStream:
    """Minimal async-iterable fake matching the OpenAI streaming shape."""

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class _FakeChatCompletions:
    def __init__(self):
        self.last_call_kwargs: dict | None = None

    async def create(self, **kwargs):
        self.last_call_kwargs = kwargs
        return _FakeStream()


class _FakeChat:
    def __init__(self):
        self.completions = _FakeChatCompletions()


class _FakeClient:
    def __init__(self):
        self.chat = _FakeChat()


@pytest.fixture(autouse=True)
def mock_capacity_limiter(monkeypatch):
    """Bypass the Redis-backed capacity limiter in unit tests."""
    monkeypatch.setattr(
        "src.core.generation.infrastructure.providers.ollama.get_ollama_capacity_limiter",
        lambda: _NoOpLimiter(),
    )


@pytest.fixture
def provider():
    config = ProviderConfig(base_url="http://test-ollama:11434/v1")
    p = OllamaLLMProvider(config)
    fake_client = _FakeClient()
    p._client = fake_client
    return p, fake_client


@pytest.mark.asyncio
async def test_generate_stream_with_history_orders_messages(provider):
    """system_prompt + 4 history messages + current prompt, in that order."""
    p, fake_client = provider

    history = [
        {"role": "user", "content": "turn 1 user"},
        {"role": "assistant", "content": "turn 1 assistant"},
        {"role": "user", "content": "turn 2 user"},
        {"role": "assistant", "content": "turn 2 assistant"},
    ]

    stream = p.generate_stream(
        prompt="current question",
        system_prompt="You are a helpful assistant.",
        history=history,
    )
    async for _ in stream:
        pass

    sent_messages = fake_client.chat.completions.last_call_kwargs["messages"]

    assert sent_messages == [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "turn 1 user"},
        {"role": "assistant", "content": "turn 1 assistant"},
        {"role": "user", "content": "turn 2 user"},
        {"role": "assistant", "content": "turn 2 assistant"},
        {"role": "user", "content": "current question"},
    ]


@pytest.mark.asyncio
async def test_generate_stream_without_history_is_unchanged(provider):
    """history=None must produce the same payload as before (no regression)."""
    p, fake_client = provider

    stream = p.generate_stream(
        prompt="current question",
        system_prompt="You are a helpful assistant.",
        history=None,
    )
    async for _ in stream:
        pass

    sent_messages = fake_client.chat.completions.last_call_kwargs["messages"]

    assert sent_messages == [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "current question"},
    ]

    # history must never leak into the provider payload as a stray kwarg
    assert "history" not in fake_client.chat.completions.last_call_kwargs


@pytest.mark.asyncio
async def test_num_ctx_matches_the_budget_used_for_proxied_cloud_models(provider, monkeypatch):
    """Prompt budgeting grants cloud models their full window, so the daemon must be
    told the same num_ctx instead of the local 32768 default."""
    p, fake_client = provider
    monkeypatch.setenv("OLLAMA_NUM_CTX", "32768")

    stream = p.generate_stream(prompt="hi", model="gemma4:31b-cloud")
    async for _ in stream:
        pass

    options = fake_client.chat.completions.last_call_kwargs["extra_body"]["options"]
    assert options["num_ctx"] == llm_context_window("ollama", "gemma4:31b-cloud")
    assert options["num_ctx"] == 131_072


@pytest.mark.asyncio
async def test_num_ctx_stays_local_for_local_models(provider, monkeypatch):
    p, fake_client = provider
    monkeypatch.setenv("OLLAMA_NUM_CTX", "16384")

    stream = p.generate_stream(prompt="hi", model="llama3")
    async for _ in stream:
        pass

    options = fake_client.chat.completions.last_call_kwargs["extra_body"]["options"]
    assert options["num_ctx"] == 16_384
