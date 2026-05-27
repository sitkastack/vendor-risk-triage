"""Distributed tracing for the vendor risk triage framework.

The framework emits trace spans for every meaningful operation. Spans
form a parent-child tree: a triage call's root span has child spans
for LLM calls, retrieval calls, validation, and audit pack rendering.
Deployments consume spans by configuring a ``Tracer`` implementation;
the default is ``NoopTracer`` (silent).

OpenTelemetry is supported via the optional ``[otel]`` extra:

    pip install -e '.[otel]'

When OTel is installed, deployments construct an ``OtelTracer`` by
passing a configured ``opentelemetry.trace.Tracer`` instance:

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor, ConsoleSpanExporter,
    )

    provider = TracerProvider()
    provider.add_span_processor(
        BatchSpanProcessor(ConsoleSpanExporter())
    )
    trace.set_tracer_provider(provider)

    from observability.tracing import OtelTracer
    tracer = OtelTracer(otel_tracer=trace.get_tracer(__name__))

    from observability import Observability, TriageAgent, TriageAgentConfig
    obs = Observability(tracer=tracer)
    agent = TriageAgent(TriageAgentConfig(observability=obs))

Span names used by the framework (stable as of 0.7.0):

- ``vrt.triage``: root span for a triage operation
- ``vrt.llm_call``: an LLM provider call
- ``vrt.retrieval``: a regulation chunk retrieval call
- ``vrt.validation``: TriageRecord validation
- ``vrt.audit_pack.render``: rendering an audit pack HTML

Span attributes set by the framework:

On ``vrt.triage``:
- ``vrt.submission_id``: the input submission's vendor_id
- ``vrt.decision_id``: the produced TriageRecord's decision_id
- ``vrt.tier``: produced risk tier
- ``vrt.disposition``: produced disposition
- ``vrt.correlation_id``: the correlation_id for this operation
- ``vrt.framework_version``: FRAMEWORK_VERSION

On ``vrt.llm_call``:
- ``vrt.model``: model identifier
- ``vrt.retry_count``: number of retries before success (or final
  failure)

On ``vrt.retrieval``:
- ``vrt.chunk_count``: number of chunks returned

Design choices:

- **Tracer Protocol, not direct OTel dependency.** The framework
  doesn't import OpenTelemetry in its core path; tracing is a
  ``typing.Protocol``. This means the framework runs in environments
  that don't have OTel installed at all.
- **Span context manager pattern.** ``Tracer.start_span()`` returns a
  context manager. ``with tracer.start_span('x') as span:`` is the
  ergonomic surface for framework code. The default NoopTracer's
  span object accepts ``set_attribute()`` and ``record_error()``
  calls without side effects.
- **Status, not exceptions.** Spans record errors via
  ``record_error()`` so the framework can decide whether an error is
  fatal or recoverable separately from how it's reported.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional, Protocol, runtime_checkable


__all__ = [
    "NoopSpan",
    "NoopTracer",
    "Span",
    "Tracer",
]


@runtime_checkable
class Span(Protocol):
    """A single trace span.

    Spans are returned by ``Tracer.start_span()`` as a context manager.
    Code sets attributes and records errors during the span's lifetime;
    the framework auto-closes the span when the context manager exits.
    """

    def set_attribute(self, key: str, value: Any) -> None: ...

    def record_error(self, exc: BaseException) -> None: ...


@runtime_checkable
class Tracer(Protocol):
    """Sink for framework trace spans.

    Implementations must provide ``start_span()`` as a context manager
    that yields a ``Span``. The framework wraps each meaningful
    operation in a ``with tracer.start_span(name) as span:`` block.

    Implementations must not raise; trace recording failures should be
    suppressed rather than propagated into the operational path.
    """

    @contextmanager
    def start_span(
        self,
        name: str,
        attributes: Optional[dict[str, Any]] = None,
    ) -> Iterator[Span]: ...


class NoopSpan:
    """A span that discards all attributes and errors."""

    def set_attribute(self, key: str, value: Any) -> None:
        return None

    def record_error(self, exc: BaseException) -> None:
        return None


class NoopTracer:
    """Default tracer: produces no-op spans.

    The framework's default. Deployments wanting tracing inject their
    own implementation (OtelTracer or a custom adapter).
    """

    @contextmanager
    def start_span(
        self,
        name: str,
        attributes: Optional[dict[str, Any]] = None,
    ) -> Iterator[Span]:
        yield NoopSpan()


def _build_otel_tracer_adapter():  # pragma: no cover - exercised in [otel] extra integration tests
    """Construct the OpenTelemetry adapter class lazily.

    Defined as a function so importing this module does not require
    the OpenTelemetry packages. The adapter is constructed only when
    the deployment opts in by importing ``OtelTracer`` directly.

    Returns the OtelTracer class. Raises ImportError if OpenTelemetry
    is not installed.
    """
    try:
        from opentelemetry import trace as _otel_trace  # noqa: F401
        from opentelemetry.trace import Status, StatusCode  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "OpenTelemetry not installed. Install the framework with "
            "the [otel] extra: pip install -e '.[otel]'"
        ) from exc

    class _OtelSpan:
        """Adapter that wraps an OTel span as a framework Span."""

        def __init__(self, otel_span) -> None:
            self._span = otel_span

        def set_attribute(self, key: str, value: Any) -> None:
            self._span.set_attribute(key, value)

        def record_error(self, exc: BaseException) -> None:
            self._span.record_exception(exc)
            self._span.set_status(Status(StatusCode.ERROR, str(exc)))

    class OtelTracer:
        """Tracer adapter that ships spans via an OpenTelemetry tracer.

        Args:
            otel_tracer: A configured ``opentelemetry.trace.Tracer``
                instance. Obtain via
                ``trace.get_tracer(__name__)`` after configuring an
                exporter.
        """

        def __init__(self, otel_tracer) -> None:
            self._tracer = otel_tracer

        @contextmanager
        def start_span(
            self,
            name: str,
            attributes: Optional[dict[str, Any]] = None,
        ) -> Iterator[Span]:
            attrs = attributes or {}
            with self._tracer.start_as_current_span(
                name, attributes=attrs,
            ) as otel_span:
                yield _OtelSpan(otel_span)

    return OtelTracer


def __getattr__(name: str):  # pragma: no cover - import-time hook only
    """Lazy attribute lookup so ``OtelTracer`` is exposed only when used.

    Avoids forcing OpenTelemetry import at framework startup. The
    OtelTracer class is constructed on first access by callers that
    opted in via the [otel] extra.
    """
    if name == "OtelTracer":
        return _build_otel_tracer_adapter()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
