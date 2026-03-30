
import asyncio
import uuid

import httpx


async def test_delete_tenant():
    headers = {"X-API-Key": "amber-dev-key-2024"}
    base_url = "http://localhost:8000/v1/admin/tenants"

    tenant_name = f"Test Delete {uuid.uuid4().hex[:8]}"

    async with httpx.AsyncClient() as client:
        # 1. Create Tenant
        print(f"Creating tenant: {tenant_name}")
        resp = await client.post(base_url, headers=headers, json={"name": tenant_name})
        if resp.status_code != 200:
            print(f"Failed to create tenant: {resp.text}")
            return

        tenant = resp.json()
        tenant_id = tenant["id"]
        print(f"Created tenant ID: {tenant_id}")

        # 2. Check it exists
        resp = await client.get(f"{base_url}/{tenant_id}", headers=headers)
        if resp.status_code != 200:
            print(f"Failed to get tenant: {resp.text}")
            return
        print("Tenant exists.")

        # 3. Delete Tenant
        print(f"Deleting tenant: {tenant_id}")
        resp = await client.delete(f"{base_url}/{tenant_id}", headers=headers)
        print(f"Delete status: {resp.status_code}")

        if resp.status_code == 204:
            print("Delete successful.")
        else:
            print(f"Delete failed: {resp.text}")

        # 4. Verify it's gone
        resp = await client.get(f"{base_url}/{tenant_id}", headers=headers)
        if resp.status_code == 404:
            print("Verified: Tenant not found.")
        else:
            print(f"Tenant still exists or error: {resp.status_code}")

if __name__ == "__main__":
    asyncio.run(test_delete_tenant())
