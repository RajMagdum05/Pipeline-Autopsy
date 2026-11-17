"""
Focused Verification Suite for child OpenTelemetry span: 'document_processing'
=============================================================================
Verifies:
1. Success Path: All 8 required contract attributes, stage.status == 'success',
   artifact arrays, domain attributes, OK status, and parent link to 'claim_processing'.
2. Lineage Contract:
   claim_input.output.artifact_ids
     == document_processing.input.artifact_ids
     -> document_processing.output.artifact_ids
3. Failure Path (controlled OCR / dependency failure):
   All 8 required attributes, stage.status == 'failed', span status == ERROR,
   error.type & error.message, preserved input.artifact_ids, exception event recorded,
   and exception propagation without swallowed errors.
4. Safety & PII/Blob Protection: No base64, PDF bytes, raw documents, customer names,
   or bloated payloads in span attributes.
"""

from decimal import Decimal
from unittest.mock import patch, MagicMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from opentelemetry.trace import StatusCode

from app.database import Base
from app.models.claim import Claim
from app.models.document import Document
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
    VALIDATION_STATUS,
    DOCUMENTS_TOTAL_COUNT,
)
from app.pipeline_services.orchestrator.pipeline_orchestrator import run_claim_pipeline
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


def create_claim_with_documents(db, customer_name="Jane Doe", amount=1800.00, doc_count=2, prefill_ocr=True):
    """Helper to seed a test claim and attached documents in SQLite."""
    claim = Claim(
        customer_name=customer_name,
        claim_amount=Decimal(str(amount)),
        status="pending",
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)

    docs = []
    for i in range(1, doc_count + 1):
        ocr_data = {
            "status": "success",
            "engine": "pymupdf",
            "pages": [{"page_number": 1, "raw_text": f"Medical Bill #{i}: $900"}],
        } if prefill_ocr else None

        doc = Document(
            claim_id=claim.id,
            document_type="Medical Bill",
            file_name=f"bill_{i}.pdf",
            file_path=f"storage/claims/test/bill_{i}.pdf",
            ocr_status="completed" if prefill_ocr else "pending",
            ocr_result=ocr_data,
        )
        db.add(doc)
        docs.append(doc)

    db.commit()
    for d in docs:
        db.refresh(d)
    return claim, docs


def test_document_processing_success_path_contract(in_memory_telemetry, db_session):
    """
    Proves that on successful document processing:
    1. 'document_processing' span is created as a child of 'claim_processing'.
    2. All 8 required contract attributes are present with valid types and values.
    3. stage.status == 'success'.
    4. Span status is StatusCode.OK.
    5. input.artifact_ids matches claim_input.output.artifact_ids.
    6. output.artifact_ids contains OCR output artifact IDs.
    7. Diagnostic domain attributes exist: documents.total_count, ocr.total_pages, validation.status.
    8. execution.id and execution.entity_id are present.
    """
    claim, docs = create_claim_with_documents(db_session, amount=1800.0, doc_count=2)
    exec_id = "EXEC-DOCPROC-SUCCESS-001"

    mock_extraction = ValidatedExtractionResult(
        claim_id=claim.id,
        execution_id=exec_id,
        extraction_status="VALIDATED",
        ready_for_rule_engine=True,
        patient_name="Jane Doe",
        amount=Decimal("1800.00"),
        diagnosis="Gastritis",
    )
    mock_decision = RuleEngineDecision(
        claim_id=claim.id,
        execution_id=exec_id,
        decision="APPROVED",
        decision_reason="Covered condition.",
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
    assert len(root_spans) == 1
    root_span = root_spans[0]

    input_spans = [s for s in spans if s.name == "claim_input"]
    assert len(input_spans) == 1
    input_span = input_spans[0]

    doc_spans = [s for s in spans if s.name == "document_processing"]
    assert len(doc_spans) == 1, "Expected exactly one 'document_processing' span"
    doc_span = doc_spans[0]
    ocr_span = next(s for s in spans if s.name == "ocr" and s.parent.span_id == doc_span.context.span_id)
    validation_span = next(
        s for s in spans
        if s.name == "ocr_validation" and s.parent.span_id == doc_span.context.span_id
    )
    per_document_validation_span = next(s for s in spans if s.name == "ocr_validation.document")

    # 1. Verify Parent Linkage (Child of claim_processing)
    assert doc_span.parent is not None, "document_processing must have a parent span"
    assert doc_span.parent.span_id == root_span.context.span_id, (
        "document_processing must be a direct child of root span 'claim_processing'"
    )

    # 2. Verify All 8 Required Contract Attributes
    attrs = doc_span.attributes
    assert attrs[PIPELINE_NAME] == "insurance-pipeline"
    assert attrs[PIPELINE_VERSION] == "1.0.0"
    assert attrs[EXECUTION_ID] == exec_id
    assert attrs[EXECUTION_ENTITY_ID] == str(claim.id)
    assert attrs[STAGE_NAME] == "document_processing"
    assert attrs[STAGE_STATUS] == "success"

    # 3. Verify Artifact Lineage Handoff
    expected_input_artifacts = [f"doc_{d.id}" for d in docs]
    expected_output_artifacts = [f"art_ocr_{d.id}" for d in docs]

    assert list(attrs[INPUT_ARTIFACT_IDS]) == expected_input_artifacts
    assert list(attrs[INPUT_ARTIFACT_IDS]) == list(input_span.attributes[OUTPUT_ARTIFACT_IDS]), (
        "document_processing.input.artifact_ids must match claim_input.output.artifact_ids"
    )

    assert list(attrs[OUTPUT_ARTIFACT_IDS]) == expected_output_artifacts

    # 4. Diagnostic domain attributes
    assert attrs[DOCUMENTS_TOTAL_COUNT] == 2
    assert attrs["ocr.total_pages"] == 2
    assert attrs[VALIDATION_STATUS] == "VALIDATED"

    # 5. Span Status
    assert doc_span.status.status_code == StatusCode.OK

    for span, name, inputs, outputs in (
        (ocr_span, "ocr", expected_input_artifacts, expected_output_artifacts),
        (validation_span, "ocr_validation", expected_output_artifacts, [f"art_ocr_val_{d.id}" for d in docs]),
    ):
        assert span.attributes[PIPELINE_NAME] == "insurance-pipeline"
        assert span.attributes[PIPELINE_VERSION] == "1.0.0"
        assert span.attributes[EXECUTION_ID] == exec_id
        assert span.attributes[EXECUTION_ENTITY_ID] == str(claim.id)
        assert span.attributes[STAGE_NAME] == name
        assert span.attributes[STAGE_STATUS] == "success"
        assert list(span.attributes[INPUT_ARTIFACT_IDS]) == inputs
        assert list(span.attributes[OUTPUT_ARTIFACT_IDS]) == outputs
        assert span.status.status_code == StatusCode.OK

    per_doc_attrs = per_document_validation_span.attributes
    assert per_doc_attrs[PIPELINE_NAME] == "insurance-pipeline"
    assert per_doc_attrs[PIPELINE_VERSION] == "1.0.0"
    assert per_doc_attrs[EXECUTION_ID] == exec_id
    assert per_doc_attrs[EXECUTION_ENTITY_ID] == str(claim.id)
    assert per_doc_attrs[STAGE_NAME] == "ocr_validation"
    assert per_doc_attrs[STAGE_STATUS] == "success"
    assert list(per_doc_attrs[INPUT_ARTIFACT_IDS]) == [f"art_ocr_{docs[0].id}"]
    assert list(per_doc_attrs[OUTPUT_ARTIFACT_IDS]) == [f"art_ocr_val_{docs[0].id}"]
    assert per_document_validation_span.status.status_code == StatusCode.OK


def test_document_processing_failure_path_ocr_error(in_memory_telemetry, db_session):
    """
    Proves that when OCR/document processing fails:
    1. An unhandled exception in document processing is caught by stage_span.
    2. 'document_processing' span is marked with stage.status == 'failed'.
    3. Span status is StatusCode.ERROR.
    4. error.type and error.message are recorded accurately.
    5. input.artifact_ids remains present and preserved.
    6. Exception is recorded in span events.
    7. Exception propagates to caller without being silently swallowed.
    """
    # Create claim with document needing OCR processing (ocr_result is None)
    claim, docs = create_claim_with_documents(db_session, amount=999.0, doc_count=1, prefill_ocr=False)
    exec_id = "EXEC-DOCPROC-FAIL-001"

    simulated_error_msg = "Corrupted PDF stream encountered during OCR rasterization."

    with patch(
        "app.pipeline_services.ocr.OCRApplicationService.process_document",
        side_effect=RuntimeError(simulated_error_msg),
    ):
        with pytest.raises(RuntimeError) as exc_info:
            run_claim_pipeline(
                claim_id=claim.id,
                db=db_session,
                execution_id=exec_id,
            )

    assert simulated_error_msg in str(exc_info.value)

    spans = in_memory_telemetry.get_finished_spans()
    doc_spans = [s for s in spans if s.name == "document_processing"]
    assert len(doc_spans) == 1, "Expected 'document_processing' span to be created and exported"
    doc_span = doc_spans[0]
    ocr_span = next(s for s in spans if s.name == "ocr")

    attrs = doc_span.attributes

    # 1. Verify 8 Required Contract Attributes on Failure
    assert attrs[PIPELINE_NAME] == "insurance-pipeline"
    assert attrs[PIPELINE_VERSION] == "1.0.0"
    assert attrs[EXECUTION_ID] == exec_id
    assert attrs[EXECUTION_ENTITY_ID] == str(claim.id)
    assert attrs[STAGE_NAME] == "document_processing"
    assert attrs[STAGE_STATUS] == "failed"

    # 2. Input artifacts preserved, output artifacts empty on pre-completion failure
    assert list(attrs[INPUT_ARTIFACT_IDS]) == [f"doc_{docs[0].id}"]
    assert list(attrs[OUTPUT_ARTIFACT_IDS]) == []

    # 3. Diagnostic domain attributes
    assert attrs[DOCUMENTS_TOTAL_COUNT] == 1

    # 4. Error attributes and status
    assert attrs[ERROR_TYPE] == "RuntimeError"
    assert attrs[ERROR_MESSAGE] == "Document processing failed."
    assert doc_span.status.status_code == StatusCode.ERROR

    # 5. Exception event recorded
    exception_events = [e for e in doc_span.events if e.name == "exception"]
    assert len(exception_events) >= 1
    assert "RuntimeError" in exception_events[0].attributes["exception.type"]

    assert ocr_span.attributes[STAGE_STATUS] == "failed"
    assert ocr_span.attributes[ERROR_TYPE] == "RuntimeError"
    assert ocr_span.attributes[ERROR_MESSAGE] == "OCR processing failed."
    assert ocr_span.status.status_code == StatusCode.ERROR
    assert list(ocr_span.attributes[INPUT_ARTIFACT_IDS]) == [f"doc_{docs[0].id}"]
    assert list(ocr_span.attributes[OUTPUT_ARTIFACT_IDS]) == []


def test_ocr_validation_failure_path_contract(in_memory_telemetry, db_session):
    claim, docs = create_claim_with_documents(db_session, doc_count=1)
    exec_id = "EXEC-OCR-VALIDATION-FAIL-001"
    failure_message = "OCR validation dependency failed."

    with patch(
        "app.pipeline_services.orchestrator.pipeline_orchestrator.OCRQualityValidator.validate_document",
        side_effect=RuntimeError(failure_message),
    ):
        with pytest.raises(RuntimeError, match=failure_message):
            run_claim_pipeline(claim_id=claim.id, db=db_session, execution_id=exec_id)

    spans = in_memory_telemetry.get_finished_spans()
    validation_span = next(s for s in spans if s.name == "ocr_validation")
    attrs = validation_span.attributes

    assert attrs[PIPELINE_NAME] == "insurance-pipeline"
    assert attrs[PIPELINE_VERSION] == "1.0.0"
    assert attrs[EXECUTION_ID] == exec_id
    assert attrs[EXECUTION_ENTITY_ID] == str(claim.id)
    assert attrs[STAGE_NAME] == "ocr_validation"
    assert attrs[STAGE_STATUS] == "failed"
    assert list(attrs[INPUT_ARTIFACT_IDS]) == [f"art_ocr_{docs[0].id}"]
    assert list(attrs[OUTPUT_ARTIFACT_IDS]) == []
    assert attrs[ERROR_TYPE] == "RuntimeError"
    assert attrs[ERROR_MESSAGE] == "OCR quality validation failed."
    assert validation_span.status.status_code == StatusCode.ERROR
    assert any(event.name == "exception" for event in validation_span.events)


def test_document_processing_safety_and_no_bloat(in_memory_telemetry, db_session):
    """
    Proves that 'document_processing' span attributes never contain PII, base64 data,
    PDF bytes, customer names, or oversized payloads.
    """
    claim, docs = create_claim_with_documents(
        db_session,
        customer_name="Secret Healthcare Patient",
        amount=3400.0,
        doc_count=1,
    )
    exec_id = "EXEC-SAFETY-DOCPROC-001"

    mock_extraction = ValidatedExtractionResult(
        claim_id=claim.id,
        execution_id=exec_id,
        extraction_status="VALIDATED",
        ready_for_rule_engine=True,
        patient_name="Secret Healthcare Patient",
        amount=Decimal("3400.00"),
        diagnosis="Physical Therapy",
    )
    mock_decision = RuleEngineDecision(
        claim_id=claim.id,
        execution_id=exec_id,
        decision="APPROVED",
        decision_reason="Valid claim.",
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
        run_claim_pipeline(
            claim_id=claim.id,
            db=db_session,
            execution_id=exec_id,
        )

    spans = in_memory_telemetry.get_finished_spans()
    doc_span = next(s for s in spans if s.name == "document_processing")
    attrs = doc_span.attributes

    # Check for PII leakage and payload bloating
    for key, value in attrs.items():
        assert "Secret Healthcare Patient" not in str(value), (
            f"PII customer name leaked in attribute '{key}': {value}"
        )
        assert not str(value).startswith("%PDF-"), f"PDF bytes found in attribute '{key}'"
        assert "JVBERi0" not in str(value), f"Base64 PDF data found in attribute '{key}'"
        assert len(str(value)) < 500, f"Attribute '{key}' is too large ({len(str(value))} chars)"

    # Check artifact reference format
    for artifact_id in attrs[INPUT_ARTIFACT_IDS]:
        assert artifact_id.startswith("doc_"), f"Unexpected input artifact ID: {artifact_id}"
    for artifact_id in attrs[OUTPUT_ARTIFACT_IDS]:
        assert artifact_id.startswith("art_ocr_"), f"Unexpected output artifact ID: {artifact_id}"
