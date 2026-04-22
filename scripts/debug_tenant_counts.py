import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from sqlalchemy import (
    select,
    text,  # Import text
)

from src.api.deps import _async_session_maker
from src.core.models.document import Document
from src.core.models.tenant import Tenant


async def main():
    async with _async_session_maker() as session:
        # Disable RLS for this debug session
        await session.execute(text("SET row_security = off"))

        # Get all tenants
        result = await session.execute(select(Tenant))
        tenants = result.scalars().all()

        print(f"Found {len(tenants)} tenants.")

        # Get list of valid tenant IDs
        valid_tenant_ids = [t.id for t in tenants]

        # Get ALL documents
        print("\n--- All Documents in Database ---")
        doc_query = select(Document.id, Document.filename, Document.tenant_id)
        doc_result = await session.execute(doc_query)
        all_docs = doc_result.all()

        for doc_id, filename, doc_tenant_id in all_docs:
            status = "VALID" if doc_tenant_id in valid_tenant_ids else "ORPHAN/GHOST"
            if doc_tenant_id is None:
                status = "NULL_TENANT"

            print(f"Doc: {filename} | TenantID: {doc_tenant_id} | Status: {status}")

        count_orphans = sum(1 for d in all_docs if d[2] not in valid_tenant_ids)
        print(f"\nTotal Documents: {len(all_docs)}")
        print(f"Total Orphans/Ghosts: {count_orphans}")

if __name__ == "__main__":
    asyncio.run(main())
