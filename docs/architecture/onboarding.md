# Architecture Onboarding Guide

Welcome to the Amber backend architecture. This guide helps contributors understand the codebase structure and development patterns.

## Core Principles

1. **Clean Architecture**: Dependencies flow inward (delivery → application → domain)
2. **Bounded Contexts**: Six contexts own their domain logic (ingestion, retrieval, graph, generation, admin_ops, tenants)
3. **Dependency Inversion**: Core depends on abstractions, not frameworks
4. **Explicit Wiring**: All dependencies are wired in the composition root (`src/amber_platform/composition_root.py`)

## Project Structure

```
src/
├── api/              # Delivery adapter (FastAPI routes, middleware)
├── workers/          # Delivery adapter (Celery tasks)
├── core/             # Business logic (bounded contexts)
│   ├── ingestion/    # Document registration, extraction, chunking
│   ├── retrieval/    # Query routing, vector/graph retrieval
│   ├── graph/        # Entity extraction, community detection
│   ├── generation/   # Prompt orchestration, answer assembly
│   ├── admin_ops/    # Tuning, evaluation, maintenance
│   └── tenants/      # Tenant config, access control
├── shared/
│   └── kernel/       # Shared IDs, errors, interfaces
└── amber_platform/
    └── composition_root.py  # Dependency wiring
```

## Dependency Rules

| Layer                 | May Import                                |
| --------------------- | ----------------------------------------- |
| Domain                | `shared/kernel`, own domain modules only  |
| Application           | Domain + `shared/kernel`                  |
| Infrastructure        | Application + Domain + external libraries |
| Delivery (API/Worker) | Application ports + composition root (`src/amber_platform`) |

### Forbidden Imports

- ❌ `src.core` must NOT import `src.api` or `src.workers`
- ❌ `src.core` must NOT import `src.amber_platform` (composition root)
- ❌ No cross-context repository access
- ❌ No framework-specific imports in domain/application layers

### Architecture Contracts (lint-imports)

These rules are enforced by `poetry run lint-imports`:

- Domain layer independence
- Application → Infrastructure isolation
- Core → API decoupling
- Core → Platform decoupling
- Shared Kernel independence

### Fixing lint-imports failures

1. Identify the forbidden import from the lint output.
2. Replace the import with a port from the domain/application layer.
3. Wire the concrete implementation in `src/amber_platform/composition_root.py`.

Common offenders and fixes:
- Replace direct provider imports in application code with `ProviderFactoryPort` or `get_llm_provider`.
- Swap any tracing import to `src/shared/kernel/observability`.
- Use graph/document/embedding ports instead of infrastructure clients.

## Key Patterns

### 1. Unit of Work (UoW)

Transaction boundaries are managed via UoW:

```python
async with uow_factory(tenant_id, is_super_admin=False) as uow:
    # All DB operations within transaction
    repo = DocumentRepository(uow.session)
    await repo.save(document)
    # Auto-commit on success, rollback on exception
```

### 2. Application Services (Use Cases)

Route handlers call use cases, not repositories directly:

```python
# Good ✅
@router.post("/documents")
async def upload(request: Request):
    result = await ingest_document_use_case(tenant_id, payload)
    return result

# Bad ❌
@router.post("/documents")
async def upload(db: AsyncSession = Depends(get_db)):
    # Multi-step business logic in route handler
    ...
```

### 3. Ports and Adapters

Core defines interfaces (ports), infrastructure provides implementations:

```python
# Port (in application layer)
class StoragePort(Protocol):
    async def upload(self, path: str, data: bytes) -> str: ...

# Adapter (in infrastructure layer)
class MinIOStorageAdapter:
    def __init__(self, client: MinIOClient):
        self._client = client
    
    async def upload(self, path: str, data: bytes) -> str:
        return await self._client.upload_file(path, data)
```

## Testing Strategy

| Layer          | Test Type              | What to Test                            |
| -------------- | ---------------------- | --------------------------------------- |
| Domain         | Unit                   | Entity rules, value objects, invariants |
| Application    | Unit + Contract        | Use cases, port contracts               |
| Infrastructure | Contract + Integration | Adapter behavior, external systems      |
| Delivery       | Integration            | API routes, request/response mapping    |

## Common Tasks

### Adding a New Feature

1. Identify the bounded context
2. Add domain entities/value objects if needed
3. Create application service (use case)
4. Add port interfaces for external dependencies
5. Implement infrastructure adapters
6. Wire in composition root
7. Add route handler (thin, calls use case)

### Debugging Import Violations

Run import-linter to check boundaries:

```bash
poetry run lint-imports
```

## Resources

- [Architecture Proposal](internal/architecture_update/architecture-proposal.md)
- [Migration Tracker](internal/architecture_update/migration-tracker.md)
- [Dependency Graph Snapshot](internal/architecture_update/dependency-graph-snapshot.md)
- [ADR Template](adr/template.md)
