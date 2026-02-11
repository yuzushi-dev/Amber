import pytest

from src.core.graph.application.concurrency_governor import ConcurrencyGovernor


@pytest.mark.asyncio
async def test_governor_scales_down_on_high_latency():
    governor = ConcurrencyGovernor(
        initial_limit=3,
        min_limit=1,
        max_limit=5,
        adjust_every=1,
        cooldown=1,
        scale_down_latency_ms=50,
        window_size=10,
    )

    for _ in range(6):
        await governor.acquire()
        await governor.release(latency_ms=120, had_error=False)

    assert governor.limit < 3
    assert governor.limit >= 1


@pytest.mark.asyncio
async def test_governor_scales_up_on_low_latency_without_errors():
    governor = ConcurrencyGovernor(
        initial_limit=1,
        min_limit=1,
        max_limit=4,
        adjust_every=1,
        cooldown=1,
        scale_up_latency_ms=20,
        window_size=10,
    )

    for _ in range(12):
        await governor.acquire()
        await governor.release(latency_ms=5, had_error=False)

    assert governor.limit > 1
    assert governor.limit <= 4
