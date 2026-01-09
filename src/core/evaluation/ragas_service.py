"""
Ragas Evaluation Service
========================

Wraps the official Ragas library for systematic RAG evaluation.
Falls back to custom JudgeService if Ragas is not installed.
"""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)
logging.getLogger("ragas").setLevel(logging.DEBUG)

# Check if ragas is available
try:
    import ragas
    from ragas.llms import llm_factory
    from ragas.metrics import Faithfulness, ResponseRelevancy
    RAGAS_AVAILABLE = True
    logger.info(f"Ragas library loaded (version {ragas.__version__})")
except ImportError:
    RAGAS_AVAILABLE = False
    logger.warning("Ragas library not installed. Using fallback JudgeService.")


@dataclass
class RagasEvaluationResult:
    """Result from a Ragas evaluation."""
    faithfulness: float | None = None
    response_relevancy: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class RagasService:
    """
    Evaluates RAG outputs using the official Ragas library.

    Falls back to JudgeService for faithfulness/relevance if Ragas is unavailable.
    """

    def __init__(
        self,
        llm_client: Any | None = None,
        model_name: str = "gpt-4o-mini"
    ):
        """
        Initialize the RagasService.

        Args:
            llm_client: An async LLM client (e.g., AsyncOpenAI instance)
            model_name: Name of the model to use for evaluation
        """
        self.model_name = model_name
        self.llm_client = llm_client
        self._llm = None
        self._metrics_initialized = False

        if RAGAS_AVAILABLE and llm_client:
            try:
                from langchain_openai import OpenAIEmbeddings
                
                # Increase max_tokens to prevent truncation errors during evaluation
                self._llm = llm_factory(model_name, client=llm_client, max_tokens=4096)
                
                # Create LangChain-compatible embeddings wrapper using the client's API key
                api_key = llm_client.api_key if hasattr(llm_client, 'api_key') else None
                self._embeddings = OpenAIEmbeddings(openai_api_key=api_key)
                
                self._faithfulness = Faithfulness(llm=self._llm)
                self._response_relevancy = ResponseRelevancy(llm=self._llm, embeddings=self._embeddings)
                self._metrics_initialized = True
                logger.info("RagasService initialized with official Ragas metrics")
            except Exception as e:
                logger.error(f"Failed to initialize Ragas metrics: {e}", exc_info=True)
                self._metrics_initialized = False
        else:
             logger.warning(f"Ragas Init Skipped - Available: {RAGAS_AVAILABLE}, Client: {bool(llm_client)}")

    @property
    def is_available(self) -> bool:
        """Check if Ragas is available and initialized."""
        return RAGAS_AVAILABLE and self._metrics_initialized

    async def evaluate_faithfulness(
        self,
        query: str,
        context: str,
        response: str
    ) -> float:
        """
        Evaluate the faithfulness of a response to the context.

        Args:
            query: The user's question
            context: The retrieved context (concatenated chunks)
            response: The generated answer

        Returns:
            Faithfulness score (0.0 to 1.0)
        """
        if not self.is_available:
            raise RuntimeError("Ragas is not initialized and fallback is disabled.")

        try:
            from ragas.dataset_schema import SingleTurnSample
            # Ragas expects contexts as a list
            contexts = [context] if isinstance(context, str) else context
            
            logger.info(f"Evaluating Faithfulness - Query: {query[:50]}..., Context Len: {len(context)}, Response Len: {len(response)}")
            
            sample = SingleTurnSample(
                user_input=query,
                response=response,
                retrieved_contexts=contexts
            )

            result = await self._faithfulness.single_turn_ascore(sample)
            logger.info(f"Faithfulness Score: {result}")
            return result
        except Exception as e:
            logger.error(f"Ragas faithfulness evaluation failed: {e}", exc_info=True)
            raise

    async def evaluate_response_relevancy(
        self,
        query: str,
        response: str
    ) -> float:
        """
        Evaluate how relevant the response is to the query.

        Args:
            query: The user's question
            response: The generated answer

        Returns:
            Relevancy score (0.0 to 1.0)
        """
        if not self.is_available:
            raise RuntimeError("Ragas is not initialized and fallback is disabled.")

        try:
            from ragas.dataset_schema import SingleTurnSample
            
            sample = SingleTurnSample(
                user_input=query,
                response=response
            )

            result = await self._response_relevancy.single_turn_ascore(sample)
            logger.info(f"Relevancy Score: {result}")
            return result
        except Exception as e:
            logger.error(f"Ragas relevancy evaluation failed: {e}", exc_info=True)
            raise

    async def evaluate_sample(
        self,
        query: str,
        context: str,
        response: str,
        reference: str | None = None
    ) -> RagasEvaluationResult:
        """
        Run full evaluation on a single sample.

        Args:
            query: The user's question
            context: The retrieved context
            response: The generated answer
            reference: Optional reference answer for comparison

        Returns:
            RagasEvaluationResult with all available scores
        """
        faithfulness = await self.evaluate_faithfulness(query, context, response)
        relevancy = await self.evaluate_response_relevancy(query, response)

        return RagasEvaluationResult(
            faithfulness=faithfulness,
            response_relevancy=relevancy,
            metadata={
                "ragas_available": self.is_available,
                "model": self.model_name
            }
        )

    async def evaluate_batch(
        self,
        samples: list[dict[str, str]]
    ) -> list[RagasEvaluationResult]:
        """
        Evaluate a batch of samples.

        Args:
            samples: List of dicts with keys: query, context, response

        Returns:
            List of RagasEvaluationResult
        """
        results = []
        for sample in samples:
            result = await self.evaluate_sample(
                query=sample["query"],
                context=sample.get("context", ""),
                response=sample.get("response", "")
            )
            results.append(result)
        return results

    async def _fallback_faithfulness(
        self,
        query: str,
        context: str,
        response: str
    ) -> float:
        """Use JudgeService as fallback for faithfulness."""
        try:
            from src.api.config import settings
            from src.core.evaluation.judge import JudgeService
            from src.core.generation.registry import PromptRegistry
            from src.core.providers.factory import ProviderFactory

            factory = ProviderFactory(
                openai_api_key=settings.openai_api_key,
                anthropic_api_key=settings.anthropic_api_key
            )
            llm = factory.get_llm_provider("openai")
            registry = PromptRegistry()

            judge = JudgeService(llm=llm, prompt_registry=registry)
            result = await judge.evaluate_faithfulness(query, context, response)
            return result.score
        except Exception as e:
            logger.error(f"Fallback faithfulness evaluation failed: {e}")
            return 0.0

    async def _fallback_relevance(
        self,
        query: str,
        response: str
    ) -> float:
        """Use JudgeService as fallback for relevance."""
        try:
            from src.api.config import settings
            from src.core.evaluation.judge import JudgeService
            from src.core.generation.registry import PromptRegistry
            from src.core.providers.factory import ProviderFactory

            factory = ProviderFactory(
                openai_api_key=settings.openai_api_key,
                anthropic_api_key=settings.anthropic_api_key
            )
            llm = factory.get_llm_provider("openai")
            registry = PromptRegistry()

            judge = JudgeService(llm=llm, prompt_registry=registry)
            result = await judge.evaluate_relevance(query, response)
            return result.score
        except Exception as e:
            logger.error(f"Fallback relevance evaluation failed: {e}")
            return 0.0
