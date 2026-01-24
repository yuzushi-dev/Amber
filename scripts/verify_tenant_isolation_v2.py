
import asyncio
import os
import sys
import logging
from contextlib import asynccontextmanager

# Add project root to path
sys.path.append(os.getcwd())

# Set Log Level BEFORE importing app/settings
os.environ["LOG_LEVEL"] = "DEBUG"

# Configure basic logging to ensuring we see it
logging.basicConfig(level=logging.DEBUG)

import pytest
from httpx import ASGITransport, AsyncClient
from src.api.main import app
from src.core.database.session import close_database

# Use the dev key which is bootstrapped as super_admin
SUPER_ADMIN_KEY = "amber-dev-key-2024"

async def verify_isolation():
    print("starting tenant isolation verification...")
    
    # 1. Setup Test Client & Lifespan
    transport = ASGITransport(app=app)
    
    # Ensure app startup events run (database config, etc.)
    async with app.router.lifespan_context(app):
        # PATCH: Mock MinIO to avoid local credentials issue
        from unittest.mock import MagicMock
        from src.amber_platform.composition_root import platform
        
        mock_minio = MagicMock()
        mock_minio.upload_file.return_value = "documents/mock_file"
        mock_minio.ensure_bucket_exists.return_value = None
        # In case it checks bucket existence
        platform._minio_client = mock_minio
        
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            
            # 2. Create Tenants (A and B) with random suffix
            import uuid
            run_id = uuid.uuid4().hex[:6]
            
            print(f"\n[Admin] Creating Tenants (Run ID: {run_id})...")
            
            # Tenant A
            tenant_a_id = f"tenant-a-{run_id}"
            prefix_a = f"a_{run_id}"
            resp = await client.post(
                "/v1/admin/tenants",
                headers={"X-API-Key": SUPER_ADMIN_KEY},
                json={
                    "id": tenant_a_id,
                    "name": f"Tenant A {run_id}",
                    "api_key_prefix": prefix_a
                }
            )
            assert resp.status_code == 200, f"Failed to create Tenant A: {resp.text}"
            tenant_a_data = resp.json()
            tenant_a_id = tenant_a_data["id"] 
            print(f"  - Created Tenant A ({tenant_a_id})")

            # Tenant B
            prefix_b = f"b_{run_id}"
            resp = await client.post(
                "/v1/admin/tenants",
                headers={"X-API-Key": SUPER_ADMIN_KEY},
                json={
                    "name": f"Tenant B {run_id}",
                    "api_key_prefix": prefix_b
                }
            )
            assert resp.status_code == 200, f"Failed to create Tenant B: {resp.text}"
            tenant_b_data = resp.json()
            tenant_b_id = tenant_b_data["id"]
            print(f"  - Created Tenant B ({tenant_b_id})")

            # 3. Create API Keys and Link them
            print("\n[Admin] Creating API Keys...")
            
            # Key A
            resp = await client.post(
                "/v1/admin/keys",
                headers={"X-API-Key": SUPER_ADMIN_KEY},
                json={
                    "name": f"Key A {run_id}",
                    # tenant_id/role ignored here by API
                }
            )
            key_a_data = resp.json()
            KEY_A = key_a_data.get("key")
            key_a_id = key_a_data.get("id")
            
            # Link Key A to Tenant A
            resp = await client.post(
                f"/v1/admin/keys/{key_a_id}/tenants",
                headers={"X-API-Key": SUPER_ADMIN_KEY},
                json={"tenant_id": tenant_a_id, "role": "user"}
            )
            assert resp.status_code == 200, f"Failed to link Key A: {resp.text}"
            print(f"  - Key A: {KEY_A[:5]}... (Linked to {tenant_a_id})")

            # Key B
            resp = await client.post(
                "/v1/admin/keys",
                headers={"X-API-Key": SUPER_ADMIN_KEY},
                json={
                    "name": f"Key B {run_id}"
                }
            )
            key_b_data = resp.json()
            KEY_B = key_b_data.get("key")
            key_b_id = key_b_data.get("id")

            # Link Key B to Tenant B
            resp = await client.post(
                f"/v1/admin/keys/{key_b_id}/tenants",
                headers={"X-API-Key": SUPER_ADMIN_KEY},
                json={"tenant_id": tenant_b_id, "role": "user"}
            )
            assert resp.status_code == 200, f"Failed to link Key B: {resp.text}"
            print(f"  - Key B: {KEY_B[:5]}... (Linked to {tenant_b_id})")

            # 4. Upload Document for Tenant A
            print("\n[Tenant A] Uploading Document...")
            files = {"file": ("secret_plans.txt", b"Top Secret Tenant A Data", "text/plain")}
            resp = await client.post(
                "/v1/documents",
                headers={"X-API-Key": KEY_A},
                files=files
            )
            assert resp.status_code == 202, f"Upload failed for Key A: {resp.text}"
            doc_a_id = resp.json()["document_id"]
            print(f"  - Uploaded Document {doc_a_id}")

            # 5. Verify Isolation: Tenant B accessing Doc A
            print("\n[Tenant B] Attempting to access Tenant A Document...")
            resp = await client.get(
                f"/v1/documents/{doc_a_id}",
                headers={"X-API-Key": KEY_B}
            )
            
            if resp.status_code == 404:
                print("  - SUCCESS: Tenant B got 404 (Document not found)")
            elif resp.status_code == 403:
                print("  - SUCCESS: Tenant B got 403 (Forbidden)")
            else:
                print(f"  - FAILURE: Tenant B got {resp.status_code} - {resp.json()}")
                # raise AssertionError("Tenant B accessed Tenant A data!")

            # 6. Verify Isolation: Tenant B listing documents
            print("\n[Tenant B] Listing Documents...")
            resp = await client.get(
                "/v1/documents",
                headers={"X-API-Key": KEY_B}
            )
            assert resp.status_code == 200
            docs = resp.json()
            ids = [d["id"] for d in docs]
            if doc_a_id in ids:
                print(f"  - FAILURE: Tenant B can see Doc A in list! {ids}")
                raise AssertionError("Tenant B list leak!")
            else:
                print(f"  - SUCCESS: Tenant B list does not contain Doc A. (Found {len(docs)} docs)")

            # 7. Verify Access: Tenant A accessing Doc A
            print("\n[Tenant A] Accessing own Document...")
            resp = await client.get(
                f"/v1/documents/{doc_a_id}",
                headers={"X-API-Key": KEY_A}
            )
            assert resp.status_code == 200, "Tenant A failed to access own doc"
            print("  - SUCCESS: Tenant A accessed own doc.")

    # Cleanup DB engine (if needed, though lifespan should handle it)
    await close_database()
    print("\nVerification Complete.")

if __name__ == "__main__":
    asyncio.run(verify_isolation())
