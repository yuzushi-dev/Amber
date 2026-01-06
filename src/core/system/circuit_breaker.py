import logging
from collections import deque

logger = logging.getLogger(__name__)

class CircuitBreaker:
    """
    Monitors system latency and determines if the system should enter 'Degraded Mode'.
    Uses a sliding window of recent latencies.
    """

    def __init__(
        self,
        window_size: int = 50,
        latency_threshold_ms: float = 800.0,
        degradation_ratio: float = 0.5
    ):
        self.window_size = window_size
        self.latency_threshold_ms = latency_threshold_ms
        self.degradation_ratio = degradation_ratio
        self.latencies = deque(maxlen=window_size)
        self._is_degraded = False

    def record_latency(self, latency_ms: float):
        """Record a new latency observation."""
        self.latencies.append(latency_ms)
        self._check_status()

    def _check_status(self):
        """Update degradation status based on recent latencies."""
        if len(self.latencies) < self.window_size // 2:
            self._is_degraded = False
            return

        # Calculate ratio of latencies exceeding threshold
        exceed_count = sum(1 for latency in self.latencies if latency > self.latency_threshold_ms)
        ratio = exceed_count / len(self.latencies)

        if not self._is_degraded and ratio >= self.degradation_ratio:
            logger.warning(f"System entering DEGRADED mode (ratio: {ratio:.2f})")
            self._is_degraded = True
        elif self._is_degraded and ratio < self.degradation_ratio / 2:
            logger.info("System exiting DEGRADED mode")
            self._is_degraded = False

    @property
    def should_degrade(self) -> bool:
        """Determines if the system should operate in degraded mode."""
        return self._is_degraded

    def get_stats(self) -> dict:
        """Return current monitoring statistics."""
        avg_latency = sum(self.latencies) / len(self.latencies) if self.latencies else 0
        return {
            "avg_latency_ms": avg_latency,
            "window_count": len(self.latencies),
            "is_degraded": self._is_degraded
        }
