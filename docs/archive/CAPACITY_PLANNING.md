# Capacity Planning

## Overview

Sizing guidance and scaling triggers for storage and compute.

## Formulas

### Storage

- **Raw Text**: 1MB per 500 pages
- **Vector Index**: `Num_Chunks * Dimensions * 4 bytes` (approx + overhead)
- **Graph Storage**: `Num_Nodes * 300 bytes + Num_Edges * 100 bytes`

### Compute

- **Embedding Generation**: ~50ms per chunk (CPU)
- **LLM Context**: 1k tokens ~= 4KB memory (approx)

## Scaling Triggers

- **Scale Up API**: When CPU > 70% or Latency P95 > 2s
- **Scale Up Worker**: When Ingestion Queue > 100 items
- **Scale Database**: When Memory > 80% or IQ Wait > 10%
