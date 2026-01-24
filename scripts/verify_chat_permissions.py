import asyncio
import os
import sys
import logging
import uuid
from httpx import ASGITransport, AsyncClient
from src.api.main import app

# Setup
os.environ["LOG_LEVEL"] = "INFO"
# Ensure we use test DB
os.environ["DATABASE_URL"] = "postgresql+asyncpg://graphrag:graphrag@localhost:5433/graphrag_test"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"

async def verify_chat_permissions():
    # Use lifespan to handle startup events (DB config, etc.)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            
            # 1. Setup Tenant & Super Admin
            run_id = uuid.uuid4().hex[:6]
            print(f"Running Chat Verification {run_id}...")
            
            # Bootstrap a known Super Admin Key
            from src.api.deps import _get_async_session_maker
            from src.core.admin_ops.application.api_key_service import ApiKeyService
            
            BOOTSTRAP_KEY = "amber-bootstrap-key-123"
            async with _get_async_session_maker()() as session:
                service = ApiKeyService(session)
                # Ensure the bootstrap key exists and has admin rights
                await service.ensure_bootstrap_key(raw_key=BOOTSTRAP_KEY, name="Verification Bootstrap")
                # Also ensure it has super_admin scope explicitly if ensure_bootstrap_key doesn't set it (it sets admin)
                # Checking ensure_bootstrap_key impl: it sets ['admin', 'root', 'super_admin'] in create_key_from_raw
                # but role='admin' in link.
                
            SUPER_ADMIN_KEY = BOOTSTRAP_KEY
            
            # Create Tenant
            resp = await client.post(
                "/v1/admin/tenants",
                headers={"X-API-Key": SUPER_ADMIN_KEY},
                json={"name": f"Chat Tenant {run_id}"}
            )
            if resp.status_code != 200:
                print("Failed to create tenant:", resp.text)
                return
            tenant_data = resp.json()
            tenant_id = tenant_data["id"] 
            
            # Create Regular User Key
            resp = await client.post(
                "/v1/admin/keys",
                headers={"X-API-Key": SUPER_ADMIN_KEY},
                json={"name": f"User Key {run_id}"}
            )
            user_key_data = resp.json()
            USER_KEY = user_key_data["key"]
            user_key_id = user_key_data["id"]
            
            # Link to Tenant as USER (Default Role)
            await client.post(
                f"/v1/admin/keys/{user_key_id}/tenants",
                headers={"X-API-Key": SUPER_ADMIN_KEY},
                json={"tenant_id": tenant_id, "role": "user"}
            )
            
            # 2. Regular User Creates a Chat via SQL Injection (Simulated)
            print("\n[User] Creating Chat...")
            
            from src.core.database.session import get_session_maker
            from src.core.generation.domain.memory_models import ConversationSummary
            
            session_maker = get_session_maker()
            user_id_val = f"user_{run_id}"
            conversation_id = str(uuid.uuid4())
            
            async with session_maker() as session:
                h = ConversationSummary(
                    id=conversation_id,
                    tenant_id=tenant_id,
                    user_id=user_id_val,
                    title="User's Secret Chat",
                    summary="Discussing private things."
                )
                session.add(h)
                await session.commit()
                print(f"  - Inserted Chat {conversation_id} for User {user_id_val}")
                
            # 3. User Verifies Visibility (Sidebar)
            print("\n[User] Checking Sidebar (/v1/chat/history)...")
            resp = await client.get(
                "/v1/chat/history",
                headers={
                    "X-API-Key": USER_KEY,
                    "X-Tenant-ID": tenant_id,
                    "X-User-ID": user_id_val 
                }
            )
            history = resp.json()
            found = any(c['request_id'] == conversation_id for c in history.get('conversations', []))
            if found:
                print("  - SUCCESS: User can see their own chat.")
            else:
                print("  - FAILURE: User cannot see their own chat!")
                print(history)
                
            # 4. Super Admin Verifies Visibility (User Endpoint - Sidebar Sim)
            print("\n[Super Admin] Checking Sidebar (/v1/chat/history)...")
            # Super Admin logging in WITHOUT X-User-ID (defaults to 'default_user')
            resp = await client.get(
                "/v1/chat/history",
                headers={
                    "X-API-Key": SUPER_ADMIN_KEY,
                    "X-Tenant-ID": tenant_id,
                    # No X-User-ID -> "default_user"
                }
            )
            history = resp.json()
            found = any(c['request_id'] == conversation_id for c in history.get('conversations', []))
            if found:
                print("  - UNEXPECTED: Super Admin SAW the user's chat in PERSONAL sidebar (User ID mismatch ignored?)")
            else:
                print("  - SUCCESS: Super Admin did NOT see user's chat in PERSONAL sidebar (Expected behavior).")
                
            # 5. Super Admin Verifies Visibility (Admin Dashboard Endpoint)
            print("\n[Super Admin] Checking Admin Dashboard (/v1/admin/chat/history)...")
            resp = await client.get(
                "/v1/admin/chat/history",
                params={"tenant_id": tenant_id},
                headers={
                    "X-API-Key": SUPER_ADMIN_KEY,
                    "X-Tenant-ID": tenant_id
                }
            )
            
            if resp.status_code == 200:
                history = resp.json()
                found = any(c['request_id'] == conversation_id for c in history.get('conversations', []))
                if found:
                    item = next(c for c in history['conversations'] if c['request_id'] == conversation_id)
                    print("  - SUCCESS: Super Admin SAW the chat in Admin Dashboard.")
                    print(f"  - Privacy Check: Query='{item.get('query_text')}'")
                else:
                    print("  - FAILURE: Super Admin could NOT see the chat in Admin Dashboard!")
            else:
                print(f"  - FAILURE: Admin Endpoint Error {resp.status_code} {resp.text}")

if __name__ == "__main__":
    asyncio.run(verify_chat_permissions())
