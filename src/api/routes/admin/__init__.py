"""
Admin Routes Module
====================

Administrative API endpoints for system management, monitoring, and tuning.

Phase 10 - Admin/Engineer UI Backend
"""

from fastapi import APIRouter

# Create main admin router
router = APIRouter(prefix="/admin", tags=["admin"])

# Import and include sub-routers
from src.api.routes.admin import chat_history, config, curation, jobs, keys, maintenance, ragas, tenants, feedback

router.include_router(jobs.router)
router.include_router(config.router)
router.include_router(curation.router)
router.include_router(maintenance.router)
router.include_router(chat_history.router)
router.include_router(ragas.router)
router.include_router(keys.router)
router.include_router(tenants.router)
router.include_router(feedback.router)

