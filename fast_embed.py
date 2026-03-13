import asyncio
from src.amber_platform.composition_root import platform, build_vector_store_factory
from src.api.config import settings
from src.shared.kernel.runtime import configure_settings
from src.core.database.session import configure_database
from src.core.retrieval.application.embeddings_service import EmbeddingService
from src.core.retrieval.application.sparse_embeddings_service import SparseEmbeddingService
from src.core.graph.application.communities.embeddings import CommunityEmbeddingService
from src.core.generation.infrastructure.providers.factory import ProviderFactory

async def run():
    configure_settings(settings)
    configure_database(settings.db.database_url)
    
    # Initialize Neo4j
    await platform.initialize()
    
    factory = ProviderFactory(
        openai_api_key=settings.openai_api_key,
        anthropic_api_key=settings.anthropic_api_key,
        ollama_base_url=settings.ollama_base_url,
        default_llm_provider=settings.default_llm_provider,
        default_llm_model=settings.default_llm_model,
        llm_fallback_local=settings.llm_fallback_local,
        llm_fallback_economy=settings.llm_fallback_economy,
        llm_fallback_standard=settings.llm_fallback_standard,
        llm_fallback_premium=settings.llm_fallback_premium,
        openrouter_api_key=settings.openrouter_api_key,
        openrouter_base_url=settings.openrouter_base_url,
        nvidia_nim_api_key=settings.nvidia_nim_api_key,
        nvidia_nim_base_url=settings.nvidia_nim_base_url,
        llm_fallback_enabled=settings.llm_fallback_enabled,
    )
    
    embedding_provider = factory.get_embedding_provider(
        provider_name=settings.default_embedding_provider,
        model=settings.default_embedding_model,
    )
    
    embedding_svc = EmbeddingService(
        provider=embedding_provider,
        model=settings.default_embedding_model,
    )
    
    vector_store_factory = build_vector_store_factory()
    comm_vector_store = vector_store_factory(
        settings.embedding_dimensions or 1536,
        collection_name="community_embeddings",
    )
    
    sparse_svc = SparseEmbeddingService()
    
    comm_embedding_svc = CommunityEmbeddingService(
        embedding_service=embedding_svc,
        vector_store=comm_vector_store,
        sparse_embedding_service=sparse_svc,
    )
    
    query = "MATCH (c:Community) WHERE c.summary IS NOT NULL RETURN c.id AS id, c.tenant_id AS tenant_id, c.level AS level, c.title AS title, c.summary AS summary LIMIT 100"
    print("Fetching communities from Neo4j...")
    records = await platform.neo4j_client.execute_read(query)
    
    print(f"Found {len(records)} communities with summaries. Embedding...")
    
    for i, rec in enumerate(records):
        await comm_embedding_svc.embed_and_store_community({
            "id": rec["id"],
            "tenant_id": rec.get("tenant_id", "default"),
            "level": int(rec.get("level", 0)) if rec.get("level") is not None else 0,
            "title": rec.get("title", ""),
            "summary": rec.get("summary", "")
        })
        if i % 10 == 0:
            print(f"Processed {i} communities...")
            
    print("Done!")

if __name__ == "__main__":
    asyncio.run(run())
