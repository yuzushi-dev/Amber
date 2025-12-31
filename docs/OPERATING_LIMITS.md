# Operating Limits

> [!WARNING]
> These limits are based on initial load testing and may vary based on infrastructure updates.

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
- **Max Context Window**: 128k tokens
- **Max Graph Depth**: 2 hops
