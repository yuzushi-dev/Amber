"""
Evaluation Runner
=================

Orchestrates the evaluation of RAG outputs against a golden dataset using JudgeService.
"""

import asyncio
import json
import logging
from typing import List, Dict, Any

from src.core.evaluation.judge import JudgeService
from src.core.generation.registry import PromptRegistry
from src.core.providers.factory import ProviderFactory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_evaluation(dataset_path: str, provider_name: str = "openai"):
    """
    Runs evaluation for each entry in the golden dataset.
    """
    # Load dataset
    with open(dataset_path, "r") as f:
        dataset = json.load(f)

    # Initialize Services
    factory = ProviderFactory()
    llm = factory.get_llm_provider(provider_name)
    registry = PromptRegistry()
    judge = JudgeService(llm=llm, prompt_registry=registry)

    results = []
    
    print(f"\n--- Starting Evaluation on {len(dataset)} items ---\n")

    for i, entry in enumerate(dataset):
        query = entry["query"]
        ideal_answer = entry["ideal_answer"]
        
        # In a real scenario, you would call your RetrievalService here:
        # actual_result = await retrieval_service.retrieve(query, tenant_id="eval")
        # For demonstration, we simulate an answer:
        actual_answer = f"Simulated answer for: {query}" 
        actual_context = entry.get("ideal_context", "Sample context")

        print(f"[{i+1}/{len(dataset)}] Evaluating Query: {query}")

        # Evaluate Faithfulness
        faith_res = await judge.evaluate_faithfulness(
            query=query, 
            context=actual_context, 
            answer=actual_answer
        )

        # Evaluate Relevance
        rel_res = await judge.evaluate_relevance(
            query=query, 
            answer=actual_answer
        )

        results.append({
            "query": query,
            "faithfulness": faith_res.score,
            "relevance": rel_res.score,
            "reasoning_faith": faith_res.reasoning,
            "reasoning_rel": rel_res.reasoning
        })

    # Summary
    avg_faith = sum(r["faithfulness"] for r in results) / len(results)
    avg_rel = sum(r["relevance"] for r in results) / len(results)

    print("\n--- Evaluation Summary ---")
    print(f"Average Faithfulness: {avg_faith:.2f}")
    print(f"Average Relevance: {avg_rel:.2f}")
    print("--------------------------\n")

    return results

if __name__ == "__main__":
    asyncio.run(run_evaluation("src/core/evaluation/golden_dataset.json"))
