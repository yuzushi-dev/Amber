# Migration & cutover runbook

How to move Amber to another host, or deploy a release that touches the
datastores, without losing data.

Scope: the quiesce → backup → verify → restore-drill → cutover → rollback loop.
Everything here is either a script in this repo or a command you can paste.

Companion scripts:

| Script | What it does | Safe on production |
|---|---|---|
| `scripts/backup.sh` | takes the snapshot | yes — no container is stopped |
| `scripts/verify_backup.sh` | proves the snapshot is restorable | yes — read-only |
| `scripts/restore.sh` | restores into a project (drill, or a fresh host) | only against a non-production project |
| `scripts/smoke_production_readonly.sh` | post-cutover smoke | yes — read-only |
| `deploy/cutover.sh` | switches the nginx upstream live ⇄ canary | yes — nginx only, auto-rollback |

`scripts/backup_preflight.sh` is **obsolete**: it requires a running
`amber2-garage-1` and aborts, because Garage was replaced by MinIO. Do not put it
in a procedure. Use `backup.sh` + `verify_backup.sh`.

---

## 0. Preconditions — do not start until all of these hold

These are gates, not suggestions. Each one is a way to lose data that has
already been observed or read off the merged code.

- [ ] **`scripts/backup.sh` produces a replayable Neo4j dump.** The fix is commit
  `ffd4b1f3`; without it `apoc.export.cypher.all(null, {stream:true})` is piped
  through cypher-shell's result-cell rendering and the dump is not a script,
  while the log still says `APOC export OK`. `verify_backup.sh` fails the backup
  if this regresses, so the gate is: **`verify_backup.sh` exits 0.**

- [ ] **The recovery sweep never touches live work.** Closed by
  `recovery.STALE_MIN_AGE_MINUTES`: both the periodic and the boot-time sweep now
  skip documents updated within the last 30 minutes, and the blanket flush of
  `locks:process_communities:*` at worker boot is gone (the locks carry a 2h TTL
  and expire on their own). Verify it still holds — `tests/unit/test_recovery_boot_safety.py`
  fails if either regresses.
  Why it matters: the boot sweep used to run with no threshold, justified by
  "nothing is in-flight at startup", which stopped being true when
  `docker-compose.yml` declared `replicas: 3`. One restarting replica would mark
  the other two replicas' `EXTRACTING`/`CLASSIFYING` documents `FAILED` and reset
  `EMBEDDING`/`GRAPH_SYNC` ones to `INGESTED` and requeue them while the original
  task was still running under `task_acks_late=True` — the requeued run then
  executes the destructive pre-ingest cleanup (Milvus `delete_by_document`, Neo4j
  `DETACH DELETE`) concurrently with the original run's writes.
  There is still no per-document heartbeat, so `updated_at` only advances at
  stage transitions: a single stage running longer than 30 minutes can be swept.
  Watch the graph-sync duration on the new hardware.

- [ ] **A re-upload cannot destroy the only copy of the source file.** Closed in
  `_replace_document_content`: the object key now carries the content hash, so a
  replace writes a new object instead of overwriting the one it supersedes.
  `tests/unit/test_ingestion_register_document_replace.py` fails if the colliding
  key comes back.
  Why it matters: the id is preserved by design, so the old key was reused
  verbatim whenever the filename was unchanged, and `StorageClient.upload_file`
  is a plain `put_object` into a bucket created without versioning. The original
  bytes were unrecoverable, the pre-ingest cleanup then dropped the old vectors
  and graph nodes, and `provisioning_service` copies `storage_path` across tenants
  by reference — so the overwrite also mutated another tenant's document content.
  Superseded objects are not garbage-collected. Budget for the growth, or add a
  retention sweep over `{tenant}/{doc_id}/`.

- [ ] **`DEFAULT_LLM_MODEL` on the target host is not `gemma3:27b`.** Retired
  upstream, answers 410 on every key. Use `gemma4:31b-cloud`.
  `verify_backup.sh` warns when it sees the retired value in the env snapshot.

- [ ] **Memory limits re-derived for the target host.** The values in
  `docker-compose.yml` are calibrated for the 15 GB `amber-u24`: api 5500M +
  worker 3×2G + neo4j 2560M + minio 1G + milvus 1536M ≈ **16.5 GB of caps on
  15 GB of RAM**, with postgres, redis, etcd, nginx and celery_beat uncapped.
  Under host pressure the kernel OOM killer picks an uncapped process — Postgres
  or etcd. Milvus at 1536M is thin: an OOM-kill during a flush leaves segments
  inconsistent with the etcd metadata. Do not copy these numbers to a machine
  with different RAM without re-measuring.

---

## 0b. Cutover gates from the release review

An adversarial review of #20–#37 plus these commits approved the deploy
**conditional on all six of these**. They are the gate, not advice.

1. **Rebuild the images explicitly**: `docker compose build --no-cache api worker celery_beat`.
   Do not rely on a bind-mount-only `up -d` recreate. `api`, `worker` and
   `celery_beat` all mount `./src:ro` (`docker-compose.yml:114,229,303`, a line
   older than prod's own HEAD), so a recreate alone jumps a container's *code*
   forward 68 commits while its *installed dependencies* stay at whatever the
   image was built with. That is version skew inside one container, not between
   two.
2. **Fix `.env` `DEFAULT_LLM_MODEL` before any restart.** Env vars are read at
   startup; a restart with `gemma3:27b` still answers 410.
3. **Fresh backup + `verify_backup.sh` + a new restore drill** immediately before
   cutover. Not a drill from days earlier — 62+ commits of behaviour sit between.
4. **Recreate all 3 worker replicas and `celery_beat` in the same window**, never
   staggered: a stale-code replica still defaults to `min_age_minutes=0` and can
   sweep the fixed replicas' in-flight work on its own boot.
5. **`ENABLE_MULTITURN_HISTORY_REINJECTION` stays `False`.** Not flipped as part
   of this cutover — the `X-User-ID` trust boundary is what neutralises it.
6. **Throttle or pause ingestion fan-out during the window**, so no single
   document's GRAPH_SYNC runs past 30 minutes while a replica restarts. This is
   the one place `STALE_MIN_AGE_MINUTES` is probabilistic rather than absolute,
   and the one thing this deploy cannot fully close.

### Watch for the first hour

- `Requeued document ... for reprocess (was in EMBEDDING/GRAPH_SYNC state)` right
  after any replica restart. If it fires **and** two different task ids log
  `Pre-ingest cleanup` for the same `document_id`, that is the residual race
  actually happening, not a hypothetical.
- `Failed to invalidate result cache (... content replaced)` — logged at `error`
  precisely so it is not lost in warning noise. Means a replace left stale answers
  live until TTL.
- `worker` memory: expect child recycles around 800 MiB, **not** hard OOM-kills of
  the container. A hard kill means the ~400 MiB master headroom estimate is wrong.
- Confirm the api actually serves `gemma4:31b-cloud` after restart, not a cached
  410 from the retired model.

Not held back: the #20 and #22 fail-open ACL gaps have zero blast radius while
there are 0 `document_shares` and 0 `group_document_access` rows. They stop being
inert the day someone issues a group grant — re-read those two before that day.

### One note on the cache invalidation

`_invalidate_result_cache` clears the **whole tenant**, because cache keys are
`result:{tenant_id}:{query_hash}` and there is no per-document key to clear. Fine
at one tenant and replace-as-a-rare-event. It becomes a trap in a high-query
multi-tenant deployment, or if a bulk connector sync ever calls the replace path
in a loop — each iteration would re-nuke the tenant's cache and effectively
disable caching for the duration of the sync.

## 1. Quiesce ingestion

The window where a deploy or migration destroys data is the window where a
document is mid-pipeline. Close it first.

```bash
# 1. Stop new work from arriving: pause the ingestion-facing queues.
docker exec amber2-worker-1 celery -A src.workers.celery_app inspect active_queues

# 2. Watch until no document is in a processing state.
docker exec -i amber2-postgres-1 psql -U graphrag -d graphrag -c "
  SELECT status, count(*) FROM documents
  WHERE status IN ('INGESTED','EXTRACTING','CLASSIFYING','CHUNKING','EMBEDDING','GRAPH_SYNC')
  GROUP BY status ORDER BY status;"
```

Proceed when that query returns zero rows. If it will not drain, stop celery_beat
first so the 10-minute periodic sweep does not keep requeueing:

```bash
docker compose stop celery_beat
```

Do not run this during the nightly ingestion burst — that is the window the
memory limits of #25 were added to survive, and the one with the most documents
in flight.

## 2. Backup, then prove it

```bash
bash scripts/backup.sh --dry-run                     # read the plan
bash scripts/backup.sh --destination=/opt/backups/amber --retention=7
bash scripts/verify_backup.sh --backup=/opt/backups/amber/backup_YYYYmmdd_HHMMSS
```

`verify_backup.sh` must exit 0. It checks the `FAILED` marker, `SHA256SUMS`, the
Neo4j dump's replayability, that the Postgres TOC parses and contains
`TABLE DATA public documents`, that each tar is a valid non-empty gzip, that
`etcdutl snapshot status` can read `etcd.snap`, and that the env snapshot carries
`GRAPHRAG_APP_PASSWORD` (without it the RLS GRANTs never land on restore).

Read every WARN. Expected and benign today: `uploads.tar.gz` holds no files, the
legacy volume is empty now that uploads live in MinIO.

Two properties of `backup.sh` worth knowing before you rely on it:

- **Retention counts partial backups.** A snapshot taken with `--skip=` or
  `--include=` is rotated in like any other and can evict a complete one. Keep
  partial backups in a different `--destination`.
- **Milvus is tarred hot (step 4) and etcd snapshotted after (step 5).** Writes
  in between leave etcd metadata referencing segments that are not in the tar.
  This is why step 1 exists; for a host migration, quiescing is not optional.

## 3. Restore drill — the only proof that matters

Run it into a throwaway project on a machine that is not production. A backup is
not a backup until it has been restored.

```bash
bash scripts/restore.sh --backup=/path/to/backup_YYYYmmdd_HHMMSS \
                       --project=drill --dry-run
bash scripts/restore.sh --backup=/path/to/backup_YYYYmmdd_HHMMSS --project=drill
```

`restore.sh` runs `verify_backup.sh` as a preflight and refuses to restore an
artifact set that does not pass. It also refuses to touch a project whose
`graphrag-*` volumes already exist, and aborts if compose resolves any volume
outside the `${PROJECT}_` prefix.

Datastores only by default. `--with-app` starts api/worker/nginx with the **prod
env snapshot**: connectors and webhooks can make real outbound calls with
production credentials, and the worker's boot recovery sweep will rewrite
document statuses in the restored copy. Only pass it after sanitising outbound
side effects.

Parity checks against the source host — the numbers must match:

```bash
# Postgres
docker compose -p drill exec -T postgres psql -U graphrag -d graphrag -c "
  SELECT (SELECT count(*) FROM documents) AS documents,
         (SELECT count(*) FROM chunks)    AS chunks,
         (SELECT count(*) FROM document_shares) AS shares,
         (SELECT count(*) FROM group_document_access) AS group_grants;"

# Neo4j
docker compose -p drill exec -T neo4j cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH (n) RETURN labels(n)[0] AS label, count(*) ORDER BY label;"
```

For Milvus use a real `count(*)` query, not `num_entities` — the latter is stale
after a restore and will happily report the pre-restore figure.

Check `document_shares` and `group_document_access` explicitly: both cascade on
deletion of a document row, so they are the first thing a bad restore loses
quietly.

## 4. Migrate to the dedicated host

Same script, pointed at the real project on the new machine.

```bash
# On the new host, with the repo checked out at the commit you intend to run:
git rev-parse HEAD                        # record it; it belongs in the change log
cp /path/to/backup_*/config/.env.snapshot .env
# Edit .env: DEFAULT_LLM_MODEL=gemma4:31b-cloud, and any host-specific value.

bash scripts/restore.sh --backup=/path/to/backup_YYYYmmdd_HHMMSS \
                        --project=amber2 --repo="$PWD" --dry-run
bash scripts/restore.sh --backup=/path/to/backup_YYYYmmdd_HHMMSS \
                        --project=amber2 --repo="$PWD"
```

Then repeat the step 3 parity checks against `--project=amber2` before any
traffic reaches it. Re-run `alembic upgrade head` only if the target commit adds
a revision — the #20–#37 block adds none, the newest revision is
`20260603_1300_add_chunks_group_read_policy`.

Start the app only after parity passes:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## 5. Cutover

For a code release on an existing host, use the canary path — it never recreates
a datastore container:

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.canary.yml up -d api-canary
bash scripts/smoke_production_readonly.sh --base-url http://127.0.0.1:8001
bash deploy/cutover.sh --to canary --dry-run
bash deploy/cutover.sh --to canary
```

`cutover.sh` rewrites the nginx upstream and reloads; it runs the smoke suite
against the canary before switching and again after, and rolls back to `live`
by itself if the post-cutover smoke fails.

The canary is queue-isolated (`canary_*` queues, broker on redis db 1/2), so it
does not consume live work. It shares Postgres, Neo4j and Milvus, which is the
point — but it means a document ingested through `canary_ingestion` writes to
production data, including the destructive replace path of §0. Do not enqueue
ingestion at the canary to test it.

Applying the memory limits of #25 is the one step that does recreate containers:

```bash
docker compose up -d api worker            # brief downtime, in-flight tasks interrupted
```

Only do this after step 1 has drained the pipeline, and only with the §0 boot
sweep gate resolved.

## 6. Rollback

| Failure | Action |
|---|---|
| Canary is bad | `bash deploy/cutover.sh --to live` — instant, nginx only |
| New code is bad after cutover to live | check out the previous commit, `docker compose up -d api worker` |
| Data is wrong on the new host | stop the app, `docker compose -p amber2 down`, wipe the volumes, re-run `restore.sh` from the verified backup |
| Migration is abandoned | point DNS/traffic back at the old host; it was never written to after the quiesce |

Keep the old host intact and un-started until the new one has served traffic for
a full ingestion cycle. It is the real rollback.

## 7. After the migration

- Re-take a backup on the new host and run `verify_backup.sh` against it. The
  first backup on new hardware is the one most likely to reveal a wrong volume
  name or a missing tool.
- Confirm the recovery sweep did not mass-fail documents on first boot:
  ```bash
  docker logs amber2-worker-1 2>&1 | grep -E 'Stale document recovery|Marked document'
  docker exec -i amber2-postgres-1 psql -U graphrag -d graphrag -c "
    SELECT count(*) FROM documents WHERE status='FAILED'
      AND error_message LIKE 'Processing interrupted by worker restart%';"
  ```
  Anything above the pre-migration count means §0's second gate was not closed.
- Documents left `FAILED` have their chunks excluded from retrieval by the
  non-READY blocklist of #31, so they go quiet rather than erroring. Re-ingest
  them explicitly.

## Runtime state the backup does not carry

`backup.sh` covers postgres, neo4j, redis, milvus, etcd, minio, uploads and
config. It does **not** cover three pieces of runtime state that live outside both
the images and the data volumes, and a fresh host is broken in a specific way
without each. All three were found by running the restore drill, not by reading
the code.

| What | Where | Size | Symptom when missing |
|---|---|---|---|
| Python deps | `<project>_pip-packages` volume, on `PYTHONPATH` as `/app/.packages` | 6.1G | every query 500s with `torch and transformers are required for SparseEmbeddingService` |
| Sparse-embedding model | host bind mount `./.cache/huggingface` | 837M | `PermissionError at /home/appuser/.cache/huggingface/hub` downloading `naver/splade-cocondenser-ensembledistil` |
| Reranker model | FlashRank cache inside the container | 22M | downloaded at first query (`ms-marco-MiniLM-L-12-v2.zip`) |

Nothing in `api.Dockerfile` or `entrypoint.sh` populates the first two: they are
hand-provisioned state that exists only as a docker volume and a host directory.
The HuggingFace mount is *relative to the compose file*, so running the same
compose from a different checkout silently gets an empty, root-owned directory.

Before cutting traffic over to the new host, either copy both across:

```bash
# deps volume
docker run --rm -v amber2_pip-packages:/from:ro -v <new>_pip-packages:/to \
  alpine sh -c 'cp -a /from/. /to/'
# model cache
rsync -a <old>:/root/amber2/.cache/huggingface/ /root/amber2/.cache/huggingface/
```

…or accept a long, network-dependent first start and verify a real query returns
sources before sending traffic. An offline host cannot recover on its own.

## Calibrating RERANK_SCORE_FLOOR

The description on the setting says "on-topic >= 0.82, no-coverage ~0.0". That
does not match what the reranker actually returns on the production corpus.
Measured on the drill against restored production data, with FlashRank
`ms-marco-MiniLM-L-12-v2`:

```
Rerank floor 0.990 dropped 5/10 chunks for 'How does alerting work in Carbonio?'
```

Half the chunks for a well-covered question score **above 0.99**. A floor of 0.82
would therefore drop nothing and the gate would be a silent no-op. Calibrate
against `Rerank floor %.3f dropped %d/%d` in the logs on your own corpus before
trusting any value, and treat the number in the setting's description as stale.

## What this runbook does not cover

- **Point-in-time recovery.** `backup.sh` is a periodic snapshot; there is no WAL
  archiving. Recovery point = the last verified backup.
- **The result cache after a restore.** `_fetch_chunks_by_ids`
  (`retrieval_service.py:1527`) fetches chunks by id with no document-status
  filter, so for the cache TTL a hit can serve chunks of a document that is no
  longer READY. Invalidate per tenant after a restore if answers look stale.
- **Cross-version restores.** A dump taken at a commit with a different alembic
  head is not covered here; check `alembic heads` on both sides first.
