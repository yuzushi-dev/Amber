"""
Document Summarizer
===================

LLM-based document summarization, type classification, and hashtag extraction.
Ported from reference Amber project.
"""

import logging
import re
from typing import Any

from src.core.generation.domain.provider_models import ProviderTier
from src.core.generation.domain.ports.provider_factory import build_provider_factory, get_provider_factory

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

    def _get_llm(self, provider_name: str | None = None, model: str | None = None):
        """Lazy-load LLM provider."""
        from src.shared.kernel.runtime import get_settings
        settings = get_settings()
        if settings.openai_api_key or settings.anthropic_api_key:
            factory = build_provider_factory(
                openai_api_key=settings.openai_api_key,
                anthropic_api_key=settings.anthropic_api_key,
            )
        else:
            factory = get_provider_factory()

        if provider_name or model:
            return factory.get_llm_provider(
                provider_name=provider_name,
                model=model,
                tier=ProviderTier.ECONOMY,
            )

        if self._llm is None:
            self._llm = factory.get_llm_provider(tier=ProviderTier.ECONOMY)
        return self._llm

    async def extract_summary(
        self,
        chunks: list[str],
        document_title: str = "",
        max_summary_length: int = 1000,
        tenant_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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

            # Generate response with metrics tracking
            from src.shared.kernel.runtime import get_settings
            settings = get_settings()
            from src.core.admin_ops.application.metrics.collector import MetricsCollector
            from src.shared.identifiers import generate_query_id
            
            from src.core.generation.application.llm_steps import resolve_llm_step_config

            tenant_config = tenant_config or {}
            llm_cfg = resolve_llm_step_config(
                tenant_config=tenant_config,
                step_id="ingestion.document_summarization",
                settings=settings,
            )

            llm = self._get_llm(provider_name=llm_cfg.provider, model=llm_cfg.model)
            query_id = generate_query_id()
            collector = MetricsCollector(redis_url=settings.db.redis_url)
            
            async with collector.track_query(query_id, "system", f"Summarize: {document_title}") as qm:
                qm.operation = "summarization"
                result = await llm.generate(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    temperature=llm_cfg.temperature,
                    max_tokens=800,
                    seed=llm_cfg.seed,
                )
                qm.tokens_used = result.usage.total_tokens if hasattr(result, 'usage') else 0
                qm.input_tokens = result.usage.input_tokens if hasattr(result, 'usage') else 0
                qm.output_tokens = result.usage.output_tokens if hasattr(result, 'usage') else 0
                qm.cost_estimate = result.cost_estimate if hasattr(result, 'cost_estimate') else 0.0
                qm.model = result.model if hasattr(result, 'model') else ""
                qm.provider = result.provider if hasattr(result, 'provider') else ""
                qm.response = result.text[:500] if len(result.text) > 500 else result.text

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

    def _parse_response(self, response_text: str) -> dict[str, Any]:
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

    def _clean_hashtags(self, hashtags: list[Any]) -> list[str]:
        """Clean and normalize hashtags."""
        cleaned = []
        for tag in hashtags:
            if isinstance(tag, str):
                tag = tag.strip()
                if not tag.startswith('#'):
                    tag = '#' + tag
                cleaned.append(tag)
        return cleaned[:8]  # Limit to 8

    def _empty_result(self) -> dict[str, Any]:
        """Return empty result structure."""
        return {
            "summary": "",
            "document_type": "other",
            "hashtags": []
        }


# Module-level singleton
_summarizer_instance: DocumentSummarizer | None = None


def get_document_summarizer() -> DocumentSummarizer:
    """Get or create the document summarizer singleton."""
    global _summarizer_instance
    if _summarizer_instance is None:
        _summarizer_instance = DocumentSummarizer()
    return _summarizer_instance
