"""
Ragas Benchmark Admin Routes
=============================

API endpoints for managing Ragas benchmark runs and evaluation.
"""

import json
import logging
import os
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session, verify_admin
from src.core.models.benchmark_run import BenchmarkRun, BenchmarkStatus
from src.workers.tasks import run_ragas_benchmark

logger = logging.getLogger(__name__)

# Fix: Protect all ragas routes with admin check
router = APIRouter(
    prefix="/ragas",
    tags=["admin", "ragas"],
    dependencies=[Depends(verify_admin)]
)


# =============================================================================
# Schemas
# =============================================================================
# ... (Schemas unchanged) ...

# =============================================================================
# Helpers
# =============================================================================

def validate_safe_filename(filename: str) -> str:
    """Ensure filename is safe and has no path traversal components."""
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename: Path traversal characters detected"
        )
    return filename


# =============================================================================
# Endpoints
# =============================================================================




class BenchmarkRunSummary(BaseModel):
    """Summary of a benchmark run."""
    id: str
    tenant_id: str
    dataset_name: str
    status: str
    metrics: dict | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class BenchmarkRunDetail(BenchmarkRunSummary):
    """Detailed benchmark run with per-sample results."""
    details: list | None
    config: dict | None
    error_message: str | None


class BenchmarkStatsResponse(BaseModel):
    """Aggregate statistics for benchmarks."""
    total_runs: int
    completed_runs: int
    failed_runs: int
    avg_faithfulness: float | None
    avg_relevancy: float | None


class DatasetInfo(BaseModel):
    """Information about a golden dataset."""
    name: str
    sample_count: int
    path: str


class RunBenchmarkRequest(BaseModel):
    """Request to trigger a benchmark run."""
    dataset_name: str
    metrics: list[str] = ["faithfulness", "response_relevancy"]


class RunBenchmarkResponse(BaseModel):
    """Response after triggering a benchmark."""
    benchmark_run_id: str
    task_id: str
    status: str
    message: str


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/stats", response_model=BenchmarkStatsResponse)
async def get_ragas_stats(
    session: AsyncSession = Depends(get_db_session)
):
    """
    Get overall Ragas benchmark statistics.
    """
    try:
        # Total runs
        total_result = await session.execute(select(func.count(BenchmarkRun.id)))
        total_runs = total_result.scalar() or 0

        # Completed runs
        completed_result = await session.execute(
            select(func.count(BenchmarkRun.id)).where(
                BenchmarkRun.status == BenchmarkStatus.COMPLETED
            )
        )
        completed_runs = completed_result.scalar() or 0

        # Failed runs
        failed_result = await session.execute(
            select(func.count(BenchmarkRun.id)).where(
                BenchmarkRun.status == BenchmarkStatus.FAILED
            )
        )
        failed_runs = failed_result.scalar() or 0

        # Average metrics from completed runs
        completed_runs_result = await session.execute(
            select(BenchmarkRun).where(
                BenchmarkRun.status == BenchmarkStatus.COMPLETED
            )
        )
        completed_benchmarks = completed_runs_result.scalars().all()

        avg_faithfulness = None
        avg_relevancy = None

        if completed_benchmarks:
            # Safe access ensuring metrics is a dict
            faith_scores = [
                b.metrics.get("faithfulness", 0)
                for b in completed_benchmarks
                if b.metrics and isinstance(b.metrics, dict)
            ]
            rel_scores = [
                b.metrics.get("response_relevancy", 0)
                for b in completed_benchmarks
                if b.metrics and isinstance(b.metrics, dict)
            ]

            if faith_scores:
                avg_faithfulness = sum(faith_scores) / len(faith_scores)
            if rel_scores:
                avg_relevancy = sum(rel_scores) / len(rel_scores)

        return BenchmarkStatsResponse(
            total_runs=total_runs,
            completed_runs=completed_runs,
            failed_runs=failed_runs,
            avg_faithfulness=avg_faithfulness,
            avg_relevancy=avg_relevancy
        )

    except Exception as e:
        logger.error(f"Failed to get Ragas stats: {e}")
        # Return zero stats instead of 500
        return BenchmarkStatsResponse(
            total_runs=0,
            completed_runs=0,
            failed_runs=0,
            avg_faithfulness=0.0,
            avg_relevancy=0.0
        )


@router.get("/datasets", response_model=list[DatasetInfo])
async def list_datasets():
    """
    List available golden datasets.
    """
    datasets = []

    # Check known dataset locations
    paths_to_check = [
        "src/core/evaluation",
        "tests/data",
    ]

    for base_path in paths_to_check:
        if os.path.exists(base_path):
            for filename in os.listdir(base_path):
                if filename.endswith(".json") and ("golden" in filename.lower() or "dataset" in filename.lower()):
                    full_path = os.path.join(base_path, filename)
                    try:
                        with open(full_path) as f:
                            data = json.load(f)
                            sample_count = len(data) if isinstance(data, list) else 0
                    except Exception:
                        sample_count = 0

                    datasets.append(DatasetInfo(
                        name=filename,
                        sample_count=sample_count,
                        path=full_path
                    ))

    return datasets


@router.post("/datasets")
async def upload_dataset(
    file: UploadFile = File(...)
):
    """
    Upload a new golden dataset (JSON file).
    """
    # Fix: Validate filename to prevent path traversal
    if ".." in file.filename or "/" in file.filename or "\\" in file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename"
        )
    if not file.filename.endswith(".json"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dataset must be a JSON file"
        )

    # Read and validate content
    try:
        content = await file.read()
        data = json.loads(content)

        if not isinstance(data, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dataset must be a JSON array"
            )

        # Validate structure
        for i, sample in enumerate(data):
            if not isinstance(sample, dict):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Sample {i} must be an object"
                )
            if "query" not in sample and "question" not in sample:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Sample {i} must have 'query' or 'question' field"
                )
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON: {e}"
        ) from e

    # Save to evaluation directory
    save_path = f"src/core/evaluation/{file.filename}"
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    with open(save_path, "wb") as f:
        f.write(content)

    return {
        "filename": file.filename,
        "samples": len(data),
        "path": save_path,
        "message": "Dataset uploaded successfully"
    }


@router.post("/run-benchmark", response_model=RunBenchmarkResponse)
async def run_benchmark(
    request: RunBenchmarkRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Trigger a new Ragas benchmark run.
    """
    # Fix: Validate dataset_name to prevent path traversal
    if ".." in request.dataset_name or "/" in request.dataset_name or "\\" in request.dataset_name:
         raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid dataset name"
        )

    # Create benchmark run record
    benchmark_id = str(uuid4())

    benchmark = BenchmarkRun(
        id=benchmark_id,
        tenant_id="default",  # TODO: Get from auth context
        dataset_name=request.dataset_name,
        status=BenchmarkStatus.PENDING,
        config={"metrics": request.metrics}
    )

    session.add(benchmark)
    await session.commit()

    # Dispatch Celery task
    task = run_ragas_benchmark.delay(benchmark_id, "default")

    return RunBenchmarkResponse(
        benchmark_run_id=benchmark_id,
        task_id=task.id,
        status="pending",
        message=f"Benchmark run started for dataset '{request.dataset_name}'"
    )


@router.get("/job/{job_id}", response_model=BenchmarkRunDetail)
async def get_benchmark_job(
    job_id: str,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Get status and results of a benchmark run.
    """
    result = await session.execute(
        select(BenchmarkRun).where(BenchmarkRun.id == job_id)
    )
    benchmark = result.scalars().first()

    if not benchmark:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Benchmark run {job_id} not found"
        )

    return BenchmarkRunDetail(
        id=benchmark.id,
        tenant_id=benchmark.tenant_id,
        dataset_name=benchmark.dataset_name,
        status=benchmark.status.value,
        metrics=benchmark.metrics,
        details=benchmark.details,
        config=benchmark.config,
        error_message=benchmark.error_message,
        started_at=benchmark.started_at,
        completed_at=benchmark.completed_at,
        created_at=benchmark.created_at
    )


@router.get("/comparison")
async def compare_runs(
    run_ids: str,  # Comma-separated list of run IDs
    session: AsyncSession = Depends(get_db_session)
):
    """
    Compare results across multiple benchmark runs.
    """
    ids = [r.strip() for r in run_ids.split(",")]

    result = await session.execute(
        select(BenchmarkRun).where(BenchmarkRun.id.in_(ids))
    )
    benchmarks = result.scalars().all()

    if not benchmarks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No benchmark runs found"
        )

    comparison = []
    for benchmark in benchmarks:
        comparison.append({
            "id": benchmark.id,
            "dataset_name": benchmark.dataset_name,
            "status": benchmark.status.value,
            "metrics": benchmark.metrics,
            "completed_at": benchmark.completed_at.isoformat() if benchmark.completed_at else None
        })

    return {"runs": comparison, "count": len(comparison)}


@router.get("/runs", response_model=list[BenchmarkRunSummary])
async def list_benchmark_runs(
    limit: int = 20,
    offset: int = 0,
    status_filter: str | None = None,
    session: AsyncSession = Depends(get_db_session)
):
    """
    List benchmark runs with optional filtering.
    """
    query = select(BenchmarkRun).order_by(BenchmarkRun.created_at.desc())

    if status_filter:
        try:
            status_enum = BenchmarkStatus(status_filter)
            query = query.where(BenchmarkRun.status == status_enum)
        except ValueError:
            pass  # Invalid status, ignore filter

    query = query.offset(offset).limit(limit)
    result = await session.execute(query)
    benchmarks = result.scalars().all()

    return [
        BenchmarkRunSummary(
            id=b.id,
            tenant_id=b.tenant_id,
            dataset_name=b.dataset_name,
            status=b.status.value,
            metrics=b.metrics,
            started_at=b.started_at,
            completed_at=b.completed_at,
            created_at=b.created_at
        )
        for b in benchmarks
    ]
