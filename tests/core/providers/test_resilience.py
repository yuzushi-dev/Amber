import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.providers.base import GenerationResult, ProviderUnavailableError, TokenUsage
from src.core.providers.failover import FailoverLLMProvider
from src.core.providers.resilience import CircuitBreaker, CircuitState


class TestCircuitBreaker:
    def test_initial_state(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request()

    def test_open_circuit(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert not cb.allow_request()

    def test_recovery(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.2)
        assert cb.allow_request() # Should transition to HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED

@pytest.mark.asyncio
class TestFailoverLLMProvider:
    async def test_failover_logic(self):
        # Mock providers
        p1 = MagicMock()
        p1.provider_name = "p1"
        p1.generate = AsyncMock(side_effect=ProviderUnavailableError("Down", "p1"))

        p2 = MagicMock()
        p2.provider_name = "p2"
        p2.generate = AsyncMock(return_value=GenerationResult(
            text="Success", model="m", provider="p2", usage=TokenUsage()
        ))

        failover = FailoverLLMProvider([p1, p2])

        # Determine strict circuit behavior
        # p1 should fail and record failure
        # p2 should succeed

        result = await failover.generate("test")
        assert result.text == "Success"
        assert result.provider == "p2"

        assert failover.circuits["p1"].failures == 1
        assert failover.circuits["p2"].failures == 0

    async def test_circuit_skipping(self):
        p1 = MagicMock()
        p1.provider_name = "p1"
        p1.generate = AsyncMock(side_effect=ProviderUnavailableError("Down", "p1"))

        failover = FailoverLLMProvider([p1])
        failover.circuits["p1"].state = CircuitState.OPEN
        failover.circuits["p1"].last_failure_time = time.time()


        # Should skip p1 without calling generate
        # Since all skipped, should raise ProviderUnavailableError
        with pytest.raises(ProviderUnavailableError) as exc:
            await failover.generate("test")

        assert "All providers skipped or unavailable" in str(exc.value)
        p1.generate.assert_not_called()
