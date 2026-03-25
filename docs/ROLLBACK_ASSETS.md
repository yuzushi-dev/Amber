# Rollback Assets

This document records the exact restore commands for every stateful service in the Amber2 production stack. Update the **Active Snapshot** section each time `scripts/backup_preflight.sh` is run successfully.

## Active Snapshot

| Field | Value |
|---|---|
| Snapshot timestamp | `20260325_111201` |
| Backup directory | `/root/amber2/backups/preflight_20260325_111201/` |
| Git commit at snapshot | `d2c9d9610fdff5b4c55415c4c3dba151622d599a` |
| Restore drill verified | 2026-03-25 (Postgres drill passed; see `restore_drill_*.log`) |

## Custom Image Digests

These are the image SHAs running at snapshot time. Image tarballs are **not saved by default** (too large). If the images are still present on the host, rollback is via `docker tag`. If not, rebuild from the pinned git commit above.

```
amber2-api:latest     sha256:d70d0751de2b310735ed6bb83e60d7cb6ea0748c8eea7d0d64e533b5de199418
amber2-worker:latest  sha256:f24eb91f0254bf979de325aefa3235793802b5c187317c86e35fe11ca650f2a2
amber2-frontend:latest sha256:5d61902ebed51a87f21161b2b52f271e8e5a9952d5257332fe5105d70f68882e
```

To roll back to a prior image by digest:
```bash
docker tag sha256:<digest> amber2-api:latest
# then: cd /root/amber2 && docker compose up -d api
```

To save image tarballs for offline rollback (run once, ~3GB):
```bash
docker save amber2-api amber2-worker amber2-frontend \
  | gzip > /root/amber2/backups/preflight_20260325_111201/custom_images_20260325_111201.tar.gz
```

## PostgreSQL

**Artifact:** `backups/preflight_20260325_111201/postgres_20260325_111201.sql.gz` (7MB)
**Method:** Online `pg_dump` — fully consistent.

### Restore (isolated drill target)
```bash
# Spin up an isolated container to verify the dump
docker run -d --name pg-restore-drill \
  -e POSTGRES_PASSWORD=drillpass -e POSTGRES_DB=drilldb \
  postgres:16-alpine
sleep 5
zcat backups/preflight_20260325_111201/postgres_20260325_111201.sql.gz \
  | docker exec -i pg-restore-drill psql -U postgres -d drilldb -q
docker exec pg-restore-drill psql -U postgres -d drilldb -c "SELECT count(*) FROM documents;"
docker rm -f pg-restore-drill
```

### Restore (live — use only during rollback)
```bash
# WARNING: this overwrites live data. Only run during an active rollback.
docker stop amber2-api-1 amber2-worker-1
docker exec -i amber2-postgres-1 psql -U graphrag -d graphrag -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
zcat backups/preflight_20260325_111201/postgres_20260325_111201.sql.gz \
  | docker exec -i amber2-postgres-1 psql -U graphrag -d graphrag -q
docker start amber2-api-1 amber2-worker-1
```

## Redis

**Artifact:** `backups/preflight_20260325_111201/redis_20260325_111201.rdb` (1.2MB)
**Method:** `BGSAVE` + `docker cp` — point-in-time RDB snapshot.

### Restore (live — use only during rollback)
```bash
docker stop amber2-redis-1
docker run --rm \
  -v amber2_graphrag-redis:/data \
  -v /root/amber2/backups/preflight_20260325_111201/redis_20260325_111201.rdb:/dump.rdb:ro \
  alpine cp /dump.rdb /data/dump.rdb
docker start amber2-redis-1
docker exec amber2-redis-1 redis-cli DBSIZE
```

## Neo4j

**Artifact:** `backups/preflight_20260325_111201/neo4j_volume_20260325_111201.tar.gz` (135MB)
**Method:** Crash-consistent volume tar taken while Neo4j was running.
**Caveat:** Neo4j Community does not support online logical backup. This snapshot is crash-consistent. Neo4j will run transaction log recovery on first start after restore if it was mid-write at snapshot time. This is automatic and expected.

### Restore (live — use only during rollback)
```bash
docker stop amber2-api-1 amber2-worker-1 amber2-neo4j-1
docker run --rm -v amber2_graphrag-neo4j:/data alpine sh -c 'rm -rf /data/*'
docker run --rm \
  -v amber2_graphrag-neo4j:/data \
  -v /root/amber2/backups/preflight_20260325_111201/neo4j_volume_20260325_111201.tar.gz:/backup.tar.gz:ro \
  alpine tar -xzf /backup.tar.gz -C /data
docker start amber2-neo4j-1
# Wait for neo4j healthy, then restart api and worker
docker exec amber2-neo4j-1 neo4j-admin dbms check-consistency --database=neo4j 2>/dev/null || true
docker start amber2-api-1 amber2-worker-1
```

## Milvus and Etcd

**Artifacts:**
- `backups/preflight_20260325_111201/milvus_volume_20260325_111201.tar.gz` (67MB)
- `backups/preflight_20260325_111201/etcd_volume_20260325_111201.tar.gz` (47MB)

**Method:** Crash-consistent volume tars. Milvus and etcd must be restored together — etcd holds Milvus metadata and must match the milvus data volume.

### Restore (live — use only during rollback)
```bash
docker stop amber2-api-1 amber2-worker-1 amber2-milvus-1 amber2-etcd-1

# Restore etcd first (Milvus metadata)
docker run --rm -v amber2_graphrag-etcd:/data alpine sh -c 'rm -rf /data/*'
docker run --rm \
  -v amber2_graphrag-etcd:/data \
  -v /root/amber2/backups/preflight_20260325_111201/etcd_volume_20260325_111201.tar.gz:/bk.tar.gz:ro \
  alpine tar -xzf /bk.tar.gz -C /data

# Restore Milvus data
docker run --rm -v amber2_graphrag-milvus:/data alpine sh -c 'rm -rf /data/*'
docker run --rm \
  -v amber2_graphrag-milvus:/data \
  -v /root/amber2/backups/preflight_20260325_111201/milvus_volume_20260325_111201.tar.gz:/bk.tar.gz:ro \
  alpine tar -xzf /bk.tar.gz -C /data

docker start amber2-etcd-1 amber2-milvus-1
# Wait for both healthy, then restart api and worker
docker start amber2-api-1 amber2-worker-1
```

## Garage Object Storage

**Artifacts:**
- `backups/preflight_20260325_111201/garage-data_volume_20260325_111201.tar.gz` (175MB)
- `backups/preflight_20260325_111201/garage-meta_volume_20260325_111201.tar.gz` (877MB)

**Method:** Crash-consistent volume tars. Garage uses SQLite as its metadata backend. Both volumes must be restored together.

### Restore (live — use only during rollback)
```bash
docker stop amber2-garage-1

docker run --rm -v amber2_graphrag-garage-data:/data alpine sh -c 'rm -rf /data/*'
docker run --rm \
  -v amber2_graphrag-garage-data:/data \
  -v /root/amber2/backups/preflight_20260325_111201/garage-data_volume_20260325_111201.tar.gz:/bk.tar.gz:ro \
  alpine tar -xzf /bk.tar.gz -C /data

docker run --rm -v amber2_graphrag-garage-meta:/data alpine sh -c 'rm -rf /data/*'
docker run --rm \
  -v amber2_graphrag-garage-meta:/data \
  -v /root/amber2/backups/preflight_20260325_111201/garage-meta_volume_20260325_111201.tar.gz:/bk.tar.gz:ro \
  alpine tar -xzf /bk.tar.gz -C /data

docker start amber2-garage-1
docker exec amber2-garage-1 /garage bucket list
```

## Config Rollback

Config snapshots are in `backups/preflight_20260325_111201/config/`:
- `env.snapshot` — restore to `.env`
- `docker-compose.yml.snapshot` — restore to `docker-compose.yml`
- `garage.toml.snapshot` — restore to `docker/garage/garage.toml`

```bash
cp backups/preflight_20260325_111201/config/env.snapshot .env
cp backups/preflight_20260325_111201/config/docker-compose.yml.snapshot docker-compose.yml
cp backups/preflight_20260325_111201/config/garage.toml.snapshot docker/garage/garage.toml
```

## Full Stack Rollback Order

If a wave cutover fails and full rollback is needed, execute in this order:

1. Switch traffic back to old stack (reverse the cutover step)
2. Restore config files
3. Restore PostgreSQL
4. Restore Redis
5. Restore etcd + Milvus together
6. Restore Neo4j
7. Restore Garage (data + meta together)
8. Roll back images to prior digest if new images were deployed
9. Restart: `cd /root/amber2 && docker compose up -d`
10. Verify: `curl -sf http://127.0.0.1:8000/health/ready`

## Stale Scripts Warning

The following scripts in `scripts/` reference old container names and MinIO/SeaweedFS paths and **must not be used** for rollback until updated and re-verified:
- `scripts/backup.sh`
- `scripts/restore.sh`
- `scripts/backup_amber.sh`
- `docs/disaster_recovery_runbook.md` (partially stale)
