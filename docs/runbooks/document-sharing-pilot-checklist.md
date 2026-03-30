# Document Sharing Pilot Checklist

<!-- markdownlint-disable MD013 -->

## Purpose

This checklist closes the pilot rollout for Shared GraphRAG document sharing without changing or deleting historical data.

The pilot tenant is currently:

- `7eb7ef04-190c-4ec0-8717-b6db31caa683` = `Product Enablement`

## Scope

This checklist validates that:

- `default` can own the canonical Carbonio corpus
- Product Enablement can see only the `default` documents explicitly shared to it
- vector and graph retrieval honor document-level ACL
- admin operators have the minimum observability needed for rollout

This checklist does not authorize cleanup of duplicated historical rows, vectors, or graph artifacts.

## Preconditions

Proceed only if all are true:

- `amber2-api-1` is healthy
- `alembic current` is `20260327_1900` or newer
- `document_shares` read path is live
- ACL-aware vector retrieval is enabled
- ACL-aware graph retrieval is enabled
- the dev or admin operator has a valid super admin key

## Feature Flag Snapshot

Capture the runtime flags before the pilot sign-off:

```bash
docker exec -i amber2-api-1 python - <<'PYTHON_EOF'
from src.api.config import settings
print("enable_document_share_management =", settings.enable_document_share_management)
print("enable_upload_time_document_shares =", settings.enable_upload_time_document_shares)
print("enable_acl_aware_vector_retrieval =", settings.enable_acl_aware_vector_retrieval)
print("enable_acl_aware_graph_retrieval =", settings.enable_acl_aware_graph_retrieval)
PYTHON_EOF
```

Expected result:

- all four flags print `True`

## Pilot Validation Steps

### 1. Confirm tenant inventory

```bash
curl -s http://localhost:8000/v1/admin/tenants \
  -H 'Authorization: Bearer <super-admin-key>'
```

Check that:

- `default` exists
- `Product Enablement` exists

### 2. Confirm shared visibility in Product Enablement

```bash
curl -s 'http://localhost:8000/v1/documents?limit=200' \
  -H 'Authorization: Bearer <product-enablement-key>' \
  -H 'X-Tenant-ID: 7eb7ef04-190c-4ec0-8717-b6db31caa683'
```

Check that:

- the response contains both local and shared documents
- at least one document has:
  - `"is_shared": true`
  - `"owner_tenant_id": "default"`

### 3. Confirm cross-tenant access is denied

Use a Product Enablement-scoped key against the `default` tenant:

```bash
curl -i 'http://localhost:8000/v1/documents?limit=1' \
  -H 'Authorization: Bearer <product-enablement-key>' \
  -H 'X-Tenant-ID: default'
```

Expected result:

- HTTP `403`

### 4. Confirm a shared document resolves full detail

Pick one known `default` document shared to Product Enablement and verify:

```bash
curl -s 'http://localhost:8000/v1/documents/<shared-doc-id>' \
  -H 'Authorization: Bearer <product-enablement-key>' \
  -H 'X-Tenant-ID: 7eb7ef04-190c-4ec0-8717-b6db31caa683'
```

Expected checks:

- document detail loads
- `is_shared` is `true`
- stats are populated

### 5. Confirm shared sub-endpoints

Run all of:

```bash
curl -s 'http://localhost:8000/v1/documents/<shared-doc-id>/chunks' \
  -H 'Authorization: Bearer <product-enablement-key>' \
  -H 'X-Tenant-ID: 7eb7ef04-190c-4ec0-8717-b6db31caa683'

curl -s 'http://localhost:8000/v1/documents/<shared-doc-id>/entities' \
  -H 'Authorization: Bearer <product-enablement-key>' \
  -H 'X-Tenant-ID: 7eb7ef04-190c-4ec0-8717-b6db31caa683'

curl -s 'http://localhost:8000/v1/documents/<shared-doc-id>/relationships' \
  -H 'Authorization: Bearer <product-enablement-key>' \
  -H 'X-Tenant-ID: 7eb7ef04-190c-4ec0-8717-b6db31caa683'

curl -s 'http://localhost:8000/v1/documents/<shared-doc-id>/communities' \
  -H 'Authorization: Bearer <product-enablement-key>' \
  -H 'X-Tenant-ID: 7eb7ef04-190c-4ec0-8717-b6db31caa683'

curl -s 'http://localhost:8000/v1/documents/<shared-doc-id>/similarities' \
  -H 'Authorization: Bearer <product-enablement-key>' \
  -H 'X-Tenant-ID: 7eb7ef04-190c-4ec0-8717-b6db31caa683'
```

Expected result:

- each endpoint responds `200`
- at least one representative endpoint returns non-empty rows

### 6. Confirm share management protections

```bash
curl -i 'http://localhost:8000/v1/documents/<shared-doc-id>/shares' \
  -H 'Authorization: Bearer <product-enablement-key>' \
  -H 'X-Tenant-ID: 7eb7ef04-190c-4ec0-8717-b6db31caa683'
```

Expected result:

- HTTP `403`

### 7. Confirm retrieval path uses shared document

Run one `basic` and one `global` query scoped to the shared document:

```bash
curl -s http://localhost:8000/v1/query \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <product-enablement-key>' \
  -H 'X-Tenant-ID: 7eb7ef04-190c-4ec0-8717-b6db31caa683' \
  -d '{"query":"What does this shared Carbonio document describe?","mode":"basic","filters":{"document_ids":["<shared-doc-id>"]}}'

curl -s http://localhost:8000/v1/query \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <product-enablement-key>' \
  -H 'X-Tenant-ID: 7eb7ef04-190c-4ec0-8717-b6db31caa683' \
  -d '{"query":"Summarize this shared Carbonio document","mode":"global","filters":{"document_ids":["<shared-doc-id>"]}}'
```

Expected result:

- both requests return sources
- the shared document appears in the cited sources
- the `global` path completes without leaking unrelated `default` documents

### 8. Confirm observability endpoints

```bash
curl -s 'http://localhost:8000/v1/admin/observability/document-shares/summary' \
  -H 'Authorization: Bearer <super-admin-key>'

curl -s 'http://localhost:8000/v1/admin/observability/document-shares/audit?limit=20' \
  -H 'Authorization: Bearer <super-admin-key>'
```

Check that:

- `summary` returns `share_row_count` and `shared_document_count`
- `summary` returns feature flag snapshot and query metrics
- `audit` returns recent share mutations when new share operations were performed through the service layer

## Pass Criteria

The pilot is considered passed only if all are true:

- Product Enablement sees both local docs and explicitly shared `default` docs
- cross-tenant access is denied
- shared document detail and sub-endpoints resolve
- both vector and graph retrieval cite the shared document
- observability endpoints respond successfully
- no production data cleanup was required to pass the checks

## Failure Handling

If any pilot step fails:

1. stop rollout changes for additional tenants
2. capture the exact failing request and tenant context
3. inspect `document_shares`, feature flags, and retrieval trace output
4. if needed, disable the affected runtime path with the appropriate feature flag
5. do not delete historical duplicate data as a mitigation

## Sign-Off Record

Record:

- date and operator
- API container health
- Alembic head
- test tenant used
- shared document ID used for retrieval validation
- pass or fail outcome
- follow-up actions, if any
