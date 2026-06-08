"""
Query Analysis Prompts
======================

Prompts for rewriting, decomposing, classifying, and HyDE.
"""

# =============================================================================
# Query Rewriting
# =============================================================================

QUERY_REWRITE_PROMPT = """
You are an expert query refiner for a RAG system.
Your goal is to rewrite the user's latest query into a standalone, semantically rich version that preserves all core intent while resolving context from the conversation history, user memory, and global domain rules.

### Context Guidelines:
- Resolve pronouns (e.g., "it", "they", "that doc") based on previous turns or user memory.
- If the query is a follow-up (e.g., "What about the second one?"), make it explicit.
- IMPORTANT: ALWAYS apply the Global Rules and System Constraints if provided. For example, if a rule says "Unless specified otherwise, assume product X", you must explicitly add "Product X" to the standalone query if the user didn't specify a product.
- Keep the tone neutral and professional.

### Example:
History:
User: "What is the revenue for Microsoft in 2023?"
Assistant: "[Summary of Microsoft 2023 revenue]"
User: "And for Apple?"

Output: "What is the revenue for Apple in 2023?"

---
Global System Rules & Constraints:
{rules}

User Memory / Known Facts:
{memory}

Conversation History:
{history}

User Query: "{query}"

Standalone Query:
"""

# =============================================================================
# Query Decomposition
# =============================================================================

QUERY_DECOMPOSITION_PROMPT = """
You are an expert query decomposer.
Your goal is to break down a complex user query into a list of atomic, independent sub-queries that can be executed as separate retrieval tasks.

### Guidelines:
- If the query is simple and atomic, return it as a single-item list.
- If the query involves comparisons, break it into parts for each subject.
- If the query involves multiple steps or facts, list them as separate queries.
- Return ONLY a JSON list of strings.

### Example:
Query: "Compare the safety features of Model X and Model Y."
Output: ["What are the safety features of Model X?", "What are the safety features of Model Y?"]

---
User Query: "{query}"

JSON Sub-queries:
"""

# =============================================================================
# Search Mode Classification
# =============================================================================

QUERY_MODE_PROMPT = """
You are an intelligent query router for a Hybrid GraphRAG system.
Your goal is to classify the user's query into one of five search modes:

1. **basic**: Simple factual lookups or keyword searches.
2. **local**: Questions about specific entities or their direct relationships.
3. **global**: Holistic, thematic, or summary-level questions about the entire corpus (e.g., "What are the main themes?", "Summarize the findings").
4. **drift**: Complex questions requiring multi-hop reasoning or exploratory traversal across many entities.
5. **structured**: Direct database queries for lists, counts, or statistics (e.g., "List all documents", "How many entities are there?", "Show database stats").

### Logic:
- List/count/stats operations on database objects (documents, entities, chunks) -> structured.
- Aggregation keywords ("all", "main", "themes", "summarize", "trends") -> global.
- Multiple entities + comparison/reasoning -> drift.
- Single entity + specific fact -> local.
- Unsure or very simple -> basic.

Return ONLY the mode string.

---
User Query: "{query}"

Search Mode:
"""

# =============================================================================
# Sufficient Context Check (iterative retrieval gate)
# =============================================================================

QUERY_SUFFICIENCY_PROMPT = """
You are a retrieval quality controller for a RAG system.
Decide whether the retrieved context snippets contain ENOUGH information to fully and faithfully answer the user query.

### Rules (be STRICT — default to NOT sufficient on any doubt):
- Judge ONLY by the snippets provided. Do not use outside knowledge.
- Decompose the query into ALL its distinct aspects/sub-questions. The context is "sufficient" ONLY if EVERY aspect is explicitly and completely supported by the snippets with the concrete specifics the query implies (e.g. exact commands, parameters, version numbers, ordered steps, prerequisites, ports, limits, exceptions/edge-cases).
- If ANY aspect is missing, only partially covered, generic/vague, or would require inference or assumptions to answer, mark it NOT sufficient. Partial coverage is NOT sufficient.
- Do not be charitable: when uncertain whether the snippets fully cover an aspect, treat it as NOT sufficient.
- When not sufficient, identify the SPECIFIC missing aspects and propose up to {max_gap_queries} short, targeted follow-up search queries that would retrieve the missing information. Each gap query must focus on one missing aspect (do NOT repeat the original query verbatim).
{tried_block}{draft_block}
### Output:
Return ONLY a JSON object, no prose:
{{"sufficient": <true|false>, "reason": "<one short sentence>", "gap_queries": ["...", "..."]}}
If sufficient, return an empty gap_queries list.

---
User Query: "{query}"

Retrieved Snippets:
{snippets}

JSON Verdict:
"""

# =============================================================================
# HyDE (Hypothetical Document Embedding)
# =============================================================================

HYDE_PROMPT = """
You are an expert technical writer.
Given the following question, write a short (50-100 words), highly relevant, and hypothetical excerpt from a document that would perfectly answer this question.
Use professional, factual language. Do not include introductory text like "Sure, here is an answer".

Question: "{query}"

Hypothetical Excerpt:
"""
