# Shared GraphRAG Restore Drill

<!-- markdownlint-disable MD013 -->

## Purpose

This document defines the restore drill required before any Shared GraphRAG migration step that changes production read or write paths.

## Principle

The restore drill must be isolated from live production. Do not restore over the production containers during the drill.

## Required Inputs

The drill must use one consistent backup window containing:

- PostgreSQL dump
- Neo4j dump or snapshot
- Milvus + Etcd + object storage snapshot set
- document storage manifest
- tenant inventory exports

## Target Environment

Use one of:

- a temporary host
- an isolated Docker Compose project with separate volumes and ports
- a disposable VM

Do not attach the drill environment to production volumes or production Redis.

## Restore Sequence

1. Provision isolated Postgres, Neo4j, Milvus, Etcd, and object storage services.
2. Restore PostgreSQL from the dump.
3. Restore Neo4j from the matching graph dump or snapshot.
4. Restore object storage data for documents and Milvus blobs.
5. Restore Etcd and Milvus state from the same backup window.
6. Start Amber API and worker against the isolated services.
7. Run smoke checks.

## Minimum Smoke Checks

### Tenant inventory

```bash
curl -s http://<isolated-api>/v1/admin/tenants   -H 'Authorization: Bearer <admin-token>'
```

### Shared document list

```bash
curl -s http://<isolated-api>/v1/documents   -H 'X-Tenant-ID: default'   -H 'Authorization: Bearer <api-key-or-token>'
```

### Document detail

Use one known shared Carbonio document ID and verify stats are populated.

### Retrieval smoke test

```bash
curl -s http://<isolated-api>/v1/query   -H 'Content-Type: application/json'   -H 'X-Tenant-ID: default'   -H 'Authorization: Bearer <api-key-or-token>'   -d '{"query":"How do Carbonio admin roles work?"}'
```

### Neo4j smoke test

```bash
docker exec -i <isolated-neo4j-container>   cypher-shell -u neo4j -p <password>   "MATCH (e:Entity) RETURN count(e);"
```

### Milvus smoke test

```bash
docker exec -i <isolated-api-container> python - <<'PYTHON_EOF'
from pymilvus import Collection, connections, utility
connections.connect(alias='default', host='milvus', port='19530')
for name in sorted(utility.list_collections()):
    print(name, Collection(name).num_entities)
PYTHON_EOF
```

## Drill Pass Criteria

The drill passes only if:

- tenant inventory loads successfully
- shared documents are visible in `default`
- one representative query returns sources
- Neo4j and Milvus both show non-empty restored state
- no production service or production volume was touched

## Drill Failure Criteria

The drill fails if any of the following occur:

- Postgres restores but Neo4j or Milvus cannot be restored from the same window
- retrieved results are empty for known-good shared docs
- object storage references are broken
- the environment accidentally points to live production services

## Output Artifacts

Save these artifacts for sign-off:

- restored service versions and container names
- command transcript
- smoke-test outputs
- tenant/document/vector/graph counts
- final pass/fail summary

No migration step that changes the production read path should proceed until this drill is recorded as passed.
