#!/bin/bash
# =============================================================================
# Garage Object Storage - First-time Initialization Script
# =============================================================================
# Run this ONCE after the Garage container starts for the first time.
# It sets up the cluster layout, creates buckets, and configures access keys.
#
# Usage: ./docker/garage/init-garage.sh
# =============================================================================

set -e

CONTAINER_NAME="amber2-garage-1"
GARAGE="docker exec $CONTAINER_NAME /garage"

echo "=== Garage Initialization ==="
echo ""

# 1. Wait for Garage to be ready
echo "[1/6] Waiting for Garage to be ready..."
for i in $(seq 1 30); do
    if $GARAGE status > /dev/null 2>&1; then
        echo "  Garage is ready."
        break
    fi
    if [ $i -eq 30 ]; then
        echo "  ERROR: Garage did not become ready in time."
        exit 1
    fi
    sleep 1
done

# 2. Get node ID
echo ""
echo "[2/6] Getting node ID..."
NODE_ID=$($GARAGE status 2>/dev/null | grep -oP '^[a-f0-9]+' | head -1)
if [ -z "$NODE_ID" ]; then
    echo "  ERROR: Could not determine node ID"
    exit 1
fi
echo "  Node ID: $NODE_ID"

# 3. Assign layout
echo ""
echo "[3/6] Assigning cluster layout..."
$GARAGE layout assign -z dc1 -c 100G "$NODE_ID"
$GARAGE layout apply --version 1
echo "  Layout applied."

# 4. Create buckets
echo ""
echo "[4/6] Creating buckets..."
$GARAGE bucket create documents || echo "  'documents' bucket may already exist"
echo "  Created: documents"

# 5. Create API key with specific credentials (matching existing minioadmin/minioadmin)
echo ""
echo "[5/6] Creating API key..."
KEY_OUTPUT=$($GARAGE key create amber-admin 2>&1)
echo "$KEY_OUTPUT"

# Extract key ID and secret from output
KEY_ID=$(echo "$KEY_OUTPUT" | grep "Key ID:" | awk '{print $3}')
KEY_SECRET=$(echo "$KEY_OUTPUT" | grep "Secret key:" | awk '{print $3}')

echo ""
echo "  ╔══════════════════════════════════════════════════════════════╗"
echo "  ║  IMPORTANT: Save these credentials!                         ║"
echo "  ║                                                              ║"
echo "  ║  Key ID:     $KEY_ID"
echo "  ║  Secret Key: $KEY_SECRET"
echo "  ║                                                              ║"
echo "  ║  Update your .env or docker-compose.yml:                     ║"
echo "  ║    OBJECT_STORAGE_ACCESS_KEY=<Key ID>                        ║"
echo "  ║    OBJECT_STORAGE_SECRET_KEY=<Secret Key>                    ║"
echo "  ╚══════════════════════════════════════════════════════════════╝"

# 6. Grant access
echo ""
echo "[6/6] Granting bucket access..."
$GARAGE bucket allow --read --write --owner documents --key amber-admin
echo "  Access granted to 'documents' bucket."

echo ""
echo "=== Garage initialization complete ==="
echo ""
echo "Next steps:"
echo "  1. Update OBJECT_STORAGE_ACCESS_KEY and OBJECT_STORAGE_SECRET_KEY"
echo "     in your .env or docker-compose.yml with the credentials above."
echo "  2. Restart api and worker services: docker compose restart api worker"
echo "  3. Restart milvus: docker compose restart milvus"
