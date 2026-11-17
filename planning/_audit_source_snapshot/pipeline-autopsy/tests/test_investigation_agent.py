import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone

from autopsy.services.agent_service import (
    AutopsyInvestigationAgent,
    AutopsyInvestigationTools,
    InvestigationReport,
)


def _create_mock_tools(
    execution=None,
    trace=None,
    failures=None,
    root_cause=None,
    evidence=None,
    diagnosis=None,
):
    mock = MagicMock(spec=AutopsyInvestigationTools)
    mock.get_execution.return_value = execution
    mock.get_trace.return_value = trace
    mock.get_failures.return_value = failures if failures is not None else []
    mock.get_root_cause.return_value = root_cause if root_cause is not None else {"analysis_status": "NO_FAILURES", "candidates": []}
    mock.get_evidence.return_value = evidence if evidence is not None else []
    mock.generate_diagnosis.return_value = diagnosis if diagnosis is not None else {
        "summary": "Default deterministic diagnosis",
        "affected_component": "Service B",
        "observed_failure": "TimeoutError",
        "root_cause_candidate": "Service B",
        "supporting_evidence": ["TimeoutError observed in Service B"],
        "downstream_impact": [],
        "uncertainty": "SUPPORTED_BY_EVIDENCE",
        "suggested_investigation": ["Inspect logs for Service B"],
        "reasoning_source": "DETERMINISTIC_ENGINE",
    }
    return mock


def test_test1_simple_failure():
    """
    TEST 1 — Simple failure
    A -> B ERROR
    Expected: Agent retrieves B evidence and produces investigation report.
    """
    tools = _create_mock_tools(
        execution={"execution_id": "exec_1", "status": "FAILED", "trace_ids": ["trace_1"]},
        trace={"trace_id": "trace_1", "total_spans": 2},
        failures=[
            {
                "failure_id": "fail_1",
                "span_id": "span_b",
                "failure_type": "SPAN_ERROR_STATUS",
                "description": "TimeoutError in Service B",
                "attributes": {"service_name": "Service B", "operation_name": "process_order"},
            }
        ],
        root_cause={
            "analysis_status": "ROOT_CAUSE_IDENTIFIED",
            "candidates": [
                {
                    "service_name": "Service B",
                    "operation_name": "process_order",
                    "span_id": "span_b",
                    "confidence_state": "supported",
                    "reason": "Direct operational failure",
                }
            ],
        },
        evidence=[
            {"evidence_id": "ev_1", "evidence_type": "EXCEPTION", "summary": "ReadTimeoutError on external API"}
        ],
    )

    agent = AutopsyInvestigationAgent(tools=tools, max_tool_calls=10)
    report = agent.investigate(execution_id="exec_1")

    assert report.investigation_status == "COMPLETED"
    assert report.execution_id == "exec_1"
    assert report.trace_id == "trace_1"
    assert any("Service B" in c for c in report.affected_components)
    assert len(report.observed_failures) > 0
    assert len(report.supporting_evidence) > 0
    assert report.uncertainty == "SUPPORTED_BY_EVIDENCE"
    assert len(report.steps_executed) >= 4


def test_test2_propagated_failure():
    """
    TEST 2 — Propagated failure
    A -> B ERROR -> C dependency failure
    Expected: Agent identifies B as root-cause candidate and C as downstream impact.
    """
    tools = _create_mock_tools(
        execution={"execution_id": "exec_2", "status": "FAILED", "trace_ids": ["trace_2"]},
        trace={"trace_id": "trace_2", "total_spans": 3},
        failures=[
            {
                "failure_id": "fail_b",
                "span_id": "span_b",
                "failure_type": "SPAN_ERROR_STATUS",
                "description": "Database connection timeout in Service B",
                "attributes": {"service_name": "Service B", "operation_name": "db_query"},
            },
            {
                "failure_id": "fail_c",
                "span_id": "span_c",
                "failure_type": "DEPENDENCY_FAILURE",
                "description": "Upstream error in Service C",
                "attributes": {"service_name": "Service C", "operation_name": "fetch_user"},
            },
        ],
        root_cause={
            "analysis_status": "ROOT_CAUSE_IDENTIFIED",
            "candidates": [
                {
                    "service_name": "Service B",
                    "operation_name": "db_query",
                    "span_id": "span_b",
                    "confidence_state": "supported",
                    "reason": "Root cause failure",
                    "downstream_impact_spans": [
                        {"service_name": "Service C", "operation_name": "fetch_user", "span_id": "span_c"}
                    ],
                }
            ],
        },
    )

    agent = AutopsyInvestigationAgent(tools=tools, max_tool_calls=10)
    report = agent.investigate(execution_id="exec_2")

    assert report.investigation_status == "COMPLETED"
    assert any("Service C" in ds for ds in report.downstream_impact)
    assert report.root_cause_candidates[0]["service_name"] == "Service B"


def test_test3_multiple_independent_failures():
    """
    TEST 3 — Multiple independent failures
    A -> B ERROR, A -> C ERROR, no causal relationship
    Expected: Agent preserves both candidates and does not invent a causal relationship.
    """
    tools = _create_mock_tools(
        execution={"execution_id": "exec_3", "status": "FAILED", "trace_ids": ["trace_3"]},
        trace={"trace_id": "trace_3", "total_spans": 3},
        failures=[
            {
                "failure_id": "fail_b",
                "span_id": "span_b",
                "description": "Error in B",
                "attributes": {"service_name": "Service B", "operation_name": "op_b"},
            },
            {
                "failure_id": "fail_c",
                "span_id": "span_c",
                "description": "Error in C",
                "attributes": {"service_name": "Service C", "operation_name": "op_c"},
            },
        ],
        root_cause={
            "analysis_status": "MULTIPLE_CANDIDATES",
            "candidates": [
                {"service_name": "Service B", "operation_name": "op_b", "confidence_state": "possible"},
                {"service_name": "Service C", "operation_name": "op_c", "confidence_state": "possible"},
            ],
        },
        diagnosis={
            "summary": "Encountered multiple independent failures in Service B and Service C",
            "affected_component": "Service B, Service C",
            "observed_failure": "Multiple independent errors",
            "root_cause_candidate": "MULTIPLE_INDEPENDENT_CANDIDATES",
            "supporting_evidence": ["Error B", "Error C"],
            "downstream_impact": [],
            "uncertainty": "POSSIBLE",
            "suggested_investigation": ["Investigate parallel branches"],
        },
    )

    agent = AutopsyInvestigationAgent(tools=tools, max_tool_calls=10)
    report = agent.investigate(execution_id="exec_3")

    assert len(report.root_cause_candidates) == 2
    assert report.uncertainty == "POSSIBLE"


def test_test4_insufficient_evidence():
    """
    TEST 4 — Insufficient evidence
    Expected: Agent reports insufficient evidence.
    """
    tools = _create_mock_tools(
        execution={"execution_id": "exec_4", "status": "FAILED", "trace_ids": ["trace_4"]},
        trace={"trace_id": "trace_4", "total_spans": 1},
        failures=[],
        root_cause={"analysis_status": "INSUFFICIENT_EVIDENCE", "candidates": []},
        diagnosis={
            "summary": "Insufficient telemetry evidence",
            "affected_component": "Unknown",
            "observed_failure": "None",
            "root_cause_candidate": "INSUFFICIENT_EVIDENCE",
            "supporting_evidence": [],
            "downstream_impact": [],
            "uncertainty": "INSUFFICIENT_EVIDENCE",
            "suggested_investigation": ["Check logs"],
        },
    )

    agent = AutopsyInvestigationAgent(tools=tools, max_tool_calls=10)
    report = agent.investigate(execution_id="exec_4")

    assert report.investigation_status == "INSUFFICIENT_EVIDENCE"
    assert report.uncertainty == "INSUFFICIENT_EVIDENCE"


def test_test5_missing_trace_or_span():
    """
    TEST 5 — Missing trace/span
    Expected: Agent handles missing information gracefully without crash.
    """
    tools = _create_mock_tools(execution=None)  # Non-existent execution

    agent = AutopsyInvestigationAgent(tools=tools, max_tool_calls=10)
    report = agent.investigate(execution_id="exec_non_existent")

    assert report.investigation_status == "INSUFFICIENT_EVIDENCE"
    assert "Execution record not found" in report.observed_failures[0]


def test_test6_gemini_unavailable():
    """
    TEST 6 — Gemini unavailable
    Expected: Agent still returns deterministic investigation information.
    """
    tools = _create_mock_tools(
        execution={"execution_id": "exec_6", "status": "FAILED", "trace_ids": ["trace_6"]},
        trace={"trace_id": "trace_6", "total_spans": 2},
        failures=[
            {
                "failure_id": "fail_6",
                "span_id": "span_6",
                "description": "Gateway timeout",
                "attributes": {"service_name": "PaymentService", "operation_name": "charge"},
            }
        ],
        root_cause={
            "analysis_status": "ROOT_CAUSE_IDENTIFIED",
            "candidates": [{"service_name": "PaymentService", "operation_name": "charge", "confidence_state": "supported"}],
        },
        diagnosis={
            "summary": "Deterministic Diagnosis: PaymentService timeout",
            "affected_component": "PaymentService/charge",
            "observed_failure": "Gateway timeout",
            "root_cause_candidate": "PaymentService/charge",
            "supporting_evidence": ["Gateway timeout"],
            "downstream_impact": [],
            "uncertainty": "SUPPORTED_BY_EVIDENCE",
            "suggested_investigation": ["Check PaymentService logs"],
            "reasoning_source": "DETERMINISTIC_ENGINE",
        },
    )

    agent = AutopsyInvestigationAgent(tools=tools, max_tool_calls=10, use_llm=False)
    report = agent.investigate(execution_id="exec_6")

    assert report.investigation_status == "COMPLETED"
    assert report.diagnosis["reasoning_source"] == "DETERMINISTIC_ENGINE"
    assert "PaymentService" in report.diagnosis["affected_component"]


def test_test7_tool_failure():
    """
    TEST 7 — Tool failure
    Expected: Agent terminates safely and reports investigation failure/partial result.
    """
    tools = MagicMock(spec=AutopsyInvestigationTools)
    tools.get_execution.side_effect = RuntimeError("PostgreSQL connection lost")

    agent = AutopsyInvestigationAgent(tools=tools, max_tool_calls=10)
    report = agent.investigate(execution_id="exec_fail")

    assert report.investigation_status == "FAILED"
    assert "Tool failure in get_execution" in report.observed_failures[0]
    assert report.steps_executed[0]["success"] is False


def test_test8_maximum_tool_call_limit():
    """
    TEST 8 — Maximum tool-call limit
    Expected: Agent terminates once the configured investigation limit is reached.
    """
    tools = _create_mock_tools(
        execution={"execution_id": "exec_8", "status": "FAILED", "trace_ids": ["trace_8"]},
        trace={"trace_id": "trace_8", "total_spans": 5},
    )

    # Set very low max_tool_calls to trigger limit immediately
    agent = AutopsyInvestigationAgent(tools=tools, max_tool_calls=2)
    report = agent.investigate(execution_id="exec_8")

    assert report.investigation_status == "FAILED"
    assert "maximum tool-call limit" in report.observed_failures[0]
    assert len(report.steps_executed) == 2
