# Core Pipelines Reference

This document lists Amber's core pipelines and where they are described. It is intended as a quick, stable reference for the main application flows and their supporting sub-pipelines.

## App Pipeline (Request Lifecycle)

End-to-end application flow for the two primary user paths:
- **Ingestion path**: document upload enters the ingestion pipeline and is processed asynchronously until the document is ready for querying.
- **Query path**: user queries flow through query processing and retrieval/generation to return a response.

Sources: `README.md`, `docs/agentic-retrieval.md`

## Core Pipelines

### Document Ingestion Pipeline

Transforms raw documents into queryable knowledge: storage, extraction, semantic chunking, embedding generation, graph extraction, vector/graph storage, community detection, and ready state.

Sources: `README.md`

### Query Processing Pipeline

Turns user questions into responses via query rewriting, parsing/filtering, routing, enhancement (HyDE/decomposition), multi-modal search, fusion/reranking, and answer generation.

Sources: `README.md`

### Retrieval (RAG) Pipeline

Standard retrieval + generation flow used by the query endpoint: embed query, vector search, rerank, and generate answer with citations/timing.

Sources: `src/api/routes/query.py`, `src/core/retrieval/application/use_cases_query.py`, `src/core/retrieval/application/retrieval_service.py`

### Agentic RAG Pipeline

Optional agent-driven loop (ReAct-style) that iteratively calls tools (retrieval, graph, filesystem) until an answer is produced or a step limit is reached.

Sources: `docs/agentic-retrieval.md`

## Supporting Sub-Pipelines

### PDF Extraction Pipeline

Multi-parser fallback strategy for PDFs (fast parser first, robust parser fallback) that outputs structured markdown for downstream chunking.

Sources: `README.md`

### Embedding Pipeline

Token-aware batching, retry/backoff, and caching for scalable embedding generation.

Sources: `README.md`

### Graph Extraction & Storage Pipeline

Extracts entities/relationships from chunks and syncs to graph/vector stores for downstream retrieval and community detection.

Sources: `README.md`

### Community Detection & Summarization Pipeline

Runs Leiden clustering over the graph and summarizes communities, producing cluster-level metadata and embeddings.

Sources: `README.md`

## Test Coverage (Unit and Smoke)

Smoke tests here include integration, E2E, or manual scripts that exercise a pipeline end-to-end.

- App Pipeline (Request Lifecycle): Unit: none dedicated. Smoke: `tests/integration/test_ui_integration.sh`, `frontend/tests/e2e/pipelines.spec.ts`, `run_integration_suite.sh`.
- Document Ingestion Pipeline: Unit: `tests/unit/test_upload_document_use_case.py`, `tests/unit/test_ingestion_service_event_dispatcher.py`, `tests/unit/test_ingestion_vector_collection.py`. Smoke: `tests/integration/test_pipeline_manual.sh`, `tests/integration/test_ingestion_pipeline.py`, `tests/integration/test_ingestion_flow.py`.
- Query Processing Pipeline: Unit: `tests/unit/test_query_parser.py`, `tests/unit/test_query_router.py`, `tests/unit/test_structured_query.py`. Smoke: `tests/integration/test_chat_pipeline.py`, `tests/integration/test_retrieval.py`, `tests/integration/test_ui_integration.sh`, `frontend/tests/e2e/pipelines.spec.ts`, `run_integration_suite.sh`.
- Retrieval (RAG) Pipeline: Unit: `tests/unit/test_fusion.py`, `tests/unit/test_graph_traversal.py`, `tests/unit/test_sparse_embeddings.py`. Smoke: `tests/integration/test_retrieval_service.py`, `tests/integration/test_retrieval.py`, `tests/integration/test_chat_pipeline.py`.
- Agentic RAG Pipeline: Unit: none found. Smoke: none found.
- PDF Extraction Pipeline: Unit: none dedicated. Smoke: `tests/integration/test_extraction_flow.py`, `tests/integration/test_advanced_extraction.py`, `tests/integration/test_ingestion_pipeline.py`.
- Embedding Pipeline: Unit: `tests/unit/test_ollama_embeddings.py`, `tests/unit/test_sparse_embeddings.py`, `tests/unit/test_providers.py`. Smoke: `tests/integration/test_ingestion_pipeline.py`, `tests/integration/test_pipeline_manual.sh`.
- Graph Extraction & Storage Pipeline: Unit: `tests/unit/test_graph_extractor.py`, `tests/unit/test_graph_processor.py`, `tests/unit/test_graph_provider.py`. Smoke: `tests/integration/test_graph_pipeline.py`, `tests/integration/test_ingestion_pipeline.py`, `tests/integration/test_pipeline_manual.sh`.
- Community Detection & Summarization Pipeline: Unit: `tests/unit/test_community_services.py`. Smoke: `tests/integration/test_community_pipeline.py`.

## Related Documentation

- **GraphRAG determinism verification**: `docs/determinism_report.md`
- **Testing coverage** (non-core): `docs/TESTING.md`
