from src.core.system.circuit_breaker import CircuitBreaker


def test_circuit_breaker_degradation():
    """Verify that circuit breaker triggers degradation on high latency."""
    cb = CircuitBreaker(window_size=10, latency_threshold_ms=100.0, degradation_ratio=0.5)

    # Record low latencies
    for _ in range(10):
        cb.record_latency(50.0)
    assert not cb.should_degrade

    # Record high latencies (above threshold)
    for _ in range(6): # > 50% of 10
        cb.record_latency(200.0)

    assert cb.should_degrade

def test_circuit_breaker_recovery():
    """Verify recovery once latency drops."""
    cb = CircuitBreaker(window_size=10, latency_threshold_ms=100.0, degradation_ratio=0.5)

    # Force degradation
    for _ in range(10):
        cb.record_latency(200.0)
    assert cb.should_degrade

    # Recovery (requires ratio < degradation_ratio / 2)
    for _ in range(10):
        cb.record_latency(20.0)

    assert not cb.should_degrade
