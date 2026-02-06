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
from src.core.admin_ops.domain.benchmark_run import BenchmarkRun, BenchmarkStatus
from src.workers.tasks import run_ragas_benchmark

logger = logging.getLogger(__name__)

# Define writable path for uploads
DATASETS_UPLOAD_DIR = "/app/uploads/datasets"

# Fix: Protect all ragas routes with admin check
router = APIRouter(prefix="/ragas", tags=["admin", "ragas"], dependencies=[Depends(verify_admin)])


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
            detail="Invalid filename: Path traversal characters detected",
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
async def get_ragas_stats(session: AsyncSession = Depends(get_db_session)):
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
                BenchmarkRun.status == BenchmarkStatus.COMPLETED.value
            )
        )
        completed_runs = completed_result.scalar() or 0

        # Failed runs
        failed_result = await session.execute(
            select(func.count(BenchmarkRun.id)).where(
                BenchmarkRun.status == BenchmarkStatus.FAILED.value
            )
        )
        failed_runs = failed_result.scalar() or 0

        # Average metrics from completed runs
        completed_runs_result = await session.execute(
            select(BenchmarkRun).where(BenchmarkRun.status == BenchmarkStatus.COMPLETED.value)
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
            avg_relevancy=avg_relevancy,
        )

    except Exception as e:
        logger.error(f"Failed to get Ragas stats: {e}")
        # Return zero stats instead of 500
        return BenchmarkStatsResponse(
            total_runs=0, completed_runs=0, failed_runs=0, avg_faithfulness=0.0, avg_relevancy=0.0
        )


@router.get("/datasets", response_model=list[DatasetInfo])
async def list_datasets():
    """
    List available golden datasets.
    """
    datasets = []

    # Check known dataset locations
    paths_to_check = ["src/core/evaluation", "tests/data", DATASETS_UPLOAD_DIR]

    for base_path in paths_to_check:
        if os.path.exists(base_path):
            for filename in os.listdir(base_path):
                is_valid_ext = filename.endswith(".json") or filename.endswith(".csv")
                # For uploads, we don't enforce "golden" or "dataset" in name
                is_upload_dir = base_path == DATASETS_UPLOAD_DIR
                is_dataset = (
                    is_upload_dir or "golden" in filename.lower() or "dataset" in filename.lower()
                )

                if is_valid_ext and is_dataset:
                    full_path = os.path.join(base_path, filename)
                    try:
                        if filename.endswith(".json"):
                            with open(full_path) as f:
                                data = json.load(f)
                                sample_count = len(data) if isinstance(data, list) else 0
                        else:
                            # CSV: count lines minus header
                            with open(full_path) as f:
                                sample_count = sum(1 for _ in f) - 1
                    except Exception:
                        sample_count = 0

                    datasets.append(
                        DatasetInfo(name=filename, sample_count=sample_count, path=full_path)
                    )

    return datasets


@router.post("/datasets")
async def upload_dataset(file: UploadFile = File(...)):
    """
    Upload a new golden dataset (JSON or CSV file).

    Expected columns/fields:
    - query/question: The input question
    - ground_truth/ground_truths: Expected correct answer(s)
    - Optional: contexts (for pre-computed retrieval)
    """
    try:
        # Validate filename
        filename = file.filename or "dataset"
        lower_filename = filename.lower()
        if ".." in filename or "/" in filename or "\\" in filename:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename")

        is_json = lower_filename.endswith(".json")
        is_csv = lower_filename.endswith(".csv")

        if not is_json and not is_csv:
            logger.warning(f"Invalid dataset file extension: {filename}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Dataset must be a JSON or CSV file"
            )

        # Read file content
        content = await file.read()

        data = []
        if is_json:
            # Parse JSON
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid JSON: {str(e)}"
                ) from e

            if isinstance(parsed, list):
                data = parsed
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Dataset must be a JSON array"
                )
        else:
            # Parse CSV
            try:
                # Import here is fine, but cleaner at top. Moving imports to header via separate edit if needed,
                # but for minimal diff keeping them local or standard.
                # Actually, standard library imports are safe.
                import csv
                import io

                text_content = content.decode("utf-8")
                # Skip empty lines
                text_content = text_content.strip()

                reader = csv.DictReader(io.StringIO(text_content))

                logger.info(f"CSV Headers: {reader.fieldnames}")

                for row in reader:
                    sample = {}
                    # Map query
                    if row.get("query"):
                        sample["query"] = row["query"]
                    elif row.get("question"):
                        sample["query"] = row["question"]
                    elif row.get("user_input"):
                        sample["query"] = row["user_input"]

                    # Map ground truth
                    if row.get("ground_truth"):
                        sample["ground_truth"] = row["ground_truth"]
                    elif row.get("ground_truths"):
                        sample["ground_truth"] = row["ground_truths"]
                    elif row.get("expected_answer"):
                        sample["ground_truth"] = row["expected_answer"]
                    elif row.get("answer"):
                        sample["ground_truth"] = row["answer"]
                    elif row.get("reference"):
                        sample["ground_truth"] = row["reference"]

                    # Map contexts
                    ctx = None
                    if row.get("contexts"):
                        ctx = row["contexts"]
                    elif row.get("retrieved_contexts"):
                        ctx = row["retrieved_contexts"]

                    if ctx:
                        # Handle if it's a string representation of a list or typical separator
                        if ctx.startswith("[") and ctx.endswith("]"):
                            try:
                                sample["contexts"] = json.loads(ctx)
                            except Exception:
                                sample["contexts"] = [c.strip() for c in ctx.strip("[]").split(",")]
                        else:
                            sample["contexts"] = ctx.split(";") if ctx else []
                    else:
                        sample["contexts"] = []

                    data.append(sample)

            except UnicodeDecodeError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid CSV encoding. Please use UTF-8. Error: {str(e)}",
                ) from e
            except Exception as e:
                logger.error(f"CSV Parse Error: {e}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to parse CSV: {str(e)}"
                ) from e

        if not data:
            logger.warning("Dataset empty after parsing")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dataset is empty")

        # Validate structure
        for i, sample in enumerate(data):
            if not isinstance(sample, dict):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=f"Sample {i} must be an object"
                )
            if "query" not in sample and "question" not in sample:
                logger.warning(f"Sample {i} missing query. Found: {list(sample.keys())}")
                msg = f"Sample {i} must have 'query' or 'question' field"
                # Check for is_json variable availability or infer
                if filename.endswith(".csv"):
                    msg += ". Check CSV headers."
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

        # Save as JSON
        save_filename = filename if is_json else filename.replace(".csv", ".json")
        save_path = f"{DATASETS_UPLOAD_DIR}/{save_filename}"
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        with open(save_path, "w") as f:
            json.dump(data, f, indent=2)

        return {
            "filename": save_filename,
            "original_format": "json" if is_json else "csv",
            "samples": len(data),
            "path": save_path,
            "message": "Dataset uploaded successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error during dataset upload")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}",
        ) from e


@router.delete("/datasets/{filename}")
async def delete_dataset(filename: str):
    """
    Delete an uploaded dataset.
    """
    validate_safe_filename(filename)

    file_path = f"{DATASETS_UPLOAD_DIR}/{filename}"
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Dataset {filename} not found"
        )

    try:
        os.remove(file_path)
        return {"message": f"Dataset {filename} deleted"}
    except Exception as e:
        logger.error(f"Failed to delete dataset {filename}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete dataset: {str(e)}",
        ) from e


@router.post("/run-benchmark", response_model=RunBenchmarkResponse)
async def run_benchmark(
    request: RunBenchmarkRequest, session: AsyncSession = Depends(get_db_session)
):
    """
    Trigger a new Ragas benchmark run.
    """
    # Fix: Validate dataset_name to prevent path traversal
    if ".." in request.dataset_name or "/" in request.dataset_name or "\\" in request.dataset_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid dataset name")

    # Create benchmark run record
    benchmark_id = str(uuid4())

    benchmark = BenchmarkRun(
        id=benchmark_id,
        tenant_id="default",  # TODO: Get from auth context
        dataset_name=request.dataset_name,
        status=BenchmarkStatus.PENDING,
        config={"metrics": request.metrics},
    )

    session.add(benchmark)
    await session.commit()

    # Dispatch Celery task with delay to ensure DB commit visibility
    task = run_ragas_benchmark.apply_async(args=[benchmark_id, "default"], countdown=1)

    return RunBenchmarkResponse(
        benchmark_run_id=benchmark_id,
        task_id=task.id,
        status="pending",
        message=f"Benchmark run started for dataset '{request.dataset_name}'",
    )


@router.delete("/runs/{run_id}")
async def delete_benchmark_run(run_id: str, session: AsyncSession = Depends(get_db_session)):
    """
    Delete a benchmark run.
    """
    result = await session.execute(select(BenchmarkRun).where(BenchmarkRun.id == run_id))
    benchmark = result.scalars().first()

    if not benchmark:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Benchmark run {run_id} not found"
        )

    await session.delete(benchmark)
    await session.commit()

    return {"message": f"Benchmark run {run_id} deleted"}


@router.get("/job/{job_id}", response_model=BenchmarkRunDetail)
async def get_benchmark_job(job_id: str, session: AsyncSession = Depends(get_db_session)):
    """
    Get status and results of a benchmark run.
    """
    result = await session.execute(select(BenchmarkRun).where(BenchmarkRun.id == job_id))
    benchmark = result.scalars().first()

    if not benchmark:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Benchmark run {job_id} not found"
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
        created_at=benchmark.created_at,
    )


@router.get("/comparison")
async def compare_runs(
    run_ids: str,  # Comma-separated list of run IDs
    session: AsyncSession = Depends(get_db_session),
):
    """
    Compare results across multiple benchmark runs.
    """
    ids = [r.strip() for r in run_ids.split(",")]

    result = await session.execute(select(BenchmarkRun).where(BenchmarkRun.id.in_(ids)))
    benchmarks = result.scalars().all()

    if not benchmarks:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No benchmark runs found")

    comparison = []
    for benchmark in benchmarks:
        comparison.append(
            {
                "id": benchmark.id,
                "dataset_name": benchmark.dataset_name,
                "status": benchmark.status.value,
                "metrics": benchmark.metrics,
                "completed_at": benchmark.completed_at.isoformat()
                if benchmark.completed_at
                else None,
            }
        )

    return {"runs": comparison, "count": len(comparison)}


@router.get("/runs", response_model=list[BenchmarkRunSummary])
async def list_benchmark_runs(
    limit: int = 20,
    offset: int = 0,
    status_filter: str | None = None,
    session: AsyncSession = Depends(get_db_session),
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
            created_at=b.created_at,
        )
        for b in benchmarks
    ]
