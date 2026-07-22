"""Backup / restore CLI."""

from __future__ import annotations

from typing import cast
from uuid import uuid4

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import desc, select

from src.cli._session import run, session_scope

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command("create")
def create(
    scope: str = typer.Option("user_data", help="user_data | full_system"),
    tenant_id: str = typer.Option("default", help="Tenant to back up"),
) -> None:
    """Dispatch a new backup job through Celery."""

    from src.core.admin_ops.domain.backup_job import BackupJob, BackupScope, BackupStatus
    from src.workers.backup_tasks import create_backup as create_backup_task

    try:
        scope_enum = BackupScope(scope)
    except ValueError as exc:
        raise typer.BadParameter(f"Invalid scope: {scope}") from exc

    job_id = str(uuid4())

    async def _persist() -> None:
        async with session_scope() as session:
            session.add(
                BackupJob(
                    id=job_id,
                    tenant_id=tenant_id,
                    scope=scope_enum,
                    status=BackupStatus.PENDING,
                )
            )
            await session.commit()

    run(_persist())
    create_backup_task.delay(job_id, tenant_id, scope)
    console.print(f"[green]Queued backup job[/green] [cyan]{job_id}[/cyan] scope={scope}")


@app.command("list")
def list_backups(
    tenant_id: str = typer.Option("default"),
    limit: int = typer.Option(20),
    status: str | None = typer.Option(None, help="Filter by status (completed, failed, ...)"),
) -> None:
    """Show recent backup jobs for the tenant."""
    from src.core.admin_ops.domain.backup_job import BackupJob, BackupStatus

    async def _query() -> list[BackupJob]:
        async with session_scope() as session:
            stmt = select(BackupJob).where(BackupJob.tenant_id == tenant_id)
            if status:
                stmt = stmt.where(BackupJob.status == BackupStatus(status))
            stmt = stmt.order_by(desc(BackupJob.created_at)).limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    jobs = run(_query())

    table = Table(title=f"Backups — tenant {tenant_id}")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Scope")
    table.add_column("Status")
    table.add_column("Size")
    table.add_column("Created")
    table.add_column("Scheduled")

    for j in jobs:
        scope_v = j.scope.value if j.scope else "?"
        status_v = j.status.value if j.status else "?"
        size = f"{(j.file_size or 0) / 1024:.1f} KB" if j.file_size else "-"
        created = j.created_at.isoformat() if j.created_at else "-"
        table.add_row(j.id[:8], scope_v, status_v, size, created, "yes" if j.is_scheduled else "no")
    console.print(table)


@app.command("restore")
def restore(
    backup_id: str = typer.Argument(..., help="BackupJob.id to restore from"),
    tenant_id: str = typer.Option("default"),
    mode: str = typer.Option("merge", help="merge | replace"),
) -> None:
    """Dispatch a restore job against an existing completed backup."""
    from src.core.admin_ops.domain.backup_job import (
        BackupJob,
        BackupStatus,
        RestoreJob,
        RestoreMode,
    )
    from src.workers.backup_tasks import restore_backup as restore_backup_task

    try:
        mode_enum = RestoreMode(mode)
    except ValueError as exc:
        raise typer.BadParameter(f"Invalid mode: {mode}") from exc

    job_id = str(uuid4())

    async def _persist() -> str:
        async with session_scope() as session:
            result = await session.execute(
                select(BackupJob)
                .where(BackupJob.id == backup_id)
                .where(BackupJob.tenant_id == tenant_id)
            )
            backup = result.scalar_one_or_none()
            if not backup:
                raise typer.BadParameter(f"Backup {backup_id} not found")
            if backup.status != BackupStatus.COMPLETED:
                raise typer.BadParameter(f"Backup not completed (status={backup.status})")
            if not backup.result_path:
                raise typer.BadParameter("Backup file path missing")
            session.add(
                RestoreJob(
                    id=job_id,
                    tenant_id=tenant_id,
                    backup_job_id=backup_id,
                    mode=mode_enum,
                    status=BackupStatus.PENDING,
                )
            )
            await session.commit()
            return cast(str, backup.result_path)

    backup_path = run(_persist())
    restore_backup_task.delay(job_id, tenant_id, backup_path, mode)
    console.print(f"[green]Queued restore job[/green] [cyan]{job_id}[/cyan] mode={mode}")


@app.command("schedule")
def schedule(
    enabled: bool = typer.Option(True, "--enable/--disable"),
    frequency: str = typer.Option("daily", help="daily | weekly"),
    time_utc: str = typer.Option("02:00", help="HH:MM UTC"),
    day_of_week: int | None = typer.Option(None, help="0=Mon ... 6=Sun (weekly only)"),
    scope: str = typer.Option("user_data"),
    retention_count: int = typer.Option(7),
    tenant_id: str = typer.Option("default"),
) -> None:
    """Configure (upsert) the backup schedule for a tenant."""
    from src.core.admin_ops.domain.backup_job import BackupSchedule, BackupScope

    try:
        scope_enum = BackupScope(scope)
    except ValueError as exc:
        raise typer.BadParameter(f"Invalid scope: {scope}") from exc

    async def _upsert() -> None:
        async with session_scope() as session:
            result = await session.execute(
                select(BackupSchedule).where(BackupSchedule.tenant_id == tenant_id)
            )
            row = result.scalar_one_or_none()
            if row:
                row.enabled = enabled
                row.frequency = frequency
                row.time_utc = time_utc
                row.day_of_week = day_of_week
                row.scope = scope_enum
                row.retention_count = retention_count
            else:
                session.add(
                    BackupSchedule(
                        id=str(uuid4()),
                        tenant_id=tenant_id,
                        enabled=enabled,
                        frequency=frequency,
                        time_utc=time_utc,
                        day_of_week=day_of_week,
                        scope=scope_enum,
                        retention_count=retention_count,
                    )
                )
            await session.commit()

    run(_upsert())
    console.print(
        f"[green]Schedule saved[/green] enabled={enabled} {frequency} {time_utc} UTC scope={scope}"
    )
