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
from src.api.routes.admin import jobs
from src.api.routes.admin import config
from src.api.routes.admin import curation
from src.api.routes.admin import maintenance
from src.api.routes.admin import chat_history

router.include_router(jobs.router)
router.include_router(config.router)
router.include_router(curation.router)
router.include_router(maintenance.router)
router.include_router(chat_history.router)
