"""
Global Rules Admin API
======================

CRUD endpoints for managing global rules that guide AI reasoning.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session as get_db, verify_tenant_admin, get_current_tenant_id
from src.api.schemas.base import ResponseSchema
from src.core.models.global_rule import GlobalRule

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
    tenant_id: str | None
    created_at: Any
    updated_at: Any

    class Config:
        from_attributes = True


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/", response_model=ResponseSchema[list[RuleResponse]])
async def list_rules(
    request: Request,
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    _admin: Any = Depends(verify_tenant_admin),
):
    """List rules (System Defaults + Tenant Specific)."""
    current_tenant = get_current_tenant_id(request)
    
    # Filter: Own tenant OR System default (system default is tenant_id IS NULL)
    query = select(GlobalRule).where(
        or_(
            GlobalRule.tenant_id == current_tenant,
            GlobalRule.tenant_id.is_(None)
        )
    ).order_by(GlobalRule.priority, GlobalRule.created_at)
    
    if not include_inactive:
        query = query.where(GlobalRule.is_active == True)
    
    result = await db.execute(query)
    rules = result.scalars().all()
    
    return ResponseSchema(
        data=[RuleResponse.model_validate(r) for r in rules],
        message=f"Found {len(rules)} rules"
    )


@router.post("/", response_model=ResponseSchema[RuleResponse], status_code=status.HTTP_201_CREATED)
async def create_rule(
    data: RuleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: Any = Depends(verify_tenant_admin),
):
    """Create a new rule for the current tenant."""
    current_tenant = get_current_tenant_id(request)
    is_super = getattr(request.state, "is_super_admin", False)
    
    # By default, create for current tenant.
    # If Super Admin wants to create GLOBAL rules, they might need a flag or specific API.
    # For now, we assume standard UI usage creates tenant rules.
    # (Optional: Add `is_global` to schema if needed for SA)
    target_tenant = current_tenant
    
    rule = GlobalRule(
        content=data.content,
        category=data.category,
        priority=data.priority,
        is_active=data.is_active,
        source="manual",
        tenant_id=target_tenant
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    
    # Invalidate cache
    from src.core.services.rules import RulesService
    RulesService.invalidate_cache()
    
    logger.info(f"Created rule {rule.id} for tenant {target_tenant}")
    return ResponseSchema(data=RuleResponse.model_validate(rule), message="Rule created")


@router.put("/{rule_id}", response_model=ResponseSchema[RuleResponse])
async def update_rule(
    rule_id: str,
    data: RuleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: Any = Depends(verify_tenant_admin),
):
    """Update a rule."""
    rule = await db.get(GlobalRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    # Permission Check
    current_tenant = get_current_tenant_id(request)
    is_super = getattr(request.state, "is_super_admin", False)
    
    if rule.tenant_id is None:
        # System Rule
        if not is_super:
            raise HTTPException(status_code=403, detail="Only Super Admin can edit System Rules")
    elif rule.tenant_id != current_tenant:
        # Other Tenant's Rule
        if not is_super:
             raise HTTPException(status_code=403, detail="Cannot access this rule")
    
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
    from src.core.services.rules import RulesService
    RulesService.invalidate_cache()
    
    logger.info(f"Updated rule: {rule.id}")
    return ResponseSchema(data=RuleResponse.model_validate(rule), message="Rule updated")


@router.delete("/{rule_id}", response_model=ResponseSchema[dict])
async def delete_rule(
    rule_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: Any = Depends(verify_tenant_admin),
):
    """Delete a rule."""
    rule = await db.get(GlobalRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    # Permission Check
    current_tenant = get_current_tenant_id(request)
    is_super = getattr(request.state, "is_super_admin", False)
    
    if rule.tenant_id is None:
        if not is_super:
            raise HTTPException(status_code=403, detail="Only Super Admin can delete System Rules")
    elif rule.tenant_id != current_tenant:
        if not is_super:
             raise HTTPException(status_code=403, detail="Cannot access this rule")
    
    await db.delete(rule)
    await db.commit()
    
    # Invalidate cache
    from src.core.services.rules import RulesService
    RulesService.invalidate_cache()
    
    logger.info(f"Deleted rule: {rule_id}")
    return ResponseSchema(data={"deleted": rule_id}, message="Rule deleted")


@router.post("/upload", response_model=ResponseSchema[dict])
async def upload_rules_file(
    request: Request,
    file: UploadFile = File(...),
    replace_existing: bool = False,
    db: AsyncSession = Depends(get_db),
    _admin: Any = Depends(verify_tenant_admin),
):
    """
    Upload a rules.txt file. Each non-empty line becomes a rule.
    
    Args:
        file: Text file with one rule per line
        replace_existing: If true, deletes all existing file-sourced rules first
    """
    if not file.filename.endswith('.txt'):
        raise HTTPException(status_code=400, detail="Only .txt files are supported")
    
    content = await file.read()
    lines = content.decode('utf-8').strip().split('\n')
    
    # Filter out empty lines and comments
    rules_text = [
        line.strip() for line in lines 
        if line.strip() and not line.strip().startswith('#')
    ]
    
    if not rules_text:
        raise HTTPException(status_code=400, detail="No valid rules found in file")
    
    # Optionally delete existing file-sourced rules
    if replace_existing:
        existing = await db.execute(
            select(GlobalRule).where(GlobalRule.source.like("file:%"))
        )
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
            is_active=True
        )
        db.add(rule)
        created_count += 1
    
    await db.commit()
    
    # Invalidate cache
    from src.core.services.rules import RulesService
    RulesService.invalidate_cache()
    
    logger.info(f"Uploaded {created_count} rules from {file.filename}")
    return ResponseSchema(
        data={"created": created_count, "source": source_name},
        message=f"Created {created_count} rules from file"
    )
