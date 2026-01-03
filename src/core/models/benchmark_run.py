"""
Benchmark Run Model
===================

Stores Ragas benchmark run metadata and results.
"""

from typing import Optional
from uuid import uuid4
from datetime import datetime

from sqlalchemy import Column, String, JSON, DateTime, Enum
from sqlalchemy.sql import func
from src.core.models.base import Base, TimestampMixin
import enum


class BenchmarkStatus(str, enum.Enum):
    """Status of a benchmark run."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class BenchmarkRun(Base, TimestampMixin):
    """
    Tracks Ragas benchmark runs for evaluation.
    """
    __tablename__ = "benchmark_runs"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    tenant_id = Column(String, index=True, nullable=False)
    dataset_name = Column(String, nullable=False)  # e.g., "golden_dataset.json"
    status = Column(
        Enum(BenchmarkStatus),
        default=BenchmarkStatus.PENDING,
        nullable=False
    )
    
    # Aggregated metrics (stored after completion)
    metrics = Column(JSON, default=dict)  # {"faithfulness": 0.85, "relevancy": 0.92, ...}
    
    # Per-sample detailed results
    details = Column(JSON, default=list)  # [{"query": "...", "scores": {...}}, ...]
    
    # Timing
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Audit
    created_by = Column(String, nullable=True)  # API key or user ID
    
    # Configuration used for this run
    config = Column(JSON, default=dict)  # {"metrics": ["faithfulness", "relevancy"], ...}
    
    # Error message if failed
    error_message = Column(String, nullable=True)
    
    def __repr__(self) -> str:
        return f"<BenchmarkRun(id={self.id}, dataset={self.dataset_name}, status={self.status})>"
