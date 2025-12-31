import logging
import asyncio
from typing import List, Dict, Any, Optional
from src.core.models.candidate import Candidate
# from src.core.services.retrieval import RetrievalService # Removed to avoid circular import
from src.core.providers.base import BaseLLMProvider

logger = logging.getLogger(__name__)

class DriftSearchService:
    """
    Implements DRIFT Search (Dynamic Reasoning and Inference with Flexible Traversal).
    Performs iterative context gathering and reasoning.
    """
    
    def __init__(
        self,
        retrieval_service: Any, # Avoid circular import with RetrievalService
        llm_provider: BaseLLMProvider,
        max_iterations: int = 3,
        max_follow_ups: int = 3
    ):
        self.retrieval_service = retrieval_service
        self.llm = llm_provider
        self.max_iterations = max_iterations
        self.max_follow_ups = max_follow_ups

    async def search(
        self,
        query: str,
        tenant_id: str,
        options: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Execute DRIFT Search:
        1. Primer: Initial retrieval and follow-up generation.
        2. Expansion: Iteratively retrieve for high-confidence follow-ups.
        3. Synthesis: Final grounded answer generation.
        """
        all_candidates = []
        follow_ups_history = []
        
        # 1. Primer Phase
        logger.info(f"DRIFT Primer for query: {query}")
        primer_results = await self.retrieval_service.retrieve(
            query=query,
            tenant_id=tenant_id,
            top_k=5
        )
        all_candidates.extend(primer_results.chunks)
        
        current_context = "\n".join([c["content"] for c in primer_results.chunks])
        
        for iteration in range(self.max_iterations):
            # Generate follow-up questions to fill gaps
            follow_up_prompt = f"""
            Based on the query and current context, identify {self.max_follow_ups} specific questions 
            that would help provide a more complete answer.
            Query: {query}
            Context: {current_context}
            
            Return ONLY the questions, one per line. If no more info is needed, return 'DONE'.
            Questions:
            """
            
            response = await self.llm.generate(follow_up_prompt)
            if "DONE" in response.upper():
                break
                
            questions = [q.strip() for q in response.split("\n") if q.strip()][:self.max_follow_ups]
            follow_ups_history.append({"iteration": iteration, "questions": questions})
            
            # 2. Expansion Phase: Execute sub-queries
            expansion_tasks = [
                self.retrieval_service.retrieve(query=q, tenant_id=tenant_id, top_k=3)
                for q in questions
            ]
            expansion_results = await asyncio.gather(*expansion_tasks)
            
            new_info_found = False
            for res in expansion_results:
                for chunk in res.chunks:
                    # Simple deduplication by content or ID
                    if not any(c["chunk_id"] == chunk["chunk_id"] for c in all_candidates):
                        all_candidates.append(chunk)
                        current_context += "\n" + chunk["content"]
                        new_info_found = True
            
            if not new_info_found:
                break

        # 3. Synthesis Phase
        synthesis_prompt = f"""
        You are an expert analyst. Answer the user query using the provided context.
        Query: {query}
        Context: {current_context}
        
        Provide a detailed, grounded answer with citations where appropriate.
        Answer:
        """
        
        final_answer = await self.llm.generate(synthesis_prompt)
        
        return {
            "answer": final_answer,
            "candidates": all_candidates,
            "follow_ups": follow_ups_history
        }
