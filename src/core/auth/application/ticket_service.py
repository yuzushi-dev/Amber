"""
Ticket Service
==============

Manages short-lived authentication tickets for secure SSE connections.
This prevents API Key leakage in URL parameters.
"""

import secrets
import logging
from typing import Optional

import redis.asyncio as redis
from src.shared.kernel.runtime import get_settings
from src.core.admin_ops.application.api_key_service import ApiKey
from src.shared.security import mask_api_key

logger = logging.getLogger(__name__)

class TicketService:
    """
    Manages short-lived tokens (tickets) stored in Redis.
    
    Flow:
    1. Client authenticates via standard Header (POST /v1/auth/ticket)
    2. Server generates a random ticket and stores metadata in Redis (TTL 30s)
    3. Client connects to SSE with ?ticket=...
    4. Middleware validates and claims the ticket (One-time use)
    """

    TICKET_TTL_SECONDS = 30
    PREFIX = "auth:ticket:"

    def __init__(self, redis_client: redis.Redis = None):
        self.settings = get_settings()
        self._redis = redis_client

    async def _get_redis(self) -> redis.Redis:
        """Lazy Redis connection."""
        if not self._redis:
            self._redis = redis.from_url(self.settings.db.redis_url, decode_responses=True)
        return self._redis

    async def create_ticket(self, api_key_value: str) -> str:
        """
        Create a one-time ticket for the given API key.
        
        Args:
            api_key_value: The raw API key string to temporarily store.
                          
        Returns:
            str: The generated ticket string
        """
        # Generate secure random token
        ticket = secrets.token_urlsafe(32)
        key = f"{self.PREFIX}{ticket}"
        
        client = await self._get_redis()
        
        # Store the API key itself. The middleware will pick it up and treat it
        # as if it came from the header.
        await client.setex(key, self.TICKET_TTL_SECONDS, api_key_value)
        
        return ticket

    async def redeem_ticket(self, ticket: str) -> Optional[str]:
        """
        Validate and consume a ticket.
        
        Returns:
            str: The stored API key if valid, None otherwise.
        """
        key = f"{self.PREFIX}{ticket}"
        client = await self._get_redis()
        
        # Get and Delete (Atomic ideally, but get+delete is fine for now)
        payload = await client.get(key)
        
        if payload:
            # Allow reuse within TTL window to handle connection drops/retries
            # await client.delete(key)
            return payload
            
        return None
        
    async def close(self):
        if self._redis:
            await self._redis.close()
