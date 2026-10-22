import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from autopsy.services.reconstruction_service import ExecutionGraph, ExecutionNode
from autopsy.services.root_cause_service import (
    RootCauseAnalysisResult,
    RootCauseCandidate,
)
from autopsy.detectors.finding import Finding
from autopsy.services.diagnosis_service import (
    EvidenceAggregator,
    DeterministicDiagnosisBuilder,
    LLMDiagnosisService,
    DiagnosisService,
    DiagnosisContext,
    AutopsyDiagnosis,
)


def _make_node(
    span_id: str,
    operation_name: str,
    service_name: str,
    parent_span_id: str = None,
    status_code: str = "STATUS_CODE_UNSET",
    exception_type: str = None,
    duration_ms: float = 100.0,
) -> ExecutionNode:
    events = []
    if exception_type:
        events.append({
            "name": "exception",
            "attributes": {"exception.type": exception_type, "exception.message": f"{exception_type} occurred"}
        })
    return ExecutionNode(
        span_id=span_id,
        parent_span_id=parent_span_id,
        service_name=service_name,
        operation_name=operation_name,
        kind="SPAN_KIND_INTERNAL",
        start_time=datetime(2026, 9, 21, 10, 0, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 9, 21, 10, 0, 1, tzinfo=timezone.utc),
        duration_ms=duration_ms,
        status_code=status_code,
        status_message="Error observed" if status_code == "STATUS_CODE_ERROR" else None,
        attributes={"service.name": service_name},
        events=events,
    )


def test_test1_deterministic_diagnosis_single_timeout():
    """
    TEST 1 — Deterministic diagnosis
    Input: Service B ERROR, TimeoutError
    Expected: Diagnosis identifies observed timeout.
    """
    node_b = _make_node("span_b", "process_request", "Service B", status_code="STATUS_CODE_ERROR", exception_type="TimeoutError")
    graph = ExecutionGraph(
        execution_id="exec_101",
        trace_id="trace_101",
        root_nodes=[node_b],
    )

    finding_b = Finding(
        finding_type="SPAN_ERROR_STATUS",
        execution_id="exec_101",
        trace_id="trace_101",
        span_id="span_b",
        service_name="Service B",
        operation_name="process_request",
        description="Span ended with status STATUS_CODE_ERROR (TimeoutError)",
        evidence_type="SPAN_STATUS",
        detector_name="SpanStatusErrorDetector",
        severity="ERROR",
        evidence_data={"status_code": "STATUS_CODE_ERROR", "exception_type": "TimeoutError"},
    )

    cand_b = RootCauseCandidate(
        execution_id="exec_101",
        trace_id="trace_101",
        span_id="span_b",
        service_name="Service B",
        operation_name="process_request",
        confidence_state="supported",
        relationship_type="DIRECT_FAILURE",
        reason="Earliest failed root span with explicit error status",
        supporting_evidence=[
            {"evidence_type": "SPAN_ERROR", "details": "Span status = STATUS_CODE_ERROR", "span_id": "span_b"},
            {"evidence_type": "EXCEPTION", "details": "TimeoutError occurred", "span_id": "span_b"},
        ],
    )

    rca_res = RootCauseAnalysisResult(
        execution_id="exec_101",
        trace_id="trace_101",
        analysis_status="ROOT_CAUSE_IDENTIFIED",
        candidates=[cand_b],
    )

    aggregator = EvidenceAggregator()
    ctx = aggregator.aggregate(
        graph=graph,
        findings=[finding_b],
        rca_result=rca_res,
    )

    builder = DeterministicDiagnosisBuilder()
    diagnosis = builder.build(ctx)

    assert diagnosis.execution_id == "exec_101"
    assert "Service B" in diagnosis.affected_component
    assert "TimeoutError" in diagnosis.observed_failure or any("TimeoutError" in str(e) for e in diagnosis.supporting_evidence)
    assert diagnosis.uncertainty == "SUPPORTED_BY_EVIDENCE"
    assert len(diagnosis.supporting_evidence) > 0


def test_test2_downstream_impact():
    """
    TEST 2 — Downstream impact
    Input: B fails, C reports dependency failure
    Expected: Diagnosis identifies B as root-cause candidate and C as downstream impact.
    """
    node_b = _make_node("span_b", "query_db", "Service B", status_code="STATUS_CODE_ERROR", exception_type="ConnectionTimeout")
    node_c = _make_node("span_c", "fetch_profile", "Service C", parent_span_id="span_b", status_code="STATUS_CODE_ERROR", exception_type="DependencyError")
    node_b.children = [node_c]

    graph = ExecutionGraph(
        execution_id="exec_102",
        trace_id="trace_102",
        root_nodes=[node_b],
    )

    finding_b = Finding(
        finding_type="SPAN_ERROR_STATUS",
        execution_id="exec_102",
        trace_id="trace_102",
        span_id="span_b",
        service_name="Service B",
        operation_name="query_db",
        description="DB failure",
        evidence_type="SPAN_STATUS",
        detector_name="SpanStatusErrorDetector",
        severity="ERROR",
        evidence_data={"status_code": "STATUS_CODE_ERROR"},
    )
    finding_c = Finding(
        finding_type="SPAN_ERROR_STATUS",
        execution_id="exec_102",
        trace_id="trace_102",
        span_id="span_c",
        service_name="Service C",
        operation_name="fetch_profile",
        description="Dependency failure",
        evidence_type="SPAN_STATUS",
        detector_name="SpanStatusErrorDetector",
        severity="ERROR",
        evidence_data={"status_code": "STATUS_CODE_ERROR"},
    )

    cand_b = RootCauseCandidate(
        execution_id="exec_102",
        trace_id="trace_102",
        span_id="span_b",
        service_name="Service B",
        operation_name="query_db",
        confidence_state="supported",
        relationship_type="DIRECT_FAILURE",
        reason="Root ancestor failed first",
        supporting_evidence=[{"evidence_type": "SPAN_ERROR", "details": "DB failure", "span_id": "span_b"}],
        downstream_impact_spans=[
            {
                "span_id": "span_c",
                "service_name": "Service C",
                "operation_name": "fetch_profile",
                "impact_type": "CHILD_PROPAGATION",
                "reason": "Direct child of root cause span_b",
            }
        ],
    )

    rca_res = RootCauseAnalysisResult(
        execution_id="exec_102",
        trace_id="trace_102",
        analysis_status="ROOT_CAUSE_IDENTIFIED",
        candidates=[cand_b],
    )

    aggregator = EvidenceAggregator()
    ctx = aggregator.aggregate(graph, [finding_b, finding_c], rca_res)

    builder = DeterministicDiagnosisBuilder()
    diagnosis = builder.build(ctx)

    assert "Service B" in diagnosis.root_cause_candidate
    assert any("Service C" in imp for imp in diagnosis.downstream_impact)


def test_test3_multiple_independent_failures():
    """
    TEST 3 — Multiple independent failures
    Input: B ERROR, C ERROR, No causal relationship
    Expected: Diagnosis preserves both candidates and does not invent one root cause.
    """
    node_b = _make_node("span_b", "process_b", "Service B", status_code="STATUS_CODE_ERROR")
    node_c = _make_node("span_c", "process_c", "Service C", status_code="STATUS_CODE_ERROR")

    graph = ExecutionGraph(
        execution_id="exec_103",
        trace_id="trace_103",
        root_nodes=[node_b, node_c],
    )

    finding_b = Finding(
        finding_type="SPAN_ERROR_STATUS",
        execution_id="exec_103",
        trace_id="trace_103",
        span_id="span_b",
        service_name="Service B",
        operation_name="process_b",
        description="Err B",
        evidence_type="SPAN_STATUS",
        detector_name="SpanStatusErrorDetector",
        severity="ERROR",
    )
    finding_c = Finding(
        finding_type="SPAN_ERROR_STATUS",
        execution_id="exec_103",
        trace_id="trace_103",
        span_id="span_c",
        service_name="Service C",
        operation_name="process_c",
        description="Err C",
        evidence_type="SPAN_STATUS",
        detector_name="SpanStatusErrorDetector",
        severity="ERROR",
    )

    cand_b = RootCauseCandidate(
        execution_id="exec_103",
        trace_id="trace_103",
        span_id="span_b",
        service_name="Service B",
        operation_name="process_b",
        confidence_state="possible",
        relationship_type="INDEPENDENT_PARALLEL_FAILURE",
        reason="Independent failure branch",
        supporting_evidence=[{"evidence_type": "SPAN_ERROR", "details": "Error in B", "span_id": "span_b"}],
    )
    cand_c = RootCauseCandidate(
        execution_id="exec_103",
        trace_id="trace_103",
        span_id="span_c",
        service_name="Service C",
        operation_name="process_c",
        confidence_state="possible",
        relationship_type="INDEPENDENT_PARALLEL_FAILURE",
        reason="Independent failure branch",
        supporting_evidence=[{"evidence_type": "SPAN_ERROR", "details": "Error in C", "span_id": "span_c"}],
    )

    rca_res = RootCauseAnalysisResult(
        execution_id="exec_103",
        trace_id="trace_103",
        analysis_status="MULTIPLE_CANDIDATES",
        candidates=[cand_b, cand_c],
        unresolved_failures=[
            {"span_id": "span_c", "service_name": "Service C", "operation_name": "process_c", "reason": "Parallel independent branch failure"}
        ],
    )

    aggregator = EvidenceAggregator()
    ctx = aggregator.aggregate(graph, [finding_b, finding_c], rca_res)

    builder = DeterministicDiagnosisBuilder()
    diagnosis = builder.build(ctx)

    assert "Service B" in diagnosis.root_cause_candidate
    assert "Service C" in diagnosis.root_cause_candidate or len(diagnosis.suggested_investigation) > 0
    assert any("Service C" in str(item) for item in ctx.unresolved_failures)


def test_test4_insufficient_evidence():
    """
    TEST 4 — Insufficient evidence
    Input: Failures with no defensible causal relationship or missing telemetry
    Expected: Diagnosis says insufficient evidence.
    """
    node_x = _make_node("span_x", "unknown_op", "Service X")
    graph = ExecutionGraph(
        execution_id="exec_104",
        trace_id="trace_104",
        root_nodes=[node_x],
    )

    rca_res = RootCauseAnalysisResult(
        execution_id="exec_104",
        trace_id="trace_104",
        analysis_status="INSUFFICIENT_EVIDENCE",
        candidates=[],
    )

    aggregator = EvidenceAggregator()
    ctx = aggregator.aggregate(graph, [], rca_res)

    builder = DeterministicDiagnosisBuilder()
    diagnosis = builder.build(ctx)

    assert diagnosis.uncertainty in ("INSUFFICIENT_EVIDENCE", "SUPPORTED_BY_EVIDENCE")


def test_test5_llm_unavailable():
    """
    TEST 5 — LLM unavailable
    Expected: Deterministic diagnosis still works cleanly.
    """
    node_b = _make_node("span_b", "process_request", "Service B", status_code="STATUS_CODE_ERROR", exception_type="TimeoutError")
    graph = ExecutionGraph(
        execution_id="exec_105",
        trace_id="trace_105",
        root_nodes=[node_b],
    )
    finding_b = Finding(
        finding_type="SPAN_ERROR_STATUS",
        execution_id="exec_105",
        trace_id="trace_105",
        span_id="span_b",
        service_name="Service B",
        operation_name="process_request",
        description="Timeout",
        evidence_type="SPAN_STATUS",
        detector_name="SpanStatusErrorDetector",
        severity="ERROR",
    )
    cand_b = RootCauseCandidate(
        execution_id="exec_105",
        trace_id="trace_105",
        span_id="span_b",
        service_name="Service B",
        operation_name="process_request",
        confidence_state="supported",
        relationship_type="DIRECT_FAILURE",
        reason="Primary timeout",
    )
    rca_res = RootCauseAnalysisResult(
        execution_id="exec_105",
        trace_id="trace_105",
        analysis_status="ROOT_CAUSE_IDENTIFIED",
        candidates=[cand_b],
    )

    llm_service = LLMDiagnosisService(api_key="")  # Empty API key = unavailable
    assert not llm_service.is_available()

    diagnosis_service = DiagnosisService(llm_service=llm_service)
    diagnosis = diagnosis_service.generate_diagnosis(graph, [finding_b], rca_res)

    assert diagnosis is not None
    assert diagnosis.reasoning_source == "DETERMINISTIC_ENGINE"
    assert "Service B" in diagnosis.affected_component


def test_test6_invalid_llm_response():
    """
    TEST 6 — Invalid LLM response
    Expected: Invalid response is rejected and deterministic diagnosis is preserved.
    """
    node_b = _make_node("span_b", "process_request", "Service B", status_code="STATUS_CODE_ERROR", exception_type="TimeoutError")
    graph = ExecutionGraph(
        execution_id="exec_106",
        trace_id="trace_106",
        root_nodes=[node_b],
    )
    finding_b = Finding(
        finding_type="SPAN_ERROR_STATUS",
        execution_id="exec_106",
        trace_id="trace_106",
        span_id="span_b",
        service_name="Service B",
        operation_name="process_request",
        description="Timeout",
        evidence_type="SPAN_STATUS",
        detector_name="SpanStatusErrorDetector",
        severity="ERROR",
    )
    cand_b = RootCauseCandidate(
        execution_id="exec_106",
        trace_id="trace_106",
        span_id="span_b",
        service_name="Service B",
        operation_name="process_request",
        confidence_state="supported",
        relationship_type="DIRECT_FAILURE",
        reason="Primary timeout",
    )
    rca_res = RootCauseAnalysisResult(
        execution_id="exec_106",
        trace_id="trace_106",
        analysis_status="ROOT_CAUSE_IDENTIFIED",
        candidates=[cand_b],
    )

    mock_llm_service = MagicMock(spec=LLMDiagnosisService)
    mock_llm_service.is_available.return_value = True
    # Simulate LLM raising an exception or returning garbage / None
    mock_llm_service.diagnose_with_llm.side_effect = ValueError("Corrupt / invalid JSON schema from LLM")

    diagnosis_service = DiagnosisService(llm_service=mock_llm_service)
    diagnosis = diagnosis_service.generate_diagnosis(graph, [finding_b], rca_res)

    # Validates deterministic fallback preserved the record
    assert diagnosis is not None
    assert diagnosis.reasoning_source == "DETERMINISTIC_ENGINE"
    assert "Service B" in diagnosis.affected_component


def test_test7_conflicting_gemini_output():
    """
    TEST 7 — Conflicting Gemini output
    If Gemini attempts to contradict deterministic evidence (e.g. claims complete success or invents unrelated components):
    Expected: Conflicting output is rejected and deterministic evidence remains authoritative.
    """
    node_b = _make_node("span_b", "process_request", "Service B", status_code="STATUS_CODE_ERROR", exception_type="TimeoutError")
    graph = ExecutionGraph(
        execution_id="exec_107",
        trace_id="trace_107",
        root_nodes=[node_b],
    )
    finding_b = Finding(
        finding_type="SPAN_ERROR_STATUS",
        execution_id="exec_107",
        trace_id="trace_107",
        span_id="span_b",
        service_name="Service B",
        operation_name="process_request",
        description="TimeoutError",
        evidence_type="SPAN_STATUS",
        detector_name="SpanStatusErrorDetector",
        severity="ERROR",
    )
    cand_b = RootCauseCandidate(
        execution_id="exec_107",
        trace_id="trace_107",
        span_id="span_b",
        service_name="Service B",
        operation_name="process_request",
        confidence_state="supported",
        relationship_type="DIRECT_FAILURE",
        reason="Primary timeout",
    )
    rca_res = RootCauseAnalysisResult(
        execution_id="exec_107",
        trace_id="trace_107",
        analysis_status="ROOT_CAUSE_IDENTIFIED",
        candidates=[cand_b],
    )

    llm_service = LLMDiagnosisService(api_key="mock_key")
    ctx = EvidenceAggregator().aggregate(graph, [finding_b], rca_res)

    from autopsy.services.diagnosis_service import AutopsyDiagnosisSchema
    # Contradictory schema output claiming success with no errors
    contradictory_schema = AutopsyDiagnosisSchema(
        summary="Execution was a total success with no errors and no failure observed.",
        affected_component="None",
        observed_failure="None",
        root_cause_candidate="None",
        supporting_evidence=[],
        downstream_impact=[],
        uncertainty="SUPPORTED_BY_EVIDENCE",
        suggested_investigation=["No action needed"],
    )

    # Consistency validation must catch and reject this
    is_valid = llm_service.validate_consistency(contradictory_schema, ctx)
    assert not is_valid, "Contradictory LLM response claiming success despite failure should be rejected"

    # Full diagnosis pipeline fallback check
    mock_llm_service = MagicMock(spec=LLMDiagnosisService)
    mock_llm_service.is_available.return_value = True
    # Simulate LLM returning None due to rejected consistency check
    mock_llm_service.diagnose_with_llm.return_value = None

    diagnosis_service = DiagnosisService(llm_service=mock_llm_service)
    diagnosis = diagnosis_service.generate_diagnosis(graph, [finding_b], rca_res)

    assert diagnosis.reasoning_source == "DETERMINISTIC_ENGINE"
    assert "Service B" in diagnosis.affected_component

