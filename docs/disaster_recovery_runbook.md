# Disaster Recovery Runbook

<!-- markdownlint-disable MD013 -->

## Overview

This document covers backup and restore procedures for the Amber2 production
stack. For exact per-service restore commands and the active snapshot reference,
see [`docs/ROLLBACK_ASSETS.md`](ROLLBACK_ASSETS.md).

### Stateful Components

| Service | What it holds | Backup method |
|---|---|---|
| **PostgreSQL** | Tenants, users, documents, ACLs, RLS policies | Online `pg_dump` (consistent) |
| **Neo4j** | Knowledge graph — entities and relationships | Crash-consistent volume tar |
| **Milvus** | Vector embeddings (HNSW dense + SPLADE sparse) | Crash-consistent volume tar |
| **etcd** | Milvus metadata — must match Milvus data volume | Crash-consistent volume tar |
| **Garage** | Raw documents and Milvus object data (S3-compatible) | Crash-consistent volume tars (data + meta) |
| **Redis** | Rate-limit state, session cache | `BGSAVE` + `docker cp` (point-in-time RDB) |
| **uploads** | Local file staging area | Crash-consistent volume tar |

> **Garage** is the live S3-compatible object storage (dxflrs/garage:v1.1.0).
> It uses a SQLite metadata backend split across two Docker volumes:
> `amber2_graphrag-garage-data` (objects) and `amber2_graphrag-garage-meta`
> (SQLite). Both volumes must always be restored together from the same
> snapshot.

---

## Backup

### Script: `scripts/backup_preflight.sh`

This is the single canonical backup tool. It is **safe to run on a live
production stack**: PostgreSQL and Redis use online capture methods; all other
components use crash-consistent volume tars that do not require stopping any
service.

**Always dry-run first:**

```bash
cd /root/amber2
bash scripts/backup_preflight.sh --dry-run
```

Inspect the output. If everything looks correct, run for real:

```bash
bash scripts/backup_preflight.sh
```

**Output location:** `backups/preflight_<YYYYMMDD_HHMMSS>/`

### What the script captures (11 steps)

| Step | Artifact | Location |
|---|---|---|
| 1 | Git state (HEAD commit, dirty files) | `backups/manifests/<ts>-git.txt` |
| 2 | Container and image manifest (with custom image SHAs) | `backups/manifests/<ts>-containers.txt`, `-images.txt` |
| 3 | Docker volume inventory | `backups/manifests/<ts>-volumes.txt` |
| 4 | Config snapshots (`.env`, `docker-compose.yml`, `garage.toml`) | `backups/preflight_<ts>/config/` |
| 5 | PostgreSQL dump — online, gzip-compressed | `postgres_<ts>.sql.gz` |
| 6 | Redis RDB snapshot — `BGSAVE` then `docker cp` | `redis_<ts>.rdb` |
| 7 | Neo4j volume tar (crash-consistent) | `neo4j_volume_<ts>.tar.gz` |
| 8 | Milvus + etcd volume tars (crash-consistent, captured together) | `milvus_volume_<ts>.tar.gz`, `etcd_volume_<ts>.tar.gz` |
| 9 | Garage data + meta volume tars (crash-consistent, captured together) | `garage-data_volume_<ts>.tar.gz`, `garage-meta_volume_<ts>.tar.gz` |
| 10 | Uploads volume tar | `uploads_volume_<ts>.tar.gz` |
| 11 | Live health evidence (container states, `/health/ready`) | `backups/manifests/<ts>-health.txt` |

### Preflight guards

The script aborts the real run (dry-run just warns) if:

- Less than **20 GB** free disk space on the repo partition.
- Any of the 8 required containers (`amber2-api-1`, `amber2-worker-1`,
  `amber2-postgres-1`, `amber2-redis-1`, `amber2-neo4j-1`, `amber2-milvus-1`,
  `amber2-etcd-1`, `amber2-garage-1`) is not in `running` state.
- `POSTGRES_USER` or `POSTGRES_DB` cannot be read from `.env`.

### Custom image tarballs

Custom images (`amber2-api`, `amber2-worker`, `amber2-frontend`) are **not**
saved by default (~3 GB). Save them manually when needed for offline rollback:

```bash
docker save amber2-api amber2-worker amber2-frontend \
  | gzip > /root/amber2/backups/preflight_<ts>/custom_images_<ts>.tar.gz
```

To roll back to a prior image by digest:

```bash
docker tag sha256:<digest> amber2-api:latest
cd /root/amber2 && docker compose up -d api
```

Image SHAs at the last successful snapshot are recorded in
[`docs/ROLLBACK_ASSETS.md`](ROLLBACK_ASSETS.md) under **Custom Image Digests**.

### Scheduling backups

Run daily at 02:00 UTC (adapt path if the project root moves):

```cron
0 2 * * * cd /root/amber2 && bash scripts/backup_preflight.sh >> /var/log/amber/backup.log 2>&1
```

---

## Restore

> **Warning:** Restoring overwrites live data. Always confirm the snapshot is
> valid before proceeding. Stop writers (`api`, `worker`) before any restore
> step to prevent in-flight writes corrupting the target.

For exact, copy-pasteable restore commands for each service, see
[`docs/ROLLBACK_ASSETS.md`](ROLLBACK_ASSETS.md). That document records the
active snapshot timestamp and all restore commands against it.

### Full stack rollback order

If a deployment fails and a full rollback is required, execute in this order:

1. Reverse traffic (re-run `deploy/cutover.sh` pointing to the prior lane, or
   restore `nginx` config).
2. Restore config files (`.env`, `docker-compose.yml`, `garage.toml`) from
   `backups/preflight_<ts>/config/`.
3. Restore PostgreSQL.
4. Restore Redis.
5. Restore etcd + Milvus **together** from the same snapshot window.
6. Restore Neo4j.
7. Restore Garage **data + meta together** from the same snapshot window.
8. Roll back custom images to the prior digest (if new images were deployed).
9. Restart the full stack:

   ```bash
   cd /root/amber2 && docker compose up -d
   ```

10. Verify:

    ```bash
    curl -sf http://127.0.0.1:8000/health/ready
    ```

### Partial restore

To restore a single component, copy the relevant `docker stop / tar / docker
start` block from `ROLLBACK_ASSETS.md` for that service only.

### Restore drill

After every backup, run an isolated drill to confirm the PostgreSQL dump is
restorable without touching production:

```bash
# Spin up a temporary container, load the dump, verify row counts, tear down
docker run -d --name pg-restore-drill \
  -e POSTGRES_PASSWORD=drillpass -e POSTGRES_DB=drilldb \
  postgres:16-alpine
sleep 5
zcat backups/preflight_<ts>/postgres_<ts>.sql.gz \
  | docker exec -i pg-restore-drill psql -U postgres -d drilldb -q
docker exec pg-restore-drill psql -U postgres -d drilldb \
  -c "SELECT count(*) FROM documents;"
docker rm -f pg-restore-drill
```

A passing drill is logged in `ROLLBACK_ASSETS.md` under **Restore drill
verified**.

---

## Troubleshooting

### PostgreSQL won't start after restore

Check that the schema was dropped cleanly before loading the dump:

```bash
docker exec -i amber2-postgres-1 psql -U graphrag -d graphrag \
  -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
```

Then re-apply the dump. If the restore was interrupted, the database may be in
a partial state — drop and recreate the schema, then reload.

### Milvus/etcd inconsistency after restore

Milvus and etcd are paired — etcd holds all Milvus collection metadata. If only
one is restored, Milvus will fail to start or report missing collections.
Always restore both volumes from the **same** snapshot timestamp. If the data
is unrecoverable, re-index from scratch:

```bash
cd /root/amber2
docker compose up -d
# Then re-trigger ingestion for all documents via the API
```

### Garage object storage inconsistency

Garage uses SQLite as its metadata backend (stored in the `garage-meta`
volume). If data and meta volumes are out of sync, objects may appear present
but be unreadable, or buckets may disappear. Always restore both volumes
together. After restore, verify:

```bash
docker exec amber2-garage-1 /garage bucket list
docker exec amber2-garage-1 /garage stats
```

### Neo4j fails to start after restore

Neo4j Community does not support online consistent backup. The volume tar is
crash-consistent. On first start after restore, Neo4j runs automatic
transaction log recovery — this is expected and benign. If Neo4j still fails,
try:

```bash
docker exec amber2-neo4j-1 neo4j-admin dbms check-consistency \
  --database=neo4j 2>/dev/null
```

For a fully consistent graph backup, stop Neo4j first:

```bash
docker stop amber2-api-1 amber2-worker-1 amber2-neo4j-1
docker exec amber2-neo4j-1 neo4j-admin database dump --to-path=/backups neo4j
```

### Permission errors

All Docker volume operations require a user with access to the Docker socket
(typically `root` or a member of the `docker` group). Run `backup_preflight.sh`
as `root` from `/root/amber2`.

### Not enough disk space

The script aborts if less than 20 GB is free. Check:

```bash
df -h /root/amber2
```

Old backup directories can be deleted once the restore drill for the current
snapshot has passed and the entry in `ROLLBACK_ASSETS.md` has been updated.

---

## Deprecated Scripts

The following scripts predate v1.1.0 and reference container names, paths, and
storage backends that no longer exist. **Do not use them:**

| Script | Reason |
|---|---|
| `scripts/backup.sh` | Old MinIO-based backup; references non-existent MinIO container |
| `scripts/restore.sh` | Old MinIO-based restore; incorrect container names |
| `scripts/backup_amber.sh` | Legacy wrapper; superseded by `backup_preflight.sh` |
| `scripts/storage_manifest.py` | MinIO manifest tool; no equivalent needed for Garage |
| `scripts/storage_sync.sh` | MinIO→SeaweedFS sync tool; migration never deployed |
| `scripts/storage_compare.py` | Migration drift checker; no longer applicable |
| `scripts/seaweed_reconcile_tidy.sh` | SeaweedFS reconciliation; SeaweedFS was never deployed |

Use `scripts/backup_preflight.sh` exclusively.
