"""
Global Rules Admin API
======================

CRUD endpoints for managing global rules that guide AI reasoning.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session as get_db
from src.api.deps import verify_admin
from src.api.schemas.base import ResponseSchema
from src.core.admin_ops.domain.global_rule import GlobalRule

router = APIRouter(prefix="/rules", tags=["admin", "rules"])
logger = logging.getLogger(__name__)


# =============================================================================
# Schemas
# =============================================================================


class RuleCreate(BaseModel):
    content: str
    category: str | None = None
    priority: int = 100
    is_active: bool = True


class RuleUpdate(BaseModel):
    content: str | None = None
    category: str | None = None
    priority: int | None = None
    is_active: bool | None = None


class RuleResponse(BaseModel):
    id: str
    content: str
    category: str | None
    priority: int
    is_active: bool
    source: str
    created_at: Any
    updated_at: Any

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/", response_model=ResponseSchema[list[RuleResponse]])
async def list_rules(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    _admin: Any = Depends(verify_admin),
):
    """List all global rules."""
    query = select(GlobalRule).order_by(GlobalRule.priority, GlobalRule.created_at)

    if not include_inactive:
        query = query.where(GlobalRule.is_active.is_(True))

    result = await db.execute(query)
    rules = result.scalars().all()

    return ResponseSchema(
        data=[RuleResponse.model_validate(r) for r in rules], message=f"Found {len(rules)} rules"
    )


@router.post("/", response_model=ResponseSchema[RuleResponse], status_code=status.HTTP_201_CREATED)
async def create_rule(
    data: RuleCreate,
    db: AsyncSession = Depends(get_db),
    _admin: Any = Depends(verify_admin),
):
    """Create a new global rule."""
    rule = GlobalRule(
        content=data.content,
        category=data.category,
        priority=data.priority,
        is_active=data.is_active,
        source="manual",
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)

    # Invalidate cache
    from src.core.admin_ops.application.rules_service import RulesService

    RulesService.invalidate_cache()

    logger.info(f"Created global rule: {rule.id}")
    return ResponseSchema(data=RuleResponse.model_validate(rule), message="Rule created")


@router.put("/{rule_id}", response_model=ResponseSchema[RuleResponse])
async def update_rule(
    rule_id: str,
    data: RuleUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: Any = Depends(verify_admin),
):
    """Update a global rule."""
    rule = await db.get(GlobalRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    if data.content is not None:
        rule.content = data.content
    if data.category is not None:
        rule.category = data.category
    if data.priority is not None:
        rule.priority = data.priority
    if data.is_active is not None:
        rule.is_active = data.is_active

    await db.commit()
    await db.refresh(rule)

    # Invalidate cache
    from src.core.admin_ops.application.rules_service import RulesService

    RulesService.invalidate_cache()

    logger.info(f"Updated global rule: {rule.id}")
    return ResponseSchema(data=RuleResponse.model_validate(rule), message="Rule updated")


@router.delete("/{rule_id}", response_model=ResponseSchema[dict])
async def delete_rule(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: Any = Depends(verify_admin),
):
    """Delete a global rule."""
    rule = await db.get(GlobalRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    await db.delete(rule)
    await db.commit()

    # Invalidate cache
    from src.core.admin_ops.application.rules_service import RulesService

    RulesService.invalidate_cache()

    logger.info(f"Deleted global rule: {rule_id}")
    return ResponseSchema(data={"deleted": rule_id}, message="Rule deleted")


@router.post("/upload", response_model=ResponseSchema[dict])
async def upload_rules_file(
    file: UploadFile = File(...),
    replace_existing: bool = False,
    db: AsyncSession = Depends(get_db),
    _admin: Any = Depends(verify_admin),
):
    """
    Upload a rules.txt file. Each non-empty line becomes a rule.

    Args:
        file: Text file with one rule per line
        replace_existing: If true, deletes all existing file-sourced rules first
    """
    if not file.filename.endswith(".txt"):
        raise HTTPException(status_code=400, detail="Only .txt files are supported")

    content = await file.read()
    lines = content.decode("utf-8").strip().split("\n")

    # Filter out empty lines and comments
    rules_text = [
        line.strip() for line in lines if line.strip() and not line.strip().startswith("#")
    ]

    if not rules_text:
        raise HTTPException(status_code=400, detail="No valid rules found in file")

    # Optionally delete existing file-sourced rules
    if replace_existing:
        existing = await db.execute(select(GlobalRule).where(GlobalRule.source.like("file:%")))
        for rule in existing.scalars().all():
            await db.delete(rule)

    # Create new rules
    source_name = f"file:{file.filename}"
    created_count = 0

    for i, rule_text in enumerate(rules_text):
        rule = GlobalRule(
            content=rule_text,
            priority=i + 1,  # Order from file
            source=source_name,
            is_active=True,
        )
        db.add(rule)
        created_count += 1

    await db.commit()

    # Invalidate cache
    from src.core.admin_ops.application.rules_service import RulesService

    RulesService.invalidate_cache()

    logger.info(f"Uploaded {created_count} rules from {file.filename}")
    return ResponseSchema(
        data={"created": created_count, "source": source_name},
        message=f"Created {created_count} rules from file",
    )
