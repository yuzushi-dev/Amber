import time

from src.core.providers.base import BaseLLMProvider
from src.core.providers.resilience import CircuitBreaker, CircuitState


class FailbackManager:
    """
    Manages failback from secondary to primary provider.
    """

    def __init__(self, primary: BaseLLMProvider, cooldown: float = 300.0):
        self.primary = primary
        self.cooldown = cooldown
        self.last_switch_time = 0.0
        # We can reuse CircuitBreaker logic, or implement simple cooldown
        # If we use CircuitBreaker on the primary, this manager basically just checks the circuit.

    def should_probe_primary(self, circuit: CircuitBreaker) -> bool:
        """
        Checks if we should try to switch back to primary.
        """
        # Rely on circuit breaker's state
        if circuit.state == CircuitState.OPEN:
            # Check if enough time passed to try half-open (managed by circuit logic usually)
             return time.time() - circuit.last_failure_time > circuit.recovery_timeout

        return circuit.state == CircuitState.CLOSED or circuit.state == CircuitState.HALF_OPEN

    async def probe(self) -> bool:
        """
        Probes the primary provider with a lightweight request.
        """
        try:
            # Send a cheap prompt
            # Note: This consumes tokens.
            await self.primary.generate("ping", max_tokens=1)
            return True
        except Exception:
            return False
