from collections.abc import Callable
from typing import Any

TraceDecorator = Callable[[Callable[..., Any]], Callable[..., Any]]
TraceSpanFunc = Callable[[str | None], TraceDecorator]

_trace_span: TraceSpanFunc | None = None


def set_trace_span(trace_span: TraceSpanFunc | None) -> None:
    global _trace_span
    _trace_span = trace_span


def trace_span(name: str | None = None) -> TraceDecorator:
    if _trace_span is None:
        def _noop(func: Callable[..., Any]) -> Callable[..., Any]:
            return func
        return _noop
    return _trace_span(name)
