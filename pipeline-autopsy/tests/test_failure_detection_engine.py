from datetime import datetime, timezone, timedelta
import pytest

from autopsy.detectors import (
    ErrorStatusDetector,
    ExceptionDetector,
    TimeoutDetector,
    DependencyFailureDetector,
    StructuralTelemetryDetector,
    ExplicitValidationDetector,
)
from autopsy.services.reconstruction_service import (
    PipelineReconstructionEngine,
    ExecutionGraph,
    ExecutionNode,
)
from autopsy.services.failure_detection_service import FailureDetectionService


@pytest.fixture
def reconstruction_engine():
    return PipelineReconstructionEngine()


@pytest.fixture
def detection_service():
    return FailureDetectionService()


def _make_span(
    span_id: str,
    parent_span_id: str = None,
    operation_name: str = "op",
    service_name: str = "service_test",
    status_code: str = "OK",
    duration_ms: float = 20.0,
    attributes: dict = None,
    events: list = None,
):
    start_time = datetime(2026, 9, 22, 1, 0, 0, tzinfo=timezone.utc)
    return {
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "operation_name": operation_name,
        "service_name": service_name,
        "kind": "INTERNAL",
        "start_time": start_time,
        "end_time": start_time + timedelta(milliseconds=duration_ms),
        "duration_ms": duration_ms,
        "status_code": status_code,
        "status_message": None,
        "attributes": attributes or {},
        "events": events or [],
    }


def test_1_successful_span_no_failure(reconstruction_engine, detection_service):
    """TEST 1 — Successful span: Expected no failure findings."""
    spans = [_make_span("s1", operation_name="success_op", status_code="OK")]
    graph = reconstruction_engine.reconstruct_from_spans("e1", "t1", spans)

    findings = detection_service.run_detection(graph)
    assert len(findings) == 0


def test_2_span_with_error_status(reconstruction_engine):
    """TEST 2 — Span with ERROR status: Expected error status finding."""
    spans = [_make_span("s1", operation_name="failing_op", status_code="ERROR")]
    graph = reconstruction_engine.reconstruct_from_spans("e2", "t2", spans)

    detector = ErrorStatusDetector()
    findings = detector.detect(graph)

    assert len(findings) == 1
    assert findings[0].finding_type == "SPAN_ERROR_STATUS"
    assert findings[0].span_id == "s1"
    assert findings[0].severity == "ERROR"


def test_3_span_with_exception_event(reconstruction_engine):
    """TEST 3 — Span with exception event: Expected exception finding."""
    events = [
        {
            "name": "exception",
            "timestamp": datetime.now(timezone.utc),
            "attributes": {
                "exception.type": "ValueError",
                "exception.message": "Invalid input format",
            },
        }
    ]
    spans = [_make_span("s1", operation_name="exc_op", status_code="OK", events=events)]
    graph = reconstruction_engine.reconstruct_from_spans("e3", "t3", spans)

    detector = ExceptionDetector()
    findings = detector.detect(graph)

    assert len(findings) == 1
    assert findings[0].finding_type == "EXCEPTION_EVENT"
    assert findings[0].evidence_data["exception_type"] == "ValueError"
    assert findings[0].evidence_data["exception_message"] == "Invalid input format"


def test_4_explicit_timeout_failure(reconstruction_engine):
    """TEST 4 — Explicit timeout / duration finding."""
    spans = [
        _make_span(
            "s1",
            operation_name="db_query",
            duration_ms=4500.0,
            attributes={"timeout_exceeded": True, "http.status_code": 504},
        )
    ]
    graph = reconstruction_engine.reconstruct_from_spans("e4", "t4", spans)

    detector = TimeoutDetector(threshold_rules_ms={"db_query": 1000.0})
    findings = detector.detect(graph)

    # Both explicit attribute and threshold breach findings triggered
    assert len(findings) >= 1
    timeout_types = [f.finding_type for f in findings]
    assert "TIMEOUT_EXCEEDED" in timeout_types


def test_5_failed_dependency_relationship(reconstruction_engine):
    """TEST 5 — Failed child dependency: Expected dependency failure finding on upstream parent."""
    spans = [
        _make_span("parent_s1", operation_name="ApiGateway", status_code="OK"),
        _make_span("child_s2", parent_span_id="parent_s1", operation_name="AuthService", status_code="ERROR"),
    ]
    graph = reconstruction_engine.reconstruct_from_spans("e5", "t5", spans)

    detector = DependencyFailureDetector()
    findings = detector.detect(graph)

    assert len(findings) == 1
    f = findings[0]
    assert f.finding_type == "DEPENDENCY_FAILURE"
    assert f.span_id == "parent_s1"
    assert f.evidence_data["failed_dependent_span_id"] == "child_s2"
    assert f.evidence_data["failed_dependent_operation"] == "AuthService"


def test_6_orphan_span_structural_finding(reconstruction_engine):
    """TEST 6 — Orphan span: Expected structural telemetry finding."""
    spans = [
        _make_span("s1", parent_span_id=None, operation_name="RootOp"),
        _make_span("s2", parent_span_id="NON_EXISTENT_PARENT", operation_name="OrphanOp"),
    ]
    graph = reconstruction_engine.reconstruct_from_spans("e6", "t6", spans)

    detector = StructuralTelemetryDetector()
    findings = detector.detect(graph)

    assert len(findings) >= 1
    struct_types = [f.finding_type for f in findings]
    assert "STRUCTURAL_WARNING" in struct_types


def test_7_multi_signal_deduplication(reconstruction_engine, detection_service):
    """
    TEST 7 — Multi-signal failure deduplication:
    Span status = ERROR + exception event on the SAME span s1.

    Expected: Detectors produce 2 findings, but correlation groups them under 1 failure entry.
    """
    events = [
        {
            "name": "exception",
            "timestamp": datetime.now(timezone.utc),
            "attributes": {"exception.type": "RuntimeError", "exception.message": "Null pointer"},
        }
    ]
    spans = [_make_span("s1", operation_name="crash_op", status_code="ERROR", events=events)]
    graph = reconstruction_engine.reconstruct_from_spans("e7", "t7", spans)

    raw_findings = detection_service.run_detection(graph)
    assert len(raw_findings) == 2  # ErrorStatusDetector + ExceptionDetector

    # Grouping test
    groups = {}
    for f in raw_findings:
        key = f.span_id
        groups.setdefault(key, []).append(f)

    assert len(groups) == 1
    assert len(groups["s1"]) == 2  # 2 distinct evidence signals under 1 span


def test_8_mixed_execution_isolation(reconstruction_engine, detection_service):
    """
    TEST 8 — Mixed Execution Isolation:
    API (Root)
      ├── Service A — SUCCESS (OK)
      ├── Service B — ERROR (ERROR)
      └── Service C — SUCCESS (OK)

    Expected: Service B strictly identified as the failed operation.
    """
    spans = [
        _make_span("s_api", parent_span_id=None, operation_name="API_Gateway", status_code="OK"),
        _make_span("s_a", parent_span_id="s_api", operation_name="Service_A", status_code="OK"),
        _make_span("s_b", parent_span_id="s_api", operation_name="Service_B", status_code="ERROR"),
        _make_span("s_c", parent_span_id="s_api", operation_name="Service_C", status_code="OK"),
    ]
    graph = reconstruction_engine.reconstruct_from_spans("e8", "t8", spans)

    raw_findings = detection_service.run_detection(graph)

    # Find primary error status finding
    error_status_findings = [f for f in raw_findings if f.finding_type == "SPAN_ERROR_STATUS"]
    assert len(error_status_findings) == 1
    assert error_status_findings[0].span_id == "s_b"
    assert error_status_findings[0].operation_name == "Service_B"
