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

## Storage Migration Limits

- **Cutover Precondition**: Final MinIO->SeaweedFS manifest compare must report
  `missing_in_dst=0` and `mismatched=0`.
- **Write Freeze Window**: Stop `api`, `worker`, and `milvus` during final sync
  to avoid object drift.
- **Rollback Retention**: Keep MinIO available for at least 7 days (recommended
  14) after production cutover.
- **Daily Reconciliation**: Run manifest comparison once per day during rollback
  window, preferably via `scripts/seaweed_reconcile_tidy.sh`.
