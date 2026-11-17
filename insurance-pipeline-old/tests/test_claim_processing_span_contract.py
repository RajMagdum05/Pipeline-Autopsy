"""
Focused Verification Suite for root OpenTelemetry span: 'claim_processing'
==========================================================================
Verifies:
1. Success Path: All 8 required contract attributes, status == 'success',
   artifact arrays, domain attributes, and OK span status.
2. Failure Path (Early failure / Claim not found): All 8 required attributes,
   status == 'failed', span status == ERROR, error.type & error.message,
   empty artifact lists, and exception propagation.
3. Failure Path (Mid-execution failure): Preserves input.artifact_ids and
   partial output.artifact_ids, error recording, and exception propagation.
4. Safety & PII/Blob Protection: No base64, PDF bytes, raw documents, prompts,
   customer names, or oversized attributes.
"""

from decimal import Decimal
from unittest.mock import patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from opentelemetry.trace import StatusCode
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.database import Base
from app.models.claim import Claim
from app.models.document import Document
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
    ERROR_TYPE,
    ERROR_MESSAGE,
    DECISION_RESULT,
)
from app.pipeline_services.orchestrator.pipeline_orchestrator import (
    run_claim_pipeline,
    PipelineExecutionError,
)
from app.schemas import ValidatedExtractionResult, RuleEngineDecision


@pytest.fixture(scope="function")
def db_session():
    """Provides an isolated in-memory SQLite database session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_test_claim_with_document(db, customer_name="Alice Smith", amount=1500.00):
    """Helper to seed a test claim and attached document in SQLite."""
    claim = Claim(
        customer_name=customer_name,
        claim_amount=Decimal(str(amount)),
        status="pending",
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)

    doc = Document(
        claim_id=claim.id,
        document_type="Medical Bill",
        file_name="invoice.pdf",
        file_path="storage/claims/test/invoice.pdf",
        ocr_status="completed",
        ocr_result={
            "status": "success",
            "engine": "pymupdf",
            "pages": [{"page_number": 1, "raw_text": "Invoice #101: Appendectomy $1500"}],
        },
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return claim, doc


def test_claim_processing_success_path_contract(in_memory_telemetry, db_session):
    """
    Proves that on success:
    1. 'claim_processing' root span is created.
    2. All 8 required contract attributes are present with valid types and values.
    3. stage.status == 'success'.
    4. Span status is OK.
    5. input.artifact_ids and output.artifact_ids are lists with proper identifiers.
    6. Expected diagnostic domain attributes exist.
    """
    claim, doc = create_test_claim_with_document(db_session)
    exec_id = "EXEC-SUCCESS-001"

    mock_extraction = ValidatedExtractionResult(
        claim_id=claim.id,
        execution_id=exec_id,
        extraction_status="VALIDATED",
        ready_for_rule_engine=True,
        patient_name="Alice Smith",
        amount=Decimal("1500.00"),
        diagnosis="Appendicitis",
    )
    mock_decision = RuleEngineDecision(
        claim_id=claim.id,
        execution_id=exec_id,
        decision="APPROVED",
        decision_reason="Eligible surgical procedure within limits.",
        total_rules=8,
        passed_rules=8,
        failed_rules=0,
        missing_data_rules=0,
    )

    with patch(
        "app.pipeline_services.orchestrator.pipeline_orchestrator.extract_claim_from_validated_ocr",
        return_value=mock_extraction,
    ), patch(
        "app.pipeline_services.orchestrator.pipeline_orchestrator.evaluate_claim_rules",
        return_value=mock_decision,
    ):
        result = run_claim_pipeline(
            claim_id=claim.id,
            db=db_session,
            execution_id=exec_id,
        )

    assert result["status"] == "APPROVED"

    spans = in_memory_telemetry.get_finished_spans()
    root_spans = [s for s in spans if s.name == "claim_processing"]
    assert len(root_spans) == 1, "Expected exactly one 'claim_processing' root span"
    root_span = root_spans[0]

    # 1. Verify Root Identity (no parent)
    assert root_span.parent is None, "claim_processing must be the root span"

    # 2. Verify All 8 Required Contract Attributes
    attrs = root_span.attributes
    assert attrs[PIPELINE_NAME] == "insurance-pipeline"
    assert attrs[PIPELINE_VERSION] == "1.0.0"
    assert attrs[EXECUTION_ID] == exec_id
    assert attrs[EXECUTION_ENTITY_ID] == str(claim.id)
    assert attrs[STAGE_NAME] == "claim_processing"
    assert attrs[STAGE_STATUS] == "success"

    assert isinstance(attrs[INPUT_ARTIFACT_IDS], (list, tuple))
    assert f"doc_{doc.id}" in attrs[INPUT_ARTIFACT_IDS]

    assert isinstance(attrs[OUTPUT_ARTIFACT_IDS], (list, tuple))
    assert len(attrs[OUTPUT_ARTIFACT_IDS]) > 0
    assert f"art_ocr_claim_{claim.id}" in attrs[OUTPUT_ARTIFACT_IDS]
    assert f"art_decision_claim_{claim.id}" in attrs[OUTPUT_ARTIFACT_IDS]

    # 3. Verify Span Status
    assert root_span.status.status_code == StatusCode.OK

    # 4. Verify Useful Diagnostic Attributes
    assert attrs["claim.amount"] == 1500.00
    assert attrs["documents.total_count"] == 1
    assert attrs[DECISION_RESULT] == "APPROVED"

    # 5. Verify Removal of Deprecated / Duplicate Attributes
    assert "claim_id" not in attrs, "'claim_id' should be removed in favor of execution.entity_id"
    assert "execution.status" not in attrs, "'execution.status' should be removed in favor of stage.status"
    assert "final_decision" not in attrs, "'final_decision' duplicate should be removed"
    assert "claim.initial_status" not in attrs, "'claim.initial_status' should be removed"

    spans = in_memory_telemetry.get_finished_spans()
    decision_span = next(s for s in spans if s.name == "temporary_business_decision")
    final_span = next(s for s in spans if s.name == "final_result")
    for span, stage_name, expected_input, expected_output in (
        (decision_span, "temporary_business_decision", [f"art_decision_claim_{claim.id}"], [f"art_decision_claim_{claim.id}"]),
        (final_span, "final_result", [f"art_decision_claim_{claim.id}"], [f"art_ocr_claim_{claim.id}", f"art_entities_claim_{claim.id}", f"art_decision_claim_{claim.id}"]),
    ):
        assert span.attributes[PIPELINE_NAME] == "insurance-pipeline"
        assert span.attributes[PIPELINE_VERSION] == "1.0.0"
        assert span.attributes[EXECUTION_ID] == exec_id
        assert span.attributes[EXECUTION_ENTITY_ID] == str(claim.id)
        assert span.attributes[STAGE_NAME] == stage_name
        assert span.attributes[STAGE_STATUS] == "success"
        assert list(span.attributes[INPUT_ARTIFACT_IDS]) == expected_input
        assert list(span.attributes[OUTPUT_ARTIFACT_IDS]) == expected_output
        assert span.status.status_code == StatusCode.OK


def test_business_decision_commit_failure_marks_stage_failed(in_memory_telemetry, db_session):
    claim, _ = create_test_claim_with_document(db_session)
    exec_id = "EXEC-DECISION-COMMIT-FAIL"
    mock_extraction = ValidatedExtractionResult(
        claim_id=claim.id,
        execution_id=exec_id,
        extraction_status="VALIDATED",
        ready_for_rule_engine=True,
        patient_name="Alice Smith",
        amount=Decimal("1500.00"),
        diagnosis="Appendicitis",
    )
    mock_decision = RuleEngineDecision(
        claim_id=claim.id,
        execution_id=exec_id,
        decision="APPROVED",
        decision_reason="Eligible claim.",
        total_rules=5,
        passed_rules=5,
        failed_rules=0,
        missing_data_rules=0,
    )

    with patch(
        "app.pipeline_services.orchestrator.pipeline_orchestrator.extract_claim_from_validated_ocr",
        return_value=mock_extraction,
    ), patch(
        "app.pipeline_services.orchestrator.pipeline_orchestrator.evaluate_claim_rules",
        return_value=mock_decision,
    ), patch.object(db_session, "commit", side_effect=RuntimeError("commit failed")):
        with pytest.raises(RuntimeError, match="commit failed"):
            run_claim_pipeline(claim_id=claim.id, db=db_session, execution_id=exec_id)

    decision_span = next(
        s for s in in_memory_telemetry.get_finished_spans()
        if s.name == "temporary_business_decision"
    )
    assert decision_span.attributes[STAGE_STATUS] == "failed"
    assert decision_span.attributes[ERROR_TYPE] == "RuntimeError"
    assert decision_span.attributes[ERROR_MESSAGE] == "Business decision update failed."
    assert list(decision_span.attributes[INPUT_ARTIFACT_IDS]) == [f"art_decision_claim_{claim.id}"]
    assert list(decision_span.attributes[OUTPUT_ARTIFACT_IDS]) == []
    assert decision_span.status.status_code == StatusCode.ERROR


def test_claim_processing_failure_path_claim_not_found(in_memory_telemetry, db_session):
    """
    Proves that on early failure (claim not found in DB):
    1. 'claim_processing' root span is still created.
    2. All 8 required contract attributes exist.
    3. stage.status == 'failed'.
    4. Span status is ERROR.
    5. error.type and error.message exist.
    6. input.artifact_ids and output.artifact_ids are empty lists (not omitted).
    7. PipelineExecutionError propagates to caller.
    """
    exec_id = "EXEC-FAIL-NOTFOUND"
    missing_id = 88888

    with pytest.raises(PipelineExecutionError) as exc_info:
        run_claim_pipeline(
            claim_id=missing_id,
            db=db_session,
            execution_id=exec_id,
        )

    assert f"Claim #{missing_id} not found" in str(exc_info.value)

    spans = in_memory_telemetry.get_finished_spans()
    root_spans = [s for s in spans if s.name == "claim_processing"]
    assert len(root_spans) == 1
    root_span = root_spans[0]

    attrs = root_span.attributes
    assert attrs[PIPELINE_NAME] == "insurance-pipeline"
    assert attrs[PIPELINE_VERSION] == "1.0.0"
    assert attrs[EXECUTION_ID] == exec_id
    assert attrs[EXECUTION_ENTITY_ID] == str(missing_id)
    assert attrs[STAGE_NAME] == "claim_processing"
    assert attrs[STAGE_STATUS] == "failed"

    # Artifact IDs must be present as empty lists rather than omitted
    assert isinstance(attrs[INPUT_ARTIFACT_IDS], (list, tuple))
    assert len(attrs[INPUT_ARTIFACT_IDS]) == 0
    assert isinstance(attrs[OUTPUT_ARTIFACT_IDS], (list, tuple))
    assert len(attrs[OUTPUT_ARTIFACT_IDS]) == 0

    # Error attributes & span status
    assert root_span.status.status_code == StatusCode.ERROR
    assert attrs[ERROR_TYPE] == "PipelineExecutionError"
    assert attrs[ERROR_MESSAGE] == "Claim processing failed."

    # Verify exception event recorded
    exception_events = [e for e in root_span.events if e.name == "exception"]
    assert len(exception_events) >= 1


def test_claim_processing_failure_path_mid_execution(in_memory_telemetry, db_session):
    """
    Proves that on failure occurring during execution (e.g. Rule Engine crash):
    1. stage.status == 'failed'.
    2. Span status is ERROR.
    3. input.artifact_ids preserves the documents discovered before failure.
    4. output.artifact_ids preserves artifacts produced by preceding completed stages.
    5. error.type and error.message reflect the exact unhandled exception.
    6. Exception propagates to caller.
    """
    claim, doc = create_test_claim_with_document(db_session)
    exec_id = "EXEC-FAIL-MID"

    mock_extraction = ValidatedExtractionResult(
        claim_id=claim.id,
        execution_id=exec_id,
        extraction_status="VALIDATED",
        ready_for_rule_engine=True,
        patient_name="Alice Smith",
        amount=Decimal("1500.00"),
        diagnosis="Appendicitis",
    )

    with patch(
        "app.pipeline_services.orchestrator.pipeline_orchestrator.extract_claim_from_validated_ocr",
        return_value=mock_extraction,
    ), patch(
        "app.pipeline_services.orchestrator.pipeline_orchestrator.evaluate_claim_rules",
        side_effect=RuntimeError("Deterministic rule evaluation internal failure"),
    ):
        with pytest.raises(RuntimeError) as exc_info:
            run_claim_pipeline(
                claim_id=claim.id,
                db=db_session,
                execution_id=exec_id,
            )

    assert "Deterministic rule evaluation internal failure" in str(exc_info.value)

    spans = in_memory_telemetry.get_finished_spans()
    root_spans = [s for s in spans if s.name == "claim_processing"]
    assert len(root_spans) == 1
    root_span = root_spans[0]

    attrs = root_span.attributes
    assert attrs[STAGE_STATUS] == "failed"
    assert root_span.status.status_code == StatusCode.ERROR
    assert attrs[ERROR_TYPE] == "RuntimeError"
    assert attrs[ERROR_MESSAGE] == "Claim processing failed."

    # Input artifacts preserved
    assert f"doc_{doc.id}" in attrs[INPUT_ARTIFACT_IDS]

    # Output artifacts preserved from completed stages prior to failure
    assert isinstance(attrs[OUTPUT_ARTIFACT_IDS], (list, tuple))
    assert f"art_ocr_{doc.id}" in attrs[OUTPUT_ARTIFACT_IDS]
    assert f"art_entities_claim_{claim.id}" in attrs[OUTPUT_ARTIFACT_IDS]


def test_claim_processing_safety_and_no_bloat(in_memory_telemetry, db_session):
    """
    Proves that no PDF bytes, base64 strings, PII, prompt text, or oversized payloads
    appear anywhere in the 'claim_processing' root span attributes.
    """
    claim, _ = create_test_claim_with_document(db_session, customer_name="Confidential Patient Doe")
    exec_id = "EXEC-SAFETY-001"

    mock_extraction = ValidatedExtractionResult(
        claim_id=claim.id,
        execution_id=exec_id,
        extraction_status="VALIDATED",
        ready_for_rule_engine=True,
        patient_name="Confidential Patient Doe",
        amount=Decimal("1500.00"),
        diagnosis="Appendicitis",
    )
    mock_decision = RuleEngineDecision(
        claim_id=claim.id,
        execution_id=exec_id,
        decision="APPROVED",
        decision_reason="Eligible",
        total_rules=8,
        passed_rules=8,
        failed_rules=0,
        missing_data_rules=0,
    )

    with patch(
        "app.pipeline_services.orchestrator.pipeline_orchestrator.extract_claim_from_validated_ocr",
        return_value=mock_extraction,
    ), patch(
        "app.pipeline_services.orchestrator.pipeline_orchestrator.evaluate_claim_rules",
        return_value=mock_decision,
    ):
        run_claim_pipeline(claim_id=claim.id, db=db_session, execution_id=exec_id)

    spans = in_memory_telemetry.get_finished_spans()
    root_span = next(s for s in spans if s.name == "claim_processing")

    for key, value in root_span.attributes.items():
        val_str = str(value)
        # 1. No PII customer name
        assert "Confidential Patient Doe" not in val_str, f"PII detected in attribute '{key}'"

        # 2. No PDF binary or base64 marker
        assert "%PDF" not in val_str, f"PDF byte header found in attribute '{key}'"
        assert ";base64," not in val_str, f"Base64 marker found in attribute '{key}'"

        # 3. No massive prompt or model dump (all attributes should be compact identifiers/scalars)
        assert len(val_str) < 500, f"Attribute '{key}' exceeded safety length limit ({len(val_str)} chars)"
