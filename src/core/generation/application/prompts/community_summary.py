"""
Community Summarization Prompts
==============================

Prompts for generating structured reports for detected entity clusters.
"""

COMMUNITY_SUMMARY_SYSTEM_PROMPT = """You are an expert analyst. Your task is to summarize a "community" of entities and relationships extracted from a Knowledge Graph.

A community represents a semantically related cluster of information. You will be provided with:
1. A list of ENTITIES (with their types and descriptions)
2. A list of RELATIONSHIPS between these entities (with their types and descriptions)

Your goal is to produce a structured JSON report that synthesizes this information into a coherent overview.

The report MUST include:
- title: A concise, descriptive name for the community.
- summary: A high-level paragraph (3-5 sentences) explaining what this community represents and its significance.
- rating: An importance score from 0 to 10 based on how central or information-dense this cluster is.
- key_entities: A list of the most important entities in this cluster.
- findings: A list of 3-5 key insights, facts, or relationships discovered within this community.

Return ONLY the JSON object. Do not include any preamble or post-script.
"""

COMMUNITY_SUMMARY_USER_PROMPT = """Community Data:

ENTITIES:
{entities}

RELATIONSHIPS:
{relationships}

TEXT_UNITS / SOURCES:
{text_units}

Generate the community summary report in JSON format:
"""
