# Operating Limits

## Overview

Operational limits based on the most recent load test and current
configuration.

> **Warning:** These limits are based on the last recorded load test and may
> vary based on infrastructure updates. See
> [load_test_results.md](./load_test_results.md).

## Concurrent Users

- **Tested Limit**: 50 concurrent users
- **Recommended Limit**: 30-40 concurrent users for optimal latency
- **Bottleneck**: Database connection pool and LLM API rate limits

## Throughput

- **Chat Queries**: TBD qps (Target: >50 qps)
- **Document Ingestion**: TBD docs/min

## Latency Service Level Objectives (SLOs)

- **P95 Chat Response**: < 2.0s (Time to First Token)
- **P99 Chat Response**: < 5.0s
- **Ingestion Processing**: < 60s per 10MB PDF

## Resource Limits

- **Max File Size**: 100MB
- **Default Context Budget**: 8k tokens (generation service); model max varies
  by provider
- **Max Graph Depth**: 2 hops (configurable per query)

## Object Storage Limits (Garage)

Garage (dxflrs/garage:v1.1.0) is the live S3-compatible object storage.

- **Max Object Size**: Limited by available disk; no hard upper bound in Garage itself.
- **Backup precondition**: Both `amber2_graphrag-garage-data` and
  `amber2_graphrag-garage-meta` volumes must be snapshotted together from the
  same point in time (see `scripts/backup_preflight.sh` Step 9).
- **Restore precondition**: Restore both volumes together; restoring only one
  will leave Garage's SQLite metadata out of sync with stored objects.

## Database Connection Pool

- **pool_size**: 20 (SQLAlchemy base pool)
- **max_overflow**: 20 (additional connections above pool_size)
- **Max concurrent DB connections**: 40 (pool_size + max_overflow)
- **Bottleneck**: Shared with all API workers; reduce if running many replicas.
