import asyncio
import sys
import os
import json
from datetime import datetime, timedelta
from uuid import uuid4

# Add project root to path
sys.path.append(os.getcwd())

from src.core.database.session import async_session_maker, configure_database
from src.core.admin_ops.domain.usage import UsageLog
from src.api.routes.admin.maintenance import get_query_metrics
from src.api.config import settings

async def verify_ingestion_aggregation():
    # Configure DB
    configure_database(settings.db.database_url)
    
    tenant_id = "test_tenant_metrics"
    doc_id = f"doc_{uuid4().hex[:8]}"
    
    print(f"Setting up test data for document: {doc_id}")
    
    # 1. Insert Mock Usage Logs
    async with async_session_maker() as session:
        # Create 3 chunk embedding logs
        logs = []
        for i in range(3):
            log = UsageLog(
                tenant_id=tenant_id,
                operation="embedding",
                provider="openai",
                model="text-embedding-3-small",
                input_tokens=100,
                output_tokens=0,
                total_tokens=100,
                cost=0.00002, # $0.00002 * 3 = $0.00006 total
                metadata_json={"document_id": doc_id, "chunk_index": i},
                created_at=datetime.utcnow()
            )
            logs.append(log)
        
        session.add_all(logs)
        await session.commit()
        print("Inserted 3 usage logs.")

    # 2. Call the function (simulating API call)
    print("Fetching metrics...")
    try:
        metrics = await get_query_metrics(limit=50, tenant_id=tenant_id)
        
        # 3. Verify Results
        found = False
        for m in metrics:
            # Check for our specific ingestion event
            # Note: query_id is constructed as f"ingest_{doc_id}"
            if m.operation == "ingestion" and m.query_id == f"ingest_{doc_id}":
                found = True
                print(f"Found Ingestion Metric: {m}")
                
                # Check Totals
                if m.tokens_used == 300:
                    print("✅ Total Tokens Correct (300)")
                else:
                    print(f"❌ Total Tokens Mismatch: {m.tokens_used} != 300")
                    
                # float comparison with small epsilon
                if abs(m.cost_estimate - 0.00006) < 0.000001:
                    print(f"✅ Total Cost Correct ({m.cost_estimate})")
                else:
                    print(f"❌ Total Cost Mismatch: {m.cost_estimate} != 0.00006")
                    
                if m.conversation_id == doc_id:
                     print(f"✅ Document ID Correct ({m.conversation_id})")
                else:
                     print(f"❌ Document ID Mismatch")
                break
        
        if not found:
            print("❌ Failed to find aggregated ingestion metric for document.")
            # Print all for debugging
            print("All returned metrics:")
            for m in metrics:
                print(f"- {m.operation}: {m.query_id}")

    except Exception as e:
        print(f"❌ Error calling get_query_metrics: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(verify_ingestion_aggregation())
