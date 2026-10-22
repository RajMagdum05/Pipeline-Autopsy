import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from app.telemetry.tracer import init_telemetry
from app.telemetry.attributes import (
    PIPELINE_NAME,
    PIPELINE_VERSION,
    EXECUTION_ID,
    EXECUTION_ENTITY_ID,
    STAGE_NAME,
    STAGE_STATUS,
    INPUT_ARTIFACT_IDS,
    OUTPUT_ARTIFACT_IDS,
)
from app.stages.runner import execute_claim_pipeline


@pytest.fixture
def memory_exporter():
    exporter = InMemorySpanExporter()
    init_telemetry(
        service_name="insurance-pipeline",
        exporter=exporter,
        use_simple_processor=True,
    )
    yield exporter
    exporter.clear()


def test_milestone1_five_stage_trace_generation(memory_exporter):
    """
    Validates Milestone 1:
    1. One root trace: 'insurance_claim_execution'
    2. Five child spans in order:
       - document_processing
       - information_extraction
       - policy_retrieval
       - claim_decision
       - decision_validation
    3. Required contract attributes on every span
    4. Valid parent-child relationships
    """
    claim_id = "CLM-TEST-9001"
    exec_id = "EXEC-MILESTONE1-TEST"

    result = execute_claim_pipeline(
        claim_id=claim_id,
        raw_document_ids=["DOC-A", "DOC-B"],
        execution_id=exec_id,
    )

    assert result["status"] == "COMPLETED"
    assert result["verdict"] in ["APPROVED", "REJECTED"]
    assert result["execution_id"] == exec_id
    assert result["claim_id"] == claim_id

    # Retrieve all captured spans in memory
    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 6, f"Expected 1 root span + 5 child spans = 6 total, got {len(spans)}"

    span_map = {s.name: s for s in spans}

    # Verify Root Span
    assert "insurance_claim_execution" in span_map
    root_span = span_map["insurance_claim_execution"]
    assert root_span.parent is None, "insurance_claim_execution must be the root span"

    # Verify 5 Child Spans
    expected_stages = [
        "document_processing",
        "information_extraction",
        "policy_retrieval",
        "claim_decision",
        "decision_validation",
    ]

    for stage in expected_stages:
        assert stage in span_map, f"Missing child stage: {stage}"
        child_span = span_map[stage]

        # Verify parent-child link
        assert child_span.parent.span_id == root_span.context.span_id, (
            f"Stage {stage} must have root span as direct parent"
        )
        assert child_span.context.trace_id == root_span.context.trace_id, (
            f"Stage {stage} must share the same trace ID with root"
        )

        # Verify 8 Required Contract Attributes
        attrs = child_span.attributes
        assert attrs[PIPELINE_NAME] == "insurance-pipeline"
        assert attrs[PIPELINE_VERSION] == "1.0.0"
        assert attrs[EXECUTION_ID] == exec_id
        assert attrs[EXECUTION_ENTITY_ID] == claim_id
        assert attrs[STAGE_NAME] == stage
        assert attrs[STAGE_STATUS] == "success"
        assert INPUT_ARTIFACT_IDS in attrs
        assert OUTPUT_ARTIFACT_IDS in attrs
