"""Tuning CLI: system prompts + retrieval parameters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from src.cli._session import run, session_scope

app = typer.Typer(no_args_is_help=True)
console = Console()


PROMPT_FIELDS = {
    "rag_system_prompt",
    "rag_user_prompt",
    "agent_system_prompt",
    "community_summary_prompt",
    "fact_extraction_prompt",
}


def _config_to_dict(tenant: Any) -> dict:
    raw = tenant.config or {}
    return dict(raw)


@app.command("show")
def show(
    tenant_id: str = typer.Option("default"),
    field: str | None = typer.Option(None, help="Show only this field"),
) -> None:
    """Print the current tuning configuration for a tenant."""
    from src.core.tenants.domain.tenant import Tenant

    async def _load() -> dict:
        async with session_scope() as session:
            res = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
            tenant = res.scalar_one_or_none()
            if not tenant:
                raise typer.BadParameter(f"Tenant {tenant_id} not found")
            return _config_to_dict(tenant)

    config = run(_load())

    if field:
        value = config.get(field)
        console.print_json(json.dumps({field: value}, default=str))
        return

    table = Table(title=f"Tuning — tenant {tenant_id}")
    table.add_column("Field", style="cyan")
    table.add_column("Value", overflow="fold")
    for key, value in sorted(config.items()):
        text = json.dumps(value, default=str) if not isinstance(value, str) else value
        if len(text) > 200:
            text = text[:200] + "…"
        table.add_row(key, text)
    console.print(table)


@app.command("set")
def set_field(
    field: str = typer.Argument(..., help="Config field name"),
    value: str = typer.Argument(..., help="JSON-encoded value, or literal string"),
    tenant_id: str = typer.Option("default"),
) -> None:
    """Set a single tuning field on the tenant config."""
    from src.core.tenants.domain.tenant import Tenant

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = value  # treat as bare string

    async def _save() -> None:
        async with session_scope() as session:
            res = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
            tenant = res.scalar_one_or_none()
            if not tenant:
                raise typer.BadParameter(f"Tenant {tenant_id} not found")
            config = _config_to_dict(tenant)
            config[field] = parsed
            tenant.config = config
            await session.commit()

    run(_save())
    console.print(f"[green]Updated[/green] {field} for tenant {tenant_id}")


@app.command("prompt-edit")
def prompt_edit(
    field: str = typer.Argument(..., help=f"One of {sorted(PROMPT_FIELDS)}"),
    file: Path = typer.Argument(..., exists=True, readable=True),
    tenant_id: str = typer.Option("default"),
) -> None:
    """Load a system prompt from a text file."""
    if field not in PROMPT_FIELDS:
        raise typer.BadParameter(f"Unknown prompt field: {field}")
    text = file.read_text(encoding="utf-8")
    set_field(field=field, value=json.dumps(text), tenant_id=tenant_id)


@app.command("reset")
def reset(
    field: str = typer.Argument(..., help="Field to remove (revert to default)"),
    tenant_id: str = typer.Option("default"),
) -> None:
    """Drop a per-tenant override so the global default applies again."""
    from src.core.tenants.domain.tenant import Tenant

    async def _save() -> None:
        async with session_scope() as session:
            res = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
            tenant = res.scalar_one_or_none()
            if not tenant:
                raise typer.BadParameter(f"Tenant {tenant_id} not found")
            config = _config_to_dict(tenant)
            if field in config:
                config.pop(field)
                tenant.config = config
                await session.commit()

    run(_save())
    console.print(f"[yellow]Cleared override[/yellow] {field} for tenant {tenant_id}")
