"""
Admin Routes Module
====================

Administrative API endpoints for system management, monitoring, and tuning.

Phase 10 - Admin/Engineer UI Backend
"""

from fastapi import APIRouter

from src.api.routes.admin import (
    backup,
    chat_history,
    config,
    context_graph,
    curation,
    embeddings,
    feedback,
    jobs,
    keys,
    maintenance,
    providers,
    ragas,
    retention,
    rules,
    tenants,
)

# Create main admin router
router = APIRouter(prefix="/admin", tags=["admin"])

router.include_router(jobs.router)
router.include_router(config.router)
router.include_router(curation.router)
router.include_router(maintenance.router)
router.include_router(chat_history.router)
router.include_router(ragas.router)
router.include_router(keys.router)
router.include_router(tenants.router)
router.include_router(feedback.router)
router.include_router(rules.router)
router.include_router(context_graph.router)
router.include_router(retention.router)
router.include_router(embeddings.router)
router.include_router(providers.router)
router.include_router(backup.router)
