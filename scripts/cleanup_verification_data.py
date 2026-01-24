import asyncio
import os
import sys
import logging
from sqlalchemy import select, delete, text
from sqlalchemy.orm import selectinload

from src.api.main import app
from src.core.tenants.domain.tenant import Tenant
from src.core.admin_ops.domain.api_key import ApiKey
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.folder import Folder
from src.core.generation.domain.memory_models import ConversationSummary, UserFact
from src.core.database.session import get_session_maker

# Setup
os.environ["LOG_LEVEL"] = "INFO"
# Target the DEFAULT DB (UI connection)
os.environ["DATABASE_URL"] = "postgresql+asyncpg://graphrag:graphrag@localhost:5433/graphrag"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["MILVUS_HOST"] = "localhost"
os.environ["MILVUS_PORT"] = "19530"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def cleanup_data():
    logger.info("Starting cleanup of verification data...")
    
    # 1. Init Dependencies (Milvus, Postgres)
    # We use lifespan to ensure connections are up
    async with app.router.lifespan_context(app):
        session_maker = get_session_maker()
        
        async with session_maker() as session:
            # ---------------------------------------------------------
            # 1. Identify Target Tenants
            # ---------------------------------------------------------
            patterns = ["Tenant A %", "Tenant B %", "Chat Tenant %"]
            tenant_ids_to_delete = []
            
            for ptrn in patterns:
                stmt = select(Tenant).where(Tenant.name.like(ptrn))
                result = await session.execute(stmt)
                tenants = result.scalars().all()
                for t in tenants:
                    tenant_ids_to_delete.append(t.id)
                    logger.info(f"Marked Tenant for deletion: {t.name} ({t.id})")
            
            if not tenant_ids_to_delete:
                logger.info("No test tenants found.")
            else:
                # ---------------------------------------------------------
                # 2. Cleanup External Resources (Milvus)
                # ---------------------------------------------------------
                from src.core.retrieval.infrastructure.vector_store.milvus import MilvusVectorStore
                # Initialize store directly or via provider
                # Hack: MilvusVectorStore needs a URL/Host
                try:
                    store = MilvusVectorStore(
                        uri=f"http://{os.environ['MILVUS_HOST']}:{os.environ['MILVUS_PORT']}",
                        user="", password=""
                    )
                    await store.connect()
                    
                    for tid in tenant_ids_to_delete:
                        collection_name = f"amber_{tid}"
                        logger.info(f"Dropping Milvus collection: {collection_name}")
                        await store.drop_collection(collection_name)
                        
                except Exception as e:
                    logger.error(f"Failed to cleanup Milvus: {e}")

            # ---------------------------------------------------------
            # 2.5 SPECIAL: Cleanup Orphaned Test Folders (Default Tenant or Others)
            # ---------------------------------------------------------
            # These folders were likely created in the default or other tenants during tests
            # and might not be caught if the tenant deletion skipped them or they are in 'default'.
            folder_patterns = [
                "cascade-test-%", 
                "delete-test-%",
                "doc-move-test-%",
                "list-test-%",
                "Test%" # From screenshot (e.g. "Test")
            ]
            
            for ptrn in folder_patterns:
                stmt = delete(Folder).where(Folder.name.like(ptrn))
                res = await session.execute(stmt)
                if res.rowcount > 0:
                    logger.info(f"Deleted {res.rowcount} Folders matching '{ptrn}'")

            if tenant_ids_to_delete:
                # ---------------------------------------------------------
                # 3. Cascade Delete in Postgres
                # ---------------------------------------------------------
                
                # Delete Documents
                stmt = delete(Document).where(Document.tenant_id.in_(tenant_ids_to_delete))
                res = await session.execute(stmt)
                logger.info(f"Deleted {res.rowcount} Documents")
                
                # Delete Chats
                stmt = delete(ConversationSummary).where(ConversationSummary.tenant_id.in_(tenant_ids_to_delete))
                res = await session.execute(stmt)
                logger.info(f"Deleted {res.rowcount} Conversation Summaries")
                
                # Delete User Facts
                stmt = delete(UserFact).where(UserFact.tenant_id.in_(tenant_ids_to_delete))
                res = await session.execute(stmt)
                logger.info(f"Deleted {res.rowcount} User Facts")
                
                # Delete Folders
                stmt = delete(Folder).where(Folder.tenant_id.in_(tenant_ids_to_delete))
                res = await session.execute(stmt)
                logger.info(f"Deleted {res.rowcount} Folders")
                
                # Delete ApiKey Tenants Links
                # Need to use SQL for association table if no model readily available or use cascade
                # We assume ApiKeyTenant model exists or usage of 'api_key_tenants' table
                # Let's try raw SQL for safety map
                await session.execute(
                    text("DELETE FROM api_key_tenants WHERE tenant_id = ANY(:tids)"),
                    {"tids": tenant_ids_to_delete}
                )
                logger.info("Deleted ApiKey links")

                # finally Delete Tenants
                stmt = delete(Tenant).where(Tenant.id.in_(tenant_ids_to_delete))
                res = await session.execute(stmt)
                logger.info(f"Deleted {res.rowcount} Tenants")

            # ---------------------------------------------------------
            # 4. Cleanup Test Keys
            # ---------------------------------------------------------
            key_patterns = ["Key A %", "Key B %", "User Key %", "Verification Bootstrap", "Development Key"]
            # Be careful with Development Key if it's used elsewhere, but verify scripts created it mostly. 
            # Actually Development Key might be system default? Check lifepan.
            # "Verification Bootstrap" is definitely ours.
            
            for ptrn in key_patterns:
                # Avoid deleting key if it has other tenants linked? 
                # For cleanup, we assume these keys are exclusively for these tests.
                
                # Special check: Don't delete 'Development Key' if it's the only admin key?
                # The user script 'verify_tenant_isolation' used 'Development Key' injected by system?
                # No, it checks Authenticated name.
                # Actually, verify_tenant_isolation uses `settings.admin_api_key`.
                # We should probably NOT delete "Development Key" if it's the system default.
                if "Development Key" in ptrn:
                    continue 

                stmt = delete(ApiKey).where(ApiKey.name.like(ptrn))
                res = await session.execute(stmt)
                if res.rowcount > 0:
                    logger.info(f"Deleted {res.rowcount} Keys matching '{ptrn}'")

            await session.commit()
            logger.info("Cleanup complete.")

if __name__ == "__main__":
    asyncio.run(cleanup_data())
