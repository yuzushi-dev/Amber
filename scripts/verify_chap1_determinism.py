import asyncio
import os
import sys
import logging
import json
from datetime import datetime
from sqlalchemy import text

# Setup path
sys.path.insert(0, os.getcwd())

from src.amber_platform.composition_root import platform, configure_settings
from src.api.config import settings
from src.shared.model_registry import DEFAULT_EMBEDDING_MODEL, DEFAULT_LLM_MODEL
from src.core.admin_ops.domain.api_key import ApiKey, ApiKeyTenant # Mapper resolution
from src.core.tenants.domain.tenant import Tenant # Mapper resolution
from src.workers.tasks import _process_document_async, _process_communities_async
from src.core.state.machine import DocumentStatus
from src.core.ingestion.domain.document import Document
from src.core.ingestion.application.ingestion_service import IngestionService
from src.core.ingestion.infrastructure.repositories.postgres_document_repository import PostgresDocumentRepository
from src.core.tenants.infrastructure.repositories.postgres_tenant_repository import PostgresTenantRepository
from src.core.ingestion.infrastructure.uow.postgres_uow import PostgresUnitOfWork
from src.core.database.session import get_session_maker, configure_database
from src.shared.identifiers import generate_document_id

logging.basicConfig(level=logging.INFO)
logging.getLogger("src.core").setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

async def get_counts(tenant_id, document_id):
    """Fetch counts of constructs from Neo4j."""
    await platform.neo4j_client.connect()
    
    # Entities
    entity_query = "MATCH (e:Entity {tenant_id: $tenant_id}) RETURN count(e) as count"
    res = await platform.neo4j_client.execute_read(entity_query, {"tenant_id": tenant_id})
    entities = res[0]["count"]
    
    # Relationships
    rel_query = "MATCH ()-[r]->() WHERE r.tenant_id = $tenant_id RETURN count(r) as count"
    res = await platform.neo4j_client.execute_read(rel_query, {"tenant_id": tenant_id})
    relationships = res[0]["count"]
    
    # Communities
    comm_query = "MATCH (c:Community {tenant_id: $tenant_id}) RETURN count(c) as count"
    res = await platform.neo4j_client.execute_read(comm_query, {"tenant_id": tenant_id})
    communities = res[0]["count"]
    
    # Similarities
    sim_query = "MATCH ()-[r:SIMILAR_TO {tenant_id: $tenant_id}]->() RETURN count(r) as count"
    res = await platform.neo4j_client.execute_read(sim_query, {"tenant_id": tenant_id})
    similarities = res[0]["count"]

    # Chunks
    chunk_query = "MATCH (c:Chunk {tenant_id: $tenant_id}) RETURN count(c) as count"
    res = await platform.neo4j_client.execute_read(chunk_query, {"tenant_id": tenant_id})
    chunks = res[0]["count"]
    
    return {
        "chunks": chunks,
        "entities": entities,
        "relationships": relationships,
        "communities": communities,
        "similarities": similarities
    }

async def run_single_test(run_id, file_path, vector_store_factory, tenant_id):
    logger.info(f"--- Starting Run {run_id} (Tenant: {tenant_id}) ---")
    
    session_maker = get_session_maker()
    async with session_maker() as session:
        repo = PostgresDocumentRepository(session)
        tenant_repo = PostgresTenantRepository(session)
        uow = PostgresUnitOfWork(session)
        
        service = IngestionService(
            document_repository=repo,
            tenant_repository=tenant_repo,
            unit_of_work=uow,
            storage_client=platform.minio_client,
            neo4j_client=platform.neo4j_client,
            vector_store=None,
            settings=settings,
            vector_store_factory=vector_store_factory
        )
        
        with open(file_path, "rb") as f:
            content = f.read()
            
        # Register
        doc = await service.register_document(
            tenant_id=tenant_id,
            filename=os.path.basename(file_path),
            file_content=content,
            content_type="application/pdf"
        )
        
        await session.commit()
        document_id = doc.id
        
        # Process (Full Pipeline)
        await service.process_document(document_id)
        
        # Process Communities
        await _process_communities_async(tenant_id)
        
        # Get Stats
        stats = await get_counts(tenant_id, document_id)
        logger.info(f"Run {run_id} Results: {stats}")
        return stats

async def main():
    file_path = "/home/daniele/Amber_2.0/Chap1.pdf"
    
    # settings = get_settings() # Handled by import
    configure_settings(settings)
    
    # Force environment variables for newly created factories/settings
    os.environ["DEFAULT_LLM_PROVIDER"] = "openai"
    os.environ["DEFAULT_LLM_MODEL"] = DEFAULT_LLM_MODEL["openai"]
    os.environ["DEFAULT_EMBEDDING_PROVIDER"] = "openai"
    os.environ["DEFAULT_EMBEDDING_MODEL"] = DEFAULT_EMBEDDING_MODEL["openai"]
    os.environ["EMBEDDING_DIMENSIONS"] = "1536"
    os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434/v1"
    
    # Update settings object too
    settings.default_llm_provider = "openai"
    settings.default_llm_model = DEFAULT_LLM_MODEL["openai"]
    settings.default_embedding_provider = "openai"
    settings.default_embedding_model = DEFAULT_EMBEDDING_MODEL["openai"]
    settings.embedding_dimensions = 1536
    
    from src.shared.kernel.runtime import configure_settings as configure_runtime_settings
    settings.seed = 42
    settings.default_llm_temperature = 0.0
    configure_runtime_settings(settings)
    
    # Disable Failover for test
    from src.core.generation.infrastructure.providers.factory import ProviderFactory
    original_get_ep = ProviderFactory.get_embedding_provider
    def patched_get_ep(self, provider_name=None, with_failover=True, model=None):
        return original_get_ep(self, provider_name=provider_name, with_failover=False, model=model)
    ProviderFactory.get_embedding_provider = patched_get_ep

    # Disable Sparse Vectors for local test (missing torch/transformers in this env)
    from src.core.retrieval.infrastructure.vector_store.milvus import MilvusVectorStore
    original_create = MilvusVectorStore._create_collection
    async def patched_create(self, milvus):
        # Modify the milvus dict to 'hide' sparse vector support
        if "DataType" in milvus and hasattr(milvus["DataType"], "SPARSE_FLOAT_VECTOR"):
            # We create a proxy class or just remove from dict
            # Actually, _get_milvus returns a dict. We can't change the Enum but we can change the dict!
            # But _create_collection is called with the dict.
            # I'll just monkey patch the function to skip those lines.
            pass
        return await original_create(self, milvus)
    
    # Actually, easier to just provide a dummy sparse vector in the upsert?
    # No, Milvus requires the INDEX too.
    
    # I'll just patch _create_collection to not add the field.
    async def skip_sparse_create(self, milvus):
        # This is a bit of work to copy-paste.
        # Let's try to just mock 'hasattr' if possible? No.
        
        # How about I just patch the dict entry?
        # milvus['DataType'] is the real Enum.
        # I'll create a wrapper for milvus['DataType']
        class DataTypeWrapper:
            def __init__(self, original):
                self.original = original
            def __getattr__(self, name):
                if name == "SPARSE_FLOAT_VECTOR":
                    raise AttributeError()
                return getattr(self.original, name)
        
        milvus["DataType"] = DataTypeWrapper(milvus["DataType"])
        return await original_create(self, milvus)

    MilvusVectorStore._create_collection = skip_sparse_create

    # Overrides for local/host run
    if "localhost:5432" in settings.db.database_url:
        settings.db.database_url = settings.db.database_url.replace("localhost:5432", "localhost:5433")
    elif "127.0.0.1:5432" in settings.db.database_url:
        settings.db.database_url = settings.db.database_url.replace("127.0.0.1:5432", "localhost:5433")
    
    if not settings.db.neo4j_password:
        settings.db.neo4j_password = "graphrag123"
    
    settings.ollama_base_url = "http://localhost:11434/v1"
    
    if not settings.minio.root_user:
        settings.minio.root_user = "minioadmin"
    if not settings.minio.root_password:
        settings.minio.root_password = "minioadmin"

    # Initialize Engine
    configure_database(
        settings.db.database_url,
        pool_size=settings.db.pool_size,
        max_overflow=settings.db.max_overflow
    )
    
    # Initialize Providers
    from src.core.generation.infrastructure.providers.factory import init_providers
    init_providers(
        openai_api_key=settings.openai_api_key,
        anthropic_api_key=settings.anthropic_api_key,
        default_llm_provider=settings.default_llm_provider,
        default_llm_model=settings.default_llm_model,
        default_embedding_provider=settings.default_embedding_provider,
        default_embedding_model=settings.default_embedding_model,
        ollama_base_url=settings.ollama_base_url,
    )
    
    # Initialize Extractors
    from src.core.graph.domain.ports.graph_extractor import set_graph_extractor
    from src.core.ingestion.infrastructure.extraction.graph_extractor import GraphExtractor
    set_graph_extractor(GraphExtractor(use_gleaning=False))
    
    from src.core.ingestion.domain.ports.content_extractor import set_content_extractor
    from src.core.ingestion.infrastructure.extraction.fallback_extractor import FallbackContentExtractor
    set_content_extractor(FallbackContentExtractor())

    # Initialize Platform Client
    await platform.initialize()
    
    # Drop existing collections for clean state
    from src.core.retrieval.infrastructure.vector_store.milvus import MilvusConfig, MilvusVectorStore
    for coll in ["document_chunks", "community_embeddings"]:
        clean_store = MilvusVectorStore(MilvusConfig(
            host=settings.db.milvus_host,
            port=settings.db.milvus_port,
            collection_name=coll
        ))
        await clean_store.drop_collection()

    from src.amber_platform.composition_root import build_vector_store_factory
    vector_store_factory = build_vector_store_factory()

    results = []
    base_tenant_id = f"test_det_{datetime.now().strftime('%M%S')}"
    session_maker = get_session_maker()
    
    for i in range(1, 4):
        # Deep Cleanup for each run to ensure fresh state but stable IDs
        await platform.neo4j_client.connect()
        await platform.neo4j_client.execute_write("MATCH (n {tenant_id: $tid}) DETACH DELETE n", {"tid": base_tenant_id})
        
        # Postgres cleanup (simple way: delete documents, chunks cascade)
        async with session_maker() as session:
            await session.execute(text(f"DELETE FROM chunks WHERE tenant_id = '{base_tenant_id}'"))
            await session.execute(text(f"DELETE FROM documents WHERE tenant_id = '{base_tenant_id}'"))
            await session.commit()

        res = await run_single_test(i, file_path, vector_store_factory, base_tenant_id)
        results.append(res)
        
    print("\n" + "="*80)
    print(f"DETERMINISM VERIFICATION SUMMARY (@[Chap1.pdf])")
    print("="*80)
    print(f"{'Metric':<15} | {'Run 1':<10} | {'Run 2':<10} | {'Run 3':<10} | {'Match?'}")
    print("-" * 80)
    
    metrics = ["chunks", "entities", "relationships", "communities", "similarities"]
    all_match = True
    
    for m in metrics:
        v1 = results[0][m]
        v2 = results[1][m]
        v3 = results[2][m]
        match = "✅" if v1 == v2 == v3 else "❌"
        if not v1 == v2 == v3:
            all_match = False
        print(f"{m:<15} | {v1:<10} | {v2:<10} | {v3:<10} | {match}")
        
    print("="*80)
    if all_match:
        print("SUCCESS: 100% Deterministic outcome achieved!")
    else:
        print("FAILURE: Variance detected. Further investigation needed.")
    print("="*80 + "\n")

    await platform.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
