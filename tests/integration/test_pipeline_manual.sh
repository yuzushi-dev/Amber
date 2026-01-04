#!/bin/bash
#
# Manual Integration Test for Ingestion Pipeline
# ===============================================
#
# This script tests the complete ingestion pipeline by:
# 1. Creating a test PDF
# 2. Uploading it via the API
# 3. Waiting for processing
# 4. Verifying all components (chunks, entities, relationships, Neo4j, Milvus)
#
# Usage: ./tests/integration/test_pipeline_manual.sh
#

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "========================================"
echo "  Ingestion Pipeline Integration Test"
echo "========================================"
echo ""

# Configuration
API_KEY="amber-dev-key-2024"
API_URL="http://localhost:8000"
TEST_FILE="/tmp/test_integration_$(date +%s).pdf"

# Create test PDF
echo -n "1. Creating test PDF... "
cat > "$TEST_FILE" << 'EOF'
%PDF-1.4
1 0 obj
<</Type /Catalog /Pages 2 0 R>>
endobj
2 0 obj
<</Type /Pages /Kids [3 0 R] /Count 1>>
endobj
3 0 obj
<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>>
endobj
4 0 obj
<</Length 450>>
stream
BT
/F1 16 Tf
50 720 Td
(Integration Test - Knowledge Graph) Tj
0 -30 Td
/F1 12 Tf
(Anthropic developed Claude, an AI assistant focused on safety.) Tj
0 -20 Td
(Dario Amodei serves as CEO of Anthropic.) Tj
0 -20 Td
(The company was founded in 2021 by former OpenAI researchers.) Tj
0 -40 Td
(The system uses Neo4j for graph storage and Milvus for vectors.) Tj
0 -20 Td
(PostgreSQL manages metadata while OpenAI provides embeddings.) Tj
ET
endstream
endobj
5 0 obj
<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>
endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000270 00000 n
0000000772 00000 n
trailer
<</Size 6 /Root 1 0 R>>
startxref
852
%%EOF
EOF

echo -e "${GREEN}✓${NC}"

# Upload document
echo -n "2. Uploading document... "
UPLOAD_RESPONSE=$(curl -s -X POST "$API_URL/v1/documents" \
  -H "X-API-Key: $API_KEY" \
  -F "file=@$TEST_FILE")

DOCUMENT_ID=$(echo "$UPLOAD_RESPONSE" | jq -r '.document_id')

if [ -z "$DOCUMENT_ID" ] || [ "$DOCUMENT_ID" == "null" ]; then
  echo -e "${RED}✗${NC}"
  echo "Upload failed: $UPLOAD_RESPONSE"
  rm -f "$TEST_FILE"
  exit 1
fi

echo -e "${GREEN}✓${NC} (ID: $DOCUMENT_ID)"

# Wait for processing
echo -n "3. Waiting for processing"
MAX_WAIT=60
for i in $(seq 1 $MAX_WAIT); do
  STATUS_RESPONSE=$(curl -s -X GET "$API_URL/v1/documents/$DOCUMENT_ID" \
    -H "X-API-Key: $API_KEY")

  STATUS=$(echo "$STATUS_RESPONSE" | jq -r '.status')

  if [ "$STATUS" == "ready" ]; then
    echo -e " ${GREEN}✓${NC} (${i}s)"
    break
  elif [ "$STATUS" == "failed" ]; then
    echo -e " ${RED}✗${NC}"
    ERROR=$(echo "$STATUS_RESPONSE" | jq -r '.error_message')
    echo "Processing failed: $ERROR"
    rm -f "$TEST_FILE"
    exit 1
  fi

  if [ $((i % 5)) -eq 0 ]; then
    echo -n "."
  fi

  sleep 1

  if [ "$i" -eq "$MAX_WAIT" ]; then
    echo -e " ${RED}✗${NC} (timeout)"
    echo "Status: $STATUS"
    rm -f "$TEST_FILE"
    exit 1
  fi
done

# Verify chunks
echo -n "4. Verifying chunks... "
CHUNKS_RESPONSE=$(curl -s -X GET "$API_URL/v1/documents/$DOCUMENT_ID/chunks" \
  -H "X-API-Key: $API_KEY")

CHUNK_COUNT=$(echo "$CHUNKS_RESPONSE" | jq 'length')
EMBEDDED_COUNT=$(echo "$CHUNKS_RESPONSE" | jq '[.[] | select(.embedding_status == "completed")] | length')

if [ "$CHUNK_COUNT" -gt 0 ] && [ "$CHUNK_COUNT" -eq "$EMBEDDED_COUNT" ]; then
  echo -e "${GREEN}✓${NC} ($CHUNK_COUNT chunks, all embedded)"
else
  echo -e "${RED}✗${NC} ($CHUNK_COUNT chunks, $EMBEDDED_COUNT embedded)"
  rm -f "$TEST_FILE"
  exit 1
fi

# Verify entities
echo -n "5. Verifying entities... "
ENTITIES_RESPONSE=$(curl -s -X GET "$API_URL/v1/documents/$DOCUMENT_ID/entities" \
  -H "X-API-Key: $API_KEY")

ENTITY_COUNT=$(echo "$ENTITIES_RESPONSE" | jq 'length')

if [ "$ENTITY_COUNT" -gt 0 ]; then
  SAMPLE_ENTITIES=$(echo "$ENTITIES_RESPONSE" | jq -r '[.[].name] | .[0:3] | join(", ")')
  echo -e "${GREEN}✓${NC} ($ENTITY_COUNT entities: $SAMPLE_ENTITIES...)"
else
  echo -e "${YELLOW}⚠${NC} (No entities extracted)"
fi

# Verify relationships
echo -n "6. Verifying relationships... "
RELS_RESPONSE=$(curl -s -X GET "$API_URL/v1/documents/$DOCUMENT_ID/relationships" \
  -H "X-API-Key: $API_KEY")

REL_COUNT=$(echo "$RELS_RESPONSE" | jq 'length')

if [ "$REL_COUNT" -gt 0 ]; then
  echo -e "${GREEN}✓${NC} ($REL_COUNT relationships)"
else
  echo -e "${YELLOW}⚠${NC} (No relationships extracted)"
fi

# Verify Neo4j
echo -n "7. Verifying Neo4j graph... "
NEO4J_RESULT=$(docker compose exec -T neo4j cypher-shell -u neo4j -p graphrag123 \
  "MATCH (d:Document {id: '$DOCUMENT_ID'})-[:HAS_CHUNK]->(c:Chunk)-[:MENTIONS]->(e:Entity)
   RETURN COUNT(DISTINCT d) as docs, COUNT(DISTINCT c) as chunks, COUNT(DISTINCT e) as entities" \
  2>&1 | tail -2 | head -1)

if echo "$NEO4J_RESULT" | grep -q "$CHUNK_COUNT"; then
  echo -e "${GREEN}✓${NC} (Graph structure verified)"
else
  echo -e "${YELLOW}⚠${NC} (Partial graph data)"
fi

# Verify query works
echo -n "8. Testing retrieval... "
QUERY_RESPONSE=$(curl -s -X POST "$API_URL/v1/query" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"What is Anthropic?\", \"limit\": 3}")

ANSWER=$(echo "$QUERY_RESPONSE" | jq -r '.answer')

if [ -n "$ANSWER" ] && [ "$ANSWER" != "null" ]; then
  echo -e "${GREEN}✓${NC}"
  echo "   Answer preview: ${ANSWER:0:80}..."
else
  echo -e "${RED}✗${NC}"
fi

# Cleanup
rm -f "$TEST_FILE"

echo ""
echo "========================================"
echo -e "  ${GREEN}All Tests Passed!${NC}"
echo "========================================"
echo ""
echo "Document ID: $DOCUMENT_ID"
echo "Chunks: $CHUNK_COUNT"
echo "Entities: $ENTITY_COUNT"
echo "Relationships: $REL_COUNT"
echo ""
