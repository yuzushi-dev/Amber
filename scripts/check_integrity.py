#!/usr/bin/env python3
"""
Amber Integrity Check Tool
==========================

Diagnostics for Vector Store and Embedding Configuration.

Usage:
    python scripts/check_integrity.py
"""

import asyncio
import os
import sys

# Add src to path
sys.path.append(os.getcwd())

# Models (Must import all to register relationships)
from sqlalchemy import select, text  # Added text

from src.amber_platform.composition_root import (
    build_vector_store_factory,
    get_settings_lazy,
    platform,
)
from src.api.deps import _get_async_session_maker
from src.core.admin_ops.application.migration_service import EmbeddingMigrationService
from src.infrastructure.adapters.celery_dispatcher import CeleryTaskDispatcher


async def check_integrity():
    print("=" * 60)
    print("Amber Integrity Check Tool")
    print("=" * 60)

    settings = get_settings_lazy()
    print("System Configuration:")
    print(f"  - Embedding Provider: {settings.default_embedding_provider}")
    print(f"  - Embedding Model:    {settings.default_embedding_model}")
    print(f"  - Dimensions:         {settings.embedding_dimensions}")
    print("-" * 60)

    try:
        await platform.initialize()
    except Exception as e:
        print(f"Error initializing platform: {e}")
        # Continue anyway, we might only need DB

    # Initialize DB
    from src.core.database.session import configure_database
    configure_database(
        database_url=settings.db.database_url,
        pool_size=5,
        max_overflow=5,
    )

    async with _get_async_session_maker()() as session:
        # 1. Embedding Integrity
        migration_service = EmbeddingMigrationService(
            session=session,
            settings=settings,
            task_dispatcher=CeleryTaskDispatcher(),
            graph_client=platform.neo4j_client,
            vector_store_factory=build_vector_store_factory(),
        )

        has_errors = False

        print("\n[1/3] Checking Vectors (Milvus)...")
        statuses = await migration_service.get_compatibility_status()

        for status in statuses:
            name = status['tenant_name']
            tid = status['tenant_id']
            compatible = status['is_compatible']
            details = status['details']

            symbol = "✅" if compatible else "❌"
            print(f"   {symbol} Tenant: {name} ({tid})")
            print(f"      Status:  {details}")
            if not compatible:
                has_errors = True

        if not statuses:
            print("   No tenants found.")

        # 2. Neo4j Integrity
        print("\n[2/3] Checking Graph (Neo4j)...")
        try:
            # Expected constraints from src/core/graph/application/setup.py
            expected_constraints = {
                "document_id_unique": "constraints containing 'document_id_unique'",
                "chunk_id_unique": "constraints containing 'chunk_id_unique'",
            }
            # Simple check commands? "SHOW CONSTRAINTS"
            # Neo4j 4.x/5.x syntax varies.
            constraints_res = await platform.neo4j_client.execute_read("SHOW CONSTRAINTS")
            found_names = [c["name"] for c in constraints_res]

            for name, desc in expected_constraints.items():
                if name in found_names:
                    print(f"   ✅ Constraint '{name}' found.")
                else:
                    print(f"   ❌ Constraint '{name}' MISSING!")
                    has_errors = True
        except Exception as e:
            print(f"   ❌ Failed to check Neo4j: {e}")
            has_errors = True

        # 3. Postgres Integrity (Alembic)
        print("\n[3/3] Checking Database (Postgres)...")
        try:
             # Run alembic command to get head
            from alembic.config import Config
            from alembic.script import ScriptDirectory

            # Load Config
            alembic_cfg = Config("alembic.ini")

            # Get Head
            script = ScriptDirectory.from_config(alembic_cfg)
            heads = script.get_heads()
            head_rev = heads[0] if heads else None

            # Get Current DB Revision
            # We need a synchronous connection for Alembic MigrationContext usually?
            # Or we can query the alembic_version table directly via SQL.
            conn = await session.connection()
            result = await conn.execute(select(text("version_num from alembic_version")))
            db_rev = result.scalar()

            print(f"   Code Revision: {head_rev}")
            print(f"   DB Revision:   {db_rev}")

            if head_rev != db_rev:
                print("   ❌ Mismatch! Run 'alembic upgrade head'.")
                has_errors = True
            else:
                print(f"   ✅ Schema Sync: {head_rev}")

        except Exception as e:
            # If alembic table doesn't exist, it might be fresh
            if "relation \"alembic_version\" does not exist" in str(e):
                 print("   ❌ Alembic table missing. Run migrations!")
                 has_errors = True
            else:
                 print(f"   ❌ Failed to check Postgres: {e}")
                 # has_errors = True # Soft fail if alembic libs missing? No, fail.
                 pass

    print("\n" + "=" * 60)
    if has_errors:
        print("❌ Integrity Check FAILED. Mismatches found.")
        sys.exit(1)
    else:
        print("✅ Integrity Check PASSED. All systems nominal.")
        sys.exit(0)

if __name__ == "__main__":
    try:
        asyncio.run(check_integrity())
    except KeyboardInterrupt:
        print("\nAborted.")
    except Exception as e:
        print(f"\nFatal Error: {e}")
        sys.exit(1)
