"""
Focused Verification Suite for child OpenTelemetry span: 'information_extraction'
==================================================================================
Verifies:
1. Success Path: All 8 required contract attributes, stage.status == 'success',
   artifact arrays, domain attributes, OK status, and parent link to 'claim_processing'.
2. Lineage Contract:
   document_processing.output.artifact_ids
     == information_extraction.input.artifact_ids
     -> information_extraction.output.artifact_ids
     == [f"art_entities_claim_{claim_id}"] (usable as rule_engine.input.artifact_ids)
3. Failure Path (controlled Gemini API / extraction failure):
   All 8 required attributes, stage.status == 'failed', span status == ERROR,
   error.type & error.message, preserved input.artifact_ids, exception event recorded,
   and exception propagation without swallowed errors.
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
    RETRY_COUNT,
)
from app.pipeline_services.orchestrator.pipeline_orchestrator import run_claim_pipeline
from app.pipeline_services.extraction.extraction_service import (
    extract_claim_from_validated_ocr,
    validate_and_finalize_extraction,
    ExtractionAPIError,
    ExtractionValidationError,
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


def create_claim_with_documents(db, customer_name="Alice Brown", amount=2200.00, doc_count=2):
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
        doc = Document(
            claim_id=claim.id,
            document_type="Medical Bill",
            file_name=f"invoice_{i}.pdf",
            file_path=f"storage/claims/test/invoice_{i}.pdf",
            ocr_status="completed",
            ocr_result={
                "status": "success",
                "engine": "pymupdf",
                "pages": [
                    {
                        "page_number": 1,
                        "raw_text": f"Patient: Alice Brown\nHospital: General Clinic\nDiagnosis: Pneumonia\nTreatment: Antibiotics\nDate: 2026-09-01\nAmount: $1100.00\nInvoice #{i}",
                    }
                ],
            },
        )
        db.add(doc)
        docs.append(doc)

    db.commit()
    for d in docs:
        db.refresh(d)
    return claim, docs


def test_information_extraction_success_path_contract(in_memory_telemetry, db_session):
    """
    Proves that on successful information extraction:
    1. 'information_extraction' span is created as a child of 'claim_processing'.
    2. All 8 required contract attributes are present with valid types and values.
    3. stage.status == 'success' (changed from 'completed').
    4. Span status is StatusCode.OK.
    5. input.artifact_ids matches document_processing.output.artifact_ids.
    6. output.artifact_ids == [f"art_entities_claim_{claim.id}"], usable by rule_engine.
    7. Diagnostic attributes exist: extraction.model, extraction.status, extraction.extracted_fields, retry.count.
    8. execution.id and execution.entity_id are present.
    """
    claim, docs = create_claim_with_documents(db_session, amount=2200.0, doc_count=2)
    exec_id = "EXEC-INFEXT-SUCCESS-001"

    mock_decision = RuleEngineDecision(
        claim_id=claim.id,
        execution_id=exec_id,
        decision="APPROVED",
        decision_reason="Valid treatment covered under policy.",
        total_rules=8,
        passed_rules=8,
        failed_rules=0,
        missing_data_rules=0,
    )

    with patch.dict("os.environ", {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}), patch(
        "app.pipeline_services.orchestrator.pipeline_orchestrator.evaluate_claim_rules",
        return_value=mock_decision,
    ):
        result = run_claim_pipeline(
            claim_id=claim.id,
            db=db_session,
            execution_id=exec_id,
            allow_extraction_fallback=True,  # Uses deterministic offline extraction parser
        )

    assert result["status"] == "APPROVED"

    spans = in_memory_telemetry.get_finished_spans()
    root_spans = [s for s in spans if s.name == "claim_processing"]
    assert len(root_spans) == 1
    root_span = root_spans[0]

    doc_spans = [s for s in spans if s.name == "document_processing"]
    assert len(doc_spans) == 1
    doc_span = doc_spans[0]

    ext_spans = [s for s in spans if s.name == "information_extraction"]
    assert len(ext_spans) == 1, "Expected exactly one 'information_extraction' span"
    ext_span = ext_spans[0]

    # 1. Verify Parent Linkage (Child of claim_processing)
    assert ext_span.parent is not None, "information_extraction must have a parent span"
    assert ext_span.parent.span_id == root_span.context.span_id, (
        "information_extraction must be a direct child of root span 'claim_processing'"
    )

    # 2. Verify All 8 Required Contract Attributes
    attrs = ext_span.attributes
    assert attrs[PIPELINE_NAME] == "insurance-pipeline"
    assert attrs[PIPELINE_VERSION] == "1.0.0"
    assert attrs[EXECUTION_ID] == exec_id
    assert attrs[EXECUTION_ENTITY_ID] == str(claim.id)
    assert attrs[STAGE_NAME] == "information_extraction"
    assert attrs[STAGE_STATUS] == "success"  # Strictly 'success', never 'completed'

    # 3. Verify Artifact Lineage Handoff
    expected_input_artifacts = [f"art_ocr_{d.id}" for d in docs]
    expected_output_artifacts = [f"art_entities_claim_{claim.id}"]

    assert list(attrs[INPUT_ARTIFACT_IDS]) == expected_input_artifacts
    assert list(attrs[INPUT_ARTIFACT_IDS]) == list(doc_span.attributes[OUTPUT_ARTIFACT_IDS]), (
        "information_extraction.input.artifact_ids must match document_processing.output.artifact_ids"
    )

    assert list(attrs[OUTPUT_ARTIFACT_IDS]) == expected_output_artifacts

    # 4. Diagnostic attributes
    assert attrs["extraction.model"] == "offline_fallback"
    assert attrs["extraction.status"] == "FALLBACK"
    assert isinstance(attrs["extraction.extracted_fields"], (list, tuple))
    assert "diagnosis" in attrs["extraction.extracted_fields"]
    assert attrs[RETRY_COUNT] == 0

    # 5. Span Status
    assert ext_span.status.status_code == StatusCode.OK


def test_information_extraction_failure_path_api_error(in_memory_telemetry, db_session):
    """
    Proves that when Information Extraction fails:
    1. 'information_extraction' span is marked with stage.status == 'failed'.
    2. Span status is StatusCode.ERROR.
    3. error.type and error.message are recorded accurately.
    4. input.artifact_ids remains present and preserved.
    5. Exception is recorded in span events.
    6. Exception propagates without being swallowed.
    """
    claim, docs = create_claim_with_documents(db_session, amount=1500.0, doc_count=1)
    exec_id = "EXEC-INFEXT-FAIL-001"

    simulated_error_msg = "Gemini API resource quota exhausted across all preferred models."

    with patch.dict("os.environ", {"GEMINI_API_KEY": "test-api-key"}), patch(
        "google.genai.Client"
    ) as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.models.generate_content.side_effect = RuntimeError(simulated_error_msg)

        with pytest.raises(ExtractionAPIError) as exc_info:
            run_claim_pipeline(
                claim_id=claim.id,
                db=db_session,
                execution_id=exec_id,
                allow_extraction_fallback=False,  # Fallback disabled to test failure path
            )

    assert "Gemini API execution failed across all models" in str(exc_info.value)

    spans = in_memory_telemetry.get_finished_spans()
    ext_spans = [s for s in spans if s.name == "information_extraction"]
    assert len(ext_spans) == 1, "Expected 'information_extraction' span to be created and exported"
    ext_span = ext_spans[0]

    attrs = ext_span.attributes

    # 1. Verify 8 Required Contract Attributes on Failure
    assert attrs[PIPELINE_NAME] == "insurance-pipeline"
    assert attrs[PIPELINE_VERSION] == "1.0.0"
    assert attrs[EXECUTION_ID] == exec_id
    assert attrs[EXECUTION_ENTITY_ID] == str(claim.id)
    assert attrs[STAGE_NAME] == "information_extraction"
    assert attrs[STAGE_STATUS] == "failed"

    # 2. Input artifacts preserved, output artifacts empty on failure
    expected_input_artifacts = [f"art_ocr_{docs[0].id}"]
    assert list(attrs[INPUT_ARTIFACT_IDS]) == expected_input_artifacts
    assert list(attrs[OUTPUT_ARTIFACT_IDS]) == []

    # 3. Error attributes and status
    assert attrs[ERROR_TYPE] == "ExtractionAPIError"
    assert attrs[ERROR_MESSAGE] == "Information extraction failed."
    assert ext_span.status.status_code == StatusCode.ERROR

    # 4. Exception event recorded
    exception_events = [e for e in ext_span.events if e.name == "exception"]
    assert len(exception_events) >= 1
    assert "ExtractionAPIError" in exception_events[0].attributes["exception.type"]


def test_information_extraction_safety_and_no_bloat(in_memory_telemetry, db_session):
    """
    Proves that 'information_extraction' span attributes never contain PII, base64 data,
    PDF bytes, customer names, prompts, or oversized payloads.
    """
    claim, docs = create_claim_with_documents(
        db_session,
        customer_name="Highly Confidential Patient",
        amount=4500.0,
        doc_count=1,
    )
    exec_id = "EXEC-SAFETY-INFEXT-001"

    mock_decision = RuleEngineDecision(
        claim_id=claim.id,
        execution_id=exec_id,
        decision="APPROVED",
        decision_reason="Valid claim under emergency terms.",
        total_rules=8,
        passed_rules=8,
        failed_rules=0,
        missing_data_rules=0,
    )

    with patch(
        "app.pipeline_services.orchestrator.pipeline_orchestrator.evaluate_claim_rules",
        return_value=mock_decision,
    ):
        run_claim_pipeline(
            claim_id=claim.id,
            db=db_session,
            execution_id=exec_id,
            allow_extraction_fallback=True,
        )

    spans = in_memory_telemetry.get_finished_spans()
    ext_span = next(s for s in spans if s.name == "information_extraction")
    attrs = ext_span.attributes

    # Check for PII leakage, prompt leakage, and payload bloating
    for key, value in attrs.items():
        assert "Highly Confidential Patient" not in str(value), (
            f"PII customer name leaked in attribute '{key}': {value}"
        )
        assert not str(value).startswith("%PDF-"), f"PDF bytes found in attribute '{key}'"
        assert "JVBERi0" not in str(value), f"Base64 PDF data found in attribute '{key}'"
        assert "You are an expert medical billing AI" not in str(value), (
            f"Extraction prompt leaked in attribute '{key}'"
        )
        assert len(str(value)) < 500, f"Attribute '{key}' is too large ({len(str(value))} chars)"

    # Check artifact reference format
    for artifact_id in attrs[INPUT_ARTIFACT_IDS]:
        assert artifact_id.startswith("art_ocr_"), f"Unexpected input artifact ID: {artifact_id}"
    for artifact_id in attrs[OUTPUT_ARTIFACT_IDS]:
        assert artifact_id.startswith("art_entities_"), f"Unexpected output artifact ID: {artifact_id}"


def test_extraction_validation_span_contract_success_and_failure(in_memory_telemetry):
    execution_id = "EXEC-EXTVAL-CONTRACT-001"
    claim_id = 77

    validate_and_finalize_extraction(
        raw_response={"patient_name": "Private Patient", "amount": "125.00"},
        claim_id=claim_id,
        execution_id=execution_id,
        extraction_model="test_model",
    )

    success_span = next(s for s in in_memory_telemetry.get_finished_spans() if s.name == "extraction_validation")
    attrs = success_span.attributes
    assert attrs[PIPELINE_NAME] == "insurance-pipeline"
    assert attrs[PIPELINE_VERSION] == "1.0.0"
    assert attrs[EXECUTION_ID] == execution_id
    assert attrs[EXECUTION_ENTITY_ID] == str(claim_id)
    assert attrs[STAGE_NAME] == "extraction_validation"
    assert attrs[STAGE_STATUS] == "success"
    assert list(attrs[INPUT_ARTIFACT_IDS]) == []
    assert list(attrs[OUTPUT_ARTIFACT_IDS]) == [f"art_entities_claim_{claim_id}"]
    assert success_span.status.status_code == StatusCode.OK

    in_memory_telemetry.clear()
    with pytest.raises(ExtractionValidationError):
        validate_and_finalize_extraction(
            raw_response={"amount": "Highly Confidential Patient"},
            claim_id=claim_id,
            execution_id=execution_id,
            extraction_model="test_model",
        )

    failure_span = next(s for s in in_memory_telemetry.get_finished_spans() if s.name == "extraction_validation")
    attrs = failure_span.attributes
    assert attrs[PIPELINE_NAME] == "insurance-pipeline"
    assert attrs[PIPELINE_VERSION] == "1.0.0"
    assert attrs[EXECUTION_ID] == execution_id
    assert attrs[EXECUTION_ENTITY_ID] == str(claim_id)
    assert attrs[STAGE_NAME] == "extraction_validation"
    assert attrs[STAGE_STATUS] == "failed"
    assert list(attrs[INPUT_ARTIFACT_IDS]) == []
    assert list(attrs[OUTPUT_ARTIFACT_IDS]) == []
    assert attrs[ERROR_TYPE] == "ExtractionValidationError"
    assert attrs[ERROR_MESSAGE] == "Extraction validation failed."
    assert failure_span.status.status_code == StatusCode.ERROR
    assert any(event.name == "exception" for event in failure_span.events)
    assert all("Highly Confidential Patient" not in str(value) for value in attrs.values())


def test_full_pipeline_trace_contract_and_artifact_lineage(in_memory_telemetry, db_session):
    claim, docs = create_claim_with_documents(
        db_session,
        customer_name="Private Patient Trace Check",
        amount=2200.0,
        doc_count=1,
    )
    exec_id = "EXEC-AUTOPSY-TRACE-001"

    with patch.dict("os.environ", {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}):
        run_claim_pipeline(
            claim_id=claim.id,
            db=db_session,
            execution_id=exec_id,
            allow_extraction_fallback=True,
        )

    spans = in_memory_telemetry.get_finished_spans()
    required = (
        PIPELINE_NAME, PIPELINE_VERSION, EXECUTION_ID, EXECUTION_ENTITY_ID,
        STAGE_NAME, STAGE_STATUS, INPUT_ARTIFACT_IDS, OUTPUT_ARTIFACT_IDS,
    )
    for span in spans:
        attrs = span.attributes
        for key in required:
            assert key in attrs, f"{span.name} is missing required attribute {key}"
        assert attrs[PIPELINE_NAME] == "insurance-pipeline"
        assert attrs[PIPELINE_VERSION] == "1.0.0"
        assert attrs[EXECUTION_ID] == exec_id
        assert attrs[EXECUTION_ENTITY_ID] == str(claim.id)
        assert attrs[STAGE_STATUS] in {"success", "failed", "partial"}
        assert "Private Patient Trace Check" not in str(attrs)
        assert not any(str(value).startswith("%PDF-") for value in attrs.values())

    def stage(name):
        return next(s for s in spans if s.attributes[STAGE_NAME] == name and s.name == name)

    claim_input = stage("claim_input")
    document_processing = stage("document_processing")
    information_extraction = stage("information_extraction")
    rule_engine = stage("rule_engine")
    decision = stage("temporary_business_decision")
    final_result = stage("final_result")

    assert list(claim_input.attributes[OUTPUT_ARTIFACT_IDS]) == list(document_processing.attributes[INPUT_ARTIFACT_IDS])
    assert list(document_processing.attributes[OUTPUT_ARTIFACT_IDS]) == list(information_extraction.attributes[INPUT_ARTIFACT_IDS])
    assert list(information_extraction.attributes[OUTPUT_ARTIFACT_IDS]) == list(rule_engine.attributes[INPUT_ARTIFACT_IDS])
    assert list(rule_engine.attributes[OUTPUT_ARTIFACT_IDS]) == list(decision.attributes[INPUT_ARTIFACT_IDS])
    assert list(decision.attributes[OUTPUT_ARTIFACT_IDS]) == list(final_result.attributes[INPUT_ARTIFACT_IDS])
    assert list(rule_engine.attributes[OUTPUT_ARTIFACT_IDS]) == [f"art_decision_claim_{claim.id}"]
