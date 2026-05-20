# Rollback Plan: Garage → MinIO Migration

**Date:** 2026-05-15 (prepared)
**Purpose:** Steps to revert MinIO → Garage if migration fails
**Trigger:** Any data inconsistency, vector search failures, or upload failures after migration

---

## Pre-Migration Checkpoint

Before starting migration, ensure these exist:

```bash
# 1. Full preflight backup (must pass)
cd /root/amber2
bash scripts/backup_preflight.sh

# 2. .env backup
cp .env .env.backup.minio-migration-$(date +%Y%m%d)

# 3. Garage volumes NOT deleted (will be needed for rollback)
docker volume ls | grep amber2_graphrag-garage
```

---

## Rollback Steps

### If rollback needed BEFORE data migration (Garage still has data)

```bash
cd /root/amber2

# 1. Stop api + worker (preserve data volumes)
docker compose stop api worker minio

# 2. Restore .env
cp .env.backup.minio-migration-* .env

# 3. Remove MinIO container only — do NOT use -v (would delete volumes)
docker compose rm -f minio

# 4. Start Garage only
docker compose up -d garage postgres redis
docker compose ps

# 5. Verify Garage health
docker exec amber2-garage-1 /garage bucket list

# 6. Start remaining services
docker compose up -d
```

### If rollback needed AFTER data migration (cutover already done — MinIO is active)

> **Warning:** Objects written to MinIO after the cutover are NOT in Garage.
> Step 3 syncs them back before switching — do not skip it.

```bash
cd /root/amber2

# 1. Stop api + worker to prevent new writes during rollback
docker compose stop api worker

# 2. Sync objects written to MinIO post-cutover back to Garage
#    (run inside Docker network so hostnames resolve)
docker run --rm --network amber2_graphrag-network \
  rclone/rclone:latest copy \
  :s3,provider=Minio,access_key_id=${OBJECT_STORAGE_ACCESS_KEY},secret_access_key=${OBJECT_STORAGE_SECRET_KEY},endpoint=http://minio:9000:documents \
  :s3,provider=Minio,access_key_id=${OBJECT_STORAGE_ACCESS_KEY},secret_access_key=${OBJECT_STORAGE_SECRET_KEY},endpoint=http://garage:3900:documents \
  --progress
docker run --rm --network amber2_graphrag-network \
  rclone/rclone:latest copy \
  :s3,...:a-bucket :s3,...:a-bucket \
  --progress

# 3. Stop Milvus and MinIO
docker compose stop milvus minio

# 4. Restore .env
cp .env.backup.minio-migration-* .env

# 5. Start Garage
docker compose up -d garage
sleep 10
docker exec amber2-garage-1 /garage bucket list

# 6. Restart all services
docker compose up -d
```

---

## Data Verification After Rollback

```bash
# Verify documents bucket (via S3 API — Garage has no 'object list' subcommand)
docker run --rm --network amber2_graphrag-network \
  amazon/aws-cli s3 ls s3://documents/ \
  --endpoint-url http://garage:3900 \
  --no-verify-ssl 2>/dev/null | wc -l
# Expected: ~1198 objects

# Verify Milvus can access a-bucket
docker exec amber2-milvus-1 curl -s localhost:9091/healthz

# Verify uploads volume integrity (docker data-root on amber-u24 is /opt/docker)
ls /opt/docker/volumes/amber2_graphrag-uploads/_data | wc -l

# Check for FAILED documents in last hour
docker exec amber2-postgres-1 psql -U graphrag -d graphrag \
  -c "SELECT COUNT(*) FROM documents WHERE status='FAILED' AND updated_at > NOW() - INTERVAL '1 hour';"
```

---

## Emergency Contacts

| Component | Owner | Notes |
|-----------|-------|-------|
| Garage | Local | Has SQLite, check docker logs |
| MinIO | Local | Check docker logs, mc admin |
| PostgreSQL | Local | Check connection, query status |
| Milvus | Local | Check minio connectivity |

---

## Rollback Verification Checklist

- [ ] Garage container running and healthy
- [ ] `docker compose ps` shows all services running
- [ ] API /health endpoint responds
- [ ] Documents are downloadable (test with a known document)
- [ ] Vector search returns results (test a query)
- [ ] No new FAILED documents in PostgreSQL
- [ ] Check backup_preflight.sh logs for any anomalies
