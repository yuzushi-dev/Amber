"""
Setup API
=========

Endpoints for managing optional feature installation and setup status.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.deps import verify_admin
from src.api.services.setup_service import get_setup_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/setup", tags=["admin-setup"], dependencies=[Depends(verify_admin)])


class SetupStatusResponse(BaseModel):
    """Setup status response."""

    initialized: bool
    setup_complete: bool
    db_migration_needed: bool = False
    features: list[dict[str, Any]]
    summary: dict[str, int]


class BatchInstallRequest(BaseModel):
    """Request to install multiple features."""

    feature_ids: list[str]


async def _check_db_migration_status() -> bool:
    """
    Check if database migration is needed.
    Returns True if migration is needed, False otherwise.
    """
    import asyncio

    from alembic.runtime import migration
    from sqlalchemy import create_engine

    from alembic import config, script
    from api.config import settings

    try:

        def _check_sync():
            alembic_cfg = config.Config("alembic.ini")
            script_dir = script.ScriptDirectory.from_config(alembic_cfg)
            head_rev = script_dir.get_current_head()

            sync_url = settings.db.database_url.replace("postgresql+asyncpg", "postgresql")
            temp_engine = create_engine(sync_url)

            with temp_engine.connect() as conn:
                context = migration.MigrationContext.configure(conn)
                current_rev = context.get_current_revision()

            return current_rev != head_rev

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _check_sync)

    except Exception as e:
        logger.error(f"Failed to check DB status: {e}")
        return True


@router.get("/status", response_model=SetupStatusResponse)
async def get_setup_status():
    """Get current setup status and installed features."""
    try:
        service = get_setup_service()
        status = service.get_setup_status()

        # Add DB status check
        migration_needed = await _check_db_migration_status()
        status["db_migration_needed"] = migration_needed

        return status
    except Exception as e:
        logger.error(f"Failed to get setup status: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/install", response_model=dict[str, Any])
async def install_features(request: BatchInstallRequest):
    """Install optional features."""
    try:
        service = get_setup_service()
        # Returns dict of results per feature
        return await service.install_features_batch(request.feature_ids)
    except Exception as e:
        logger.error(f"Failed to install features: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/skip")
async def skip_setup():
    """Mark the setup wizard as complete."""
    try:
        service = get_setup_service()
        service.mark_setup_complete()
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Failed to mark setup complete: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/install/events")
async def install_events_stream(feature_ids: str):
    """
    SSE endpoint for streaming installation progress.

    Args:
        feature_ids: Comma-separated list of feature IDs to install.

    Returns:
        EventSourceResponse streaming progress events.
    """
    import json

    from sse_starlette.sse import EventSourceResponse

    # Parse feature IDs
    ids = [fid.strip() for fid in feature_ids.split(",") if fid.strip()]

    if not ids:
        raise HTTPException(status_code=400, detail="No feature IDs provided")

    async def event_generator():
        """Generate SSE events from installation progress."""
        service = get_setup_service()

        try:
            async for progress in service.install_features_stream(ids):
                yield {"event": "progress", "data": json.dumps(progress)}

            # Send completion event
            yield {"event": "complete", "data": json.dumps({"status": "finished"})}
        except Exception as e:
            logger.error(f"Installation stream error: {e}")
            yield {"event": "error", "data": json.dumps({"error": str(e)})}

    return EventSourceResponse(event_generator())


# =============================================================================
# Database Setup Endpoints
# =============================================================================


@router.get("/db/status")
async def get_db_status():
    """
    Check if the database is up to date with migrations.
    """
    # Use sync engine directly created here or retrieved properly
    # To be safe, we create a temporary sync engine or use the main one properly
    # But Alembic is purely sync. We should run the whole block in a thread.
    import asyncio

    from alembic.runtime import migration
    from sqlalchemy import create_engine

    from alembic import config, script
    from src.api.config import settings

    try:

        def _check_status_sync():
            # Create a dedicated sync engine for Alembic operations to avoid AsyncEngine mixups
            # Alembic config usually reads alembic.ini, but we need to ensure it uses the same DB
            # OR better: let alembic use its own env.py logic which loads config

            # Implementation 2: Use Alembic's native config loading which handles DB connection
            alembic_cfg = config.Config("alembic.ini")

            # Overwrite sqlalchemy.url in config if needed (to ensure we check the right DB)
            # alembic_cfg.set_main_option("sqlalchemy.url", db_url)

            script_dir = script.ScriptDirectory.from_config(alembic_cfg)
            head_rev = script_dir.get_current_head()

            # To get current revision, we need to connect
            # We use the connection from the config's engine logic or create one
            # Ideally we let MigrationContext inspect the DB

            # Create a throwaway sync engine just for this check
            # This is safer than trying to bridge the async engine
            sync_url = settings.db.database_url.replace("postgresql+asyncpg", "postgresql")
            temp_engine = create_engine(sync_url)

            with temp_engine.connect() as conn:
                context = migration.MigrationContext.configure(conn)
                current_rev = context.get_current_revision()

            return {
                "status": "healthy" if current_rev == head_rev else "needs_migration",
                "current_revision": current_rev,
                "head_revision": head_rev,
                "up_to_date": current_rev == head_rev,
            }

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _check_status_sync)
        return result

    except Exception as e:
        logger.error(f"Failed to check DB status: {e}")
        return {"status": "error", "error": str(e), "up_to_date": False}


@router.post("/db/migrate")
async def run_db_migration():
    """
    Run database migrations (alembic upgrade head).
    """
    import asyncio

    from alembic import command, config
    from src.api.config import settings

    try:

        def _run_upgrade_sync():
            alembic_cfg = config.Config("alembic.ini")
            # Ensure we target the right DB
            sync_url = settings.db.database_url.replace("postgresql+asyncpg", "postgresql")
            alembic_cfg.set_main_option("sqlalchemy.url", sync_url)

            command.upgrade(alembic_cfg, "head")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _run_upgrade_sync)

        return {"status": "success", "message": "Database migrated successfully"}

    except Exception as e:
        logger.error(f"Failed to run migration: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
