"""LLM / embedding provider/model CLI."""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from src.cli._session import run, session_scope

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command("show")
def show(tenant_id: str = typer.Option("default")) -> None:
    """Show current LLM/embedding settings for a tenant."""
    from src.core.tenants.domain.tenant import Tenant

    async def _load() -> dict:
        async with session_scope() as session:
            res = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
            tenant = res.scalar_one_or_none()
            if not tenant:
                raise typer.BadParameter(f"Tenant {tenant_id} not found")
            return dict(tenant.config or {})

    config = run(_load())
    table = Table(title=f"LLM settings — tenant {tenant_id}")
    table.add_column("Field", style="cyan")
    table.add_column("Value", overflow="fold")
    keys = [
        "llm_provider",
        "llm_model",
        "temperature",
        "seed",
        "embedding_provider",
        "embedding_model",
        "ollama_base_url",
    ]
    for key in keys:
        table.add_row(key, str(config.get(key, "—")))

    steps = config.get("llm_steps") or {}
    table.add_row("llm_steps (overrides)", json.dumps(steps, indent=2) if steps else "—")
    console.print(table)


@app.command("set-default")
def set_default(
    provider: str = typer.Argument(...),
    model: str = typer.Argument(...),
    temperature: float | None = typer.Option(None),
    seed: int | None = typer.Option(None),
    tenant_id: str = typer.Option("default"),
) -> None:
    """Set the global default LLM provider+model (+ optional sampling)."""
    from src.core.tenants.domain.tenant import Tenant

    async def _save() -> None:
        async with session_scope() as session:
            res = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
            tenant = res.scalar_one_or_none()
            if not tenant:
                raise typer.BadParameter(f"Tenant {tenant_id} not found")
            config = dict(tenant.config or {})
            config["llm_provider"] = provider
            config["llm_model"] = model
            if temperature is not None:
                config["temperature"] = temperature
            if seed is not None:
                config["seed"] = seed
            tenant.config = config
            await session.commit()

    run(_save())
    console.print(f"[green]Default LLM set:[/green] {provider}/{model}")


@app.command("set-step")
def set_step(
    step_id: str = typer.Argument(..., help="LLM step id (see backend llm_steps registry)"),
    provider: str | None = typer.Option(None),
    model: str | None = typer.Option(None),
    temperature: float | None = typer.Option(None),
    seed: int | None = typer.Option(None),
    tenant_id: str = typer.Option("default"),
    force: bool = typer.Option(
        False, "--force", help="Save the override even if provider/model isn't in the model registry."
    ),
) -> None:
    """Override LLM settings for a specific pipeline step."""
    from src.core.generation.application.llm_steps import validate_llm_step_override
    from src.core.tenants.domain.tenant import Tenant

    override: dict[str, object] = {}
    if provider is not None:
        override["provider"] = provider
    if model is not None:
        override["model"] = model
    if temperature is not None:
        override["temperature"] = temperature
    if seed is not None:
        override["seed"] = seed

    if not override:
        raise typer.BadParameter("At least one of --provider/--model/--temperature/--seed required")

    async def _save() -> None:
        async with session_scope() as session:
            res = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
            tenant = res.scalar_one_or_none()
            if not tenant:
                raise typer.BadParameter(f"Tenant {tenant_id} not found")
            config = dict(tenant.config or {})
            steps = dict(config.get("llm_steps") or {})
            existing = dict(steps.get(step_id) or {})
            existing.update(override)

            # Validate the MERGED result that will actually be persisted --
            # not just this call's --provider/--model delta. A delta of
            # --model alone, merged onto an already-stored --provider, can
            # produce an invalid pair that neither value looks wrong in
            # isolation for (issue #98).
            registry_error = validate_llm_step_override(existing.get("provider"), existing.get("model"))
            if registry_error:
                if not force:
                    raise typer.BadParameter(
                        f"{registry_error} Pass --force to save this override anyway."
                    )
                console.print(
                    f"[yellow]Warning:[/yellow] {registry_error} Saving anyway because --force was passed."
                )

            steps[step_id] = existing
            config["llm_steps"] = steps
            tenant.config = config
            await session.commit()

    run(_save())
    console.print(f"[green]Step override saved:[/green] {step_id} → {override}")


@app.command("clear-step")
def clear_step(
    step_id: str = typer.Argument(...),
    tenant_id: str = typer.Option("default"),
) -> None:
    """Drop a per-step override so the global default applies again."""
    from src.core.tenants.domain.tenant import Tenant

    async def _save() -> None:
        async with session_scope() as session:
            res = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
            tenant = res.scalar_one_or_none()
            if not tenant:
                raise typer.BadParameter(f"Tenant {tenant_id} not found")
            config = dict(tenant.config or {})
            steps = dict(config.get("llm_steps") or {})
            steps.pop(step_id, None)
            config["llm_steps"] = steps
            tenant.config = config
            await session.commit()

    run(_save())
    console.print(f"[yellow]Cleared step override:[/yellow] {step_id}")


@app.command("set-embedding")
def set_embedding(
    provider: str = typer.Argument(...),
    model: str = typer.Argument(...),
    tenant_id: str = typer.Option("default"),
) -> None:
    """Set embedding provider+model. NOTE: changing this requires a vector re-index."""
    from src.core.tenants.domain.tenant import Tenant

    async def _save() -> None:
        async with session_scope() as session:
            res = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
            tenant = res.scalar_one_or_none()
            if not tenant:
                raise typer.BadParameter(f"Tenant {tenant_id} not found")
            config = dict(tenant.config or {})
            config["embedding_provider"] = provider
            config["embedding_model"] = model
            tenant.config = config
            await session.commit()

    run(_save())
    console.print(
        f"[green]Embedding set:[/green] {provider}/{model} "
        "[yellow]— run the vector re-index to apply.[/yellow]"
    )
