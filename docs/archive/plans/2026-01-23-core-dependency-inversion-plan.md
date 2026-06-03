# Core Dependency Inversion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove all `src.amber_platform` imports from `src/core` while keeping pipelines unchanged.

**Architecture:** Introduce a graph client provider in core and rely on shared kernel runtime settings. Replace platform imports with provider access and wire providers from composition root/worker startup.

**Tech Stack:** Python, FastAPI, Celery, Neo4j, MinIO, Pytest.

---

### Task 1: Graph Client Provider + Query Tool Usage

**Files:**
- Create: `src/core/graph/domain/ports/graph_client.py`
- Create: `src/core/graph/domain/ports/__init__.py`
- Modify: `src/core/tools/graph.py`
- Test: `tests/unit/test_graph_provider.py`

**Step 1: Write the failing test**

```python
import pytest

from src.core.tools.graph import query_graph
from src.core.graph.domain.ports.graph_client import set_graph_client

class FakeGraphClient:
    async def execute_read(self, query, parameters=None):
        return [{"id": "1"}, {"id": "2"}]

@pytest.mark.asyncio
async def test_query_graph_uses_injected_client():
    set_graph_client(FakeGraphClient())
    result = await query_graph("MATCH (n) RETURN n")
    assert "{'id': '1'}" in result

@pytest.mark.asyncio
async def test_query_graph_raises_when_not_configured():
    set_graph_client(None)
    with pytest.raises(RuntimeError, match="Graph client not configured"):
        await query_graph("MATCH (n) RETURN n")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_graph_provider.py::test_query_graph_uses_injected_client -v`
Expected: FAIL (provider not implemented / query_graph still uses platform)

**Step 3: Write minimal implementation**

```python
# src/core/graph/domain/ports/graph_client.py
from typing import Any, Protocol

class GraphClientPort(Protocol):
    async def execute_read(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ...

    async def execute_write(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ...

_graph_client: GraphClientPort | None = None


def set_graph_client(client: GraphClientPort | None) -> None:
    global _graph_client
    _graph_client = client


def get_graph_client() -> GraphClientPort:
    if _graph_client is None:
        raise RuntimeError("Graph client not configured. Call set_graph_client() at startup.")
    return _graph_client
```

```python
# src/core/tools/graph.py
from src.core.graph.domain.ports.graph_client import get_graph_client

# ...
results = await get_graph_client().execute_read(query, parameters)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_graph_provider.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/core/graph/domain/ports/graph_client.py src/core/graph/domain/ports/__init__.py src/core/tools/graph.py tests/unit/test_graph_provider.py
git commit -m "feat: add graph client provider"
```

---

### Task 2: Settings-backed Clients Use Shared Runtime Settings

**Files:**
- Modify: `src/core/graph/infrastructure/neo4j_client.py`
- Modify: `src/core/ingestion/infrastructure/storage/storage_client.py`
- Test: `tests/unit/test_settings_backed_clients.py`

**Step 1: Write the failing test**

```python
from src.shared.kernel.runtime import configure_settings, _reset_for_tests
from src.core.graph.infrastructure.neo4j_client import Neo4jClient
from src.core.ingestion.infrastructure.storage.storage_client import MinIOClient

class FakeDb:
    database_url = "postgresql+asyncpg://user:pass@localhost/db"
    pool_size = 5
    max_overflow = 10
    neo4j_uri = "bolt://localhost:7687"
    neo4j_user = "neo4j"
    neo4j_password = "pass"
    milvus_host = "localhost"
    milvus_port = 19530
    redis_url = "redis://localhost:6379/0"

class FakeMinio:
    host = "minio"
    port = 9000
    root_user = "minio"
    root_password = "minio"
    secure = False
    bucket_name = "amber"

class FakeSettings:
    app_name = "amber"
    debug = False
    log_level = "INFO"
    secret_key = "secret"
    db = FakeDb()
    minio = FakeMinio()
    openai_api_key = ""
    anthropic_api_key = ""
    ollama_base_url = ""
    default_llm_provider = None
    default_llm_model = None
    default_embedding_provider = None
    default_embedding_model = None
    embedding_dimensions = None


def setup_function():
    _reset_for_tests()


def test_neo4j_client_uses_shared_settings():
    configure_settings(FakeSettings())
    client = Neo4jClient()
    assert client.uri == FakeDb.neo4j_uri
    assert client.user == FakeDb.neo4j_user
    assert client.password == FakeDb.neo4j_password


def test_minio_client_uses_shared_settings():
    configure_settings(FakeSettings())
    client = MinIOClient()
    assert client.bucket_name == FakeMinio.bucket_name
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_settings_backed_clients.py::test_neo4j_client_uses_shared_settings -v`
Expected: FAIL (clients still use composition root settings)

**Step 3: Write minimal implementation**

```python
# src/core/graph/infrastructure/neo4j_client.py
from src.shared.kernel.runtime import get_settings

# ...
if uri is None or user is None or password is None:
    settings = get_settings()
    uri = uri or settings.db.neo4j_uri
    user = user or settings.db.neo4j_user
    password = password or settings.db.neo4j_password
```

```python
# src/core/ingestion/infrastructure/storage/storage_client.py
from src.shared.kernel.runtime import get_settings

# ...
if any(v is None for v in [host, port, access_key, secret_key, secure, bucket_name]):
    settings = get_settings()
    host = host if host is not None else settings.minio.host
    port = port if port is not None else settings.minio.port
    access_key = access_key if access_key is not None else settings.minio.root_user
    secret_key = secret_key if secret_key is not None else settings.minio.root_password
    secure = secure if secure is not None else settings.minio.secure
    bucket_name = bucket_name if bucket_name is not None else settings.minio.bucket_name
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_settings_backed_clients.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/core/graph/infrastructure/neo4j_client.py src/core/ingestion/infrastructure/storage/storage_client.py tests/unit/test_settings_backed_clients.py
git commit -m "refactor: read settings from shared runtime"
```

---

### Task 3: Remove Remaining Platform Imports in Core (Boundary Test)

**Files:**
- Create: `tests/unit/test_architecture_boundaries.py`
- Modify (platform imports):
  - `src/core/graph/application/context_writer.py`
  - `src/core/graph/application/deduplication.py`
  - `src/core/graph/application/setup.py`
  - `src/core/graph/application/writer.py`
  - `src/core/graph/application/enrichment.py`
  - `src/core/retrieval/application/query/structured_query.py`
- Modify (settings imports):
  - `src/core/generation/application/generation_service.py`
  - `src/core/generation/application/intelligence/classifier.py`
  - `src/core/generation/application/intelligence/document_summarizer.py`
  - `src/core/ingestion/infrastructure/extraction/graph_extractor.py`
  - `src/core/admin_ops/application/evaluation/ragas_service.py`
- Modify wiring:
  - `src/amber_platform/composition_root.py`
  - `src/workers/celery_app.py`

**Step 1: Write the failing test**

```python
from pathlib import Path


def test_no_amber_platform_imports_in_core():
    core_root = Path("src/core")
    offenders = []
    for path in core_root.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        content = path.read_text(encoding="utf-8")
        if "amber_platform" in content:
            offenders.append(str(path))

    assert offenders == [], f"core imports amber_platform: {offenders}"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_architecture_boundaries.py -v`
Expected: FAIL (current core imports include amber_platform)

**Step 3: Write minimal implementation**

Key changes:

```python
# graph modules (example)
from src.core.graph.domain.ports.graph_client import get_graph_client

# replace platform.neo4j_client.* with get_graph_client().*
```

```python
# settings usage
from src.shared.kernel.runtime import get_settings

# replace get_settings_lazy usage with get_settings()
```

```python
# src/amber_platform/composition_root.py
from src.core.graph.domain.ports.graph_client import set_graph_client

# inside PlatformRegistry.initialize after creating neo4j client
set_graph_client(self._neo4j_client)
```

```python
# src/workers/celery_app.py
# In worker_process_init, initialize platform so graph provider is set
from src.amber_platform.composition_root import platform
import asyncio
asyncio.run(platform.initialize())
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_architecture_boundaries.py -v`
Expected: PASS

Run: `pytest tests/unit/test_graph_provider.py tests/unit/test_settings_backed_clients.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/unit/test_architecture_boundaries.py src/core/graph/application/context_writer.py src/core/graph/application/deduplication.py src/core/graph/application/setup.py src/core/graph/application/writer.py src/core/graph/application/enrichment.py src/core/retrieval/application/query/structured_query.py src/core/generation/application/generation_service.py src/core/generation/application/intelligence/classifier.py src/core/generation/application/intelligence/document_summarizer.py src/core/ingestion/infrastructure/extraction/graph_extractor.py src/core/admin_ops/application/evaluation/ragas_service.py src/amber_platform/composition_root.py src/workers/celery_app.py
git commit -m "refactor: remove platform imports from core"
```

---

### Task 4: Verification

**Files:**
- None (commands only)

**Step 1: Run boundary check**

Run: `rg "amber_platform" src/core`
Expected: No matches

**Step 2: Run focused tests**

Run: `pytest tests/unit/test_graph_provider.py tests/unit/test_settings_backed_clients.py tests/unit/test_architecture_boundaries.py -v`
Expected: PASS

**Step 3: Commit (if needed)**

```bash
# Only if verification required additional fixes
# git add ...
# git commit -m "fix: boundary verification"
```
