import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from sqlalchemy import select, text, update

from src.api.deps import _async_session_maker
from src.core.models.chunk import Chunk
from src.core.models.document import Document
from src.core.models.tenant import Tenant


async def main():
    async with _async_session_maker() as session:
        # 1. Disable RLS
        await session.execute(text("SET row_security = off"))

        # 2. Find Admin Tenant
        # We assume the user wants to migrate to the first available tenant (which is Admin in this context)
        # or specifically one named "Admin"
        result = await session.execute(select(Tenant).limit(1))
        admin_tenant = result.scalars().first()

        if not admin_tenant:
            print("Error: No tenants found to migrate data to.")
            return

        print(f"Target Tenant: {admin_tenant.name} (ID: {admin_tenant.id})")

        # 3. Update Documents
        print("Migrating documents...")
        doc_stmt = (
            update(Document)
            .where(Document.tenant_id == 'default')
            .values(tenant_id=admin_tenant.id)
            .execution_options(synchronize_session=False)
        )
        doc_result = await session.execute(doc_stmt)
        print(f"  - Updated {doc_result.rowcount} documents.")

        # 4. Update Chunks
        print("Migrating chunks...")
        chunk_stmt = (
            update(Chunk)
            .where(Chunk.tenant_id == 'default')
            .values(tenant_id=admin_tenant.id)
            .execution_options(synchronize_session=False)
        )
        chunk_result = await session.execute(chunk_stmt)
        print(f"  - Updated {chunk_result.rowcount} chunks.")

        await session.commit()
        print("Migration complete.")

if __name__ == "__main__":
    asyncio.run(main())
