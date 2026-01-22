"""
API Dependencies
================

FastAPI dependency injection utilities.
"""

from collections.abc import AsyncGenerator

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.config import settings

# Create async engine
_engine = create_async_engine(
    settings.db.database_url,
    echo=False,
    pool_pre_ping=True,
)

# Session factory
_async_session_maker = async_sessionmaker(
    _engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that yields a database session.
    
    Injects the current tenant ID into the session for RLS.
    Sets app.is_super_admin if the user has the 'super_admin' scope.
    """
    async with _async_session_maker() as session:
        try:
            # Inject current tenant into session configuration
            from sqlalchemy import text
            from src.shared.context import get_current_tenant
            
            tenant_id = get_current_tenant()
            if tenant_id:
                await session.execute(
                    text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
                    {"tenant_id": str(tenant_id)}
                )
            
            # Check for super admin privilege from request state
            permissions = getattr(request.state, "permissions", [])
            if "super_admin" in permissions:
                 await session.execute(
                    text("SELECT set_config('app.is_super_admin', 'true', false)")
                )
            
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def verify_admin(request: Request):
    """
    Dependency to verify admin privileges.
    """
    # Check permissions from request state (set by AuthMiddleware)
    permissions = getattr(request.state, "permissions", [])

    if "admin" not in permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )


def get_current_tenant_id(request: Request) -> str:
    """
    Dependency to retrieve the current tenant ID.
    Derived from request state set by AuthenticationMiddleware.
    """
    return str(getattr(request.state, "tenant_id", "default"))
