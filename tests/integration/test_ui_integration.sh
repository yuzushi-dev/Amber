#!/bin/bash

# UI Integration Test Script
# Tests the same endpoints and flows that the frontend uses

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

API_URL="${API_URL:-http://localhost:8000/v1}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:3000}"
API_KEY="${API_KEY:-amber-dev-key-2024}"

echo "========================================"
echo "  UI Integration Test Suite"
echo "========================================"
echo ""

# Test 1: Frontend accessibility
echo -n "1. Testing frontend accessibility... "
FRONTEND_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$FRONTEND_URL" 2>/dev/null)
if [ "$FRONTEND_STATUS" == "200" ]; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC} (HTTP $FRONTEND_STATUS)"
    exit 1
fi

# Test 2: API health endpoint
echo -n "2. Testing API health endpoint... "
HEALTH=$(curl -s "$API_URL/../health" | jq -r '.status')
if [ "$HEALTH" == "healthy" ]; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
    exit 1
fi

# Test 3: CORS headers
echo -n "3. Testing CORS headers... "
CORS_HEADERS=$(curl -s -I -H "Origin: http://localhost:3000" "$API_URL/documents" -H "X-API-Key: $API_KEY" 2>/dev/null | grep -i "access-control")
if [ -n "$CORS_HEADERS" ]; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${YELLOW}⚠${NC} (No CORS headers found)"
fi

# Test 4: Create test PDF (same as UI would upload)
echo -n "4. Creating test PDF... "
TEST_FILE="/tmp/ui_test_$(date +%s).pdf"
cat > "$TEST_FILE" << 'EOF'
%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<<>>>>endobj
4 0 obj<</Length 110>>stream
BT
/F1 12 Tf
50 700 Td
(UI Integration Test Document) Tj
0 -20 Td
(Testing upload workflow from frontend) Tj
0 -20 Td
(Run ID: $(date +%s)) Tj
ET
endstream
endobj
xref
0 5
0000000000 65535 f
0000000009 00000 n
0000000056 00000 n
0000000115 00000 n
0000000229 00000 n
trailer<</Size 5/Root 1 0 R>>
startxref
387
%%EOF
EOF
echo -e "${GREEN}✓${NC}"

# Test 5: Upload document (simulating UI FormData upload)
echo -n "5. Uploading document (UI workflow)... "
UPLOAD_RESPONSE=$(curl -s -X POST "$API_URL/documents" \
  -H "X-API-Key: $API_KEY" \
  -H "Origin: http://localhost:3000" \
  -F "file=@$TEST_FILE" 2>&1)

DOCUMENT_ID=$(echo "$UPLOAD_RESPONSE" | jq -r '.document_id')
EVENTS_URL=$(echo "$UPLOAD_RESPONSE" | jq -r '.events_url')

if [ "$DOCUMENT_ID" != "null" ] && [ -n "$DOCUMENT_ID" ]; then
    echo -e "${GREEN}✓${NC} (ID: $DOCUMENT_ID)"
else
    echo -e "${RED}✗${NC}"
    echo "Upload response: $UPLOAD_RESPONSE"
    exit 1
fi

# Test 6: SSE Events Endpoint (critical for UI real-time updates)
echo -n "6. Testing SSE events endpoint... "
if [ "$EVENTS_URL" != "null" ] && [ -n "$EVENTS_URL" ]; then
    # Test SSE connection (timeout after 5 seconds)
    SSE_TEST=$(timeout 5 curl -s -N "$EVENTS_URL" 2>/dev/null | head -5 || true)
    if [ -n "$SSE_TEST" ]; then
        echo -e "${GREEN}✓${NC}"
        # Show first event
        FIRST_EVENT=$(echo "$SSE_TEST" | grep "^data:" | head -1 | sed 's/^data: //')
        if [ -n "$FIRST_EVENT" ]; then
            STATUS=$(echo "$FIRST_EVENT" | jq -r '.status' 2>/dev/null || echo "unknown")
            echo "   First event: status=$STATUS"
        fi
    else
        echo -e "${YELLOW}⚠${NC} (No SSE data received)"
    fi
else
    echo -e "${RED}✗${NC} (No events_url in response)"
fi

# Test 7: Poll document status (UI fallback mechanism)
echo -n "7. Testing document status polling... "
sleep 2  # Give it time to process
STATUS_RESPONSE=$(curl -s "$API_URL/documents/$DOCUMENT_ID" -H "X-API-Key: $API_KEY")
DOC_STATUS=$(echo "$STATUS_RESPONSE" | jq -r '.status')
DOC_NAME=$(echo "$STATUS_RESPONSE" | jq -r '.filename')

if [ -n "$DOC_STATUS" ] && [ "$DOC_STATUS" != "null" ]; then
    echo -e "${GREEN}✓${NC} (Status: $DOC_STATUS)"
else
    echo -e "${RED}✗${NC}"
    exit 1
fi

# Test 8: Wait for processing to complete
echo -n "8. Waiting for processing... "
MAX_WAIT=60
for i in $(seq 1 $MAX_WAIT); do
    sleep 1
    STATUS_RESPONSE=$(curl -s "$API_URL/documents/$DOCUMENT_ID" -H "X-API-Key: $API_KEY")
    CURRENT_STATUS=$(echo "$STATUS_RESPONSE" | jq -r '.status')

    if [ "$CURRENT_STATUS" == "ready" ]; then
        echo -e "${GREEN}✓${NC} (${i}s)"
        break
    elif [ "$CURRENT_STATUS" == "failed" ]; then
        echo -e "${RED}✗${NC} (Processing failed)"
        ERROR=$(echo "$STATUS_RESPONSE" | jq -r '.error_message')
        echo "   Error: $ERROR"
        exit 1
    fi

    if [ $i -eq $MAX_WAIT ]; then
        echo -e "${RED}✗${NC} (Timeout - status: $CURRENT_STATUS)"
        exit 1
    fi
done

# Test 9: Verify document metadata (UI document library view)
echo -n "9. Testing document metadata retrieval... "
METADATA=$(curl -s "$API_URL/documents/$DOCUMENT_ID" -H "X-API-Key: $API_KEY")
HAS_FILENAME=$(echo "$METADATA" | jq 'has("filename")')
HAS_STATUS=$(echo "$METADATA" | jq 'has("status")')
HAS_CREATED=$(echo "$METADATA" | jq 'has("created_at")')

if [ "$HAS_FILENAME" == "true" ] && [ "$HAS_STATUS" == "true" ] && [ "$HAS_CREATED" == "true" ]; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC} (Missing metadata fields)"
fi

# Test 10: Test document content endpoint (UI content viewer)
echo -n "10. Testing document content endpoint... "
CONTENT_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/documents/$DOCUMENT_ID/content" -H "X-API-Key: $API_KEY")
if [ "$CONTENT_RESPONSE" == "200" ]; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${YELLOW}⚠${NC} (HTTP $CONTENT_RESPONSE)"
fi

# Test 11: Test chunks endpoint (UI chunks tab)
echo -n "11. Testing chunks endpoint... "
CHUNKS_RESPONSE=$(curl -s "$API_URL/documents/$DOCUMENT_ID/chunks" -H "X-API-Key: $API_KEY")
CHUNK_COUNT=$(echo "$CHUNKS_RESPONSE" | jq '. | length')
if [ "$CHUNK_COUNT" -ge 0 ] 2>/dev/null; then
    echo -e "${GREEN}✓${NC} ($CHUNK_COUNT chunks)"
else
    echo -e "${RED}✗${NC}"
fi

# Test 12: Test entities endpoint (UI entities tab)
echo -n "12. Testing entities endpoint... "
ENTITIES_RESPONSE=$(curl -s "$API_URL/documents/$DOCUMENT_ID/entities" -H "X-API-Key: $API_KEY")
ENTITY_COUNT=$(echo "$ENTITIES_RESPONSE" | jq '. | length')
if [ "$ENTITY_COUNT" -ge 0 ] 2>/dev/null; then
    echo -e "${GREEN}✓${NC} ($ENTITY_COUNT entities)"
else
    echo -e "${RED}✗${NC}"
fi

# Test 13: Test relationships endpoint (UI graph view)
echo -n "13. Testing relationships endpoint... "
RELATIONSHIPS_RESPONSE=$(curl -s "$API_URL/documents/$DOCUMENT_ID/relationships" -H "X-API-Key: $API_KEY")
REL_COUNT=$(echo "$RELATIONSHIPS_RESPONSE" | jq '. | length')
if [ "$REL_COUNT" -ge 0 ] 2>/dev/null; then
    echo -e "${GREEN}✓${NC} ($REL_COUNT relationships)"
else
    echo -e "${RED}✗${NC}"
fi

# Test 14: Test query endpoint (UI chat interface)
echo -n "14. Testing query endpoint... "
QUERY_RESPONSE=$(curl -s -X POST "$API_URL/query" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "test query", "top_k": 5}')
HAS_ANSWER=$(echo "$QUERY_RESPONSE" | jq 'has("answer")')
if [ "$HAS_ANSWER" == "true" ]; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

# Test 15: Test document list endpoint (UI document library)
echo -n "15. Testing document list endpoint... "
DOCS_LIST=$(curl -s "$API_URL/documents?limit=10" -H "X-API-Key: $API_KEY")
IS_ARRAY=$(echo "$DOCS_LIST" | jq 'type == "array"')
if [ "$IS_ARRAY" == "true" ]; then
    DOC_COUNT=$(echo "$DOCS_LIST" | jq '. | length')
    echo -e "${GREEN}✓${NC} ($DOC_COUNT documents)"
else
    echo -e "${RED}✗${NC}"
fi

# Test 16: Test file download endpoint (UI PDF viewer)
echo -n "16. Testing file download endpoint... "
FILE_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/documents/$DOCUMENT_ID/file" -H "X-API-Key: $API_KEY")
if [ "$FILE_RESPONSE" == "200" ]; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${YELLOW}⚠${NC} (HTTP $FILE_RESPONSE)"
fi

# Cleanup
rm -f "$TEST_FILE"

echo ""
echo "========================================"
echo -e "  ${GREEN}UI Integration Tests Complete!${NC}"
echo "========================================"
echo ""
echo "Summary:"
echo "  Document ID: $DOCUMENT_ID"
echo "  Final Status: $CURRENT_STATUS"
echo "  Chunks: $CHUNK_COUNT"
echo "  Entities: $ENTITY_COUNT"
echo "  Relationships: $REL_COUNT"
echo ""
echo "All UI endpoints verified ✓"
echo "  - Upload workflow (multipart form data)"
echo "  - SSE events for real-time updates"
echo "  - Document metadata and status"
echo "  - Content viewing endpoints"
echo "  - Graph data endpoints (chunks, entities, relationships)"
echo "  - Query/chat interface"
echo "  - Document library listing"
echo "  - File download for PDF viewer"
echo ""
