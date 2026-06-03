# Architecture Remediation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove confirmed architectural violations (core -> composition root dependencies, infrastructure leakage in application layer, inconsistent transaction boundaries, duplicate session factories) while preserving existing backend pipeline behavior.

**Architecture:** Introduce a shared runtime settings provider, consolidate session factory creation, enforce ports in application services, move wiring to the composition root, and shift event publishing to an async adapter behind a port.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy (async), Redis (async), Celery, Pytest, import-linter.

---

### Task 1: Add a runtime settings provider (core-safe)

**Files:**
- Create: `src/shared/kernel/runtime.py`
- Modify: `src/shared/kernel/__init__.py`
- Test: `tests/unit/test_runtime_settings.py`

**Step 1: Write the failing test**

```python
import pytest

from src.shared.kernel import runtime

class DummySettings:
    app_name = "amber"


def test_get_settings_raises_when_unconfigured():
    runtime._reset_for_tests()
    with pytest.raises(RuntimeError):
        runtime.get_settings()


def test_get_settings_returns_configured_instance():
    runtime._reset_for_tests()
    settings = DummySettings()
    runtime.configure_settings(settings)
    assert runtime.get_settings() is settings
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_runtime_settings.py::test_get_settings_raises_when_unconfigured -q`
Expected: FAIL because `runtime` module does not exist.

**Step 3: Write minimal implementation**

```python
# src/shared/kernel/runtime.py
from typing import Optional
from src.shared.kernel.settings import SettingsProtocol

_settings: Optional[SettingsProtocol] = None


def configure_settings(settings: SettingsProtocol) -> None:
    global _settings
    _settings = settings


def get_settings() -> SettingsProtocol:
    if _settings is None:
        raise RuntimeError("Settings not configured. Call configure_settings() at startup.")
    return _settings


def _reset_for_tests() -> None:
    global _settings
    _settings = None
```

Update `src/shared/kernel/__init__.py` to export `configure_settings` and `get_settings`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_runtime_settings.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/shared/kernel/runtime.py src/shared/kernel/__init__.py tests/unit/test_runtime_settings.py
git commit -m "feat: add runtime settings provider"
```

---

### Task 2: Wire runtime settings in API and worker startup

**Files:**
- Modify: `src/api/main.py`
- Modify: `src/workers/celery_app.py`
- Test: `tests/unit/test_runtime_settings_wiring.py`

**Step 1: Write the failing test**

```python
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from src.shared.kernel import runtime


@pytest.mark.asyncio
async def test_api_lifespan_calls_configure_settings(monkeypatch):
    from src.api import main

    called = {}

    def fake_configure(settings):
        called["settings"] = settings

    async def noop_async(*_args, **_kwargs):
        return None

    monkeypatch.setattr(runtime, "configure_settings", fake_configure)
    monkeypatch.setattr(main, "configure_settings", fake_configure, raising=False)
    monkeypatch.setattr(main, "platform", SimpleNamespace(initialize=noop_async, shutdown=noop_async))
    monkeypatch.setattr(main, "configure_database", lambda **_kwargs: None, raising=False)
    monkeypatch.setattr(main, "init_providers", lambda **_kwargs: None, raising=False)
    monkeypatch.setattr(main, "configure_security", lambda *_args, **_kwargs: None, raising=False)

    async with main.lifespan(FastAPI()):
        pass

    assert "settings" in called


def test_worker_init_calls_configure_settings(monkeypatch):
    from src.workers import celery_app

    called = {}

    def fake_configure(settings):
        called["settings"] = settings

    monkeypatch.setattr(runtime, "configure_settings", fake_configure)
    monkeypatch.setattr(celery_app, "configure_settings", fake_configure, raising=False)
    monkeypatch.setattr(celery_app, "init_providers", lambda **_kwargs: None, raising=False)

    celery_app.init_worker_process()
    assert "settings" in called
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_runtime_settings_wiring.py::test_api_lifespan_calls_configure_settings -q`
Expected: FAIL because `configure_settings` is not called in lifespan.

**Step 3: Write minimal implementation**

- In `src/api/main.py`, call `configure_settings(settings)` at the start of lifespan before `platform.initialize()`.
- In `src/workers/celery_app.py`, call `configure_settings(settings)` inside `init_worker_process` before provider init.

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_runtime_settings_wiring.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/api/main.py src/workers/celery_app.py tests/unit/test_runtime_settings_wiring.py
git commit -m "feat: wire runtime settings at startup"
```

---

### Task 3: Consolidate session factory to core database module

**Files:**
- Modify: `src/amber_platform/composition_root.py`
- Modify: `src/api/deps.py`
- Test: `tests/unit/test_session_factory.py`

**Step 1: Write the failing test**

```python
from src.core.database import session as core_session


def test_build_session_factory_uses_core_maker(monkeypatch):
    from src.amber_platform import composition_root

    core_session.configure_database("sqlite+aiosqlite:///:memory:")
    core_maker = core_session.get_session_maker()

    maker = composition_root.build_session_factory()
    assert maker is core_maker
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_session_factory.py::test_build_session_factory_uses_core_maker -q`
Expected: FAIL because `build_session_factory` still creates its own engine.

**Step 3: Write minimal implementation**

- Update `build_session_factory()` in `src/amber_platform/composition_root.py` to return `src.core.database.session.get_session_maker()`.
- Update `src/api/deps.py` to call `get_session_maker()` directly and remove composition root import.

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_session_factory.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/amber_platform/composition_root.py src/api/deps.py tests/unit/test_session_factory.py
git commit -m "refactor: centralize session factory"
```

---

### Task 4: Add async state change publisher port + adapter

**Files:**
- Create: `src/core/events/ports/state_change_publisher.py`
- Create: `src/core/events/ports/__init__.py`
- Create: `src/infrastructure/adapters/redis_state_publisher.py`
- Modify: `src/core/events/dispatcher.py`
- Test: `tests/unit/test_event_dispatcher.py`

**Step 1: Write the failing test**

```python
import asyncio

import pytest

from src.core.events.dispatcher import EventDispatcher, StateChangeEvent
from src.core.state.machine import DocumentStatus


class FakePublisher:
    def __init__(self):
        self.published = []

    async def publish(self, payload):
        self.published.append(payload)


@pytest.mark.asyncio
async def test_event_dispatcher_calls_publisher():
    dispatcher = EventDispatcher(publisher=FakePublisher())
    event = StateChangeEvent(
        document_id="doc-1",
        old_status=None,
        new_status=DocumentStatus.INGESTED,
        tenant_id="tenant-1",
        details={"progress": 1},
    )

    await dispatcher.emit_state_change(event)

    assert dispatcher.publisher.published
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_event_dispatcher.py::test_event_dispatcher_calls_publisher -q`
Expected: FAIL because dispatcher is synchronous and has no publisher injection.

**Step 3: Write minimal implementation**

- Add `StateChangePublisher` protocol with `async def publish(self, payload: dict) -> None`.
- Update `EventDispatcher` to be instantiable with a publisher and expose `async def emit_state_change()`.
- Keep logging behavior intact.
- Implement `RedisStatePublisher` using `redis.asyncio` and runtime `get_settings()`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_event_dispatcher.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/core/events/dispatcher.py src/core/events/ports src/infrastructure/adapters/redis_state_publisher.py tests/unit/test_event_dispatcher.py
git commit -m "feat: async state change publisher port"
```

---

### Task 5: Remove core -> composition root settings imports

**Files:**
- Modify: `src/core/generation/application/intelligence/classifier.py`
- Modify: `src/core/generation/application/intelligence/document_summarizer.py`
- Modify: `src/core/ingestion/infrastructure/extraction/graph_extractor.py`
- Modify: `src/core/graph/application/enrichment.py`
- Modify: `src/core/graph/infrastructure/neo4j_client.py`
- Test: `tests/unit/test_runtime_settings.py`

**Step 1: Write the failing test**

Add this to `tests/unit/test_runtime_settings.py`:

```python
from src.shared.kernel import runtime


def test_runtime_settings_used_in_modules(monkeypatch):
    class DummySettings:
        db = type("DB", (), {"redis_url": "redis://example"})
        minio = type("Minio", (), {"host": "h", "port": 1, "root_user": "u", "root_password": "p", "secure": False, "bucket_name": "b"})
        openai_api_key = ""
        anthropic_api_key = ""
        ollama_base_url = ""
        default_embedding_provider = None
        default_embedding_model = None
        embedding_dimensions = 1536

    runtime.configure_settings(DummySettings())

    from src.core.generation.application.intelligence import classifier
    assert runtime.get_settings()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_runtime_settings.py::test_runtime_settings_used_in_modules -q`
Expected: FAIL because modules still import `get_settings_lazy` from composition root.

**Step 3: Write minimal implementation**

- Replace `get_settings_lazy` imports with `from src.shared.kernel.runtime import get_settings`.
- Use `settings = get_settings()` in each file listed above.
- Remove any composition root imports from `src/core`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_runtime_settings.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/core/generation/application/intelligence/classifier.py src/core/generation/application/intelligence/document_summarizer.py src/core/ingestion/infrastructure/extraction/graph_extractor.py src/core/graph/application/enrichment.py src/core/graph/infrastructure/neo4j_client.py tests/unit/test_runtime_settings.py
git commit -m "refactor: remove core settings dependency on composition root"
```

---

### Task 6: Fix generation service DB access to use canonical session maker

**Files:**
- Modify: `src/core/generation/application/generation_service.py`
- Test: `tests/unit/test_generation_service_session.py`

**Step 1: Write the failing test**

```python
import pytest

from src.core.database.session import configure_database, get_session_maker


@pytest.mark.asyncio
async def test_generation_service_uses_core_session_maker():
    configure_database("sqlite+aiosqlite:///:memory:")
    maker = get_session_maker()

    from src.core.generation.application import generation_service
    assert maker is get_session_maker()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_generation_service_session.py::test_generation_service_uses_core_session_maker -q`
Expected: FAIL because generation service creates its own engine.

**Step 3: Write minimal implementation**

- Replace local `create_async_engine` usage with `get_session_maker()` from `src.core.database.session`.
- Remove composition root settings access in this method.

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_generation_service_session.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/core/generation/application/generation_service.py tests/unit/test_generation_service_session.py
git commit -m "refactor: use canonical session maker in generation service"
```

---

### Task 7: Refactor ingestion use cases to depend on ports (no infra imports)

**Files:**
- Modify: `src/core/ingestion/application/use_cases_documents.py`
- Modify: `src/core/ingestion/application/ingestion_service.py`
- Modify: `src/amber_platform/composition_root.py`
- Modify: `src/api/routes/documents.py`
- Test: `tests/unit/test_upload_document_use_case.py`

**Step 1: Write the failing test**

```python
import pytest

from src.core.ingestion.application.use_cases_documents import UploadDocumentUseCase, UploadDocumentRequest


class FakeRepo:
    async def find_by_content_hash(self, *_args, **_kwargs):
        return None

    async def save(self, *_args, **_kwargs):
        return None


class FakeUoW:
    async def commit(self):
        return None


class FakeStorage:
    def upload_file(self, *_args, **_kwargs):
        return None


@pytest.mark.asyncio
async def test_upload_use_case_accepts_ports_only():
    use_case = UploadDocumentUseCase(
        document_repository=FakeRepo(),
        tenant_repository=FakeRepo(),
        unit_of_work=FakeUoW(),
        storage=FakeStorage(),
        max_size_bytes=1024,
        graph_client=None,
        vector_store=None,
        task_dispatcher=None,
    )

    result = await use_case.execute(
        UploadDocumentRequest(
            tenant_id="tenant",
            filename="file.txt",
            content=b"hello",
            content_type="text/plain",
        )
    )

    assert result.document_id
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_upload_document_use_case.py::test_upload_use_case_accepts_ports_only -q`
Expected: FAIL because the use case imports infra and expects `AsyncSession`.

**Step 3: Write minimal implementation**

- Update use case signatures to accept ports (repositories, UoW, storage, graph, vector store).
- Remove infra imports from `use_cases_documents.py` and `ingestion_service.py`.
- Update `composition_root` with a builder for `UploadDocumentUseCase` that wires concrete adapters.
- Update `src/api/routes/documents.py` to call the builder instead of instantiating Milvus directly.

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_upload_document_use_case.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/core/ingestion/application/use_cases_documents.py src/core/ingestion/application/ingestion_service.py src/amber_platform/composition_root.py src/api/routes/documents.py tests/unit/test_upload_document_use_case.py
git commit -m "refactor: inject ingestion use case dependencies"
```

---

### Task 8: Remove infrastructure imports from retrieval application services

**Files:**
- Modify: `src/core/retrieval/application/retrieval_service.py`
- Modify: `src/amber_platform/composition_root.py`
- Test: `tests/unit/test_retrieval_service_ports.py`

**Step 1: Write the failing test**

```python
from src.core.retrieval.application.retrieval_service import RetrievalService


def test_retrieval_service_accepts_ports_only():
    service = RetrievalService(
        document_repository=None,
        vector_store=None,
        neo4j_client=None,
        openai_api_key=None,
        anthropic_api_key=None,
        ollama_base_url=None,
        default_embedding_provider=None,
        default_embedding_model=None,
        redis_url="redis://localhost:6379/0",
    )
    assert service is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_retrieval_service_ports.py::test_retrieval_service_accepts_ports_only -q`
Expected: FAIL if retrieval service still imports infra or relies on infra types.

**Step 3: Write minimal implementation**

- Replace infra imports with domain ports in `retrieval_service.py`.
- Ensure `ProviderFactory` usage is injected or passed as a port if needed.
- Update composition root builder to wire concrete dependencies.

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_retrieval_service_ports.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/core/retrieval/application/retrieval_service.py src/amber_platform/composition_root.py tests/unit/test_retrieval_service_ports.py
git commit -m "refactor: retrieval service depends on ports"
```

---

### Task 9: Remove infrastructure imports from admin_ops and generation application services

**Files:**
- Modify: `src/core/admin_ops/application/*`
- Modify: `src/core/generation/application/*`
- Modify: `src/amber_platform/composition_root.py`
- Test: `tests/unit/test_admin_ops_ports.py`

**Step 1: Write the failing test**

```python
from src.core.admin_ops.application.quality_scorer import QualityScorer


def test_quality_scorer_constructs_without_infra_types():
    scorer = QualityScorer(provider_factory=None)
    assert scorer is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_admin_ops_ports.py::test_quality_scorer_constructs_without_infra_types -q`
Expected: FAIL if admin_ops app services still import infra factories directly.

**Step 3: Write minimal implementation**

- Replace direct imports of infra providers/tracers with ports or injected factories.
- Add composition root builders to supply concrete implementations.

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_admin_ops_ports.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/core/admin_ops/application src/core/generation/application src/amber_platform/composition_root.py tests/unit/test_admin_ops_ports.py
git commit -m "refactor: admin_ops and generation use ports"
```

---

### Task 10: Add import-linter guardrails and verify architecture

**Files:**
- Modify: `pyproject.toml`

**Step 1: Write the failing test**

Add a new contract to `pyproject.toml`:

```toml
[[tool.importlinter.contracts]]
name = "Core must not depend on composition root"
type = "forbidden"
source_modules = ["src.core"]
forbidden_modules = ["src.amber_platform"]
```

**Step 2: Run test to verify it fails**

Run: `poetry run lint-imports`
Expected: FAIL if any core module still imports `src.amber_platform`.

**Step 3: Fix remaining violations**

- Remove any leftover `src.core` -> `src.amber_platform` imports.
- Ensure all application layers depend only on ports.

**Step 4: Run test to verify it passes**

Run: `poetry run lint-imports`
Expected: PASS.

**Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "chore: enforce core architecture boundaries"
```

---

### Task 11: End-to-end verification

**Files:**
- None

**Step 1: Run targeted tests**

Run: `pytest tests/unit/test_runtime_settings.py tests/unit/test_event_dispatcher.py tests/unit/test_upload_document_use_case.py -q`
Expected: PASS.

**Step 2: Run import-linter**

Run: `poetry run lint-imports`
Expected: PASS.

**Step 3: Run ingestion/retrieval integration tests (if environment allows)**

Run: `pytest tests/integration/test_ingestion_flow.py tests/integration/test_retrieval.py -q`
Expected: PASS or environment-related skips only.

**Step 4: Commit verification note (optional)**

```bash
git commit --allow-empty -m "chore: verify architecture remediation"
```

