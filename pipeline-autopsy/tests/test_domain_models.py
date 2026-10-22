import json
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from autopsy.domain import (
    ExecutionStatus,
    SpanKind,
    SpanStatusCode,
    EvidenceType,
    FailureType,
    SeverityLevel,
    IncidentStatus,
    Pipeline,
    Execution,
    Event,
    Span,
    Trace,
    Evidence,
    Failure,
    Incident,
)


def test_pipeline_instantiation_and_serialization():
    pipeline = Pipeline(
        name="multi_agent_code_evaluator",
        description="Autonomous multi-agent test and static code evaluation pipeline",
        version="2.1.0",
        tags=["agentic", "eval", "python"],
        metadata={"owner": "platform-engineering", "max_concurrency": 8},
    )

    assert pipeline.id is not None
    assert pipeline.name == "multi_agent_code_evaluator"
    assert "agentic" in pipeline.tags
    assert pipeline.metadata["max_concurrency"] == 8

    # Serialization test
    dumped_json = pipeline.model_dump_json()
    data = json.loads(dumped_json)
    assert data["name"] == "multi_agent_code_evaluator"


def test_execution_lifecycle():
    execution = Execution(
        pipeline_id="pipe-12345",
        status=ExecutionStatus.RUNNING,
        environment="staging",
        trigger_type="webhook",
        attributes={"commit_sha": "a1b2c3d4", "worker_id": "node-us-east-1a"},
    )

    assert execution.pipeline_id == "pipe-12345"
    assert execution.status == ExecutionStatus.RUNNING
    assert execution.attributes["commit_sha"] == "a1b2c3d4"
    assert execution.started_at is not None


def test_telemetry_models_and_relationships():
    event1 = Event(
        span_id="span-001",
        name="prompt_sent_to_llm",
        attributes={"token_estimate": 450, "model": "gemini-3.7-flash"},
    )

    span1 = Span(
        span_id="span-001",
        trace_id="trace-001",
        service_name="llm-orchestrator",
        operation_name="generate_reasoning",
        kind=SpanKind.CLIENT,
        start_time=datetime.now(timezone.utc),
        status_code=SpanStatusCode.ERROR,
        status_message="HTTP 429: Resource exhausted",
        attributes={"http.status_code": 429, "retry_count": 3},
        events=[event1],
    )

    trace1 = Trace(
        trace_id="trace-001",
        execution_id="exec-999",
        root_span_id="span-001",
        duration_ms=1420.5,
        attributes={"user_id": "user-8871"},
    )

    assert span1.span_id == "span-001"
    assert len(span1.events) == 1
    assert span1.events[0].name == "prompt_sent_to_llm"
    assert span1.status_code == SpanStatusCode.ERROR
    assert trace1.trace_id == "trace-001"


def test_evidence_reference_integrity():
    evidence = Evidence(
        execution_id="exec-999",
        trace_id="trace-001",
        span_id="span-001",
        evidence_type=EvidenceType.LOG_SNIPPET,
        reference_uri="s3://telemetry-evidence-vault/2026/09/exec-999/span-001-raw.log",
        digest="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        summary="Upstream LLM gateway responded with 429 Too Many Requests quota exhaustion",
        metadata={"payload_bytes": 1024, "redacted": True},
    )

    assert evidence.evidence_type == EvidenceType.LOG_SNIPPET
    assert evidence.digest is not None
    assert evidence.metadata["redacted"] is True


def test_failure_and_incident_aggregation():
    evidence_id = "evi-111"

    failure = Failure(
        execution_id="exec-999",
        trace_id="trace-001",
        span_id="span-001",
        failure_type=FailureType.RATE_LIMIT,
        severity=SeverityLevel.HIGH,
        error_class="ResourceExhaustedError",
        description="Daily project quota exceeded during critical generation batch",
        evidence_ids=[evidence_id],
        root_cause_hypothesis="Free-tier concurrency saturation across concurrent worker threads",
    )

    incident = Incident(
        execution_id="exec-999",
        title="High rate-limit failure rate in batch evaluation worker",
        status=IncidentStatus.OPEN,
        severity=SeverityLevel.HIGH,
        summary="Execution #exec-999 failed due to unmitigated rate limiting in downstream API gateway",
        failure_ids=[failure.id],
        diagnosis_reference="autopsy://reports/incidents/inc-2026-09-001.md",
    )

    assert failure.failure_type == FailureType.RATE_LIMIT
    assert failure.id in incident.failure_ids
    assert incident.status == IncidentStatus.OPEN
    assert incident.severity == SeverityLevel.HIGH


def test_validation_error_on_missing_required_fields():
    with pytest.raises(ValidationError):
        # Missing required 'name' field
        Pipeline(description="Missing name")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
