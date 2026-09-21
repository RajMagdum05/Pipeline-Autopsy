"""
Autopsy Client module.

Provides the primary customer-facing API for initializing instrumentation,
managing pipeline execution context, and creating traces and spans.
"""
import functools
import logging
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Dict, Optional

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode, Span
from opentelemetry.sdk.trace import TracerProvider

from autopsy_sdk.config import AutopsyConfig
from autopsy_sdk.telemetry import setup_tracer_provider

logger = logging.getLogger("autopsy_sdk")


class AutopsySpan:
    """
    Wrapper around OpenTelemetry Span providing convenient helper methods.
    """
    def __init__(self, otel_span: Span):
        self._span = otel_span

    @property
    def raw_span(self) -> Span:
        return self._span

    def set_attribute(self, key: str, value: Any) -> "AutopsySpan":
        """Sets a single attribute on the active span."""
        try:
            self._span.set_attribute(key, value)
        except Exception as e:
            logger.debug("Failed to set attribute %s: %s", key, e)
        return self

    def set_attributes(self, attributes: Dict[str, Any]) -> "AutopsySpan":
        """Sets multiple attributes on the active span."""
        if attributes:
            for k, v in attributes.items():
                self.set_attribute(k, v)
        return self

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> "AutopsySpan":
        """Adds a timestamped event to the active span."""
        try:
            self._span.add_event(name, attributes or {})
        except Exception as e:
            logger.debug("Failed to add event %s: %s", name, e)
        return self

    def record_exception(self, exception: Exception, attributes: Optional[Dict[str, Any]] = None) -> "AutopsySpan":
        """Records an exception event on the span and sets error status."""
        try:
            self._span.record_exception(exception, attributes=attributes)
            self._span.set_status(Status(StatusCode.ERROR, str(exception)))
        except Exception as e:
            logger.debug("Failed to record exception: %s", e)
        return self

    def set_status_ok(self, description: Optional[str] = None) -> "AutopsySpan":
        """Sets the span status to OK."""
        try:
            self._span.set_status(Status(StatusCode.OK, description))
        except Exception:
            pass
        return self

    def set_status_error(self, description: str) -> "AutopsySpan":
        """Sets the span status to ERROR with description."""
        try:
            self._span.set_status(Status(StatusCode.ERROR, description))
        except Exception:
            pass
        return self


class Autopsy:
    """
    Primary customer-facing Autopsy SDK client.

    Example:
        autopsy = Autopsy(
            api_key="sk_live_12345",
            endpoint="http://localhost:8000",
            project_id="billing_service",
            service_name="payment_worker",
        )

        with autopsy.span("process_payment", attributes={"user.id": "u123"}):
            do_work()
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        project_id: Optional[str] = None,
        service_name: Optional[str] = None,
        environment: Optional[str] = None,
        execution_id: Optional[str] = None,
        batch_export: bool = False,
        timeout_seconds: float = 5.0,
        debug: bool = False,
        config: Optional[AutopsyConfig] = None,
    ):
        if config is not None:
            self.config = config
        else:
            self.config = AutopsyConfig(
                api_key=api_key or "",
                endpoint=endpoint or "http://localhost:8000",
                project_id=project_id or "default_project",
                service_name=service_name or "customer_service",
                environment=environment or "production",
                batch_export=batch_export,
                timeout_seconds=timeout_seconds,
                debug=debug,
            )

        self.execution_id = execution_id or f"exec-{uuid.uuid4().hex[:12]}"
        self.tracer_provider: TracerProvider = setup_tracer_provider(
            config=self.config,
            execution_id=self.execution_id,
        )
        self.tracer = self.tracer_provider.get_tracer(self.config.service_name, "0.1.0")

    def start_execution(self, execution_id: Optional[str] = None) -> str:
        """
        Starts a new execution scope with a designated or generated execution ID.
        Re-initializes tracer provider resource attributes with the new execution ID.
        """
        self.execution_id = execution_id or f"exec-{uuid.uuid4().hex[:12]}"
        self.tracer_provider = setup_tracer_provider(
            config=self.config,
            execution_id=self.execution_id,
        )
        self.tracer = self.tracer_provider.get_tracer(self.config.service_name, "0.1.0")
        return self.execution_id

    @contextmanager
    def span(
        self,
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
        kind: trace.SpanKind = trace.SpanKind.INTERNAL,
    ):
        """
        Context manager to create a timed span.
        Automatically captures unhandled exceptions, records them as exception events,
        marks span status as ERROR, and re-raises to protect customer application control flow.
        """
        with self.tracer.start_as_current_span(name=name, kind=kind) as otel_span:
            wrapped_span = AutopsySpan(otel_span)
            if attributes:
                wrapped_span.set_attributes(attributes)
            try:
                yield wrapped_span
                # If status not set explicitly, default to OK
                if otel_span.status.status_code == StatusCode.UNSET:
                    otel_span.set_status(Status(StatusCode.OK))
            except Exception as exc:
                wrapped_span.record_exception(exc)
                raise exc


    def trace_fn(
        self,
        name: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Callable:
        """
        Decorator to instrument functions automatically.

        Example:
            @autopsy.trace_fn("compute_metrics")
            def calculate(data):
                ...
        """
        def decorator(func: Callable) -> Callable:
            span_name = name or func.__name__

            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                with self.span(span_name, attributes=attributes):
                    return func(*args, **kwargs)

            return wrapper
        return decorator

    def get_current_trace_id(self) -> Optional[str]:
        """Returns the active trace ID in hex format if available."""
        current_span = trace.get_current_span()
        if current_span and current_span.get_span_context().is_valid:
            return f"{current_span.get_span_context().trace_id:032x}"
        return None

    def get_current_span_id(self) -> Optional[str]:
        """Returns the active span ID in hex format if available."""
        current_span = trace.get_current_span()
        if current_span and current_span.get_span_context().is_valid:
            return f"{current_span.get_span_context().span_id:016x}"
        return None

    def flush(self, timeout_seconds: float = 5.0) -> bool:
        """Flushes buffered spans to Autopsy backend."""
        try:
            return self.tracer_provider.force_flush(int(timeout_seconds * 1000))
        except Exception as e:
            logger.warning("[Autopsy SDK] Force flush failed safely: %s", e)
            return False

    def shutdown(self):
        """Shuts down the tracer provider."""
        try:
            self.tracer_provider.shutdown()
        except Exception:
            pass
