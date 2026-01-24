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
Your goal is to rewrite the user's latest query into a standalone, semantically rich version that preserves all core intent while resolving context from the conversation history.

### Context Guidelines:
- Resolve pronouns (e.g., "it", "they", "that doc") based on previous turns.
- If the query is an follow-up (e.g., "What about the second one?"), make it explicit.
- Add domain-specific context if inferred from history.
- Keep the tone neutral and professional.

### Example:
History:
User: "What is the revenue for Microsoft in 2023?"
Assistant: "[Summary of Microsoft 2023 revenue]"
User: "And for Apple?"

Output: "What is the revenue for Apple in 2023?"

---
History:
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
Your goal is to classify the user's query into one of four search modes:

1. **basic**: Simple factual lookups or keyword searches.
2. **local**: Questions about specific entities or their direct relationships.
3. **global**: Holistic, thematic, or summary-level questions about the entire corpus (e.g., "What are the main themes?", "Summarize the findings").
4. **drift**: Complex questions requiring multi-hop reasoning or exploratory traversal across many entities.

### Logic:
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
# HyDE (Hypothetical Document Embedding)
# =============================================================================

HYDE_PROMPT = """
You are an expert technical writer.
Given the following question, write a short (50-100 words), highly relevant, and hypothetical excerpt from a document that would perfectly answer this question.
Use professional, factual language. Do not include introductory text like "Sure, here is an answer".

Question: "{query}"

Hypothetical Excerpt:
"""
