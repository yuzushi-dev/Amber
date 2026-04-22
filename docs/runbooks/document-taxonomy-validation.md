# Runbook: Document Taxonomy Validation

## Purpose

Verify that the taxonomy routing is working correctly after the backfill or after
a new batch of documents is ingested.

## Pre-requisites

- Access to `root@cph-01.demo.zextras.io`
- Amber2 service running

---

## 1. Check Corpus Distribution

Call the observability endpoint (requires super-admin API key):

```bash
curl -s -H "X-API-Key: <super-admin-key>" \
  http://localhost:8000/api/v1/admin/observability/taxonomy/corpus-summary | python3 -m json.tool
```

Expected healthy output:

```json
{
  "total_stamped": 1121,
  "total_unstamped": 0,
  "buckets": [
    {"edition": "commercial", "audience": "admin", "source_family": "admin_guide", "count": 727},
    {"edition": "ce",         "audience": "admin", "source_family": "ce_guide",    "count": 164},
    {"edition": "commercial", "audience": "admin", "source_family": "zendesk_kb",  "count": 168},
    {"edition": "commercial", "audience": "user",  "source_family": "user_guide",  "count": 38},
    {"edition": "commercial", "audience": "user",  "source_family": "zendesk_kb",  "count": 24}
  ]
}
```

**Red flags:**
- `total_unstamped > 0` → run backfill script (see below)
- Large `unknown` bucket → investigate folder assignment of those documents

---

## 2. Run the Validation Query Pack

These queries cover the four main routing cases. Use the API with `include_trace: true`
and `include_sources: true` to inspect the taxonomy routing step.

```bash
API="http://localhost:8000/api/v1"
KEY="<super-admin-key>"

for QUERY in \
  "How do delegate admins work?" \
  "How do delegate admins work in CE?" \
  "How do I use message search in chat?" \
  "How do I update directory server credentials?"; do

  echo "=== $QUERY ==="
  curl -s -X POST "$API/query" \
    -H "X-API-Key: $KEY" \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"$QUERY\", \"options\": {\"include_trace\": true, \"include_sources\": true}}" \
  | python3 -c "
import sys, json
r = json.load(sys.stdin)
trace = r.get('trace') or []
tax = next((s for s in trace if s.get('step') == 'taxonomy_routing'), None)
if tax:
    d = tax.get('details', {})
    print('  edition:', d.get('inferred_edition'))
    print('  audience:', d.get('inferred_audience'))
    print('  broadening_stage:', d.get('broadening_stage'))
    print('  strict_count:', d.get('strict_candidate_count'))
sources = r.get('sources') or []
print('  sources:', [s.get('document_name') for s in sources[:3]])
  "
  echo
done
```

**Expected routing:**

| Query | edition | audience | broadening_stage |
|---|---|---|---|
| `delegate admins work?` | commercial | admin | strict |
| `delegate admins work in CE?` | ce | admin | strict |
| `message search in chat?` | commercial | user | strict |
| `update directory server credentials?` | commercial | admin | strict |

---

## 3. Fix Unstamped Documents

If `total_unstamped > 0`, run the backfill script:

```bash
cd /root/amber2

# Dry-run first
python scripts/backfill_document_taxonomy.py

# If output looks correct, apply
python scripts/backfill_document_taxonomy.py --write
```

---

## 4. Check Logs for Taxonomy Routing

```bash
# Live log stream filtered to taxonomy events
docker logs amber2 --follow 2>&1 | grep taxonomy_routing
```

Each RAG query should emit a log line like:

```
taxonomy_routing query_id=<id> edition=commercial audience=admin broadening_stage=strict strict_count=120
```

If `broadening_stage` is frequently `unfiltered`, it means the strict filter is
returning too few results — check that the corpus is stamped correctly.

---

## 5. Manual Override

To temporarily disable taxonomy routing for debugging, set the query filter explicitly:

```json
{
  "query": "...",
  "filters": {"edition": null, "audience": null}
}
```

Or pass explicit overrides to force a specific corpus:

```json
{
  "query": "...",
  "filters": {"edition": "ce", "audience": "admin"}
}
```
