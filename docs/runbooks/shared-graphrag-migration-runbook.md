# Shared GraphRAG Migration Runbook

<!-- markdownlint-disable MD013 -->

## Purpose

This runbook defines the safety procedure for the Shared GraphRAG migration.
The goal is to stop creating new tenant duplicates and move toward a model where
`default` owns the shared Carbonio corpus while child tenants query `default + tenant overlay`.

## Scope

This runbook covers only pre-migration safety and operator procedure. It does not
authorize destructive cleanup of existing duplicate documents, chunks, vectors, or graph data.

## Hard Rules

1. Do not run `scripts/backup.sh` or `scripts/restore.sh` as the primary migration safety path.
2. Do not delete tenant-local rows or vector collections during the first rollout waves.
3. Do not use tenant provisioning to copy shared corpus into child tenants unless a recovery scenario has been approved.
4. Keep `ENABLE_TENANT_PROVISIONING=false` during the migration by default.

## Production Baseline To Capture

Capture all of the following before the first rollout:

### PostgreSQL inventory

```bash
docker exec -i amber2-postgres-1   psql -U graphrag -d graphrag   -c "select tenant_id, count(*) as documents from documents group by tenant_id order by tenant_id;"

docker exec -i amber2-postgres-1   psql -U graphrag -d graphrag   -c "select tenant_id, count(*) as chunks from chunks group by tenant_id order by tenant_id;"
```

### Shared filename overlap

```bash
docker exec -i amber2-postgres-1   psql -U graphrag -d graphrag   -c "select count(*) as shared_filenames from (select filename from documents where tenant_id='default' intersect select filename from documents where tenant_id='7eb7ef04-190c-4ec0-8717-b6db31caa683') t;"
```

### Neo4j graph inventory

```bash
docker exec -i amber2-neo4j-1   cypher-shell -u neo4j -p graphrag123   "MATCH (d:Document) RETURN d.tenant_id, count(d) ORDER BY d.tenant_id;"

docker exec -i amber2-neo4j-1   cypher-shell -u neo4j -p graphrag123   "MATCH (e:Entity) RETURN e.tenant_id, count(e) ORDER BY e.tenant_id;"
```

### Milvus collection inventory

```bash
docker exec -i amber2-api-1 python - <<'PYTHON_EOF'
from pymilvus import Collection, connections, utility
connections.connect(alias='default', host='milvus', port='19530')
for name in sorted(utility.list_collections()):
    print(name, Collection(name).num_entities)
PYTHON_EOF
```

## Infrastructure-Level Backup Requirements

Create one consistent backup window containing:

- PostgreSQL logical dump
- Neo4j dump or volume snapshot
- Milvus-related volume snapshots taken from the same window
  - Milvus
  - Etcd
  - object storage backing Milvus
- document storage manifest with content hashes and object paths
- exported tenant inventory results from the commands above

## Recommended Backup Window Procedure

1. Announce a write-sensitive maintenance window to operators.
2. Pause non-essential admin mutations.
3. Capture PostgreSQL logical dump.
4. Capture Neo4j snapshot or dump.
5. Capture Milvus, Etcd, and object storage snapshots from the same time window.
6. Export the inventory commands above into timestamped files.
7. Save all artifacts under a single timestamped backup directory.

## Provisioning Freeze

Legacy tenant provisioning is now expected to stay disabled by default.

To verify current runtime intent:

```bash
python - <<'PYTHON_EOF'
from src.api.config import settings
print('ENABLE_TENANT_PROVISIONING =', settings.enable_tenant_provisioning)
PYTHON_EOF
```

Only enable it for controlled recovery or migration operations, and disable it immediately afterward.

## Go / No-Go Before Implementation

Proceed only if all are true:

- A fresh infrastructure-level backup exists
- Inventory snapshot is saved
- Restore drill owner and target environment are defined
- `ENABLE_TENANT_PROVISIONING` is confirmed false

Abort rollout if any are false.
