"""Async data helpers shared by TUI screens. Keep it boring — no business logic here."""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select

from src.cli._session import session_scope


async def list_backups(tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
    from src.core.admin_ops.domain.backup_job import BackupJob

    async with session_scope() as session:
        res = await session.execute(
            select(BackupJob)
            .where(BackupJob.tenant_id == tenant_id)
            .order_by(desc(BackupJob.created_at))
            .limit(limit)
        )
        rows = list(res.scalars().all())
        return [
            {
                "id": r.id,
                "scope": r.scope.value if r.scope else "?",
                "status": r.status.value if r.status else "?",
                "file_size": r.file_size or 0,
                "created_at": r.created_at.isoformat() if r.created_at else "-",
                "is_scheduled": bool(r.is_scheduled),
            }
            for r in rows
        ]


async def get_schedule(tenant_id: str) -> dict[str, Any] | None:
    from src.core.admin_ops.domain.backup_job import BackupSchedule

    async with session_scope() as session:
        res = await session.execute(
            select(BackupSchedule).where(BackupSchedule.tenant_id == tenant_id)
        )
        row = res.scalar_one_or_none()
        if not row:
            return None
        return {
            "enabled": bool(row.enabled),
            "frequency": row.frequency,
            "time_utc": row.time_utc,
            "day_of_week": row.day_of_week,
            "scope": row.scope.value if row.scope else "user_data",
            "retention_count": row.retention_count,
            "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
            "last_run_status": row.last_run_status,
        }


async def load_tenant_config(tenant_id: str) -> dict[str, Any]:
    from src.core.tenants.domain.tenant import Tenant

    async with session_scope() as session:
        res = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = res.scalar_one_or_none()
        if not tenant:
            return {}
        return dict(tenant.config or {})


async def save_tenant_field(tenant_id: str, field: str, value: Any) -> None:
    from src.core.tenants.domain.tenant import Tenant

    async with session_scope() as session:
        res = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = res.scalar_one_or_none()
        if not tenant:
            raise RuntimeError(f"Tenant {tenant_id} not found")
        config = dict(tenant.config or {})
        config[field] = value
        tenant.config = config
        await session.commit()


async def read_eval_state(run_id: str) -> dict[str, Any] | None:
    """Read the latest eval state cached by judge_eval on Redis. None if absent."""
    import json

    try:
        import redis  # type: ignore

        from src.api.config import settings
    except Exception:
        return None

    try:
        client = redis.Redis.from_url(settings.db.redis_url)
        try:
            raw = client.get(f"eval:state:{run_id}")
            if not raw:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            return json.loads(raw)
        finally:
            client.close()
    except Exception:
        return None


async def list_benchmark_runs(tenant_id: str, limit: int = 30) -> list[dict[str, Any]]:
    from src.core.admin_ops.domain.benchmark_run import BenchmarkRun

    async with session_scope() as session:
        res = await session.execute(
            select(BenchmarkRun)
            .where(BenchmarkRun.tenant_id == tenant_id)
            .order_by(desc(BenchmarkRun.created_at))
            .limit(limit)
        )
        rows = list(res.scalars().all())
        return [
            {
                "id": r.id,
                "framework": r.framework or "?",
                "dataset": r.dataset_name,
                "status": r.status.value if r.status else "?",
                "overall": (r.metrics or {}).get("overall"),
                "created_at": r.created_at.isoformat() if r.created_at else "-",
            }
            for r in rows
        ]
