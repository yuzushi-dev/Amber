# Amber Architecture

Implementation notes for the ingestion and query pipelines. For setup and usage see the [README](../README.md).

What follows is the ingestion pipeline, the query pipeline, and the caching and failure handling wrapped around both.

## Document Ingestion Pipeline

The ingestion pipeline transforms raw documents into queryable knowledge representations through multiple stages:

```
Document Upload
    ↓
[1] Storage (Garage)
    ↓
[2] Format Detection & Extraction
    ↓
[3] Semantic Chunking
    ↓
[4] Embedding Generation
    ↓
[5] Graph Extraction (Entities & Relationships)
    ↓
[6] Vector Storage (Milvus)
    ↓
[7] Graph Storage (Neo4j)
    ↓
[8] Community Detection (Leiden)
    ↓
Document Ready
```

### 1. Storage Layer

**Implementation**: [src/core/ingestion/infrastructure/storage/storage_client.py](../src/core/ingestion/infrastructure/storage/storage_client.py)

- Raw documents stored in **Garage** (S3-compatible object storage)
- Content-addressed storage using SHA-256 hashing
- Automatic deduplication at upload time
- Tenant-isolated buckets: `{tenant_id}/{document_id}/filename`

### 2. Format Detection & Extraction

**Implementation**: [src/core/ingestion/infrastructure/extraction/](../src/core/ingestion/infrastructure/extraction/)

Multi-parser fallback strategy:

```python
# Priority order:
1. PyMuPDF4LLM (PDF) - Fast, preserves structure
2. Marker-PDF (PDF) - Slower, better for complex layouts
3. Unstructured (PDF, DOCX, HTML) - Universal fallback
4. Native parsers (Markdown, TXT)
```

**PDF Extraction Pipeline**:
```python
async def extract_pdf(file_content: bytes) -> str:
    # Try fast parser first
    try:
        return pymupdf4llm.to_markdown(file_content)
    except Exception:
        # Fallback to robust parser
        return marker_pdf.convert(file_content)
```

**Output**: Markdown-formatted text with preserved structure (headers, lists, tables)

### 3. Semantic Chunking

**Implementation**: [src/core/ingestion/application/chunking/semantic.py](../src/core/ingestion/application/chunking/semantic.py)

**Hierarchical Splitting Strategy**:

Amber uses a **4-level hierarchical splitter** that respects document semantics:

```
Level 1: Code Blocks (```)   protected, never split
    ↓
Level 2: Headers (# ## ###)
    ↓
Level 3: Paragraphs (\n\n)
    ↓
Level 4: Sentences (.!?)
```

**Algorithm**:

1. **Code Block Protection**: Extract and replace code blocks with placeholders
2. **Header Splitting**: Divide by markdown headers to preserve logical sections
3. **Size-Aware Chunking**: For each section:
   - If fits in `chunk_size` → keep as-is
   - Else split by paragraphs
   - If paragraph too large → split by sentences
4. **Overlap Application**: Prepend last N tokens from previous chunk
5. **Token Counting**: Use tiktoken (`cl100k_base`) for accurate counts

**Configuration**:
```python
ChunkingStrategy(
    chunk_size=600,      # Target tokens per chunk (General default)
    chunk_overlap=50,    # Overlap tokens for context
)
```

**Example**:
```
Input (1000 tokens):
  # Introduction
  Paragraph 1 (300 tokens)
  Paragraph 2 (400 tokens)
  ## Methods
  Paragraph 3 (300 tokens)

Output:
  Chunk 0: "# Introduction\nParagraph 1\n" (300 tokens)
  Chunk 1: "[50 token overlap]Paragraph 2\n" (450 tokens)
  Chunk 2: "[50 token overlap]## Methods\nParagraph 3" (350 tokens)
```

**Metadata Enrichment**:
- `document_title`: For context
- `start_char`, `end_char`: Source location
- `index`: Chunk position in document
- `token_count`: Actual token count

### 4. Embedding Generation

**Implementation**: [src/core/graph/application/communities/embeddings.py](../src/core/graph/application/communities/embeddings.py)

**Embedding pipeline**:

**Token-Aware Batching**:
```python
# Automatic batching by token count
MAX_TOKENS_PER_BATCH = 8000  # OpenAI limit
MAX_ITEMS_PER_BATCH = 2048   # API limit

batches = batch_texts_for_embedding(
    texts=chunks,
    model="text-embedding-3-small",
    max_tokens=8000,
    max_items=2048
)
```

**Retry Logic with Exponential Backoff**:
```python
@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=60),
    retry=retry_if_exception_type((RateLimitError, ProviderUnavailableError))
)
async def _embed_batch_with_retry(texts, model):
    return await provider.embed(texts, model)
```

**Features**:
- **Parallel batching**: Process multiple batches concurrently
- **Cost tracking**: Track tokens and estimated costs per batch
- **Failover**: Automatic fallback to alternative providers
- **Statistics**: Detailed metrics (latency, tokens, failures)

**Semantic Caching**:

**Implementation**: [src/core/cache/semantic_cache.py](../src/core/cache/semantic_cache.py)

```python
# Cache embeddings to avoid re-computation
key = SHA256(query.lower().strip())
cached_embedding = await cache.get(key)

if cached_embedding:
    return cached_embedding
else:
    embedding = await embed(query)
    await cache.set(key, embedding, ttl=86400)  # 24 hours
    return embedding
```

**Cache Performance**:
- TTL: 24 hours (configurable)
- Storage: Redis with JSON serialization
- A hit replaces a provider round-trip with a Redis read

### 5. Graph Extraction

**Implementation**: [src/core/ingestion/infrastructure/extraction/graph_extractor.py](../src/core/ingestion/infrastructure/extraction/graph_extractor.py)

**Two-Pass Extraction with Gleaning**:

**Pass 1: Initial Extraction**

The prompt below is simplified for readability. The production extractor uses the tuple-delimited output format described in the README, not JSON.

```python
# LLM prompt for structured extraction
system_prompt = """
Extract entities and relationships from the text.
Output JSON:
{
  "entities": [{"name": "...", "type": "...", "description": "..."}],
  "relationships": [{"source": "...", "target": "...", "type": "..."}]
}
"""

result = await llm.generate(text, system_prompt, temperature=0.0)
entities, relationships = parse_json(result)
```

**Pass 2: Gleaning (Iterative Refinement)**

Maximizes recall by asking the LLM to find missed entities:

```python
for iteration in range(max_gleaning_steps):  # default: 1
    existing_entities = [e.name for e in entities]

    prompt = f"""
    Text: {text}
    Existing Entities: {existing_entities}

    Find any entities you missed in the first pass.
    """

    new_entities = await llm.generate(prompt, temperature=0.2)

    if not new_entities:
        break  # No more entities found

    entities.extend(new_entities)
```

**Gleaning Impact**:
- Recall improvement: +15-25% more entities
- Cost: 2x LLM calls per chunk
- Trade-off: Configurable via `use_gleaning` flag

**Entity Schema**:
```python
{
    "id": "ent_abc123",
    "name": "GraphRAG",
    "type": "Technology",
    "description": "Hybrid retrieval system combining graphs and vectors",
    "tenant_id": "default",
    "source_chunks": ["chunk_1", "chunk_2"]
}
```

**Relationship Schema**:
```python
{
    "source": "ent_abc123",  # Entity ID
    "target": "ent_def456",
    "type": "ENABLES",
    "weight": 1.0,
    "description": "GraphRAG enables contextual retrieval"
}
```

### 6. Vector Storage (Milvus)

**Implementation**: [src/core/retrieval/infrastructure/vector_store/milvus.py](../src/core/retrieval/infrastructure/vector_store/milvus.py)

**Collection Schema**:
```python
# Chunk embeddings collection
Collection: "amber_{collection_name}"  # per-tenant, prefix "amber_"
Fields:
  - chunk_id: VARCHAR (primary key)
  - document_id: VARCHAR
  - embedding: FLOAT_VECTOR(dims)  # configurable; default 1536 (text-embedding-3-small) or 768 (nomic-embed-text)
  - sparse_embedding: SPARSE_FLOAT_VECTOR  # SPLADE vectors for hybrid search
  - content: TEXT
  - metadata: JSON

Dense index: HNSW
  - M: 16, efConstruction: 256
  - metric_type: COSINE
Sparse index: SPARSE_INVERTED_INDEX
  - metric_type: IP
```

**Search Parameters**:
```python
search_params = {
    "metric_type": "COSINE",
    "params": {"ef": 128}  # HNSW search-time parameter
}

results = collection.search(
    data=[query_embedding],
    anns_field="embedding",
    param=search_params,
    limit=top_k,
    output_fields=["chunk_id", "content", "metadata"]
)
```

**Performance**:
- Query latency: <50ms for 100K vectors
- Indexing: ~5K vectors/second
- Memory: ~4GB per 1M vectors (1536 dims)

### 7. Graph Storage (Neo4j)

**Implementation**: [src/core/graph/infrastructure/neo4j_client.py](../src/core/graph/infrastructure/neo4j_client.py)

**Graph Schema**:

```cypher
// Nodes
(:Document {id, title, tenant_id, status})
(:Chunk {id, document_id, content, index})
(:Entity {id, name, type, description, tenant_id})
(:Community {id, level, title, tenant_id})

// Relationships
(:Chunk)-[:PART_OF]->(:Document)
(:Chunk)-[:MENTIONS]->(:Entity)
(:Entity)-[:RELATED_TO {type, weight}]->(:Entity)
(:Entity)-[:BELONGS_TO]->(:Community)
(:Community)-[:PARENT_OF]->(:Community)
```

**Indexes**:
```cypher
CREATE INDEX entity_tenant_idx FOR (e:Entity) ON (e.tenant_id);
CREATE INDEX entity_name_idx FOR (e:Entity) ON (e.name);
CREATE INDEX community_tenant_idx FOR (c:Community) ON (c.tenant_id, c.level);
```

**Write Pattern**:
```python
# Batched writes for performance
async def write_entities(entities: List[Entity]):
    query = """
    UNWIND $entities AS entity
    MERGE (e:Entity {id: entity.id})
    SET e.name = entity.name,
        e.type = entity.type,
        e.tenant_id = $tenant_id
    """
    await neo4j.execute_write(query, {"entities": entities})
```

### 8. Community Detection (Leiden Algorithm)

**Implementation**: [src/core/graph/application/communities/leiden.py](../src/core/graph/application/communities/leiden.py)

**Hierarchical Leiden Clustering**:

Amber uses the **Leiden algorithm** (Traag et al., 2019) for hierarchical community detection. Leiden improves upon Louvain by guaranteeing well-connected communities.

**Algorithm Steps**:

**Level 0: Entity Clustering**

1. **Fetch Entity Graph**:
```cypher
MATCH (s:Entity)-[r]->(t:Entity)
WHERE s.tenant_id = $tenant_id
RETURN s.id, t.id, type(r), r.weight
```

2. **Build igraph**:
```python
# Convert Neo4j graph to igraph
nodes = list(entity_ids)
edges = [(src, tgt, weight) for src, tgt, weight in relationships]

g = igraph.Graph(len(nodes))
g.add_edges(edges)
g.es['weight'] = weights
```

3. **Run Leiden**:
```python
partition = leidenalg.find_partition(
    g,
    leidenalg.RBConfigurationVertexPartition,
    weights=weights,
    resolution_parameter=1.0  # Higher = smaller communities
)
```

4. **Create Communities**:
```python
for comm_idx, members in enumerate(partition):
    community = Community(
        id=generate_community_id(level=0),
        level=0,
        members=[entity_ids[i] for i in members]
    )
```

**Level 1+: Hierarchical Aggregation**

5. **Aggregate Graph**:
```python
# Create super-graph where nodes are Level 0 communities
induced_graph = partition.cluster_graph()
```

6. **Recursive Leiden**:
```python
for level in range(1, max_levels):
    # Run Leiden on induced graph
    partition = leidenalg.find_partition(induced_graph, ...)

    # Create higher-level communities
    for super_comm in partition:
        community = Community(
            level=level,
            child_communities=[comm_ids from level-1]
        )

    # Check convergence
    if no_new_structure:
        break
```

**Persistence**:
```cypher
// Store communities and relationships
MERGE (c:Community {id: $id})
SET c.level = $level, c.title = $title

// Link entities (Level 0)
FOREACH (entity_id IN $members |
    MERGE (e:Entity {id: entity_id})
    MERGE (e)-[:BELONGS_TO]->(c)
)

// Link child communities (Level 1+)
FOREACH (child_id IN $children |
    MERGE (child:Community {id: child_id})
    MERGE (c)-[:PARENT_OF]->(child)
)
```

**Community Summarization**:

After detection, each community is summarized using an LLM:

```python
# Gather community content
entities = get_community_entities(community_id)
chunks = get_related_chunks(entities)

prompt = f"""
Summarize the following content as a coherent theme:

Entities: {entity_names}
Context: {chunk_contents}

Provide:
1. A title (5-10 words)
2. A summary (2-3 sentences)
3. Key themes (3-5 keywords)
"""

summary = await llm.generate(prompt)
community.summary = summary.text
community.embedding = await embed(summary.text)
```

**Why Leiden?**
- **Quality**: Guarantees well-connected communities (vs Louvain)
- **Speed**: O(n log n) on sparse graphs
- **Hierarchical**: Natural multi-level structure
- **Proven**: Standard in network science

## Query Processing Pipeline

The query pipeline transforms user questions into contextual answers through multiple stages:

```
User Query
    ↓
[1] Query Rewriting
    ↓
[2] Query Parsing & Filtering
    ↓
[3] Query Routing (Mode Selection)
    ↓
[4] Query Enhancement (HyDE/Decomposition)
    ↓
[5] Multi-Modal Search
    ↓
[6] Result Fusion & Reranking
    ↓
[7] Answer Generation
    ↓
Response
```

### 1. Query Rewriting

**Implementation**: [src/core/retrieval/application/query/rewriter.py](../src/core/retrieval/application/query/rewriter.py)

**Purpose**: Convert context-dependent queries into standalone versions.

**Example**:
```python
# Conversation history
History:
  User: "What is GraphRAG?"
  AI: "GraphRAG is a hybrid retrieval system..."
  User: "How does it work?"  # ← Ambiguous!

# Rewriting
Original: "How does it work?"
Rewritten: "How does GraphRAG work?"
```

**Implementation**:
```python
prompt = f"""
Conversation History:
{format_history(last_5_turns)}

Current Query: {query}

Rewrite the query to be standalone and clear.
Output only the rewritten query.
"""

rewritten = await llm.generate(prompt, temperature=0.0)
```

**Features**:
- Uses conversation history (last 5 turns)
- Timeout guard (2 seconds, fallback to original)
- Uses economy-tier LLM for cost efficiency

### 2. Query Parsing & Filtering

**Implementation**: [src/core/retrieval/application/query/parser.py](../src/core/retrieval/application/query/parser.py)

**Extract Structured Filters**:

```python
# Parse filters from natural language
query = "Show me documents about AI from 2024 tagged research"

parsed = QueryParser.parse(query)
# Output:
{
    "cleaned_query": "documents about AI",
    "filters": {
        "date_range": {"start": "2024-01-01", "end": "2024-12-31"},
        "tags": ["research"]
    },
    "document_ids": []
}
```

**Supported Filters**:
- Date ranges: "from Jan 2024", "between 2023-2024"
- Tags: "tagged X", "#X"
- Document IDs: "in doc_123", "document doc_abc"

### 3. Query Routing

**Implementation**: [src/core/retrieval/application/query/router.py](../src/core/retrieval/application/query/router.py)

**Automatic Search Mode Selection**:

```python
async def route(query: str) -> SearchMode:
    """
    Classify query and select optimal search mode.
    """
    prompt = f"""
    Classify this query:

    Query: {query}

    Categories:
    - LIST: Enumeration queries ("list all", "what are")
    - ENTITY: Specific entity lookup ("who is", "when did")
    - THEME: Broad conceptual questions ("how does", "explain")
    - COMPARISON: Comparing concepts ("difference between")
    - SIMPLE: Direct factual question

    Return: BASIC | LOCAL | GLOBAL | DRIFT | STRUCTURED
    """

    mode = await llm.generate(prompt)
    return SearchMode(mode.strip())
```

**Mode Selection Logic**:
- **STRUCTURED**: Direct Cypher for "list all X", "count Y"
- **LOCAL**: Entity-centric for "who", "when", "where"
- **GLOBAL**: Community summaries for "what themes", "overview"
- **DRIFT**: Iterative for "how does X relate to Y", multi-hop
- **BASIC**: Fallback vector search

### 4. Query Enhancement

**HyDE (Hypothetical Document Embeddings)**

**Implementation**: [src/core/retrieval/application/query/hyde.py](../src/core/retrieval/application/query/hyde.py)

**Technique**: Generate hypothetical answers, embed them instead of the query.

**Why?** Bridges semantic gap between short queries and long documents.

```python
query = "What is the capital of France?"

# Generate hypothesis
hypothesis = await llm.generate(f"""
Generate a passage that would answer: {query}

Write 2-3 sentences as if from a Wikipedia article.
""")
# Output: "Paris is the capital and largest city of France.
#          Located on the Seine River, Paris is known for..."

# Embed hypothesis instead of query
embedding = await embed(hypothesis)
results = vector_search(embedding)
```

**Consistency Check**:
```python
# Generate multiple hypotheses
hypotheses = [await generate_hypothesis(query) for _ in range(3)]
embeddings = [await embed(h) for h in hypotheses]

# Check semantic consistency
avg_similarity = cosine_similarity_matrix(embeddings).mean()
if avg_similarity < 0.7:
    logger.warning("Inconsistent hypotheses, fallback to direct query")
    use_direct_query()
```

**Query Decomposition**

**Implementation**: [src/core/retrieval/application/query/decomposer.py](../src/core/retrieval/application/query/decomposer.py)

**Technique**: Break complex multi-part questions into sub-queries.

```python
query = "How does GraphRAG compare to traditional RAG and what are its advantages?"

sub_queries = await decompose(query)
# Output:
[
    "What is GraphRAG?",
    "What is traditional RAG?",
    "How does GraphRAG differ from traditional RAG?",
    "What are the advantages of GraphRAG?"
]

# Execute in parallel
results = await asyncio.gather(*[
    retrieve(sq) for sq in sub_queries
])

# Aggregate results
combined_context = fuse_results(results)
```

### 5. Multi-Modal Search

Amber supports 5 search modes, each optimized for different query types.

**Basic Mode: Vector-Only Search**

```python
# Standard semantic similarity search
embedding = await embed(query)
results = milvus.search(
    data=[embedding],
    limit=10,
    metric="IP"  # Inner product (cosine for normalized)
)
```

**Local Mode: Entity-Focused Graph Traversal**

**Implementation**: [src/core/retrieval/application/search/graph_search.py](../src/core/retrieval/application/search/graph_search.py)

```python
# 1. Find entities matching query
entity_embedding = await embed(query)
entities = entity_search(entity_embedding, limit=3)

# 2. Traverse graph from entities
for entity in entities:
    # Get 2-hop neighborhood
    cypher = """
    MATCH (e:Entity {id: $entity_id})
    MATCH (e)-[r1]-(neighbor)
    MATCH (neighbor)-[r2]-(extended)
    RETURN e, r1, neighbor, r2, extended
    """

    neighborhood = await neo4j.execute_read(cypher)

    # 3. Get chunks mentioning these entities
    chunks = get_chunks_mentioning(neighborhood.entities)

    candidates.extend(chunks)
```

**Global Mode: Community Summary Map-Reduce**

**Implementation**: [src/core/retrieval/application/search/global_search.py](../src/core/retrieval/application/search/global_search.py)

```python
# 1. Search community summaries
summary_embedding = await embed(query)
communities = search_community_summaries(summary_embedding, limit=5)

# 2. For each community, get member entities and chunks
community_contexts = []
for community in communities:
    entities = get_community_entities(community.id)
    chunks = get_related_chunks(entities)
    community_contexts.append({
        "summary": community.summary,
        "chunks": chunks
    })

# 3. Map-Reduce generation
intermediate_answers = await asyncio.gather(*[
    llm.generate(f"Based on: {ctx['summary']}\n{ctx['chunks']}\n\nAnswer: {query}")
    for ctx in community_contexts
])

# 4. Final reduce step
final_answer = await llm.generate(f"""
Synthesize these partial answers into a comprehensive response:

{intermediate_answers}

Question: {query}
""")
```

**Drift Mode: Iterative Agentic Search**

**Implementation**: [src/core/retrieval/application/search/drift_search.py](../src/core/retrieval/application/search/drift_search.py)

DRIFT = **D**ynamic **R**easoning and **I**nference with **F**lexible **T**raversal

**Three-Phase Process**:

```python
async def drift_search(query, max_iterations=3):
    all_context = []

    # Phase 1: Primer - Initial retrieval
    initial_results = await retrieve(query, top_k=5)
    all_context.extend(initial_results)

    # Phase 2: Expansion - Iterative follow-ups
    for iteration in range(max_iterations):
        # Generate follow-up questions
        prompt = f"""
        Query: {query}
        Current Context: {all_context}

        What 3 questions would help provide a more complete answer?
        If context is sufficient, respond 'DONE'.
        """

        follow_ups = await llm.generate(prompt)

        if "DONE" in follow_ups:
            break

        # Execute follow-up searches in parallel
        follow_up_results = await asyncio.gather(*[
            retrieve(fq, top_k=3) for fq in parse_questions(follow_ups)
        ])

        # Add only new, non-duplicate chunks
        for chunks in follow_up_results:
            for chunk in chunks:
                if chunk.id not in seen_ids:
                    all_context.append(chunk)
                    seen_ids.add(chunk.id)

    # Phase 3: Synthesis - Final generation
    answer = await llm.generate(f"""
    Question: {query}
    Context: {all_context}

    Provide a comprehensive, grounded answer with citations.
    """)

    return answer
```

**Example Flow**:
```
Query: "How does attention mechanism relate to transformers?"

Iteration 0 (Primer):
  Retrieved: ["Attention basics", "Transformer overview"]

Iteration 1:
  Follow-ups: ["What is self-attention?", "What is multi-head attention?"]
  Retrieved: ["Self-attention formula", "Multi-head details"]

Iteration 2:
  Follow-ups: ["How are they used in transformers?"]
  Retrieved: ["Transformer architecture", "Attention in encoder-decoder"]
  Context deemed sufficient → DONE

Synthesis:
  Generates comprehensive answer from 6 chunks
```

**Structured Mode: Direct Cypher Execution**

For simple enumeration/count queries, bypass RAG entirely:

```python
query = "List all documents about AI"

cypher = """
MATCH (d:Document)-[:HAS_TAG]->(t:Tag {name: "AI"})
RETURN d.title, d.created_at
ORDER BY d.created_at DESC
LIMIT 50
"""

results = await neo4j.execute_read(cypher)
return format_list(results)
```

### 6. Result Fusion & Reranking

**Reciprocal Rank Fusion (RRF)**

**Implementation**: [src/core/retrieval/application/search/fusion.py](../src/core/retrieval/application/search/fusion.py)

When combining results from multiple sources (vector + graph + entity), use RRF:

```python
def reciprocal_rank_fusion(
    results_lists: List[List[Candidate]],
    k: int = 60  # RRF constant
) -> List[Candidate]:
    """
    Fuse multiple ranked lists using RRF.

    RRF Score = Σ(1 / (k + rank_i + 1))
    """
    scores = defaultdict(float)

    for results in results_lists:
        for rank, candidate in enumerate(results):
            scores[candidate.id] += 1.0 / (k + rank + 1)

    # Sort by RRF score
    fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [get_candidate(id) for id, score in fused]
```

**Example**:
```
Vector Search:     [A, B, C, D]
Graph Search:      [C, A, E, F]
Entity Search:     [E, A, B, G]

RRF Scores:
  A: 1/61 + 1/62 + 1/62 = 0.049
  B: 1/62 + 1/63 = 0.032
  C: 1/63 + 1/61 = 0.032
  E: 1/64 + 1/61 = 0.032
  ...

Fused: [A, B, C, E, D, F, G]
```

**Semantic Reranking**

**Implementation**: [src/core/generation/infrastructure/providers/local.py](../src/core/generation/infrastructure/providers/local.py) (FlashRank)

After fusion, rerank top-k candidates using a cross-encoder:

```python
# Get top 50 from vector/graph fusion
candidates = fuse_results([vector_results, graph_results], top_k=50)

# Rerank using cross-encoder
reranker = FlashRankReranker()
reranked = await reranker.rerank(
    query=query,
    documents=[c.content for c in candidates],
    top_k=10
)
```

**Cross-Encoder vs Bi-Encoder**:
- **Bi-Encoder** (Vector Search): Encode query and docs separately, compare embeddings (fast, ~50ms)
- **Cross-Encoder** (Reranking): Encode query+doc together, predict relevance (accurate, ~200ms)

Reranking improves precision by 15-20% and costs about 200ms.

### 7. Answer Generation

**Implementation**: [src/core/generation/application/generation_service.py](../src/core/generation/application/generation_service.py)

**Prompt Engineering**:

```python
system_prompt = """
You are an expert analyst. Answer the question using ONLY the provided context.

Rules:
1. Base your answer solely on the context
2. Cite sources using [1], [2] notation
3. If context insufficient, say "I don't have enough information"
4. Be concise but complete
"""

user_prompt = f"""
Question: {query}

Context:
{format_sources(chunks)}

Provide a detailed answer with citations.
"""

answer = await llm.generate(user_prompt, system=system_prompt)
```

**Citation Extraction**:
```python
# Parse [1], [2] citations from answer
citations = extract_citations(answer.text)

# Map to source chunks
sources = [
    {
        "chunk_id": chunks[i].id,
        "document": chunks[i].document,
        "text": chunks[i].content,
        "score": chunks[i].score
    }
    for i in citations
]
```

**Streaming Response**:
```python
async def stream_answer(query, chunks):
    prompt = format_prompt(query, chunks)

    async for token in llm.stream(prompt):
        yield {
            "type": "token",
            "content": token
        }

    yield {
        "type": "sources",
        "content": format_sources(chunks)
    }
```

## Performance Optimizations

### Caching Strategy

**Three-Layer Cache**:

1. **Embedding Cache** (Redis, 24h TTL)
   - Key: SHA256(query.lower())
   - Skips the embedding round-trip on a repeated query

2. **Result Cache** (Redis, 30min TTL)
   - Key: SHA256(query + filters + options)
   - Skips retrieval and generation entirely on an exact repeat

3. **Community Summary Cache** (Redis, 1h TTL)
   - Pre-computed community summaries, so global search does not re-summarize

Hit rates and time saved depend on how repetitive your query traffic is; measure yours before assuming a number.

### Batch Processing

**Embedding Batching**:
```python
# Instead of: for chunk in chunks: embed(chunk)
# Use batching:
embeddings = await embed_batch(chunks, batch_size=100)
# 10x faster for large documents
```

**Graph Write Batching**:
```python
# Batch entity writes
async def write_entities(entities):
    for batch in chunk_list(entities, size=100):
        await neo4j.execute_write(batch_query, batch)
```

### Parallel Execution

```python
# Execute searches in parallel
vector_task = vector_search(embedding)
entity_task = entity_search(embedding)
graph_task = graph_traverse(entities)

results = await asyncio.gather(
    vector_task,
    entity_task,
    graph_task,
    return_exceptions=True  # Don't fail if one fails
)
```

### Circuit Breaker

**Implementation**: [src/core/system/circuit_breaker.py](../src/core/system/circuit_breaker.py)

Prevents cascade failures:

```python
circuit_breaker = CircuitBreaker(
    failure_threshold=5,   # Open after 5 failures
    timeout=60,            # Stay open for 60s
    half_open_max=3        # Try 3 requests when half-open
)

if circuit_breaker.is_open():
    # Fallback to simpler search mode
    return basic_vector_search(query)
else:
    try:
        result = await complex_graph_search(query)
        circuit_breaker.record_success()
    except Exception:
        circuit_breaker.record_failure()
        raise
```
