import asyncio
import time
from collections import deque


class ConcurrencyGovernor:
    """Adaptive concurrency limiter for extraction calls."""

    def __init__(
        self,
        *,
        initial_limit: int,
        min_limit: int = 1,
        max_limit: int = 5,
        adjust_every: int = 10,
        cooldown: int = 10,
        scale_up_latency_ms: int = 20_000,
        scale_down_latency_ms: int = 60_000,
        error_rate_threshold: float = 0.2,
        window_size: int = 30,
    ):
        self._limit = max(min_limit, min(initial_limit, max_limit))
        self._min_limit = min_limit
        self._max_limit = max_limit
        self._adjust_every = max(1, adjust_every)
        self._cooldown = max(1, cooldown)
        self._scale_up_latency_ms = scale_up_latency_ms
        self._scale_down_latency_ms = scale_down_latency_ms
        self._error_rate_threshold = error_rate_threshold

        self._in_flight = 0
        self._completed = 0
        self._last_adjust_at = 0
        self._consecutive_scale_up_signals = 0
        self._consecutive_scale_down_signals = 0
        self._latencies_ms: deque[float] = deque(maxlen=window_size)
        self._errors: deque[bool] = deque(maxlen=window_size)

        self._condition = asyncio.Condition()

    @property
    def limit(self) -> int:
        return self._limit

    async def acquire(self) -> float:
        wait_started = time.perf_counter()
        async with self._condition:
            while self._in_flight >= self._limit:
                await self._condition.wait()
            self._in_flight += 1
        wait_ms = (time.perf_counter() - wait_started) * 1000
        return wait_ms

    async def release(self, *, latency_ms: float, had_error: bool) -> None:
        async with self._condition:
            self._in_flight = max(0, self._in_flight - 1)
            self._latencies_ms.append(latency_ms)
            self._errors.append(had_error)
            self._completed += 1
            self._maybe_adjust_locked()
            self._condition.notify_all()

    def _maybe_adjust_locked(self) -> None:
        if len(self._latencies_ms) < 5:
            return

        if self._completed - self._last_adjust_at < self._adjust_every:
            return

        if self._completed - self._last_adjust_at < self._cooldown:
            return

        avg_latency_ms = sum(self._latencies_ms) / len(self._latencies_ms)
        error_rate = sum(self._errors) / len(self._errors) if self._errors else 0.0

        scale_down_signal = (
            error_rate >= self._error_rate_threshold
            or avg_latency_ms >= self._scale_down_latency_ms
        )
        scale_up_signal = (
            error_rate == 0.0
            and avg_latency_ms <= self._scale_up_latency_ms
        )

        if scale_down_signal:
            self._consecutive_scale_down_signals += 1
            self._consecutive_scale_up_signals = 0
        elif scale_up_signal:
            self._consecutive_scale_up_signals += 1
            self._consecutive_scale_down_signals = 0
        else:
            self._consecutive_scale_up_signals = 0
            self._consecutive_scale_down_signals = 0
            return

        if self._consecutive_scale_down_signals >= 2 and self._limit > self._min_limit:
            self._limit -= 1
            self._last_adjust_at = self._completed
            self._consecutive_scale_down_signals = 0
            self._consecutive_scale_up_signals = 0
            return

        if self._consecutive_scale_up_signals >= 3 and self._limit < self._max_limit:
            self._limit += 1
            self._last_adjust_at = self._completed
            self._consecutive_scale_down_signals = 0
            self._consecutive_scale_up_signals = 0
