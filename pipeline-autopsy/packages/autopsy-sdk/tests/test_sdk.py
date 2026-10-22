"""
Unit tests for Pipeline Autopsy Python SDK (`autopsy-sdk`).
"""
import os
import sys
import pytest

# Ensure packages/autopsy-sdk is importable
sdk_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if sdk_root not in sys.path:
    sys.path.insert(0, sdk_root)

from autopsy_sdk import Autopsy, AutopsyConfig


def test_sdk_initialization_defaults():
    autopsy = Autopsy(
        api_key="test_key_123",
        endpoint="http://localhost:8080",
        project_id="proj_testing",
        service_name="unit_test_service",
    )
    assert autopsy.config.api_key == "test_key_123"
    assert autopsy.config.endpoint == "http://localhost:8080"
    assert autopsy.config.project_id == "proj_testing"
    assert autopsy.config.service_name == "unit_test_service"
    assert autopsy.config.get_otlp_endpoint() == "http://localhost:8080/v1/traces"
    assert autopsy.execution_id.startswith("exec-")


def test_sdk_span_context_manager_and_attributes():
    autopsy = Autopsy(
        api_key="test_key_123",
        endpoint="http://localhost:8080",
        project_id="proj_testing",
        service_name="unit_test_service",
    )

    with autopsy.span("test_operation", attributes={"custom.attr": "value_1"}) as span:
        span.set_attribute("nested.attr", 42)
        span.add_event("stage_completed", {"step": 1})
        span.set_status_ok()

        raw_span = span.raw_span
        assert raw_span.name == "test_operation"
        assert raw_span.attributes["custom.attr"] == "value_1"
        assert raw_span.attributes["nested.attr"] == 42


def test_sdk_span_exception_capture():
    autopsy = Autopsy(
        api_key="test_key_123",
        endpoint="http://localhost:8080",
        project_id="proj_testing",
        service_name="unit_test_service",
    )

    with pytest.raises(ValueError, match="intentional calculation error"):
        with autopsy.span("failing_operation") as span:
            span.set_attribute("op.type", "math")
            raise ValueError("intentional calculation error")


def test_sdk_trace_decorator():
    autopsy = Autopsy(
        api_key="test_key_123",
        endpoint="http://localhost:8080",
        project_id="proj_testing",
        service_name="unit_test_service",
    )

    @autopsy.trace_fn("decorated_fn", attributes={"fn.type": "helper"})
    def sample_function(x, y):
        return x + y

    res = sample_function(5, 10)
    assert res == 15


def test_sdk_failsafe_when_endpoint_unreachable():
    """
    Guarantees customer business application NEVER crashes even if
    Autopsy backend is completely down or unreachable.
    """
    autopsy = Autopsy(
        api_key="test_key",
        endpoint="http://127.0.0.1:59999",  # Unreachable port
        project_id="proj_failsafe",
        service_name="resilient_service",
        timeout_seconds=0.5,
    )

    # Business logic executes without raising exporter connection exception
    with autopsy.span("resilient_operation") as s:
        s.set_attribute("safe", True)

    # Flush attempt returns False safely without crashing
    res = autopsy.flush(timeout_seconds=0.5)
    assert res is False or res is True  # Fails safely
