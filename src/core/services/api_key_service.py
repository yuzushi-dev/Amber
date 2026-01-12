"""
ApiKey Service
==============

Service for managing API keys with database persistence.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models.api_key import ApiKey
from src.shared.security import generate_api_key, hash_api_key, mask_api_key


class ApiKeyService:
    """
    Service for managing API access keys.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_key(
        self,
        name: str,
        prefix: str = "amber",
        scopes: List[str] = None
    ) -> Dict[str, Any]:
        """
        Generate and persist a new API key.
        Returns the raw key (only once).
        """
        raw_key = generate_api_key(prefix)
        hashed = hash_api_key(raw_key)
        masked = mask_api_key(raw_key)
        last_chars = raw_key[-4:]
        
        normalized_prefix = prefix  # generate_api_key handles prefix format
        
        key_record = ApiKey(
            name=name,
            prefix=normalized_prefix,
            hashed_key=hashed,
            last_chars=last_chars,
            is_active=True,
            scopes=scopes or ["active_user"],
            last_used_at=None
        )
        
        self.session.add(key_record)
        await self.session.commit()
        await self.session.refresh(key_record)
        
        return {
            "id": key_record.id,
            "key": raw_key,             # THIS IS THE ONLY TIME RAW KEY IS SHOWN
            "name": key_record.name,
            "prefix": key_record.prefix,
            "scopes": key_record.scopes,
            "created_at": key_record.created_at
        }

    async def validate_key(self, key: str) -> Optional[ApiKey]:
        """
        Validate a raw API key against the database.
        Returns the ApiKey record if valid and active, else None.
        Updates last_used_at timestamp.
        """
        if not key:
            return None
            
        hashed = hash_api_key(key)
        
        query = select(ApiKey).where(
            ApiKey.hashed_key == hashed,
            ApiKey.is_active == True # noqa
        )
        result = await self.session.execute(query)
        key_record = result.scalars().first()
        
        if key_record:
            # Update last used asynchronously?
            # For now, we update synchronously in the transaction
            key_record.last_used_at = datetime.now(timezone.utc)
            await self.session.commit()
            return key_record
            
        return None

    async def list_keys(self) -> List[ApiKey]:
        """
        List all active API keys.
        """
        query = select(ApiKey).where(ApiKey.is_active == True).order_by(ApiKey.created_at.desc()) # noqa
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def revoke_key(self, key_id: str) -> bool:
        """
        Revoke an API key by setting is_active to False.
        """
        query = (
            update(ApiKey)
            .where(ApiKey.id == key_id)
            .values(is_active=False)
        )
        result = await self.session.execute(query)
        await self.session.commit()
        return result.rowcount > 0

    async def update_key(
        self,
        key_id: str,
        name: Optional[str] = None,
        scopes: Optional[List[str]] = None
    ) -> Optional[ApiKey]:
        """
        Update an existing API key's name or scopes.
        """
        query = select(ApiKey).where(ApiKey.id == key_id)
        result = await self.session.execute(query)
        key_record = result.scalars().first()
        
        if not key_record:
            return None
            
        if name is not None:
            key_record.name = name
        if scopes is not None:
            key_record.scopes = scopes
            
        await self.session.commit()
        await self.session.refresh(key_record)
        return key_record

    async def ensure_bootstrap_key(self, raw_key: str, name: str = "Bootstrap Key"):
        """
        Ensure a specific key hash exists in the DB (for migrations/env vars).
        Does NOT return the key, just ensures the hash is there.
        """
        hashed = hash_api_key(raw_key)
        
        query = select(ApiKey).where(ApiKey.hashed_key == hashed)
        result = await self.session.execute(query)
        existing = result.scalars().first()
        
        if not existing:
            await self.create_key_from_raw(raw_key, name)
            
    async def create_key_from_raw(self, raw_key: str, name: str):
        """
        Manually insert a known key (e.g. from Env).
        """
        hashed = hash_api_key(raw_key)
        masked = mask_api_key(raw_key)
        
        key_record = ApiKey(
            name=name,
            prefix="env",
            hashed_key=hashed,
            last_chars=raw_key[-4:],
            is_active=True,
            scopes=["admin", "root"],
        )
        self.session.add(key_record)
        await self.session.commit()
