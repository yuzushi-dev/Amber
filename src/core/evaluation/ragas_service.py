"""
Ragas Evaluation Service
========================

Wraps the official Ragas library for systematic RAG evaluation.
Falls back to custom JudgeService if Ragas is not installed.
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

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
    faithfulness: Optional[float] = None
    response_relevancy: Optional[float] = None
    context_precision: Optional[float] = None
    context_recall: Optional[float] = None
    metadata: Dict[str, Any] = None
    
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
        llm_client: Optional[Any] = None,
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
                self._llm = llm_factory(model_name, client=llm_client)
                self._faithfulness = Faithfulness(llm=self._llm)
                self._response_relevancy = ResponseRelevancy(llm=self._llm)
                self._metrics_initialized = True
                logger.info("RagasService initialized with official Ragas metrics")
            except Exception as e:
                logger.error(f"Failed to initialize Ragas metrics: {e}")
                self._metrics_initialized = False

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
            return await self._fallback_faithfulness(query, context, response)
        
        try:
            # Ragas expects contexts as a list
            contexts = [context] if isinstance(context, str) else context
            
            result = await self._faithfulness.ascore(
                user_input=query,
                response=response,
                retrieved_contexts=contexts
            )
            return result.value if hasattr(result, 'value') else float(result)
        except Exception as e:
            logger.error(f"Ragas faithfulness evaluation failed: {e}")
            return await self._fallback_faithfulness(query, context, response)

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
            return await self._fallback_relevance(query, response)
        
        try:
            result = await self._response_relevancy.ascore(
                user_input=query,
                response=response
            )
            return result.value if hasattr(result, 'value') else float(result)
        except Exception as e:
            logger.error(f"Ragas relevancy evaluation failed: {e}")
            return await self._fallback_relevance(query, response)

    async def evaluate_sample(
        self,
        query: str,
        context: str,
        response: str,
        reference: Optional[str] = None
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
        samples: List[Dict[str, str]]
    ) -> List[RagasEvaluationResult]:
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
            from src.core.evaluation.judge import JudgeService
            from src.core.providers.factory import ProviderFactory
            from src.core.generation.registry import PromptRegistry
            from src.api.config import settings
            
            factory = ProviderFactory(
                openai_api_key=settings.providers.openai_api_key,
                anthropic_api_key=settings.providers.anthropic_api_key
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
            from src.core.evaluation.judge import JudgeService
            from src.core.providers.factory import ProviderFactory
            from src.core.generation.registry import PromptRegistry
            from src.api.config import settings
            
            factory = ProviderFactory(
                openai_api_key=settings.providers.openai_api_key,
                anthropic_api_key=settings.providers.anthropic_api_key
            )
            llm = factory.get_llm_provider("openai")
            registry = PromptRegistry()
            
            judge = JudgeService(llm=llm, prompt_registry=registry)
            result = await judge.evaluate_relevance(query, response)
            return result.score
        except Exception as e:
            logger.error(f"Fallback relevance evaluation failed: {e}")
            return 0.0
