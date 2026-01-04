# Testing Guide for Amber RAG System

This document describes how to test the complete ingestion pipeline and verify that all components are working correctly.

## Quick Test

Run this single command to verify everything is working:

```bash
./tests/integration/test_pipeline_manual.sh
```

This will test the complete pipeline from upload to retrieval in ~30 seconds.

## What Gets Tested

The integration test verifies:

1. ✅ **Document Upload** - File upload to MinIO via API
2. ✅ **Text Extraction** - PDF parsing with pymupdf4llm
3. ✅ **Classification** - Domain classification (general, legal, etc.)
4. ✅ **Chunking** - Semantic chunking into segments
5. ✅ **Embeddings** - Vector generation via OpenAI
6. ✅ **Entity Extraction** - Named entities (people, companies, etc.)
7. ✅ **Relationship Extraction** - Entity relationships
8. ✅ **Neo4j Sync** - Knowledge graph creation
9. ✅ **Milvus Storage** - Vector embeddings storage
10. ✅ **Query Retrieval** - RAG query functionality

## Test Output Example

```
========================================
  Ingestion Pipeline Integration Test
========================================

1. Creating test PDF... ✓
2. Uploading document... ✓ (ID: doc_f57ac293ab2347cc)
3. Waiting for processing... ✓ (24s)
4. Verifying chunks... ✓ (1 chunks, all embedded)
5. Verifying entities... ✓ (8 entities: Anthropic, Claude, Dario Amodei...)
6. Verifying relationships... ✓ (7 relationships)
7. Verifying Neo4j graph... ✓ (Graph structure verified)
8. Testing retrieval... ✓
   Answer preview: Anthropic is an AI safety company...

========================================
  All Tests Passed!
========================================

Document ID: doc_f57ac293ab2347cc
Chunks: 1
Entities: 8
Relationships: 7
```

## Troubleshooting

### Test Fails at Upload

**Problem:** `curl: (7) Failed to connect to localhost port 8000`

**Solution:**
```bash
# Check if API is running
docker compose ps api

# If not running, start services
docker compose up -d

# Check health
curl http://localhost:8000/health
```

### Test Fails at Processing

**Problem:** Document stays in "extracting" or "chunking" state

**Solution:**
```bash
# Check worker logs
docker compose logs worker --tail=50

# Restart worker if needed
docker compose restart worker
```

### No Entities Extracted

**Problem:** Step 5 shows 0 entities

**Possible Causes:**
- Document content is too simple or short
- LLM API key not configured
- Graph extractor not working

**Solution:**
```bash
# Check OpenAI API key
grep OPENAI_API_KEY .env

# Check worker logs for extraction errors
docker compose logs worker | grep -i "entity\|extract"
```

### Neo4j Verification Fails

**Problem:** Step 7 fails or shows partial data

**Solution:**
```bash
# Check Neo4j is running
docker compose ps neo4j

# Verify connection
docker compose exec neo4j cypher-shell -u neo4j -p graphrag123

# Inside Neo4j shell, check for recent documents:
MATCH (d:Document) RETURN d.id, d.created_at ORDER BY d.created_at DESC LIMIT 5;
```

### Milvus Verification Fails

**Problem:** Vector count mismatch

**Solution:**
```bash
# Check Milvus status
docker compose ps milvus

# Restart if needed
docker compose restart milvus

# Wait 10 seconds for initialization
sleep 10
```

## Running Tests in CI/CD

### GitHub Actions Example

```yaml
name: Integration Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Start services
        run: docker compose up -d

      - name: Wait for services
        run: sleep 30

      - name: Run integration tests
        run: ./tests/integration/test_pipeline_manual.sh
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}

      - name: Stop services
        if: always()
        run: docker compose down
```

## Manual Verification

If automated tests fail, you can verify manually:

### 1. Upload a Document

```bash
curl -X POST http://localhost:8000/v1/documents \
  -H "X-API-Key: amber-dev-key-2024" \
  -F "file=@/path/to/document.pdf"
```

### 2. Check Processing Status

```bash
curl http://localhost:8000/v1/documents/{document_id} \
  -H "X-API-Key: amber-dev-key-2024" | jq .
```

### 3. Verify Chunks

```bash
curl http://localhost:8000/v1/documents/{document_id}/chunks \
  -H "X-API-Key: amber-dev-key-2024" | jq 'length'
```

### 4. Verify Entities

```bash
curl http://localhost:8000/v1/documents/{document_id}/entities \
  -H "X-API-Key: amber-dev-key-2024" | jq 'length'
```

### 5. Check Neo4j Graph

```bash
docker compose exec neo4j cypher-shell -u neo4j -p graphrag123 \
  "MATCH (d:Document {id: 'doc_xxx'})-[:HAS_CHUNK]->(c)-[:MENTIONS]->(e)
   RETURN count(c) as chunks, count(e) as entities"
```

### 6. Query the System

```bash
curl -X POST http://localhost:8000/v1/query \
  -H "X-API-Key: amber-dev-key-2024" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is this document about?", "limit": 3}' | jq .
```

## Test Files Location

- **Integration Test Script:** `tests/integration/test_pipeline_manual.sh`
- **Python Tests:** `tests/integration/test_ingestion_pipeline.py`
- **Test Documentation:** `tests/integration/README.md`

## Regular Testing Schedule

**Recommended testing frequency:**

- **Before commits:** Run integration test
- **After dependency updates:** Full test suite
- **Weekly:** Automated integration tests
- **After infrastructure changes:** Manual verification + automated tests

## See Also

- [tests/integration/README.md](tests/integration/README.md) - Detailed test documentation
- [tests/integration/test_pipeline_manual.sh](tests/integration/test_pipeline_manual.sh) - Test script source
- [src/workers/tasks.py](src/workers/tasks.py) - Worker implementation with Neo4j fixes
