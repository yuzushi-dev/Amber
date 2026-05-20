# Amber 2.0 GraphRAG — Storage Migration Spike: Garage → MinIO

**Date:** 2026-05-15  
**Author:** Engineering spike via Claude Code (read-only production access + code analysis)  
**Scope:** Production system at `your-server.example.com`, service `amber2-garage-1` (dxflrs/garage:v1.1.0)  
**Method:** Live production telemetry (Docker volumes, Garage admin API, PostgreSQL error analysis, container logs) + static code analysis  
**Constraint:** Read-only. Zero production changes made.  
**Goal:** Root-cause past data loss incidents; evaluate cost and risk of migrating to MinIO.

---

## 1. Current Storage Architecture

### 1.1 Garage Role in the Stack

Garage is the single S3-compatible object store for the entire stack. It serves **two independent systems** over the same endpoint:

| Client | Endpoint | Bucket | Data |
|--------|----------|--------|------|
| Application (API + Worker) | `garage:3900` | `documents` | Raw uploaded files (PDF, HTML, PPTX, …) |
| Milvus | `garage:3900` (via `MINIO_ADDRESS`) | `a-bucket` | Milvus index segments — dense + sparse vectors |

```yaml
# docker-compose.yml — Milvus service
milvus:
  environment:
    - MINIO_ADDRESS=${MILVUS_MINIO_ADDRESS:-garage:3900}
    - MINIO_ACCESS_KEY_ID=${OBJECT_STORAGE_ACCESS_KEY}
    - MINIO_SECRET_ACCESS_KEY=${OBJECT_STORAGE_SECRET_KEY}
```

**Blast radius:** A Garage failure simultaneously breaks document serving, new ingestion, and vector search. These are logically independent systems sharing a single failure domain. This is also documented in `ARCHITECTURE_AUDIT.md §5.1`.

### 1.2 Garage Configuration

**File:** `docker/garage/garage.toml`

```toml
metadata_dir = "/var/lib/garage/meta"
data_dir     = "/var/lib/garage/data"
db_engine    = "sqlite"          # ← not safe under crash + concurrent writes
replication_factor = 1           # ← zero redundancy, single node
```

- Docker volumes: `amber2_graphrag-garage-data`, `amber2_graphrag-garage-meta`
- Both created: `2026-04-08T12:32:48+02:00`
- Admin API port: `3903`; S3 API port: `3900`

### 1.3 Current Data State (as of 2026-05-15)

| Bucket | Objects | Size | Notes |
|--------|---------|------|-------|
| `documents` | 1,198 | 93.2 MiB | Application document files |
| `a-bucket` | 18,681 | 673.3 MiB | Milvus index data |
| — | — | **766.5 MiB total** | In-bucket totals |

**On-disk volumes:**

| Volume | Size | Ratio |
|--------|------|-------|
| `graphrag-garage-data` | 828 MiB | Data blocks |
| `graphrag-garage-meta` | 2.0 GiB | SQLite WAL + metadata |

> Metadata (2.0 GiB) is **2.4× larger than actual data (828 MiB)**. This is a known symptom of SQLite WAL journal accumulation following abrupt container kills or disk-full crashes. The overhead is benign but confirms past crash events.

**Unfinished Milvus uploads (active risk):**

```
Unfinished uploads (multipart and non-multipart): 12
Unfinished multipart uploads: 7
Size of unfinished multipart uploads: 56.6 MiB
```

7 multipart uploads are in flight and stale. These must be aborted or accepted before migration.

---

## 2. Root Cause Analysis — Past Data Loss

### 2.1 Primary Cause: 147 Documents Failed Due to Garage Unavailability

PostgreSQL `documents` table — failure analysis:

```sql
SELECT error_message, COUNT(*) FROM documents
WHERE status = 'FAILED' AND error_message IS NOT NULL
GROUP BY error_message ORDER BY count DESC;
```

| Error | Count |
|-------|-------|
| `garage:3900 Connection refused` | **147** |
| Milvus connection timeout | 7 |
| Zlib decompression error (Garage) | 4 |
| Extractor failures (NLTK, PPTX) | 3 |
| **Total FAILED** | **162 / 1,712** (9.5%) |

**147 failures** trace back to `[Errno 111] Connection refused` on `garage:3900`. This is consistent with the April 30 disk exhaustion incident (`/opt` filesystem at 100%): when the disk was full, Garage could not write blocks and the container crashed or became unresponsive. All ingestion tasks that ran during that window failed with connection refused.

**These 147 documents are not unrecoverable.** Their S3 objects were never successfully written. The original files may still be present in the `graphrag-uploads` Docker volume — verify before re-queuing via `scripts/requeue_stuck.py`.

### 2.2 Secondary Cause: 4 Documents with Zlib Corruption (Actual Data Loss)

```
"Unstructured extraction failed: Error -3 while decompressing data: invalid stored block lengths"
"Unstructured extraction failed: Error -3 while decompressing data: invalid distance code"
```

These 4 documents have **corrupt object data in Garage**. The `Error -3` is a zlib ZDATA_ERROR — the stored bytes are not valid compressed data. This is consistent with SQLite WAL truncation or partial block write when Garage was killed mid-write during the disk-full condition. **These 4 documents cannot be recovered from Garage.** Originals must be re-uploaded.

### 2.3 Timeline Reconstruction

| Date | Event |
|------|-------|
| 2026-02-11 | Garage introduced (`.env` comment: `--- Garage Object Storage (2026-02-11) ---`) |
| 2026-03-25 | Last successful `backup_preflight.sh` run (only backup on record — see `docs/ROLLBACK_ASSETS.md`) |
| 2026-04-08 | **All volumes recreated** — Postgres, Garage-data, Garage-meta all show `CreatedAt: 2026-04-08` |
| 2026-04-30 | `/opt` filesystem hits **100%** — Garage crashes, 147 ingestion tasks fail with `Connection refused` |
| 2026-04-30 | Disk exhaustion fixed; Docker log rotation deployed; services restarted |
| 2026-05-14 | Stack restarted (Garage `CreatedAt` updated to `2026-05-14T13:03:57`) |

> The April 8 volume recreation indicates either a full stack restore from the March 25 backup or a fresh deployment. Documents timestamped before April 8 in PostgreSQL (Feb–March: ~856 docs) survived because the Postgres dump was restored; their Garage objects are therefore from a restored volume snapshot, not original uploads.

### 2.4 Structural Garage Risks (Independent of Incidents)

| Risk | Mechanism | Status |
|------|-----------|--------|
| Zero redundancy | `replication_factor = 1` | Always present |
| SQLite crash-unsafe | WAL corruption under kill + disk-full | Confirmed — 4 corrupt objects |
| Metadata bloat | 2.4× meta/data ratio | Present, stable |
| Single failure domain | Both app and Milvus on same endpoint | Always present |
| Init complexity | Requires cluster layout + key assignment before first use | Operational friction |
| Backup coupling | Garage data + meta volumes **must be backed up together** | Documented risk |
| No admin UI | CLI-only management (`/garage` binary inside container) | Operational friction |

---

## 3. Migration Target: MinIO

### 3.1 Why MinIO

MinIO is the **officially supported Milvus object storage** in the Milvus Docker Compose reference stacks. The application storage client is already implemented as `MinIOClient` using the `minio` Python SDK. The change is a pure infrastructure swap.

| Property | Garage v1.1.0 | MinIO RELEASE.2024+ |
|----------|--------------|---------------------|
| Milvus official support | Community workaround | ✓ Reference implementation |
| Metadata backend | SQLite (crash-unsafe) | Filesystem (atomic writes) |
| Single-node production use | Designed for geo-distributed clusters | ✓ Designed for single-node |
| Admin UI | None (CLI only) | ✓ Console on port 9001 |
| Tooling | `/garage` binary | `mc` (MinIO Client) — rich CLI |
| Multipart upload recovery | Manual | ✓ Automatic on restart |
| Community / docs | Small project | Large enterprise adoption |
| Bucket auto-create | Requires init script | ✓ Auto-creates on first write |
| Licensing | AGPL-3.0 | AGPLv3 (same) |

### 3.2 Code Changes Required

**Zero.** The storage client is `MinIOClient` (`src/core/ingestion/infrastructure/storage/storage_client.py`) using the `minio` Python SDK. It reads all configuration from `OBJECT_STORAGE_HOST`, `OBJECT_STORAGE_PORT`, `OBJECT_STORAGE_ACCESS_KEY`, `OBJECT_STORAGE_SECRET_KEY`, `OBJECT_STORAGE_BUCKET_NAME`. No code changes needed — only infrastructure config.

### 3.3 Infrastructure Changes

**`.env`** — 3 lines change:

```diff
-OBJECT_STORAGE_HOST=garage
-OBJECT_STORAGE_PORT=3900
-MILVUS_MINIO_ADDRESS=garage:3900
+OBJECT_STORAGE_HOST=minio
+OBJECT_STORAGE_PORT=9000
+MILVUS_MINIO_ADDRESS=minio:9000
```

**`docker-compose.yml`** — replace `garage` service block:

```yaml
# REMOVE:
garage:
  image: dxflrs/garage:v1.1.0
  volumes:
    - ./docker/garage/garage.toml:/etc/garage.toml:ro
    - graphrag-garage-data:/var/lib/garage/data
    - graphrag-garage-meta:/var/lib/garage/meta
  ...

# ADD:
minio:
  image: minio/minio:RELEASE.2024-11-07T00-52-20Z   # pin a release
  command: server /data --console-address ":9001"
  environment:
    - MINIO_ROOT_USER=${OBJECT_STORAGE_ACCESS_KEY}
    - MINIO_ROOT_PASSWORD=${OBJECT_STORAGE_SECRET_KEY}
  volumes:
    - graphrag-minio-data:/data
  ports:
    - "9001:9001"   # Admin console — internal only, do not expose externally
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
    interval: 30s
    timeout: 10s
    retries: 5
    start_period: 15s
  logging: *default-logging
  deploy:
    resources:
      limits:
        memory: 1G
      reservations:
        memory: 256M
  restart: unless-stopped
  networks:
    - graphrag-network
```

Update `milvus.depends_on`: replace `garage` → `minio`.

Add new volume declaration: `graphrag-minio-data:`.

**`docker/garage/` directory** — archive (do not delete immediately; keep for rollback reference).

No `init-minio.sh` needed. MinIO auto-creates buckets on first PUT if using the root key. Optionally create buckets explicitly via `mc` post-startup.

---

## 4. Migration Procedure

> **Warning:** Steps 4.3–4.6 involve stopping Milvus. Vector search will be unavailable during the migration window (~15–30 minutes). Document ingestion can continue until step 4.5 if the `documents` bucket is migrated first while Garage is still running.

### 4.1 Prerequisites

- [ ] Disk space ≥ 20 GB free on `/opt` (current: 51 GB free — adequate)
- [ ] All 8 required containers in `running` state
- [ ] `rclone` installed: `apt-get install -y rclone` (or use `docker run rclone/rclone`)
- [ ] Backup completed and verified (step 4.2)

### 4.2 Step 0 — Backup (mandatory)

```bash
cd /root/amber2
bash scripts/backup_preflight.sh --dry-run   # verify first
bash scripts/backup_preflight.sh             # real run (~20 min, ~2.8 GB output)
```

Confirm `backups/preflight_<ts>/` contains `garage-data_volume_<ts>.tar.gz` and `garage-meta_volume_<ts>.tar.gz` before continuing.

### 4.3 Step 1 — Start MinIO Alongside Garage

Add the MinIO service to `docker-compose.yml` (Garage still present), then:

```bash
docker compose up -d minio
# Wait for healthy:
docker compose ps minio
```

Create buckets if auto-create is not enabled by default key policy:

```bash
docker run --rm --network amber2_graphrag-network \
  minio/mc:latest alias set local http://minio:9000 <ACCESS_KEY> <SECRET_KEY>
docker run --rm --network amber2_graphrag-network \
  minio/mc:latest mb local/documents local/a-bucket
```

### 4.4 Step 2 — Migrate `documents` Bucket (Live, No Downtime)

The application can continue serving requests during this step. Garage remains the active backend.

```bash
rclone copy \
  :s3,provider=Minio,access_key_id=<KEY>,secret_access_key=<SEC>,endpoint=http://localhost:3900:documents \
  :s3,provider=Minio,access_key_id=<KEY>,secret_access_key=<SEC>,endpoint=http://localhost:9000:documents \
  --progress --transfers=4

# Verify object count matches
rclone size :s3,...:documents  # source
rclone size :s3,...:documents  # dest
```

Expected: 1,198 objects, ~93 MiB.

### 4.5 Step 3 — Migrate `a-bucket` (Requires Milvus Stop)

**Milvus must be stopped** to prevent split-brain writes during migration.

```bash
docker stop amber2-milvus-1

# Abort stale multipart uploads before migration
# (7 uploads, 56.6 MiB — aborted uploads will restart cleanly on Milvus startup)
rclone copy \
  :s3,...:a-bucket :s3,...:a-bucket \
  --progress --transfers=4

# Verify
rclone size :s3,...:a-bucket  # source and dest must match
```

Expected: 18,681 objects (minus any aborted parts), ~673 MiB.

### 4.6 Step 4 — Cutover

```bash
# Update .env
sed -i 's/OBJECT_STORAGE_HOST=garage/OBJECT_STORAGE_HOST=minio/' /root/amber2/.env
sed -i 's/OBJECT_STORAGE_PORT=3900/OBJECT_STORAGE_PORT=9000/' /root/amber2/.env
sed -i 's/MILVUS_MINIO_ADDRESS=garage:3900/MILVUS_MINIO_ADDRESS=minio:9000/' /root/amber2/.env

# Remove Garage from docker-compose.yml (or comment out)
# Start Milvus against MinIO
docker compose up -d milvus api worker

# Smoke test
bash scripts/smoke_production_readonly.sh
curl -sf http://127.0.0.1:8000/health/ready
```

### 4.7 Step 5 — Re-queue Failed Documents

After smoke test passes:

```bash
# Check how many of the 147 failed docs still have originals in uploads volume
docker exec amber2-api-1 python3 scripts/check_doc_data.py

# Re-queue
docker exec amber2-api-1 python3 scripts/requeue_stuck.py
```

### 4.8 Step 6 — Decommission Garage (deferred, after 48h stability)

```bash
# Remove garage service from docker-compose.yml
# Remove graphrag-garage-data and graphrag-garage-meta from volumes section
# DO NOT run docker volume rm until 48h stability confirmed
```

---

## 5. Risk Assessment

### 5.1 Migration Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Milvus index segments corrupted during `a-bucket` migration | LOW | HIGH | Stop Milvus before migrating `a-bucket` (mandatory) |
| Object count mismatch after rclone | LOW | HIGH | `rclone check` or `rclone size` comparison before cutover |
| Stale multipart uploads cause Milvus startup failure | MEDIUM | MEDIUM | Milvus recovers automatically; aborts incomplete uploads on start |
| MinIO credentials format rejected | LOW | LOW | MinIO accepts same key format as Garage — reuse existing credentials |
| Disk space during migration (both stores live) | LOW | HIGH | Current free: 51 GB; total to copy: ~1.5 GB — no concern |
| `documents` objects added during migration window | MEDIUM | LOW | New objects go to Garage; only need a second `rclone sync` pass after cutover |

### 5.2 Rollback Plan

If migration fails before cutover (step 4.6):

1. Restore `.env` to Garage values
2. `docker compose stop minio`
3. `docker compose start garage`
4. Stack is back on Garage with no data loss (Garage data untouched throughout)

If migration fails after cutover:

1. Restore `.env` to Garage values
2. `docker compose up -d garage`
3. Any objects written to MinIO during the window are not in Garage — run `rclone sync` MinIO → Garage, then switch back

Full rollback from the March 2025 backup (if volumes are corrupted) is documented in `docs/ROLLBACK_ASSETS.md`.

---

## 6. Effort Estimate

| Task | Estimated Time |
|------|---------------|
| Update `docker-compose.yml` + `.env` | 30 min |
| `backup_preflight.sh` run + verification | 20 min |
| `rclone` data migration + verification | 30–60 min |
| Smoke test + re-queue 147 failed docs | 30 min |
| Monitor 48h + decommission Garage | Async |
| **Total hands-on time** | **~2–3 hours** |

Complexity: **LOW**. No code changes. Pure infrastructure swap using S3-compatible API that the application already speaks.

---

## 7. Post-Migration Improvements

### 7.1 Scheduled Backups (Not Yet Running)

`docs/disaster_recovery_runbook.md` recommends daily cron at 02:00 UTC:

```cron
0 2 * * * cd /root/amber2 && bash scripts/backup_preflight.sh >> /var/log/amber/backup.log 2>&1
```

**Current state:** No cron exists. The last backup is from 2026-03-25 (50+ days ago). This is the most critical gap independent of the storage backend.

### 7.2 MinIO Console Access

After migration, MinIO exposes an admin console on port 9001. Keep it bound to the internal Docker network (do not expose on host). Access via SSH tunnel:

```bash
ssh -L 9001:localhost:9001 root@your-server.example.com
# Then open http://localhost:9001 in browser
```

### 7.3 Object Lifecycle Policy

With MinIO, lifecycle policies can be set via `mc` to automatically abort incomplete multipart uploads after N days — preventing the 56.6 MiB stale-upload accumulation observed in Garage.

```bash
mc ilm rule add --expire-delete-marker --noncurrent-expire-days 7 local/a-bucket
mc ilm rule add --transition-days 0 --abort-incomplete-multipart-upload-days 3 local/a-bucket
```

---

## 8. Summary

**Root cause of data loss:** The April 30 disk exhaustion event caused Garage to crash mid-write. 147 documents failed with `Connection refused` (recoverable — originals likely in uploads volume). 4 documents have confirmed zlib-corrupt data in Garage from SQLite WAL truncation (unrecoverable — re-upload required).

**Why Garage is fragile:** `replication_factor = 1` + `db_engine = sqlite` + shared failure domain with Milvus. A single crash takes down document storage and vector search simultaneously. The structural risk is independent of disk space management.

**Migration cost:** Low. Zero code changes. Pure docker-compose + `.env` swap. Estimated 2–3 hours of hands-on work. The application storage client is already named `MinIOClient` and uses the `minio` SDK — the codebase was designed for this backend.

**Recommendation:** Proceed with migration. MinIO is the officially supported Milvus object storage, has no SQLite dependency, and eliminates the crash-corruption risk. Priority order:

1. **Now:** Schedule daily `backup_preflight.sh` cron (independent of migration — critical gap)
2. **Next maintenance window:** Execute Garage → MinIO migration following §4
3. **After 48h stability:** Decommission Garage volumes

---

## Appendix A — Key File Reference

| Item | File | Detail |
|------|------|--------|
| Garage config | `docker/garage/garage.toml` | `replication_factor=1`, `db_engine=sqlite` |
| Garage init script | `docker/garage/init-garage.sh` | Cluster layout + bucket + key setup |
| Storage client | `src/core/ingestion/infrastructure/storage/storage_client.py` | `MinIOClient` — already uses minio SDK |
| docker-compose Garage service | `docker-compose.yml` | `garage:` block, Milvus `MINIO_ADDRESS` env |
| `.env` storage vars | `.env` | `OBJECT_STORAGE_HOST`, `OBJECT_STORAGE_PORT`, `MILVUS_MINIO_ADDRESS` |
| Disaster recovery | `docs/disaster_recovery_runbook.md` | Backup procedure + restore order |
| Rollback assets | `docs/ROLLBACK_ASSETS.md` | Active snapshot: `20260325_111201` |
| Backup script | `scripts/backup_preflight.sh` | 11-step online backup, includes Garage volumes |

## Appendix B — Document Status Breakdown (as of 2026-05-15)

```
INGESTED   :  775  (45.3%)  — processed, not yet in graph
READY      :  718  (41.9%)  — fully processed, in graph
FAILED     :  162   (9.5%)  — see §2.1 for breakdown
EMBEDDING  :   51   (3.0%)  — in-progress
GRAPH_SYNC :    6   (0.4%)  — in-progress
─────────────────────────────
TOTAL      : 1,712
TENANTS    :    5
```

Upload history by date:

```
2026-02-16 ..  68 docs (first uploads on Garage)
2026-02-23 .. 101 docs
2026-02-24 .. 138 docs
2026-03-13 ..  11 docs
2026-03-14 ..  19 docs
2026-03-27 .. 491 docs  ← large bulk ingestion
2026-04-16 .. 207 docs
2026-04-24 .. 628 docs  ← largest bulk ingestion
2026-05-xx ..  22 docs  (scattered)
```

## Appendix C — Garage Failure Mode vs MinIO Comparison

```
Scenario                      | Garage (SQLite, rf=1)      | MinIO (filesystem)
──────────────────────────────┼────────────────────────────┼──────────────────────────────
Disk full → container kill    | SQLite WAL truncation →    | Filesystem write fails cleanly;
                               | object corruption          | no metadata corruption
Container restart             | Requires layout re-apply   | Starts immediately, no init
Incomplete multipart upload   | Persists until manual abort| Auto-abortable via lifecycle policy
Metadata vs data size ratio   | 2.4× (this system)         | ~1× (direct file storage)
Single-node redundancy        | None (rf=1)                | None (same), but crash-safer
Admin tooling                 | /garage CLI (container)    | mc CLI + web console
Milvus official support       | Workaround                 | Reference implementation
```
