import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from autopsy.db import (
    Base,
    PipelineModel,
    ExecutionModel,
    TraceModel,
    SpanModel,
    EventModel,
    EvidenceModel,
    FailureModel,
    IncidentModel,
    get_database_url,
)


@pytest.fixture(scope="module")
def db_session():
    """
    Creates connected test database session using PostgreSQL (or in-memory SQLite if offline).
    """
    db_url = get_database_url()
    engine_args = {}
    if isinstance(db_url, str) and db_url.startswith("sqlite"):
        engine_args["connect_args"] = {"check_same_thread": False}

    test_engine = create_engine(db_url, **engine_args)
    Base.metadata.create_all(bind=test_engine)

    TestSession = sessionmaker(bind=test_engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


def test_full_database_persistence_flow(db_session):
    # 1. Create Pipeline
    pipeline_id = str(uuid.uuid4())
    pipeline = PipelineModel(
        id=pipeline_id,
        name="autonomous_rag_evaluation_pipeline",
        description="Generalized RAG & LLM agent observability pipeline",
        version="1.2.0",
        tags=["rag", "llm", "vector_search"],
        metadata_json={"top_k": 5, "similarity_threshold": 0.85},
    )
    db_session.add(pipeline)
    db_session.commit()

    # Verify Pipeline saved
    saved_pipe = db_session.query(PipelineModel).filter_by(id=pipeline_id).first()
    assert saved_pipe is not None
    assert saved_pipe.name == "autonomous_rag_evaluation_pipeline"
    assert saved_pipe.metadata_json["top_k"] == 5

    # 2. Create Execution
    exec_id = str(uuid.uuid4())
    execution = ExecutionModel(
        id=exec_id,
        pipeline_id=pipeline_id,
        status="RUNNING",
        started_at=datetime.now(timezone.utc),
        environment="staging",
        trigger_type="api_request",
        attributes={"batch_size": 32, "model_endpoint": "gemini-3.7-flash"},
    )
    db_session.add(execution)
    db_session.commit()

    # Verify Execution relationship
    saved_exec = db_session.query(ExecutionModel).filter_by(id=exec_id).first()
    assert saved_exec is not None
    assert saved_exec.pipeline.name == "autonomous_rag_evaluation_pipeline"

    # 3. Create OpenTelemetry Trace & Spans (Dynamic hex IDs for isolation)
    trace_hex_id = uuid.uuid4().hex
    root_span_hex_id = uuid.uuid4().hex[:16]
    child_span_hex_id = uuid.uuid4().hex[:16]

    trace = TraceModel(
        trace_id=trace_hex_id,
        execution_id=exec_id,
        root_span_id=root_span_hex_id,
        start_time=datetime.now(timezone.utc),
        attributes={"user_agent": "Python-OTLP-SDK"},
    )
    db_session.add(trace)
    db_session.commit()

    # Create Root Span
    root_span = SpanModel(
        span_id=root_span_hex_id,
        trace_id=trace_hex_id,
        parent_span_id=None,
        service_name="rag-eval-service",
        operation_name="query_vector_store",
        kind="CLIENT",
        start_time=datetime.now(timezone.utc),
        status_code="OK",
        attributes={"db.system": "pgvector", "vector.dimension": 768},
    )

    # Create Child Span
    child_span = SpanModel(
        span_id=child_span_hex_id,
        trace_id=trace_hex_id,
        parent_span_id=root_span_hex_id,
        service_name="llm-reasoner",
        operation_name="gemini_generate_response",
        kind="INTERNAL",
        start_time=datetime.now(timezone.utc),
        status_code="ERROR",
        status_message="HTTP 429: Resource exhausted",
        attributes={"llm.provider": "google", "retry_attempt": 3},
    )
    db_session.add_all([root_span, child_span])
    db_session.commit()

    # 4. Create Event under Child Span
    event = EventModel(
        span_db_id=child_span.id,
        span_id=child_span_hex_id,
        timestamp=datetime.now(timezone.utc),
        name="quota_exceeded_warning",
        attributes={"quota_metric": "generate_content_free_tier_requests"},
    )
    db_session.add(event)
    db_session.commit()

    # 5. Create Evidence
    evidence_id = str(uuid.uuid4())
    evidence = EvidenceModel(
        id=evidence_id,
        execution_id=exec_id,
        trace_id=trace_hex_id,
        span_id=child_span_hex_id,
        evidence_type="LOG_SNIPPET",
        reference_uri=f"s3://autopsy-evidence-store/traces/{trace_hex_id}/span_err.json",
        digest="9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        summary="LLM Gateway returned 429 Resource Exhausted during inference",
        metadata_json={"http_code": 429, "retry_after_seconds": 32},
    )
    db_session.add(evidence)
    db_session.commit()

    # 6. Create Failure
    failure_id = str(uuid.uuid4())
    failure = FailureModel(
        id=failure_id,
        execution_id=exec_id,
        trace_id=trace_hex_id,
        span_id=child_span_hex_id,
        failure_type="RATE_LIMIT",
        severity="HIGH",
        error_class="ResourceExhausted",
        description="Downstream LLM API quota depleted",
        evidence_ids=[evidence_id],
        root_cause_hypothesis="Unthrottled concurrent requests overwhelmed free tier quota",
        attributes={"impacted_users": 1},
    )
    db_session.add(failure)
    db_session.commit()

    # 7. Create Incident
    incident = IncidentModel(
        execution_id=exec_id,
        title="Quota Exhaustion Failure in Vector Search Pipeline",
        status="OPEN",
        severity="HIGH",
        summary="Execution failed due to RateLimit error on gemini_generate_response span",
        failure_ids=[failure_id],
        diagnosis_reference=f"autopsy://diagnosis/incidents/inc-{trace_hex_id[:8]}.json",
    )
    db_session.add(incident)
    db_session.commit()

    # 8. Query & Verify End-to-End Persistence and Relationships
    query_exec = db_session.query(ExecutionModel).filter_by(id=exec_id).first()
    assert query_exec is not None
    assert len(query_exec.traces) == 1
    assert query_exec.traces[0].trace_id == trace_hex_id

    query_spans = db_session.query(SpanModel).filter_by(trace_id=trace_hex_id).all()
    assert len(query_spans) == 2

    # Verify Child Span DAG hierarchy and Event relationship
    err_span = db_session.query(SpanModel).filter_by(span_id=child_span_hex_id).first()
    assert err_span.parent_span_id == root_span_hex_id
    assert len(err_span.events) == 1
    assert err_span.events[0].name == "quota_exceeded_warning"

    # Verify Failure & Evidence
    query_failure = db_session.query(FailureModel).filter_by(id=failure_id).first()
    assert query_failure is not None
    assert evidence_id in query_failure.evidence_ids

    # Verify Incident
    query_incident = db_session.query(IncidentModel).filter_by(execution_id=exec_id).first()
    assert query_incident is not None
    assert failure_id in query_incident.failure_ids
    assert query_incident.status == "OPEN"
