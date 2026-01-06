"""
Health Check Logic
==================

Implements health checking for all system dependencies.
"""

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx
from redis.asyncio import Redis

from src.api.config import settings


class HealthStatus(str, Enum):
    """Health check status values."""

    UP = "up"
    DOWN = "down"
    DEGRADED = "degraded"


@dataclass
class DependencyHealth:
    """Health status for a single dependency."""

    name: str
    status: HealthStatus
    latency_ms: float | None = None
    error: str | None = None
    details: dict[str, Any] | None = None


@dataclass
class SystemHealth:
    """Overall system health status."""

    status: HealthStatus
    dependencies: dict[str, DependencyHealth]

    @property
    def is_healthy(self) -> bool:
        """Check if all dependencies are healthy."""
        return all(d.status == HealthStatus.UP for d in self.dependencies.values())


class HealthChecker:
    """
    Health checker for system dependencies.

    Checks:
    - PostgreSQL (via asyncpg)
    - Redis
    - Neo4j
    - Milvus
    """

    def __init__(self, timeout: float = 5.0):
        """
        Initialize health checker.

        Args:
            timeout: Timeout in seconds for each health check
        """
        self.timeout = timeout

    async def check_postgres(self) -> DependencyHealth:
        """Check PostgreSQL connection."""
        start = time.perf_counter()
        try:
            import asyncpg

            # Parse connection URL
            url = settings.db.database_url
            # Convert asyncpg URL format
            url = url.replace("postgresql+asyncpg://", "postgresql://")

            conn = await asyncio.wait_for(
                asyncpg.connect(url),
                timeout=self.timeout,
            )
            await conn.execute("SELECT 1")
            await conn.close()

            latency = (time.perf_counter() - start) * 1000
            return DependencyHealth(
                name="postgres",
                status=HealthStatus.UP,
                latency_ms=round(latency, 2),
            )
        except TimeoutError:
            return DependencyHealth(
                name="postgres",
                status=HealthStatus.DOWN,
                error="Connection timeout",
            )
        except Exception as e:
            return DependencyHealth(
                name="postgres",
                status=HealthStatus.DOWN,
                error=str(e),
            )

    async def check_redis(self) -> DependencyHealth:
        """Check Redis connection."""
        start = time.perf_counter()
        try:
            redis = Redis.from_url(
                settings.db.redis_url,
                socket_connect_timeout=self.timeout,
            )
            await asyncio.wait_for(redis.ping(), timeout=self.timeout)
            await redis.aclose()

            latency = (time.perf_counter() - start) * 1000
            return DependencyHealth(
                name="redis",
                status=HealthStatus.UP,
                latency_ms=round(latency, 2),
            )
        except TimeoutError:
            return DependencyHealth(
                name="redis",
                status=HealthStatus.DOWN,
                error="Connection timeout",
            )
        except Exception as e:
            return DependencyHealth(
                name="redis",
                status=HealthStatus.DOWN,
                error=str(e),
            )

    async def check_neo4j(self) -> DependencyHealth:
        """Check Neo4j connection."""
        start = time.perf_counter()
        try:
            from neo4j import AsyncGraphDatabase

            driver = AsyncGraphDatabase.driver(
                settings.db.neo4j_uri,
                auth=(settings.db.neo4j_user, settings.db.neo4j_password),
            )

            async with driver.session() as session:
                await asyncio.wait_for(
                    session.run("RETURN 1"),
                    timeout=self.timeout,
                )

            await driver.close()

            latency = (time.perf_counter() - start) * 1000
            return DependencyHealth(
                name="neo4j",
                status=HealthStatus.UP,
                latency_ms=round(latency, 2),
            )
        except TimeoutError:
            return DependencyHealth(
                name="neo4j",
                status=HealthStatus.DOWN,
                error="Connection timeout",
            )
        except Exception as e:
            return DependencyHealth(
                name="neo4j",
                status=HealthStatus.DOWN,
                error=str(e),
            )

    async def check_milvus(self) -> DependencyHealth:
        """Check Milvus connection via HTTP health endpoint."""
        start = time.perf_counter()
        try:
            # Milvus health endpoint
            url = f"http://{settings.db.milvus_host}:9091/healthz"

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)

            if response.status_code == 200:
                latency = (time.perf_counter() - start) * 1000
                return DependencyHealth(
                    name="milvus",
                    status=HealthStatus.UP,
                    latency_ms=round(latency, 2),
                )
            else:
                return DependencyHealth(
                    name="milvus",
                    status=HealthStatus.DOWN,
                    error=f"HTTP {response.status_code}",
                )
        except TimeoutError:
            return DependencyHealth(
                name="milvus",
                status=HealthStatus.DOWN,
                error="Connection timeout",
            )
        except Exception as e:
            return DependencyHealth(
                name="milvus",
                status=HealthStatus.DOWN,
                error=str(e),
            )

    async def check_all(self) -> SystemHealth:
        """
        Check all dependencies in parallel.

        Returns:
            SystemHealth: Overall system health status
        """
        # Run all checks concurrently
        results = await asyncio.gather(
            self.check_postgres(),
            self.check_redis(),
            self.check_neo4j(),
            self.check_milvus(),
            return_exceptions=True,
        )

        dependencies = {}
        for result in results:
            if isinstance(result, Exception):
                # Handle unexpected exceptions
                dependencies["unknown"] = DependencyHealth(
                    name="unknown",
                    status=HealthStatus.DOWN,
                    error=str(result),
                )
            else:
                dependencies[result.name] = result

        # Determine overall status
        all_up = all(d.status == HealthStatus.UP for d in dependencies.values())
        any_down = any(d.status == HealthStatus.DOWN for d in dependencies.values())

        if all_up:
            status = HealthStatus.UP
        elif any_down:
            status = HealthStatus.DOWN
        else:
            status = HealthStatus.DEGRADED

        return SystemHealth(status=status, dependencies=dependencies)


# Singleton instance
health_checker = HealthChecker()
