"""
Query Parser
============

Extracts explicit filters and metadata from raw query strings using regex.
"""

import re
from datetime import datetime

from src.core.query.models import StructuredQuery


class QueryParser:
    """
    Parses raw queries to extract explicit filters.

    Supported syntax:
    - @filename: Filters to a specific document
    - #entity: Filters to a specific entity/tag
    - since:YYYY-MM-DD: Temporal filter
    - until:YYYY-MM-DD: Temporal filter
    """

    # Regex patterns
    DOC_PATTERN = re.compile(r"@(\w+)")
    TAG_PATTERN = re.compile(r"#(\w+)")
    SINCE_PATTERN = re.compile(r"since:(\d{4}-\d{2}-\d{2})")
    UNTIL_PATTERN = re.compile(r"until:(\d{4}-\d{2}-\d{2})")

    @classmethod
    def parse(cls, query: str) -> StructuredQuery:
        """
        Parse a raw query string into a StructuredQuery object.
        """
        original_query = query
        cleaned_query = query

        # Extract filters
        doc_ids = cls.DOC_PATTERN.findall(cleaned_query)
        tags = cls.TAG_PATTERN.findall(cleaned_query)

        since_matches = cls.SINCE_PATTERN.findall(cleaned_query)
        until_matches = cls.UNTIL_PATTERN.findall(cleaned_query)

        date_after = None
        if since_matches:
            try:
                date_after = datetime.strptime(since_matches[0], "%Y-%m-%d")
            except ValueError:
                pass

        date_before = None
        if until_matches:
            try:
                date_before = datetime.strptime(until_matches[0], "%Y-%m-%d")
            except ValueError:
                pass

        # Cleanup query text by removing patterns
        cleaned_query = cls.DOC_PATTERN.sub("", cleaned_query)
        cleaned_query = cls.TAG_PATTERN.sub("", cleaned_query)
        cleaned_query = cls.SINCE_PATTERN.sub("", cleaned_query)
        cleaned_query = cls.UNTIL_PATTERN.sub("", cleaned_query)

        # Normalize whitespace
        cleaned_query = " ".join(cleaned_query.split()).strip()

        # If query becomes empty after filter removal, revert to original_query for search
        # but keep filters. This handles queries like "@doc1 #tag1"
        if not cleaned_query:
            cleaned_query = original_query

        return StructuredQuery(
            original_query=original_query,
            cleaned_query=cleaned_query,
            document_ids=doc_ids,
            tags=tags,
            date_after=date_after,
            date_before=date_before
        )
