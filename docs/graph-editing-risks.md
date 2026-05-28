# Graph Editing — Risk Assessment & Mitigations

Scope: user-facing graph edits (heal, connect, merge, prune, bulk-prune) and
the `graph_history` pending queue. Authorisation today is `verify_tenant_admin`
on `/graph/editor/*` endpoints. Bulk prune respects an internal cap.

## Risk catalogue

### 1. Concurrent edits create silent divergence

Two admins editing the same neighborhood through the UI can produce conflicting
pending actions (e.g. one merging entity `A` into `B`, the other queuing
`connect(A, C)`). The `graph_history` queue is append-only — there is no
optimistic lock and no conflict detection. The action that applies last wins;
the other becomes a dangling reference to a node that no longer exists.

**Likelihood**: medium (admin teams ≥ 2).
**Impact**: medium. Manifests as `404` on apply, or as broken neighborhoods.

**Mitigations in place**
- Pending queue: every edit lands in `graph_history` *before* hitting Neo4j.
  Reviewer can spot duplicates by inspecting the queue.
- All mutations are write-quorum (`platform.neo4j_client.execute_write`),
  so reads after apply are consistent.

**Mitigations to add**
- Display `pending_count` per node on the visualiser (already showing global
  badge — extend per neighborhood).
- Detect cross-action targets at queue insert time and warn the reviewer.

### 2. Malicious or careless bulk prune

`/graph/editor/bulk-prune` removes Entity nodes by criterion (`orphans`,
`leaves`). A misclick or a malicious operator could prune large slices of the
graph. Recovery requires restoring from backup (slow, lossy if recent ingestion).

**Likelihood**: low.
**Impact**: high.

**Mitigations in place**
- Two-step UX: client always runs `dry_run=true` first, displays the candidate
  list, asks explicit confirmation before issuing `dry_run=false`.
- Server-side hard cap: 5000 nodes per call, default 500. Even an automated
  loop cannot wipe the graph in one request.
- `verify_tenant_admin` gates the endpoint — anonymous traffic is blocked.

**Mitigations to add**
- Append a `bulk_prune` row to `graph_history` (currently bulk prune bypasses
  the queue) so that the action is auditable.
- Rate-limit `bulk-prune` per tenant (e.g. 1 call / 5 min).

### 3. Undo is best-effort

`graph_history` stores a snapshot for `prune` (`{node}`) so undo can recreate
the node. It does **not** snapshot edges or community membership; restoring a
pruned node returns an isolated entity with the original `name` but no
relationships. `merge` actions are not reversible at all because the source
nodes are deleted server-side.

**Likelihood**: certain when used.
**Impact**: low to medium. Loss of edges around a single pruned node is usually
recoverable by re-running ingestion on the source document.

**Mitigations in place**
- UI clearly labels pending actions; reviewer can reject before apply.

**Mitigations to add**
- Snapshot `[(source, target, type, description)]` around each pruned node so
  undo can restore the immediate neighborhood.
- Mark `merge` as irreversible in the UI confirmation dialog.

### 4. Semantic drift via heal acceptance

Heal suggestions are produced by vector similarity over chunks. Accepting many
low-confidence suggestions (`confidence < 0.6`) can densify the graph with
spurious edges that survive future re-ingestion and skew community detection.

**Likelihood**: medium.
**Impact**: medium.

**Mitigations in place**
- Confidence is displayed inline (badge colour gates on `>= 0.8`).
- Acceptance always lands in the pending queue first.

**Mitigations to add**
- Default-reject suggestions below a configurable floor in
  `tenant_config.graph_heal_min_confidence` (currently no floor enforced).
- Track suggested-vs-accepted ratio per admin in `usage_logs` so operators can
  audit their own bias.

### 5. Permission gap: tenant-admin can edit shared graph

When tenant `T` views documents shared from tenant `default` and edits the
graph via `/graph/editor/*`, the change is committed against the default
tenant's graph data (because Cypher writes match by Entity name, not by
`tenant_id`). This is intentional for the multi-tenant model, but it means a
tenant-admin can modify the source-of-truth graph.

**Likelihood**: medium (shared-corpora deployments).
**Impact**: medium to high.

**Mitigations in place**
- `verify_tenant_admin` blocks non-admin roles.

**Mitigations to add**
- Require `super_admin` for edits that touch entities whose `tenant_id !=
  caller_tenant_id`. Simple where-clause check in `graph_editor.py`.

## Open decisions

- Should `graph_history` retain actions indefinitely or be pruned after
  `apply`? (current behaviour: kept for audit, no TTL).
- Should bulk-prune respect group folder access? (today: scoped only by tenant).
- Should heal suggestions be visible to non-super-admin tenants when the source
  context belongs to `default`? (today: yes).

## Operator runbook (quick)

| Symptom | Action |
| --- | --- |
| Graph health shows `orphan_nodes` > 10% | Anomalies panel → `Prune orphans` (dry-run first) |
| Communities skewed (max degree huge) | Inspect `dense_communities`, manually merge or rerun Leiden |
| Pending actions stuck | History modal → review + apply or reject. Old entries can be marked `discarded`. |
| Bulk prune by mistake | Restore Postgres + Neo4j snapshot from latest backup. Ingestion will rebuild chunks but graph edits are lost unless `graph_history` retained the action. |
