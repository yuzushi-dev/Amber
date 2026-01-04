# Integration Tests

This directory contains integration tests for the complete Amber RAG system.

## Quick Start

**Recommended:** Use the manual shell script for reliable end-to-end testing:

```bash
./tests/integration/test_pipeline_manual.sh
```

This test creates a real PDF, uploads it via the API, and verifies all pipeline stages.

## Test Files

### 1. `test_ui_integration.sh` ✅ **UI Integration**

Shell script that verifies all frontend endpoints and UI workflows are working correctly.

**Features:**
- Tests frontend accessibility
- Verifies CORS configuration
- Tests document upload (multipart form data)
- Checks SSE (Server-Sent Events) for real-time updates
- Validates all UI endpoints:
  - Document library listing
  - Document metadata retrieval
  - Content viewing
  - Chunks, entities, relationships display
  - Query/chat interface
  - PDF file download
- Provides comprehensive integration verification

**Usage:**
```bash
# Run the test
./tests/integration/test_ui_integration.sh
```

**Expected Output:**
```
========================================
  UI Integration Test Suite
========================================

1. Testing frontend accessibility... ✓
2. Testing API health endpoint... ✓
3. Testing CORS headers... ✓
4. Creating test PDF... ✓
5. Uploading document (UI workflow)... ✓ (ID: doc_xxx)
6. Testing SSE events endpoint... ⚠ (No SSE data received)
7. Testing document status polling... ✓ (Status: ready)
8. Waiting for processing... ✓ (1s)
9. Testing document metadata retrieval... ✓
10. Testing document content endpoint... ✓
11. Testing chunks endpoint... ✓ (3 chunks)
12. Testing entities endpoint... ✓ (8 entities)
13. Testing relationships endpoint... ✓ (7 relationships)
14. Testing query endpoint... ✓
15. Testing document list endpoint... ✓ (10 documents)
16. Testing file download endpoint... ✓

========================================
  UI Integration Tests Complete!
========================================
```

### 2. `test_pipeline_manual.sh` ✅ **Recommended**

Shell script that performs a complete end-to-end test of the ingestion pipeline.

**Features:**
- Creates a test PDF with knowledge graph content
- Uploads via real HTTP API
- Monitors processing progress
- Verifies chunks, entities, relationships
- Checks Neo4j graph structure
- Tests retrieval queries
- Provides colored output and detailed results

**Usage:**
```bash
# Make executable (first time only)
chmod +x tests/integration/test_pipeline_manual.sh

# Run the test
./tests/integration/test_pipeline_manual.sh
```

**Expected Output:**
```
========================================
  Ingestion Pipeline Integration Test
========================================

1. Creating test PDF... ✓
2. Uploading document... ✓ (ID: doc_xxx)
3. Waiting for processing... ✓ (20s)
4. Verifying chunks... ✓ (3 chunks, all embedded)
5. Verifying entities... ✓ (8 entities: Anthropic, Claude, Dario Amodei...)
6. Verifying relationships... ✓ (7 relationships)
7. Verifying Neo4j graph... ✓ (Graph structure verified)
8. Testing retrieval... ✓
   Answer preview: Anthropic is an AI safety company...

========================================
  All Tests Passed!
========================================
```

### 3. `test_ingestion_pipeline.py`

Python pytest integration test (note: requires running API server).

**What It Tests:**

1. **Document Upload** - File upload via API
2. **Text Extraction** - PDF text extraction with pymupdf4llm
3. **Classification** - Domain classification
4. **Chunking** - Semantic chunking into processable segments
5. **Embeddings** - Vector embedding generation via OpenAI
6. **Entity Extraction** - Named entity recognition from content
7. **Relationship Extraction** - Entity relationship mapping
8. **Neo4j Sync** - Knowledge graph creation in Neo4j
9. **Milvus Storage** - Vector storage for similarity search

**Usage:**
```bash
# Note: This requires the API server to be running
pytest tests/integration/test_ingestion_pipeline.py -v -s
```

### Prerequisites

- All services running (API, worker, Neo4j, Milvus, PostgreSQL, Redis, MinIO)
- Valid API key configured
- OpenAI API key for embeddings

### Expected Output

```
1. Uploading document...
   ✓ Document uploaded: doc_xxx

2. Waiting for processing...
   Status: extracting (0s)
   Status: chunking (5s)
   ✓ Processing complete: ready

3. Verifying chunks...
   ✓ 3 chunks created with embeddings

4. Verifying entities...
   ✓ 8 entities extracted
     Sample: ['Anthropic', 'Claude', 'Dario Amodei', 'Neo4j', 'Milvus']

5. Verifying relationships...
   ✓ 4 relationships created

6. Verifying Neo4j graph...
   ✓ Neo4j verified: 1 doc, 3 chunks, 8 entities

7. Verifying Milvus embeddings...
   ✓ 3 vectors in Milvus

✅ All pipeline stages verified!
```

### Troubleshooting

**Test fails at upload:**
- Check API is running: `curl http://localhost:8000/health`
- Verify API key is correct

**Test fails at processing:**
- Check worker logs: `docker compose logs worker --tail=50`
- Ensure all services are healthy: `docker compose ps`

**Test fails at Neo4j verification:**
- Verify Neo4j is running: `docker compose ps neo4j`
- Check connection: `docker compose exec neo4j cypher-shell -u neo4j -p graphrag123`

**Test fails at Milvus verification:**
- Check Milvus status: `docker compose ps milvus`
- Verify collection exists

### Test Data

The test uses a small PDF document embedded in the test file containing:
- Company information about Anthropic
- Technology stack description (Neo4j, Milvus, PostgreSQL)
- Leadership information

This ensures consistent test results and validates entity/relationship extraction.
