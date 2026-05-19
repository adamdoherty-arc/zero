"""Zero copy of the OTel GenAI helper (Sprint S7, 2026-05-18).

Identical to Legion's helper — see ``C:\\code\\Legion\\backend\\app\\observability\\otel_genai.py``.
Each project keeps its own copy to avoid cross-project Python imports;
behavior is the same.
"""
from __future__ import annotations

import contextlib
import logging
import time
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)


try:
    from opentelemetry import trace  # type: ignore

    _tracer = trace.get_tracer("zero.genai")
    _OTEL_AVAILABLE = True
except Exception:  # noqa: BLE001
    _tracer = None
    _OTEL_AVAILABLE = False


class _LlmSpan:
    def __init__(self, span: Any) -> None:
        self._span = span
        self._started_at = time.perf_counter()

    def set_input_tokens(self, n: int) -> None:
        if self._span is None:
            return
        self._span.set_attribute("gen_ai.usage.input_tokens", int(n))

    def set_output_tokens(self, n: int) -> None:
        if self._span is None:
            return
        self._span.set_attribute("gen_ai.usage.output_tokens", int(n))

    def set_status_ok(self) -> None:
        if self._span is None or not _OTEL_AVAILABLE:
            return
        from opentelemetry.trace.status import Status, StatusCode  # type: ignore

        self._span.set_status(Status(StatusCode.OK))

    def set_status_error(self, exc: BaseException) -> None:
        if self._span is None or not _OTEL_AVAILABLE:
            return
        from opentelemetry.trace.status import Status, StatusCode  # type: ignore

        self._span.set_status(Status(StatusCode.ERROR, str(exc)[:200]))
        self._span.record_exception(exc)

    def set_attribute(self, key: str, value: Any) -> None:
        if self._span is None:
            return
        self._span.set_attribute(key, value)

    @property
    def elapsed_s(self) -> float:
        return time.perf_counter() - self._started_at


@contextlib.contextmanager
def llm_span(
    *,
    model: str,
    provider: str,
    request_type: str = "chat",
    operation: str = "completions",
    agent: Optional[str] = None,
) -> Iterator[_LlmSpan]:
    if _tracer is None:
        yield _LlmSpan(span=None)
        return
    with _tracer.start_as_current_span(f"gen_ai.{operation}") as span:
        span.set_attribute("gen_ai.system", provider)
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("gen_ai.operation.name", operation)
        span.set_attribute("gen_ai.request.type", request_type)
        if agent:
            span.set_attribute("gen_ai.agent.name", agent)
        wrapper = _LlmSpan(span=span)
        try:
            yield wrapper
            wrapper.set_status_ok()
        except BaseException as exc:
            wrapper.set_status_error(exc)
            raise


def is_available() -> bool:
    return _OTEL_AVAILABLE
