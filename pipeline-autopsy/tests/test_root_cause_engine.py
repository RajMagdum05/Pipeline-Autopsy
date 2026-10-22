from datetime import datetime, timezone, timedelta
import pytest

from autopsy.services.reconstruction_service import PipelineReconstructionEngine
from autopsy.services.failure_detection_service import FailureDetectionService
from autopsy.services.root_cause_service import RootCauseAnalysisEngine


@pytest.fixture
def recon_engine():
    return PipelineReconstructionEngine()


@pytest.fixture
def fail_service():
    return FailureDetectionService()


@pytest.fixture
def rca_engine():
    return RootCauseAnalysisEngine()


def _make_span(
    span_id: str,
    parent_span_id: str = None,
    operation_name: str = "op",
    service_name: str = "service_test",
    status_code: str = "OK",
    start_offset_ms: float = 0.0,
    duration_ms: float = 20.0,
    events: list = None,
    attributes: dict = None,
):
    base_time = datetime(2026, 9, 22, 1, 0, 0, tzinfo=timezone.utc)
    start_dt = base_time + timedelta(milliseconds=start_offset_ms)
    return {
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "operation_name": operation_name,
        "service_name": service_name,
        "kind": "INTERNAL",
        "start_time": start_dt,
        "end_time": start_dt + timedelta(milliseconds=duration_ms),
        "duration_ms": duration_ms,
        "status_code": status_code,
        "status_message": "Error occurred" if status_code == "ERROR" else None,
        "attributes": attributes or {},
        "events": events or [],
    }


def test_rca_1_linear_propagation(recon_engine, fail_service, rca_engine):
    """
    TEST 1 — Linear Propagation:
    A (OK) -> B (ERROR) -> C (OK, but dependency failure reported)

    Expected: B is identified as supported root-cause candidate for C.
    """
    spans = [
        _make_span("s_a", parent_span_id=None, operation_name="A"),
        _make_span("s_b", parent_span_id="s_a", operation_name="B", status_code="ERROR", start_offset_ms=10),
        _make_span("s_c", parent_span_id="s_b", operation_name="C", status_code="OK", start_offset_ms=20),
    ]
    graph = recon_engine.reconstruct_from_spans("e1", "t1", spans)
    findings = fail_service.run_detection(graph)

    res = rca_engine.analyze(graph, findings)

    assert res.analysis_status == "ROOT_CAUSE_IDENTIFIED"
    assert len(res.candidates) == 1
    cand = res.candidates[0]
    assert cand.span_id == "s_b"
    assert cand.operation_name == "B"
    assert cand.confidence_state == "supported"


def test_rca_2_downstream_failure(recon_engine, fail_service, rca_engine):
    """
    TEST 2 — Downstream Failure:
    A (OK) -> B (ERROR) -> C (ERROR)

    Expected: B is root-cause candidate, C is recorded in downstream_impact_spans.
    """
    spans = [
        _make_span("s_a", parent_span_id=None, operation_name="A"),
        _make_span("s_b", parent_span_id="s_a", operation_name="B", status_code="ERROR", start_offset_ms=10),
        _make_span("s_c", parent_span_id="s_b", operation_name="C", status_code="ERROR", start_offset_ms=20),
    ]
    graph = recon_engine.reconstruct_from_spans("e2", "t2", spans)
    findings = fail_service.run_detection(graph)

    res = rca_engine.analyze(graph, findings)

    assert res.analysis_status == "ROOT_CAUSE_IDENTIFIED"
    assert len(res.candidates) == 1

    cand = res.candidates[0]
    assert cand.span_id == "s_b"
    assert cand.operation_name == "B"
    assert len(cand.downstream_impact_spans) == 1
    assert cand.downstream_impact_spans[0]["span_id"] == "s_c"


def test_rca_3_independent_failures(recon_engine, fail_service, rca_engine):
    """
    TEST 3 — Independent Parallel Failures:
    A (OK)
      ├── B (ERROR)
      └── C (ERROR)

    Expected: Both B and C are retained as independent root-cause candidates.
    """
    spans = [
        _make_span("s_a", parent_span_id=None, operation_name="A"),
        _make_span("s_b", parent_span_id="s_a", operation_name="B", status_code="ERROR", start_offset_ms=10),
        _make_span("s_c", parent_span_id="s_a", operation_name="C", status_code="ERROR", start_offset_ms=15),
    ]
    graph = recon_engine.reconstruct_from_spans("e3", "t3", spans)
    findings = fail_service.run_detection(graph)

    res = rca_engine.analyze(graph, findings)

    assert res.analysis_status == "MULTIPLE_CANDIDATES"
    assert len(res.candidates) == 2
    cand_op_names = [c.operation_name for c in res.candidates]
    assert "B" in cand_op_names
    assert "C" in cand_op_names


def test_rca_4_timing_conflict(recon_engine, fail_service, rca_engine):
    """
    TEST 4 — Timing Conflict:
    Child span C starts at t=10ms and fails.
    Parent span B starts at t=50ms and fails.

    Expected: B is not falsely claimed as causing C due to timestamp conflict.
    """
    spans = [
        _make_span("s_c", parent_span_id=None, operation_name="ChildOp_Early", status_code="ERROR", start_offset_ms=10),
        _make_span("s_b", parent_span_id="s_c", operation_name="ParentOp_Late", status_code="ERROR", start_offset_ms=50),
    ]
    graph = recon_engine.reconstruct_from_spans("e4", "t4", spans)
    findings = fail_service.run_detection(graph)

    res = rca_engine.analyze(graph, findings)

    # Early child span s_c cannot be caused by s_b which started later
    cand_ids = [c.span_id for c in res.candidates]
    assert "s_c" in cand_ids


def test_rca_5_unknown_cause_insufficient_evidence(recon_engine, rca_engine):
    """
    TEST 5 — Unknown Cause / Insufficient Evidence:
    No findings or unsupported findings.

    Expected: analysis_status = INSUFFICIENT_EVIDENCE / NO_FAILURES.
    """
    spans = [_make_span("s1", operation_name="NormalOp", status_code="OK")]
    graph = recon_engine.reconstruct_from_spans("e5", "t5", spans)

    res = rca_engine.analyze(graph, [])

    assert res.analysis_status == "NO_FAILURES"
    assert len(res.candidates) == 0


def test_rca_6_explicit_dependency_error(recon_engine, fail_service, rca_engine):
    """
    TEST 6 — Explicit Dependency Error:
    Span B produces ERROR. Span C reports dependency failure.

    Expected: Strong supporting evidence linking B to C.
    """
    spans = [
        _make_span("s_b", parent_span_id=None, operation_name="AuthService", status_code="ERROR", start_offset_ms=10),
        _make_span("s_c", parent_span_id="s_b", operation_name="PaymentService", status_code="ERROR", start_offset_ms=20),
    ]
    graph = recon_engine.reconstruct_from_spans("e6", "t6", spans)
    findings = fail_service.run_detection(graph)

    res = rca_engine.analyze(graph, findings)

    assert res.analysis_status == "ROOT_CAUSE_IDENTIFIED"
    cand = res.candidates[0]
    assert cand.span_id == "s_b"
    assert cand.relationship_type == "UPSTREAM_DEPENDENCY_PROPAGATION"
    assert len(cand.downstream_impact_spans) == 1
    assert cand.downstream_impact_spans[0]["span_id"] == "s_c"


def test_rca_7_deep_propagation(recon_engine, fail_service, rca_engine):
    """
    TEST 7 — Deep Propagation:
    A (OK) -> B (ERROR) -> C (ERROR) -> D (ERROR)

    Expected: B is identified as root cause candidate, C and D listed in downstream_impact_spans.
    """
    spans = [
        _make_span("s_a", parent_span_id=None, operation_name="A", start_offset_ms=0),
        _make_span("s_b", parent_span_id="s_a", operation_name="B", status_code="ERROR", start_offset_ms=10),
        _make_span("s_c", parent_span_id="s_b", operation_name="C", status_code="ERROR", start_offset_ms=20),
        _make_span("s_d", parent_span_id="s_c", operation_name="D", status_code="ERROR", start_offset_ms=30),
    ]
    graph = recon_engine.reconstruct_from_spans("e7", "t7", spans)
    findings = fail_service.run_detection(graph)

    res = rca_engine.analyze(graph, findings)

    assert res.analysis_status == "ROOT_CAUSE_IDENTIFIED"
    assert len(res.candidates) == 1

    cand = res.candidates[0]
    assert cand.span_id == "s_b"
    assert cand.operation_name == "B"

    downstream_ids = [d["span_id"] for d in cand.downstream_impact_spans]
    assert "s_c" in downstream_ids
    assert "s_d" in downstream_ids
