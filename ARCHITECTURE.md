# How It Works

## 1. Ingestion & Semantic Processing

Ingestion uses structure-aware semantic chunking rather than fixed-size splitting.

*   **Hierarchy-First Splitting**: The `SemanticChunker` (`src/core/ingestion/application/chunking/semantic.py`) respects document anatomy. It protects code blocks first, then splits by:
    1.  **Markdown Headers** (`#`, `##`, ...) to preserve topological context.
    2.  **Paragraphs** (`\n\n`) to maintain flow.
    3.  **Sentences** (via regex) as a last resort for dense text.
*   **Domain-Adaptive Sizing**: Chunk sizes and overlaps are automatically optimized based on document type (defined in `src/core/generation/application/intelligence/strategies.py`):
    *   **General** (Default): 600 tokens / 50 overlap
    *   **Technical** (Code/Manuals): 800 tokens / 50 overlap
    *   **Financial** (Reports/Tables): 800 tokens / 50 overlap
    *   **Scientific** (Research Papers): 1000 tokens / 100 overlap
    *   **Legal** (Contracts/Clauses): 1000 tokens / 100 overlap
    *   **Conversational**: 500 tokens / 100 overlap
*   **Token-Aware Overlap**: Rather than character-based overlap, tokens from the *end* of the previous chunk are prepended to the next to ensure semantic continuity.
*   **Chunk Quality Filtering**: Implements a helper "Quality Coloring" system (`ChunkQualityScorer`) that grades every chunk (0-1) based on text density, fragmentation, and OCR artifacts.
    *   **Noise Reduction**: Low-quality chunks (< 0.3) that also yield zero graph entities are automatically discarded during extraction, preventing "garbage-in" from polluting the vector store.
*   **Resilient Embedding**: The `EmbeddingService` uses exponential backoff retries for rate limits and uses **token-aware batching** (max 8000 tokens/batch) to optimize API throughput.

## 2. Knowledge Graph Construction

Graph construction runs in two stages: iterative entity extraction, then community detection over the extracted entities.

*   **Entity Definition**: Entities are defined via flexible Pydantic models, supporting over 30+ domain-specific types alongside standard named entities.
    *   **Core Types**: `PERSON`, `ORGANIZATION`, `LOCATION`, `EVENT`, `CONCEPT`, `DOCUMENT`, `TECHNOLOGY`, `PRODUCT`, `DATE`, `MONEY`, `ARTICLE`.
    *   **Infrastructure Types**: `COMPONENT`, `SERVICE`, `NODE`, `DOMAIN`, `CLASS_OF_SERVICE`, `RESOURCE`, `QUOTA_OBJECT`, `STORAGE_OBJECT`, `BACKUP_OBJECT`, `ITEM`.
    *   **Operational Types**: `ACCOUNT`, `ACCOUNT_TYPE`, `ROLE`, `TASK`, `PROCEDURE`, `MIGRATION_PROCEDURE`, `CLI_COMMAND`, `API_OBJECT`, `CONFIG_OPTION`, `CERTIFICATE`, `SECURITY_FEATURE`.
    *   **Schema**: Every extracted entity includes a `name` (capitalized), `type`, `description` (self-contained summary).
    *   **Relationships**: `source`, `target`, `type` (e.g., `DEPENDS_ON`, `PROTECTS`, `RUNS_ON`), and `weight` (1-10 strength score).
*   **Generation Mechanism (Dynamic Ontology Injection)**:
    *   The 30+ types are **dynamically injected** into the LLM system prompt as a canonical ontology (`{entity_types_str}`).
    *   The LLM is strictly instructed to classify entities *only* into these allowed types.
    *   **Output Format**: The system uses a strict **Tuple-Delimited Format** (e.g., `("entity"<|>NAME<|>TYPE...)`) to prevent parsing errors common with standard JSON, ensuring high-fidelity extraction even from messy text.
*   **Gleaning (Iterative Extraction)**: Implemented in `GraphExtractor`, this technique prevents "extraction amnesia."
    1.  **Pass 1**: Zero-shot extraction of entities and relationships (Temperature 0.1).
    2.  **Pass 2 (Gleaning)**: The LLM is fed the text *and* the entities found in Pass 1, and asked "What did you miss?". This raises recall on dense documents.
*   **Leiden Community Detection**: We use the hierarchical **Leiden algorithm** to cluster entities into communities.
    *   **Summarization**: Each community is summarized by an LLM to create a "Community Node," enabling **Global Search** (answering "What is the main theme?" by reading summaries rather than thousands of raw chunks).
*   **Quality Assurance (Hybrid Scoring)**: To prevent hallucinations and low-quality extractions, a strict scoring system is applied:
    *   **Intrinsic Confidence**: Entities with an LLM-generated `importance_score < 0.5` are automatically discarded.
    *   **Extrinsic Validation**: A `QualityScorer` module evaluates generated answers and critical extractions on 4 dimensions: **Context Relevance**, **Completeness**, **Factual Grounding**, and **Coherence**, using a mix of LLM evaluation and heuristic checks.

## 3. Advanced Retrieval Logic

Retrieval is handled by an orchestration layer that mixes deterministic and agentic strategies.

*   **Fusion (Hybrid Search)**: We employ **Reciprocal Rank Fusion (RRF)** to combine results from Milvus (Vector) and Neo4j (Keyword/Graph).
    *   **Milvus Hybrid**: Within Milvus itself, we combine **Dense Vectors** (Semantic) and **Sparse Vectors** (SPLADE/Keyword) to find the most relevant chunks.
    *   **Graph Fusion**: These results are then fused with graph traversals.
    *   Formula: `score = Σ(1 / (k + rank + 1))`
    *   This ensures that a document appearing in *both* top-lists is ranked significantly higher than one appearing in only one.
*   **Drift Search (Agentic)**: Defined in `DriftSearchService` (`src/core/retrieval/application/search/drift_search.py`), this is the heaviest retrieval mode:
    1.  **Primer**: Performs an initial standard retrieval (Top-5) to get a baseline context.
    2.  **Expansion Loop**: The LLM analyzes the Primer results and generates **Follow-Up Questions**. These sub-queries are executed to "drift" to related graph neighborhoods.
    3.  **Synthesis**: All accumulated context (Primer + Expansion) is deduplicated and fed to the LLM for a final, citation-backed answer.

## 4. Agentic RAG (ReAct Loop)

For complex queries requiring multi-step reasoning, Amber employs a full **Agentic RAG** architecture using a ReAct (Reason+Act) loop.

*   **Agent Orchestrator**: The `AgentOrchestrator` (`src/core/generation/application/agent/orchestrator.py`) manages the loop:
    1.  Receive query → LLM decides: call a tool OR give final answer.
    2.  If tool: execute, append result to context, repeat.
    3.  Max 10 steps to prevent infinite loops.
*   **Available Tools**:
    | Tool                                         | Description                     | Mode                |
    | -------------------------------------------- | -------------------------------- | ------------------- |
    | `search_codebase`                            | Vector search over documents    | Knowledge (default) |
    | `query_graph`                                | Execute Cypher queries on Neo4j | Knowledge           |
    | `read_file`, `list_directory`, `grep_search` | Filesystem access               | Maintainer (opt-in) |
*   **Agent Modes**: Two security levels controlled via `agent_role` parameter:
    *   **Knowledge Agent** (default): Vector + Graph tools only. Safe for production.
    *   **Maintainer Agent**: Adds filesystem tools. Requires explicit opt-in.
*   **Resilient Content Fallback**: If Milvus returns empty content, the system automatically fetches from PostgreSQL, with full observability (OTel event + log metric).
*   **Implementation**: `src/core/generation/application/agent/`, `src/core/tools/`.

## Conversation ownership

Conversation history ownership is the authenticated API key ID. `X-User-ID`
is metadata only and never authorizes access; callers sharing one API key
share that key's history. Legacy summaries with `api_key_id IS NULL` are
excluded from self-service reads and multi-turn reinjection and are never
backfilled or adopted because their original owner cannot be reconstructed.
Long-term user facts use the same authenticated API-key owner; legacy facts
with `api_key_id IS NULL` are excluded from generation-time memory injection.
Deleting an API key sets owned rows to `NULL`; those rows remain
fail-closed and require tenant-admin retention for cleanup.
Restoring a backup without a recoverable API-key owner also keeps rows
fail-closed; the restore result reports those counts for operator cleanup.

## Performance (indicative, not a benchmark)

Figures carried over from an earlier development deployment: the corpus size, model, and hardware they came from were never recorded. Treat them as an order of magnitude and measure your own.

| Search Mode | Cold   | Warm   |
| ----------- | ------ | ------ |
| Basic       | 800ms  | 250ms  |
| Local       | 1200ms | 400ms  |
| Global      | 2500ms | 800ms  |
| Drift       | 5000ms | 1500ms |

### Scaling

- **Horizontal**: Add more workers (`docker compose up -d --scale worker=4`)
- **Vertical**: Increase worker resources
- **Caching**: Tune Redis cache TTLs
- **Database**: Configure Neo4j/Milvus for your dataset size
