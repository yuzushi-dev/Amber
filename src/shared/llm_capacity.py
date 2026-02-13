"""src.shared.llm_capacity

Redis-backed concurrency limiter for LLM/embedding calls.

Why this exists
- Some providers (e.g. Ollama Cloud) enforce a hard cap on *concurrent* requests.
- Amber runs multiple API workers + Celery workers, so naive per-process semaphores
  are insufficient.
- We also want priority: chat must stay responsive even when background jobs run.

Design
- Distributed leases stored in Redis sorted sets (one set per priority class).
- Each lease has an expiry timestamp (ms). Expired leases are cleaned up on acquire.
- Reservation rules:
  - Always keep `reserved_chat` slots available for chat.
  - Always keep `reserved_ingestion` slots available for ingestion (vs communities).
  - Communities can only use the remaining shared capacity.

This is *non-preemptive*: in-flight requests are never cancelled. Reservations
ensure higher classes can always acquire capacity without needing to preempt.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Literal


logger = logging.getLogger(__name__)

WorkClass = Literal["chat", "ingestion", "communities"]


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except Exception:
        logger.warning(f"Invalid int env var {name}={raw!r}; using default {default}")
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except Exception:
        logger.warning(f"Invalid float env var {name}={raw!r}; using default {default}")
        return default


@dataclass(frozen=True)
class LLMCapacitySettings:
    enabled: bool
    redis_url: str | None
    # Total allowed in-flight requests across the whole deployment.
    total: int
    # Reserved capacity. Lower classes cannot consume these slots.
    reserved_chat: int
    reserved_ingestion: int
    # Lease TTL (crash safety). Should be > worst-case request duration.
    lease_ttl_seconds: int
    # How long we wait for capacity before failing.
    chat_wait_timeout_seconds: float
    ingestion_wait_timeout_seconds: float
    communities_wait_timeout_seconds: float

    @staticmethod
    def from_env() -> "LLMCapacitySettings":
        enabled_raw = os.getenv("OLLAMA_CAPACITY_ENABLED", "true").lower()
        enabled = enabled_raw in ("1", "true", "yes", "y", "on")

        total = _env_int("OLLAMA_CAPACITY_TOTAL", 6)
        reserved_chat = _env_int("OLLAMA_CAPACITY_RESERVED_CHAT", 2)
        reserved_ingestion = _env_int("OLLAMA_CAPACITY_RESERVED_INGESTION", 2)

        # Guardrails: avoid negative shared capacity.
        if reserved_chat < 0:
            reserved_chat = 0
        if reserved_ingestion < 0:
            reserved_ingestion = 0
        if total < 1:
            total = 1
        if reserved_chat + reserved_ingestion >= total:
            # Keep at least 1 shared slot (or 0 if total==1).
            reserved_ingestion = max(0, total - reserved_chat - 1)

        return LLMCapacitySettings(
            enabled=enabled,
            redis_url=os.getenv("REDIS_URL"),
            total=total,
            reserved_chat=reserved_chat,
            reserved_ingestion=reserved_ingestion,
            lease_ttl_seconds=_env_int("OLLAMA_CAPACITY_LEASE_TTL_SECONDS", 600),
            chat_wait_timeout_seconds=_env_float("OLLAMA_CAPACITY_CHAT_WAIT_TIMEOUT_SECONDS", 15.0),
            ingestion_wait_timeout_seconds=_env_float(
                "OLLAMA_CAPACITY_INGESTION_WAIT_TIMEOUT_SECONDS", 120.0
            ),
            communities_wait_timeout_seconds=_env_float(
                "OLLAMA_CAPACITY_COMMUNITIES_WAIT_TIMEOUT_SECONDS", 600.0
            ),
        )


_ACQUIRE_LUA = r"""
-- KEYS:
-- 1 chat_zset
-- 2 ingestion_zset
-- 3 communities_zset
--
-- ARGV:
-- 1 now_ms
-- 2 ttl_ms
-- 3 work_class (chat|ingestion|communities)
-- 4 total
-- 5 reserved_chat
-- 6 reserved_ingestion
-- 7 lease_id

local chat_key = KEYS[1]
local ing_key = KEYS[2]
local com_key = KEYS[3]

local now_ms = tonumber(ARGV[1])
local ttl_ms = tonumber(ARGV[2])
local work_class = ARGV[3]
local total = tonumber(ARGV[4])
local reserved_chat = tonumber(ARGV[5])
local reserved_ingestion = tonumber(ARGV[6])
local lease_id = ARGV[7]

-- Cleanup expired leases first.
redis.call('ZREMRANGEBYSCORE', chat_key, 0, now_ms)
redis.call('ZREMRANGEBYSCORE', ing_key, 0, now_ms)
redis.call('ZREMRANGEBYSCORE', com_key, 0, now_ms)

local chat_n = redis.call('ZCARD', chat_key)
local ing_n = redis.call('ZCARD', ing_key)
local com_n = redis.call('ZCARD', com_key)

local total_n = chat_n + ing_n + com_n
local non_chat_n = ing_n + com_n

-- Always keep reserved chat slots available.
local non_chat_max = total - reserved_chat
if non_chat_max < 0 then non_chat_max = 0 end

-- Always keep reserved ingestion slots available (vs communities).
local communities_max = total - reserved_chat - reserved_ingestion
if communities_max < 0 then communities_max = 0 end

local allowed = 0

if work_class == 'chat' then
  if total_n < total then
    allowed = 1
  end
elseif work_class == 'ingestion' then
  if (total_n < total) and (non_chat_n < non_chat_max) then
    allowed = 1
  end
elseif work_class == 'communities' then
  if (total_n < total) and (non_chat_n < non_chat_max) and (com_n < communities_max) then
    allowed = 1
  end
else
  if total_n < total then
    allowed = 1
  end
end

if allowed == 1 then
  local expiry = now_ms + ttl_ms
  if work_class == 'chat' then
    redis.call('ZADD', chat_key, expiry, lease_id)
  elseif work_class == 'ingestion' then
    redis.call('ZADD', ing_key, expiry, lease_id)
  else
    redis.call('ZADD', com_key, expiry, lease_id)
  end

  return {1, total_n + 1, chat_n, ing_n, com_n}
end

return {0, total_n, chat_n, ing_n, com_n}
"""

_RELEASE_LUA = r"""
-- KEYS: chat_zset, ingestion_zset, communities_zset
-- ARGV: lease_id
local lease_id = ARGV[1]
local removed = 0
removed = removed + redis.call('ZREM', KEYS[1], lease_id)
removed = removed + redis.call('ZREM', KEYS[2], lease_id)
removed = removed + redis.call('ZREM', KEYS[3], lease_id)
return removed
"""

class RedisLLMCapacityLimiter:
    """Distributed capacity limiter using Redis leases."""

    def __init__(self, *, provider_key: str, settings: LLMCapacitySettings):
        self._provider_key = provider_key
        self._settings = settings
        self._redis = None

        self._chat_key = f"llm_capacity:{provider_key}:chat"
        self._ingestion_key = f"llm_capacity:{provider_key}:ingestion"
        self._communities_key = f"llm_capacity:{provider_key}:communities"

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis

        if not self._settings.redis_url:
            return None

        try:
            import redis.asyncio as redis

            self._redis = redis.from_url(self._settings.redis_url, decode_responses=True)
            return self._redis
        except Exception as e:
            logger.warning(f"LLM capacity limiter disabled (Redis init failed): {e}")
            return None

    def _wait_timeout(self, work_class: WorkClass) -> float:
        if work_class == "chat":
            return self._settings.chat_wait_timeout_seconds
        if work_class == "communities":
            return self._settings.communities_wait_timeout_seconds
        return self._settings.ingestion_wait_timeout_seconds

    def _poll_interval(self, work_class: WorkClass) -> float:
        # Chat should poll quickly; communities should back off.
        if work_class == "chat":
            return 0.05
        if work_class == "ingestion":
            return 0.2
        return 0.5

    async def try_acquire(self, *, work_class: WorkClass) -> str | None:
        """Try once to acquire a lease. Returns lease_id or None."""
        if not self._settings.enabled:
            return "bypass"

        redis = await self._get_redis()
        if redis is None:
            return "bypass"

        lease_id = uuid.uuid4().hex
        now_ms = int(time.time() * 1000)
        ttl_ms = int(max(1, self._settings.lease_ttl_seconds) * 1000)

        try:
            res = await redis.eval(
                _ACQUIRE_LUA,
                3,
                self._chat_key,
                self._ingestion_key,
                self._communities_key,
                now_ms,
                ttl_ms,
                work_class,
                self._settings.total,
                self._settings.reserved_chat,
                self._settings.reserved_ingestion,
                lease_id,
            )
        except Exception as e:
            # Fail open (no limiter) if Redis is unstable.
            logger.warning(f"LLM capacity limiter bypass (Redis eval failed): {e}")
            return "bypass"

        allowed = int(res[0]) if res else 0
        return lease_id if allowed == 1 else None

    async def release(self, lease_id: str) -> None:
        if lease_id in ("", "bypass"):
            return

        redis = await self._get_redis()
        if redis is None:
            return

        try:
            await redis.eval(
                _RELEASE_LUA,
                3,
                self._chat_key,
                self._ingestion_key,
                self._communities_key,
                lease_id,
            )
        except Exception as e:
            logger.warning(f"LLM capacity limiter release failed (leaking lease?): {e}")

    @asynccontextmanager
    async def hold(self, *, work_class: WorkClass) -> AsyncIterator[None]:
        """Acquire capacity (waiting up to timeout) and release on exit."""
        timeout = self._wait_timeout(work_class)
        deadline = time.monotonic() + max(0.0, timeout)

        lease_id: str | None = None
        warned = False

        try:
            while True:
                lease_id = await self.try_acquire(work_class=work_class)
                if lease_id is not None:
                    break

                now = time.monotonic()
                if timeout > 0 and now >= deadline:
                    raise TimeoutError(
                        f"LLM capacity busy (class={work_class}, total={self._settings.total})"
                    )

                if not warned and (now + 1.0) >= deadline and work_class == "chat":
                    warned = True
                    logger.warning(
                        "Chat waiting for LLM capacity (this can indicate background saturation)"
                    )

                await asyncio.sleep(self._poll_interval(work_class))

            yield None

        finally:
            if lease_id is not None:
                await self.release(lease_id)


_ollama_limiter: RedisLLMCapacityLimiter | None = None


def get_ollama_capacity_limiter() -> RedisLLMCapacityLimiter:
    global _ollama_limiter
    if _ollama_limiter is None:
        settings = LLMCapacitySettings.from_env()
        _ollama_limiter = RedisLLMCapacityLimiter(provider_key="ollama", settings=settings)
        logger.info(
            "Ollama capacity limiter initialized | "
            f"enabled={settings.enabled}, total={settings.total}, "
            f"reserved_chat={settings.reserved_chat}, reserved_ingestion={settings.reserved_ingestion}, "
            f"redis_url={set if settings.redis_url else unset}"
        )
    return _ollama_limiter
