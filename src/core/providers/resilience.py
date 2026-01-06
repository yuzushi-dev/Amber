import logging
import time
from enum import Enum

logger = logging.getLogger(__name__)

class CircuitState(Enum):
    CLOSED = "CLOSED"     # Normal operation
    OPEN = "OPEN"         # Failing, reject requests
    HALF_OPEN = "HALF_OPEN" # Probing

class CircuitBreaker:
    """
    Circuit Breaker pattern to prevent cascading failures when a provider is down.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self.state = CircuitState.CLOSED
        self.failures = 0
        self.last_failure_time = 0.0
        self._half_open_trial = False

    def allow_request(self) -> bool:
        """Returns True if the request should be allowed to proceed."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self._half_open_trial = True
                logger.info("Circuit breaker entering HALF_OPEN state")
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            # Only allow one trial request at a time (simplification)
            # In a real distributed system, this requires a lock or atomic counter
            if self._half_open_trial:
                self._half_open_trial = False # Consume tokens
                return True
            return False

        return False

    def record_success(self):
        """Record a successful request."""
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self.failures = 0
            logger.info("Circuit breaker recovered to CLOSED state")
        elif self.state == CircuitState.CLOSED:
            self.failures = 0

    def record_failure(self):
        """Record a failed request."""
        self.failures += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            logger.warning("Circuit breaker probing failed. Returning to OPEN state.")

        elif self.state == CircuitState.CLOSED:
            if self.failures >= self.failure_threshold:
                self.state = CircuitState.OPEN
                logger.warning(f"Circuit breaker tripped to OPEN state after {self.failures} failures")
