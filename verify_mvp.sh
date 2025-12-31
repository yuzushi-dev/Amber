#!/bin/bash
API_KEY="amber-dev-key-2024"
HOST="http://localhost:8000"

echo "1. Checking Health..."
curl -s -H "X-API-Key: $API_KEY" "$HOST/health"
echo ""

echo "2. Creating Test File..."
# Unique content
echo "To explore the solar system effectively, one must understand the orbital mechanics of planets like Mars and Jupiter. The Voyager missions provided key data. Verified at $(date)" > test_doc.txt

echo "3. Uploading Document..."
UPLOAD_RESP=$(curl -s -X POST -H "X-API-Key: $API_KEY" -F "file=@test_doc.txt" "$HOST/v1/documents")
echo "Upload Response: $UPLOAD_RESP"

# Extract ID
DOC_ID=$(echo $UPLOAD_RESP | grep -o '"document_id":"[^"]*"' | cut -d'"' -f4)
echo "Document ID: $DOC_ID"

if [ -z "$DOC_ID" ]; then
    echo "Failed to get Document ID"
    exit 1
fi

echo "4. Poll Status..."
for i in {1..60}; do
    STATUS_RESP=$(curl -s -H "X-API-Key: $API_KEY" "$HOST/v1/documents/$DOC_ID")
    STATUS=$(echo $STATUS_RESP | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
    echo "Attempts $i: Status=$STATUS"
    if [ "$STATUS" == "processed" ] || [ "$STATUS" == "ready" ]; then
        echo "Processing Complete!"
        break
    fi
    sleep 2
done

echo "5. Querying..."
QUERY_RESP=$(curl -s -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d '{"query":"What missions provided data on orbital mechanics?", "stream": false}' "$HOST/v1/query")
echo "Query Response: $QUERY_RESP"

echo "Done."
