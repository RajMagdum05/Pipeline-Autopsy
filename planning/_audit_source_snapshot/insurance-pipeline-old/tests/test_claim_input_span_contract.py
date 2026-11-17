"""
Focused Verification Suite for child OpenTelemetry span: 'claim_input'
======================================================================
Verifies:
1. Success Path: All 8 required contract attributes, stage.status == 'success',
   artifact arrays, domain attributes, OK status, and parent link to 'claim_processing'.
2. Lineage Contract: claim_input.output.artifact_ids == document_processing.input.artifact_ids.
3. Failure Path (no documents attached): All 8 required attributes, stage.status == 'failed',
   span status == ERROR, error.type & error.message, empty output.artifact_ids,
   validation.status == 'FAILED', exception recorded, and exception propagated.
4. Safety & PII/Blob Protection: No base64, PDF bytes, raw documents, customer names,
   or bloated payloads in span attributes.
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
    VALIDATION_STATUS,
    DOCUMENTS_TOTAL_COUNT,
    CLAIM_AMOUNT,
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


def create_claim_with_multiple_docs(db, customer_name="Alice Smith", amount=2500.00, doc_count=2):
    """Helper to seed a test claim and multiple attached documents in SQLite."""
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
        doc = Document(
            claim_id=claim.id,
            document_type="Medical Bill",
            file_name=f"bill_{i}.pdf",
            file_path=f"storage/claims/test/bill_{i}.pdf",
            ocr_status="completed",
            ocr_result={
                "status": "success",
                "engine": "pymupdf",
                "pages": [{"page_number": 1, "raw_text": f"Bill #{i}: Treatment charge $1250"}],
            },
        )
        db.add(doc)
        docs.append(doc)
    db.commit()
    for d in docs:
        db.refresh(d)
    return claim, docs


def test_claim_input_success_path_contract(in_memory_telemetry, db_session):
    """
    Proves that on successful claim input ingestion:
    1. 'claim_input' span is created as a child of 'claim_processing'.
    2. All 8 required contract attributes are present with valid types and values.
    3. stage.status == 'success'.
    4. Span status is StatusCode.OK.
    5. input.artifact_ids and output.artifact_ids are lists with proper identifiers.
    6. Diagnostic domain attributes exist: documents.total_count, validation.status, claim.amount.
    7. Data lineage matches downstream: claim_input.output.artifact_ids == document_processing.input.artifact_ids.
    """
    claim, docs = create_claim_with_multiple_docs(db_session, amount=2500.0, doc_count=2)
    exec_id = "EXEC-INPUT-SUCCESS-001"

    mock_extraction = ValidatedExtractionResult(
        claim_id=claim.id,
        execution_id=exec_id,
        extraction_status="VALIDATED",
        ready_for_rule_engine=True,
        patient_name="Alice Smith",
        amount=Decimal("2500.00"),
        diagnosis="Fracture",
    )
    mock_decision = RuleEngineDecision(
        claim_id=claim.id,
        execution_id=exec_id,
        decision="APPROVED",
        decision_reason="Valid claim under policy terms.",
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
    assert len(input_spans) == 1, "Expected exactly one 'claim_input' child span"
    input_span = input_spans[0]

    # 1. Verify Parent Linkage (Child of claim_processing)
    assert input_span.parent is not None, "claim_input must have a parent span"
    assert input_span.parent.span_id == root_span.context.span_id, (
        "claim_input must be a direct child of root span 'claim_processing'"
    )

    # 2. Verify All 8 Required Contract Attributes
    attrs = input_span.attributes
    assert attrs[PIPELINE_NAME] == "insurance-pipeline"
    assert attrs[PIPELINE_VERSION] == "1.0.0"
    assert attrs[EXECUTION_ID] == exec_id
    assert attrs[EXECUTION_ENTITY_ID] == str(claim.id)
    assert attrs[STAGE_NAME] == "claim_input"
    assert attrs[STAGE_STATUS] == "success"

    expected_doc_artifacts = [f"doc_{d.id}" for d in docs]
    assert isinstance(attrs[INPUT_ARTIFACT_IDS], (list, tuple))
    assert list(attrs[INPUT_ARTIFACT_IDS]) == expected_doc_artifacts

    assert isinstance(attrs[OUTPUT_ARTIFACT_IDS], (list, tuple))
    assert list(attrs[OUTPUT_ARTIFACT_IDS]) == expected_doc_artifacts

    # 3. Verify Diagnostic Domain Attributes
    assert attrs[DOCUMENTS_TOTAL_COUNT] == 2
    assert attrs[VALIDATION_STATUS] == "VALIDATED"
    assert attrs[CLAIM_AMOUNT] == 2500.0

    # 4. Verify Span Status
    assert input_span.status.status_code == StatusCode.OK

    # 5. Verify Lineage to document_processing stage
    doc_spans = [s for s in spans if s.name == "document_processing"]
    assert len(doc_spans) == 1
    doc_span = doc_spans[0]
    assert list(input_span.attributes[OUTPUT_ARTIFACT_IDS]) == list(doc_span.attributes[INPUT_ARTIFACT_IDS])


def test_claim_input_failure_path_no_documents(in_memory_telemetry, db_session):
    """
    Proves that when a claim has no documents:
    1. Pipeline raises PipelineExecutionError.
    2. 'claim_input' span is marked with stage.status == 'failed'.
    3. Span status is StatusCode.ERROR.
    4. error.type == 'PipelineExecutionError' and error.message is populated.
    5. input.artifact_ids == [] and output.artifact_ids == [].
    6. validation.status == 'FAILED' and documents.total_count == 0.
    7. Exception is recorded in span events.
    """
    # Create claim with no documents
    claim = Claim(
        customer_name="Bob Jones",
        claim_amount=Decimal("300.00"),
        status="pending",
    )
    db_session.add(claim)
    db_session.commit()
    db_session.refresh(claim)

    exec_id = "EXEC-INPUT-FAIL-001"

    with pytest.raises(PipelineExecutionError) as exc_info:
        run_claim_pipeline(
            claim_id=claim.id,
            db=db_session,
            execution_id=exec_id,
        )

    assert f"No documents found for Claim #{claim.id}." in str(exc_info.value)

    spans = in_memory_telemetry.get_finished_spans()
    input_spans = [s for s in spans if s.name == "claim_input"]
    assert len(input_spans) == 1, "Expected 'claim_input' span even on failure"
    input_span = input_spans[0]

    attrs = input_span.attributes

    # 1. Verify 8 Required Contract Attributes on Failure
    assert attrs[PIPELINE_NAME] == "insurance-pipeline"
    assert attrs[PIPELINE_VERSION] == "1.0.0"
    assert attrs[EXECUTION_ID] == exec_id
    assert attrs[EXECUTION_ENTITY_ID] == str(claim.id)
    assert attrs[STAGE_NAME] == "claim_input"
    assert attrs[STAGE_STATUS] == "failed"

    # 2. Artifacts must be empty lists on validation failure
    assert isinstance(attrs[INPUT_ARTIFACT_IDS], (list, tuple))
    assert list(attrs[INPUT_ARTIFACT_IDS]) == []
    assert isinstance(attrs[OUTPUT_ARTIFACT_IDS], (list, tuple))
    assert list(attrs[OUTPUT_ARTIFACT_IDS]) == []

    # 3. Diagnostic attributes
    assert attrs[VALIDATION_STATUS] == "FAILED"
    assert attrs[DOCUMENTS_TOTAL_COUNT] == 0
    assert attrs[CLAIM_AMOUNT] == 300.0

    # 4. Error attributes and status
    assert attrs[ERROR_TYPE] == "PipelineExecutionError"
    assert attrs[ERROR_MESSAGE] == "Claim input processing failed."
    assert input_span.status.status_code == StatusCode.ERROR

    # 5. Verify exception event recorded
    exception_events = [e for e in input_span.events if e.name == "exception"]
    assert len(exception_events) >= 1
    assert "exception.type" in exception_events[0].attributes
    assert "PipelineExecutionError" in exception_events[0].attributes["exception.type"]


def test_claim_input_safety_and_no_bloat(in_memory_telemetry, db_session):
    """
    Proves that 'claim_input' span attributes never contain PII, base64 data,
    PDF bytes, customer names, or oversized payloads.
    """
    claim, docs = create_claim_with_multiple_docs(
        db_session,
        customer_name="Sensitive Customer Identity",
        amount=5000.0,
        doc_count=1,
    )
    exec_id = "EXEC-SAFETY-INPUT-001"

    mock_extraction = ValidatedExtractionResult(
        claim_id=claim.id,
        execution_id=exec_id,
        extraction_status="VALIDATED",
        ready_for_rule_engine=True,
        patient_name="Sensitive Customer Identity",
        amount=Decimal("5000.00"),
        diagnosis="Consultation",
    )
    mock_decision = RuleEngineDecision(
        claim_id=claim.id,
        execution_id=exec_id,
        decision="APPROVED",
        decision_reason="Eligible consultation.",
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
    input_span = next(s for s in spans if s.name == "claim_input")
    attrs = input_span.attributes

    # Check for PII leakage
    for key, value in attrs.items():
        assert "Sensitive Customer Identity" not in str(value), (
            f"PII customer name leaked in attribute '{key}': {value}"
        )
        assert not str(value).startswith("%PDF-"), f"PDF bytes found in attribute '{key}'"
        assert "JVBERi0" not in str(value), f"Base64 PDF data found in attribute '{key}'"
        assert len(str(value)) < 500, f"Attribute '{key}' is too large ({len(str(value))} chars)"

    # Check that artifact IDs are lightweight ID tokens
    for artifact_id in attrs[INPUT_ARTIFACT_IDS]:
        assert artifact_id.startswith("doc_"), f"Unexpected artifact format: {artifact_id}"
        assert len(artifact_id) < 50
