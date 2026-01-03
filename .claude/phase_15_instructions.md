# Phase 15: Stale Job Recovery & Structured KG Router

## Overview
This phase implements two production-ready features:
1. **Stale Job Recovery** - Automatic recovery of stuck documents on worker restart
2. **Structured KG Router** - Direct Cypher execution for list/count/aggregate queries

---

## Feature 1: Stale Job Recovery

### Context
When a Celery worker crashes or restarts during document processing, documents can get stuck in intermediate states (`extracting`, `classifying`, `chunking`). This feature automatically detects and recovers these stale documents.

### Implementation Requirements

#### File: `src/workers/recovery.py` (NEW)
```python
"""
Stale Document Recovery
=======================

Handles recovery of documents stuck in processing states after worker restart.
"""

async def recover_stale_documents() -> dict:
    """
    Find and recover documents stuck in processing states.
    
    Logic:
    1. Query documents with status in ('extracting', 'classifying', 'chunking')
    2. For each document:
       - If has chunks and status is 'chunking' -> mark as 'ready'
       - Otherwise -> mark as 'failed' with error message
    3. Publish status updates via Redis for UI consistency
    
    Returns:
        dict: {"recovered": int, "failed": int, "total": int}
    """
```

#### File: `src/workers/celery_app.py` (MODIFY)
- Add `worker_ready` signal handler
- Call `recover_stale_documents()` on worker startup
- Log recovery results

### Key Patterns
- Use `AsyncSession` from SQLAlchemy for DB queries
- Check for existing chunks before marking as failed
- Use Redis pub/sub for status updates (existing pattern in `tasks.py`)

---

## Feature 2: Structured KG Router

### Context
Queries like "List all documents" or "How many entities are there?" don't need RAG. They can be answered directly with Cypher, saving LLM costs and providing instant responses.

### Implementation Requirements

#### File: `src/core/query/structured_query.py` (NEW)
```python
"""
Structured Query Executor
=========================

Detects and executes structured queries (list, count, aggregate) directly via Cypher.
"""

from enum import Enum
from dataclasses import dataclass
import re

class StructuredQueryType(str, Enum):
    LIST_DOCUMENTS = "list_documents"
    COUNT_DOCUMENTS = "count_documents"
    LIST_ENTITIES = "list_entities"
    COUNT_ENTITIES = "count_entities"
    LIST_RELATIONSHIPS = "list_relationships"
    NOT_STRUCTURED = "not_structured"

@dataclass
class StructuredIntent:
    query_type: StructuredQueryType
    filters: dict = None  # Optional filters like document_id, entity_type
    limit: int = 50

class StructuredKGDetector:
    """
    Detects if a query is suitable for direct Cypher execution.
    Uses pattern matching first, LLM fallback for ambiguous cases.
    """
    
    # Regex patterns for common structured queries
    PATTERNS = [
        (r"^(list|show|get)\s+(all\s+)?documents?(\s+about)?", StructuredQueryType.LIST_DOCUMENTS),
        (r"^how many\s+documents?", StructuredQueryType.COUNT_DOCUMENTS),
        (r"^(list|show|get)\s+(all\s+)?entities?", StructuredQueryType.LIST_ENTITIES),
        (r"^how many\s+entities?", StructuredQueryType.COUNT_ENTITIES),
        (r"^(list|show|get)\s+(all\s+)?relationships?", StructuredQueryType.LIST_RELATIONSHIPS),
    ]
    
    def detect(self, query: str) -> StructuredIntent:
        """Detect if query is structured and extract intent."""
        
    async def execute(self, intent: StructuredIntent, tenant_id: str) -> dict | None:
        """Execute the structured query and return results."""

class CypherGenerator:
    """Generates safe, parameterized Cypher queries."""
    
    TEMPLATES = {
        StructuredQueryType.LIST_DOCUMENTS: """
            MATCH (d:Document {tenant_id: $tenant_id})
            RETURN d.id as id, d.filename as filename, d.status as status, 
                   d.created_at as created_at
            ORDER BY d.created_at DESC
            LIMIT $limit
        """,
        StructuredQueryType.COUNT_DOCUMENTS: """
            MATCH (d:Document {tenant_id: $tenant_id})
            RETURN count(d) as count
        """,
        # ... more templates
    }
```

#### File: `src/api/schemas/query.py` (MODIFY)
- Add `STRUCTURED = "structured"` to `SearchMode` enum

#### File: `src/core/query/router.py` (MODIFY)
- Add structured query keywords to heuristics
- Add early detection before LLM routing

#### File: `src/api/routes/query.py` (MODIFY)
- Import `StructuredKGDetector`
- Add early check before RAG pipeline:
  ```python
  # Check for structured query first
  detector = StructuredKGDetector()
  intent = detector.detect(request.query)
  if intent.query_type != StructuredQueryType.NOT_STRUCTURED:
      result = await detector.execute(intent, tenant_id)
      if result:
          return StructuredQueryResponse(data=result, ...)
  ```

### Response Format
For structured queries, return tabular data instead of prose:
```json
{
  "type": "structured",
  "query_type": "list_documents",
  "data": [
    {"id": "doc_123", "filename": "report.pdf", "status": "ready"},
    {"id": "doc_456", "filename": "analysis.docx", "status": "ready"}
  ],
  "count": 2,
  "timing": {"total_ms": 45}
}
```

---

## Testing Requirements

### Unit Tests
- `tests/unit/test_recovery.py` - Test stale document detection and recovery
- `tests/unit/test_structured_query.py` - Test pattern matching and Cypher generation

### Integration Tests
- Verify recovery works after simulated worker crash
- Verify structured queries return correct data from Neo4j

---

## Key Files Reference

| Component       | File Path                        |
| --------------- | -------------------------------- |
| Celery App      | `src/workers/celery_app.py`      |
| Tasks           | `src/workers/tasks.py`           |
| Document Status | `src/core/state/machine.py`      |
| Neo4j Client    | `src/core/graph/neo4j_client.py` |
| Query Router    | `src/core/query/router.py`       |
| Query Schemas   | `src/api/schemas/query.py`       |
| Query API       | `src/api/routes/query.py`        |

---

## Implementation Order
1. **Stale Job Recovery** (simpler, isolated to worker)
2. **Structured KG Router** (touches query pipeline)

## Dependencies
- No new Python packages required
- Uses existing: `neo4j`, `sqlalchemy`, `celery`, `redis`
