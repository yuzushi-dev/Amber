"""
Document Summarizer
===================

LLM-based document summarization, type classification, and hashtag extraction.
Ported from reference Amber project.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from src.core.providers.factory import ProviderFactory
from src.core.providers.base import ProviderTier

logger = logging.getLogger(__name__)

# Comprehensive document type taxonomy
DOCUMENT_TYPES = [
    "quote", "invoice", "receipt", "purchase_order",
    "contract", "agreement",
    "report", "financial_report", "research_report", "business_report", "technical_report",
    "resume", "cv", "cover_letter",
    "insurance_document", "insurance_policy", "claim_form",
    "medical_record", "prescription",
    "legal_document", "court_document", "deed", "will", "power_of_attorney",
    "academic_paper", "thesis", "dissertation",
    "article", "blog_post", "news_article", "press_release",
    "whitepaper", "specification", "technical_specification",
    "manual", "user_manual", "guide", "tutorial",
    "presentation", "slide_deck",
    "proposal", "business_proposal", "project_proposal", "grant_proposal",
    "memo", "memorandum", "letter", "business_letter", "email",
    "form", "application_form", "registration_form", "tax_form",
    "financial_statement", "balance_sheet", "income_statement", "cash_flow_statement",
    "budget", "forecast",
    "plan", "business_plan", "project_plan", "marketing_plan",
    "strategy_document", "policy_document", "procedure_document", "sop",
    "checklist", "schedule", "calendar", "agenda",
    "minutes", "meeting_minutes", "transcript", "interview_transcript",
    "certificate", "diploma", "license", "permit",
    "warranty", "guarantee",
    "specification_sheet", "datasheet",
    "brochure", "catalog", "flyer", "pamphlet", "booklet",
    "book", "ebook", "chapter", "section",
    "reference_document", "documentation", "api_documentation", "code_documentation",
    "readme", "changelog", "release_notes",
    "announcement", "notice", "notification", "alert", "bulletin", "newsletter",
    "journal_entry", "log", "record", "note", "annotation", "comment",
    "review", "feedback", "survey", "questionnaire",
    "assessment", "evaluation", "test", "exam", "quiz",
    "worksheet", "assignment", "homework",
    "syllabus", "curriculum", "lesson_plan", "lecture_notes",
    "study_guide", "reference_sheet", "cheat_sheet",
    "other"
]


class DocumentSummarizer:
    """
    LLM-based document summarizer.
    
    Generates:
    - summary: Markdown-formatted document summary
    - document_type: Classification into one of DOCUMENT_TYPES
    - hashtags: 5-8 relevant hashtags
    """

    def __init__(self):
        """Initialize the document summarizer with LLM provider."""
        self._llm = None  # Lazy init

    def _get_llm(self):
        """Lazy-load LLM provider."""
        if self._llm is None:
            from src.api.config import settings
            factory = ProviderFactory(
                openai_api_key=settings.openai_api_key,
                anthropic_api_key=settings.anthropic_api_key
            )
            self._llm = factory.get_llm_provider(tier=ProviderTier.ECONOMY)
        return self._llm

    async def extract_summary(
        self,
        chunks: List[str],
        document_title: str = "",
        max_summary_length: int = 1000
    ) -> Dict[str, Any]:
        """
        Extract summary, document type, and hashtags from document chunks.

        Args:
            chunks: List of chunk content strings
            document_title: Document filename for context
            max_summary_length: Maximum length of summary

        Returns:
            Dictionary containing:
                - summary: Markdown-formatted summary
                - document_type: Classified document type
                - hashtags: List of relevant hashtags
        """
        try:
            if not chunks:
                logger.warning("No chunks provided for summary extraction")
                return self._empty_result()

            # Combine chunks (limit to first 10 for efficiency)
            chunks_to_use = chunks[:10]
            full_content = "\n\n".join(chunks_to_use)

            # Truncate to ~12000 chars for LLM context limits
            if len(full_content) > 12000:
                full_content = full_content[:12000]
                # Try to end at a sentence boundary
                last_period = full_content.rfind('.')
                if last_period > 10000:
                    full_content = full_content[:last_period + 1]

            # Create LLM prompts
            system_prompt = self._build_system_prompt(max_summary_length)
            user_prompt = self._build_user_prompt(full_content, document_title, max_summary_length)

            # Generate response
            llm = self._get_llm()
            result = await llm.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.3,
                max_tokens=800
            )

            # Parse JSON response
            parsed = self._parse_response(result.text)
            
            # Validate and clean
            summary = parsed.get("summary", "")[:int(max_summary_length * 1.5)]
            document_type = parsed.get("document_type", "other").lower().strip()
            hashtags = self._clean_hashtags(parsed.get("hashtags", []))
            keywords = parsed.get("keywords", [])
            categories = parsed.get("categories", ["general"])

            # Validate document type
            if document_type not in DOCUMENT_TYPES:
                logger.debug(f"Invalid document type '{document_type}', using 'other'")
                document_type = "other"

            logger.info(
                f"Extracted summary ({len(summary)} chars), type: {document_type}, "
                f"hashtags: {len(hashtags)}, keywords: {len(keywords)}"
            )

            return {
                "summary": summary,
                "document_type": document_type,
                "hashtags": hashtags,
                "keywords": keywords,
                "categories": categories
            }

        except Exception as e:
            logger.error(f"Failed to extract document summary: {e}")
            return self._empty_result()

    def _build_system_prompt(self, max_length: int) -> str:
        """Build system prompt for LLM."""
        doc_types_sample = ", ".join(DOCUMENT_TYPES[:30]) + "..."
        return f"""You are an expert document analyst specialized in creating CONCISE, structured summaries.

Your task:
1. Create a brief, well-structured summary (max {max_length} chars)
2. Classify the document type
3. Generate 5-8 relevant hashtags
4. Extract 5-10 specific keywords
5. Classify into 1-3 broad categories (e.g., "technical", "financial", "legal", "general")

Format requirements:
- Use Markdown: **bold** for key info, bullet points for lists
- Be concise: focus on essentials, no fluff
- Structure: 2-3 short paragraphs or bullet points
- Preserve key details: names, dates, amounts, main topics

Document types to choose from (examples):
{doc_types_sample}

Return JSON format:
{{
    "summary": "Concise MD summary here",
    "document_type": "selected_type",
    "hashtags": ["#hashtag1", "#hashtag2"],
    "keywords": ["keyword1", "keyword2"]
    "categories": ["general", "specific_category"]
}}

Remember: Be concise and use Markdown formatting for better readability."""

    def _build_user_prompt(self, content: str, title: str, max_length: int) -> str:
        """Build user prompt for LLM."""
        return f"""Document: {title}

Content to analyze:

{content}

Provide a concise summary (max {max_length} chars), document type, and hashtags as JSON."""

    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parse JSON from LLM response."""
        import json
        
        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        
        logger.warning("Failed to parse JSON from LLM response")
        return {}

    def _clean_hashtags(self, hashtags: List[Any]) -> List[str]:
        """Clean and normalize hashtags."""
        cleaned = []
        for tag in hashtags:
            if isinstance(tag, str):
                tag = tag.strip()
                if not tag.startswith('#'):
                    tag = '#' + tag
                cleaned.append(tag)
        return cleaned[:8]  # Limit to 8

    def _empty_result(self) -> Dict[str, Any]:
        """Return empty result structure."""
        return {
            "summary": "",
            "document_type": "other",
            "hashtags": []
        }


# Module-level singleton
_summarizer_instance: Optional[DocumentSummarizer] = None


def get_document_summarizer() -> DocumentSummarizer:
    """Get or create the document summarizer singleton."""
    global _summarizer_instance
    if _summarizer_instance is None:
        _summarizer_instance = DocumentSummarizer()
    return _summarizer_instance
