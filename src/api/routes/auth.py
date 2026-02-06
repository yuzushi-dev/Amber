"""
Auth Routes
===========

Endpoints for authentication-related operations.
"""

import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from src.core.auth.application.ticket_service import TicketService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class TicketResponse(BaseModel):
    ticket: str
    expires_in_seconds: int


@router.post(
    "/ticket",
    response_model=TicketResponse,
    summary="Generate Auth Ticket",
    description="""
    Generate a short-lived, one-time use ticket for authenticating SSE connections.

    The ticket effectively represents the valid API Key for 30 seconds.
    Use this ticket in the URL parameter `?ticket=...` for EventSource connections.
    """,
)
async def create_auth_ticket(
    request: Request,
):
    """
    Create a short-lived authentication ticket.
    Requires successful authentication headers (processed by middleware).
    """
    # Middleware has already validated the key and set request.state.api_key_name
    # But we need the actual key to store it for the ticket.
    # The middleware blindly strips encryption? No, middleware validates it.
    # We need access to the key string to forward it.

    # PROBLEM: The middleware consumes the key but doesn't store the raw key in state (security best practice).
    # We need the key to store in the ticket so the SSE request can "replay" it.

    # Solution: We can extract it from the header again here.
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key header required to generate ticket",
        )

    service = TicketService()
    try:
        ticket = await service.create_ticket(api_key)
        return TicketResponse(ticket=ticket, expires_in_seconds=TicketService.TICKET_TTL_SECONDS)
    finally:
        await service.close()
