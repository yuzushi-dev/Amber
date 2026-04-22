import asyncio
import os
import sys

import httpx

# Ensure we're in project root for imports if needed, though this test hits the API
sys.path.append(os.getcwd())

BASE_URL = "http://localhost:8000/v1"
# Assuming default dev key, adjust if you changed it in .env
DEV_KEY = os.getenv("DEV_API_KEY", "amber-dev-key-2024")

async def run():
    print("Testing multitenancy strictness...")

    # 1. Setup Admin Client
    admin_headers = {"X-API-Key": DEV_KEY}
    async with httpx.AsyncClient(headers=admin_headers, timeout=30) as client:
        try:
            # Create Tenants
            print("Creating Tenant A...")
            res = await client.post(f"{BASE_URL}/admin/tenants", json={"name": "Tenant A"})
            if res.status_code != 200:
                print(f"Failed to create tenant: {res.text}")
                return
            t1 = res.json()
            print(f"Created Tenant A: {t1['id']}")

            res = await client.post(f"{BASE_URL}/admin/tenants", json={"name": "Tenant B"})
            t2 = res.json()
            print(f"Created Tenant B: {t2['id']}")

            # Create Keys
            print("Creating Keys...")
            res = await client.post(f"{BASE_URL}/admin/keys", json={"name": "Key A", "scopes": ["user"]})
            k1 = res.json()
            print(f"Created Key A: {k1['key']}")

            res = await client.post(f"{BASE_URL}/admin/keys", json={"name": "Key B", "scopes": ["user"]})
            k2 = res.json()
            print(f"Created Key B: {k2['key']}")

            # Link Keys
            print("Linking Keys...")
            res = await client.post(f"{BASE_URL}/admin/keys/{k1['id']}/tenants", json={"tenant_id": t1['id']})
            assert res.status_code == 200, f"Link failed: {res.text}"
            res = await client.post(f"{BASE_URL}/admin/keys/{k2['id']}/tenants", json={"tenant_id": t2['id']})
            assert res.status_code == 200
            print("Linked keys to tenants.")

        except Exception as e:
            print(f"Setup failed: {e}")
            return

    # 2. Test Isolation
    try:
        # Key A Client
        async with httpx.AsyncClient(headers={"X-API-Key": k1['key']}, timeout=10) as clientA:
            # Create Folder
            print("Key A creating folder...")
            f1 = await clientA.post(f"{BASE_URL}/folders", json={"name": "SecretFolderA"})
            if f1.status_code != 201:
                 print(f"Key A failed to create folder: {f1.text}")
                 # Maybe 'user' scope isn't enough? Check AuthMiddleware permissions.
                 # Actually AuthMiddleware hardcodes permissions to [] unless provided.
                 # Key creation sets scopes.
                 pass # We assert below
            assert f1.status_code == 201, f"Failed A: {f1.text}"
            print("Key A created SecretFolderA")

            # List Folders
            res = await clientA.get(f"{BASE_URL}/folders")
            folders = res.json()
            print(f"Key A found folders: {[f['name'] for f in folders]}")
            assert len(folders) == 1
            assert folders[0]['name'] == "SecretFolderA"
            print("Key A sees only SecretFolderA")

        # Key B Client
        async with httpx.AsyncClient(headers={"X-API-Key": k2['key']}, timeout=10) as clientB:
            # List Folders - Should be empty!
            print("Key B listing folders...")
            res = await clientB.get(f"{BASE_URL}/folders")
            if res.status_code != 200:
                print(f"Key B list failed: {res.text}")

            folders = res.json()
            assert len(folders) == 0, f"Key B saw folders! {folders}"
            print("Key B sees 0 folders (Correct)")

            # Create Folder
            print("Key B creating folder...")
            f2 = await clientB.post(f"{BASE_URL}/folders", json={"name": "SecretFolderB"})
            assert f2.status_code == 201
            print("Key B created SecretFolderB")

        # Key A again - Should still see only 1
        async with httpx.AsyncClient(headers={"X-API-Key": k1['key']}, timeout=10) as clientA:
            print("Key A checking again...")
            res = await clientA.get(f"{BASE_URL}/folders")
            folders = res.json()
            assert len(folders) == 1
            assert folders[0]['name'] == "SecretFolderA"
            print("Key A still sees only SecretFolderA (Correct)")

        print("VERIFICATION PASSED!")

    except AssertionError as e:
        print(f"VERIFICATION FAILED: {e}")
    except Exception as e:
        print(f"Error during test: {e}")
    finally:
        # 3. Cleanup
        print("Cleaning up...")
        async with httpx.AsyncClient(headers=admin_headers, timeout=10) as client:
            # Delete tenants (RLS might block deletion if we don't have cascade delete? Admin bypass RLS?
            # Admin API uses same session. Admin user usually bypasses RLS if `bypassrls` role, but `graphrag` user might not strictly be superuser.
            # But `verify_admin` usually uses `default` tenant? Wait.
            # Admin routes `TenantService` bypasses RLS?
            # `TenantService` uses `Tenant` model which does NOT have RLS.
            # But Deleting tenant should delete folders. `Tenant` model probably doesn't have cascade relationship to `Folder` yet?
            # Folders don't have FK to Tenants table?
            # `Folder.tenant_id` is just a string column, not FK.
            # So deleting tenant won't delete folders automatically.
            # And `delete_tenant` in `TenantService` just deletes the tenant row.
            # So "SecretFolderA" will remain orphaned. That's fine for test cleanup, but in prod we might want cleanup.

            await client.delete(f"{BASE_URL}/admin/tenants/{t1['id']}")
            await client.delete(f"{BASE_URL}/admin/tenants/{t2['id']}")
            await client.delete(f"{BASE_URL}/admin/keys/{k1['id']}")
            await client.delete(f"{BASE_URL}/admin/keys/{k2['id']}")
            print("Cleanup done.")

if __name__ == "__main__":
    asyncio.run(run())
