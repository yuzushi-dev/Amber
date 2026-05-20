# MinIO Migration Runbook: Garage → MinIO

**Date:** 2026-05-15 (prepared)
**Maintenance Window:** Required (~2-3 hours; documents bucket migrated live, Milvus down ~30 min)
**Risk Level:** Medium (storage backend swap)

---

## Pre-Migration Checklist

- [ ] Schedule maintenance window (2-3 hours)
- [ ] Notify users of brief downtime
- [ ] Run preflight backup: `bash scripts/backup_preflight.sh`
- [ ] Verify backup completes successfully
- [ ] Confirm .env backup created
- [ ] Confirm Garage volumes NOT deleted
- [ ] Review rollback plan: `docs/PRs/ROLLBACK_MINIO_MIGRATION.md`
- [ ] Verify 4 confirmed corrupt documents identified (from spike analysis)

---

## Migration Steps

### Phase 1: Pre-flight (30 min)

```bash
cd /root/amber2

# 1. Create timestamped .env backup
cp .env .env.backup.minio-migration-$(date +%Y%m%d)

# 2. Run full backup (includes Garage data + meta volume tars)
bash scripts/backup_preflight.sh

# 3. Verify Garage health
docker exec amber2-garage-1 /garage stats -a

# 4. Check disk space (docker data-root on amber-u24 is /opt/docker)
df -h /opt
```

### Phase 2: Stop Ingestion Services (10 min)

> The `documents` bucket will be migrated live (Garage still running).
> Only Milvus requires a stop, in Phase 3 step 2.

```bash
cd /root/amber2

# Stop ingestion workers to prevent new uploads during migration
docker compose stop worker

# API can stay up — document download still works from Garage
docker compose ps
```

### Phase 3: Copy Data (60-90 min)

```bash
cd /root/amber2

# 1. Start MinIO alongside Garage (add minio service to docker-compose.yml first — see SPIKE doc §3.3)
docker compose up -d minio

# Wait for healthy
sleep 15
curl -sf http://localhost:9000/minio/health/live && echo "MinIO ready"

# 2. Mirror documents bucket (Garage still active — live migration, no downtime)
#    rclone runs inside Docker network so hostnames resolve
docker run --rm --network amber2_graphrag-network \
  rclone/rclone:latest copy \
  :s3,provider=Minio,access_key_id=${OBJECT_STORAGE_ACCESS_KEY},secret_access_key=${OBJECT_STORAGE_SECRET_KEY},endpoint=http://garage:3900:documents \
  :s3,provider=Minio,access_key_id=${OBJECT_STORAGE_ACCESS_KEY},secret_access_key=${OBJECT_STORAGE_SECRET_KEY},endpoint=http://minio:9000:documents \
  --progress --transfers=4

# 3. Stop Milvus before migrating a-bucket (prevent split-brain writes)
docker compose stop milvus

# 4. Mirror a-bucket (Milvus index data)
docker run --rm --network amber2_graphrag-network \
  rclone/rclone:latest copy \
  :s3,provider=Minio,access_key_id=${OBJECT_STORAGE_ACCESS_KEY},secret_access_key=${OBJECT_STORAGE_SECRET_KEY},endpoint=http://garage:3900:a-bucket \
  :s3,provider=Minio,access_key_id=${OBJECT_STORAGE_ACCESS_KEY},secret_access_key=${OBJECT_STORAGE_SECRET_KEY},endpoint=http://minio:9000:a-bucket \
  --progress --transfers=4

# 5. Verify counts match before proceeding
docker run --rm --network amber2_graphrag-network \
  rclone/rclone:latest size \
  :s3,provider=Minio,access_key_id=${OBJECT_STORAGE_ACCESS_KEY},secret_access_key=${OBJECT_STORAGE_SECRET_KEY},endpoint=http://garage:3900:documents
docker run --rm --network amber2_graphrag-network \
  rclone/rclone:latest size \
  :s3,provider=Minio,access_key_id=${OBJECT_STORAGE_ACCESS_KEY},secret_access_key=${OBJECT_STORAGE_SECRET_KEY},endpoint=http://minio:9000:documents
# Repeat for a-bucket — object counts and sizes must match
```

### Phase 4: Switch Environment (10 min)

```bash
cd /root/amber2

# Update .env (3 lines)
sed -i 's/^OBJECT_STORAGE_HOST=garage/OBJECT_STORAGE_HOST=minio/' .env
sed -i 's/^OBJECT_STORAGE_PORT=3900/OBJECT_STORAGE_PORT=9000/' .env
sed -i 's/^MILVUS_MINIO_ADDRESS=garage:3900/MILVUS_MINIO_ADDRESS=minio:9000/' .env

# Verify
grep -E "OBJECT_STORAGE_HOST|OBJECT_STORAGE_PORT|MILVUS_MINIO_ADDRESS" .env

# Stop Garage (do NOT use -v — keep volumes for rollback)
docker compose stop garage

# Restart services against MinIO
docker compose up -d api worker milvus
```

### Phase 5: Verify (20 min)

```bash
# Check all services healthy
docker compose ps

# API health
curl -sf http://127.0.0.1:8000/health/ready && echo "API ready"

# Milvus health
docker exec amber2-milvus-1 curl -s localhost:9091/healthz

# MinIO health
curl -sf http://localhost:9000/minio/health/live && echo "MinIO ready"

# Check for FAILED documents in last hour (credentials: graphrag/graphrag)
docker exec amber2-postgres-1 psql -U graphrag -d graphrag \
  -c "SELECT COUNT(*) FROM documents WHERE status='FAILED' AND updated_at > NOW() - INTERVAL '1 hour';"

# Run smoke test
bash scripts/smoke_production_readonly.sh
```

---

## Post-Migration Cleanup

```bash
# After 48h stability confirmed:

# 1. Remove Garage service from docker-compose.yml (comment out or delete)
# 2. Remove graphrag-garage-data and graphrag-garage-meta from volumes section

# 3. Confirm volumes before deleting — verify preflight backup is current
bash scripts/backup_preflight.sh --dry-run

# 4. ONLY after backup verified — delete Garage volumes (irreversible)
#    Do NOT run this until you are certain rollback is no longer needed
# docker volume rm amber2_graphrag-garage-data amber2_graphrag-garage-meta

# 5. Add daily backup cron (recommended: 02:00 UTC)
#    Run as root on amber-u24:
#    crontab -e
#    0 2 * * * cd /root/amber2 && bash scripts/backup_preflight.sh >> /var/log/amber/backup.log 2>&1
```

---

## Estimated Timeline

| Phase | Duration | Notes |
|-------|----------|-------|
| Pre-flight | 30 min | Backup + cleanup |
| Stop services | 10 min | Minimize disruption |
| Data copy | 60-90 min | 766.5 MiB total |
| Switch env | 10 min | Quick cutover |
| Verify | 20 min | Test critical paths |
| **Total** | **~2-3 hours** | |

---

## Emergency Rollback

If anything goes wrong, follow `docs/PRs/ROLLBACK_MINIO_MIGRATION.md`.

Quick manual revert:

```bash
# Restore .env
cp .env.backup.minio-migration-* .env

# Stop MinIO (do NOT use -v)
docker compose stop minio

# Start Garage
docker compose up -d garage

# Restart services
docker compose up -d
```

---

## Verification Scripts

```bash
# Run existing smoke test (read-only, safe on production)
bash scripts/smoke_production_readonly.sh

# Check recent document failures
docker exec amber2-postgres-1 psql -U graphrag -d graphrag \
  -c "SELECT status, COUNT(*) FROM documents GROUP BY status ORDER BY status;"
```
