#!/bin/bash
set -e

# Configuration
BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
POSTGRES_CONTAINER="graphrag-postgres"
NEO4J_CONTAINER="graphrag-neo4j"
MINIO_VOLUME="graphrag-minio"
UPLOADS_VOLUME="graphrag-uploads"

# Create backup directory
mkdir -p "$BACKUP_DIR/$TIMESTAMP"

echo "Starting backup at $TIMESTAMP..."

# 1. Postgres Backup (Logical)
echo "Backing up Postgres..."
docker exec "$POSTGRES_CONTAINER" pg_dump -U graphrag graphrag > "$BACKUP_DIR/$TIMESTAMP/postgres.sql"

# 2. Neo4j Backup (Logical Cypher Export)
# Requires APOC to be enabled and configured
echo "Backing up Neo4j..."
docker exec "$NEO4J_CONTAINER" cypher-shell -u neo4j -p changeme \
    "CALL apoc.export.cypher.all(null, {format: 'cypher-shell', stream: true, useOptimizations: {type: 'UNWIND_BATCH', unwindBatchSize: 20}})" > "$BACKUP_DIR/$TIMESTAMP/neo4j.cypher"

# 3. MinIO Data (Volume Backup)
# We use a temporary container to tar the volume content
echo "Backing up MinIO volume..."
docker run --rm \
    -v "$MINIO_VOLUME":/data \
    -v "$(pwd)/$BACKUP_DIR/$TIMESTAMP":/backup \
    alpine tar czf /backup/minio_data.tar.gz -C /data .

# 4. Uploads (Volume Backup)
echo "Backing up Uploads volume..."
docker run --rm \
    -v "$UPLOADS_VOLUME":/data \
    -v "$(pwd)/$BACKUP_DIR/$TIMESTAMP":/backup \
    alpine tar czf /backup/uploads.tar.gz -C /data .

echo "Backup completed successfully at $BACKUP_DIR/$TIMESTAMP"
