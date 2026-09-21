import os
import json
import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock

from app.schemas import OCRResult, OCRPage, ValidatedExtractionResult
from app.services.extraction_service import (
    extract_claim_from_validated_ocr,
    validate_and_finalize_extraction,
    ExtractionValidationError,
)
from app.database import Base, engine, SessionLocal
from app.models import Claim, ExtractionResultRecord


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    yield db
    db.close()


def test_complete_extraction_validation_handoff_success(setup_db):
    """
    Test 1, 3, 4, 5, 6, 8:
    - Runs complete claim: documents -> OCR -> OCR validation -> Gemini -> extraction validation.
    - Verifies extraction status is 'VALIDATED' and ready_for_rule_engine is True.
    - Verifies predefined fields, additional_information, source_references, claim_id, execution_id.
    - Verifies database record persistence.
    """
    claim_id = 950
    existing = setup_db.query(Claim).filter(Claim.id == claim_id).first()
    if not existing:
        claim = Claim(id=claim_id, customer_name="Rahul Sharma", claim_amount=Decimal("75000.00"), status="processing")
        setup_db.add(claim)
        setup_db.commit()

    doc1_ocr = OCRResult(
        document_id=1001,
        engine="pymupdf",
        pages=[
            OCRPage(
                document_id=1001,
                page_number=1,
                raw_text="HEALTH INSURANCE CLAIM INVOICE #99001\nPatient: Rahul Sharma\nHospital: Metro Hospital\nDate: 2026-09-15\nAmount: $75,000.00",
                extraction_method="DIRECT_TEXT",
                status="DIRECT_TEXT",
            )
        ],
    )

    doc2_ocr = OCRResult(
        document_id=1002,
        engine="tesseract",
        pages=[
            OCRPage(
                document_id=1002,
                page_number=1,
                raw_text="CLINICAL SUMMARY\nPatient: Rahul Sharma\nDiagnosis: Acute Appendicitis\nTreatment: Laparoscopic Appendectomy",
                extraction_method="TESSERACT_OCR",
                status="OCR_REQUIRED",
            )
        ],
    )

    documents = [
        {"id": 1001, "claim_id": claim_id, "document_type": "invoice", "file_name": "medical_invoice.pdf", "ocr_result": doc1_ocr},
        {"id": 1002, "claim_id": claim_id, "document_type": "clinical_summary", "file_name": "clinical_summary.pdf", "ocr_result": doc2_ocr},
    ]

    res = extract_claim_from_validated_ocr(claim_id=claim_id, documents=documents, db_session=setup_db)

    # 1. Handoff object assertions
    assert isinstance(res, ValidatedExtractionResult)
    assert res.claim_id == claim_id
    assert res.execution_id.startswith("exec_")
    assert res.extraction_status == "VALIDATED"
    assert res.ready_for_rule_engine is True
    assert res.validation_errors == []

    # 2. Predefined fields assertions
    assert res.patient_name == "Rahul Sharma"
    assert res.hospital == "Metro Hospital"
    assert res.diagnosis == "Acute Appendicitis"
    assert res.treatment == "Laparoscopic Appendectomy"
    assert res.date == "2026-09-15"
    assert float(res.amount) == 75000.0

    # 3. Additional information assertions
    assert isinstance(res.additional_information, dict)
    assert "invoice_number" in res.additional_information

    # 4. Source references assertions
    assert len(res.source_references) >= 5
    for ref in res.source_references:
        assert ref.document_id in (1001, 1002)
        assert ref.page_number == 1

    # 5. Database record persistence assertion
    db_rec = setup_db.query(ExtractionResultRecord).filter(ExtractionResultRecord.claim_id == claim_id).order_by(ExtractionResultRecord.id.desc()).first()
    assert db_rec is not None
    assert db_rec.extraction_status == "VALIDATED"
    assert db_rec.execution_id == res.execution_id


def test_malformed_response_rejected_and_blocked_from_rule_engine(setup_db):
    """
    Test 7:
    - Tests intentionally malformed Gemini response (invalid JSON / non-numeric amount / bad refs).
    - Confirms validation fails with ExtractionValidationError.
    - Confirms status is FAILED, ready_for_rule_engine is False.
    - Confirms failure reason is stored in database.
    - Confirms invalid result is NOT passed to Rule Engine.
    """
    claim_id = 951
    existing = setup_db.query(Claim).filter(Claim.id == claim_id).first()
    if not existing:
        claim = Claim(id=claim_id, customer_name="Test Patient", claim_amount=Decimal("100.00"), status="processing")
        setup_db.add(claim)
        setup_db.commit()

    malformed_json_response = "```json\n{\n  \"claim_id\": 951,\n  \"amount\": \"INVALID_NON_NUMERIC_AMOUNT\",\n  \"additional_information\": \"SHOULD_BE_DICT_NOT_STRING\",\n  \"source_references\": \"SHOULD_BE_LIST_NOT_STRING\"\n}\n```"

    exec_id = "exec_test_malformed_951"

    with pytest.raises(ExtractionValidationError) as exc:
        validate_and_finalize_extraction(
            raw_response=malformed_json_response,
            claim_id=claim_id,
            execution_id=exec_id,
            db_session=setup_db,
        )

    # Verify exception details
    err = exc.value
    assert len(err.errors) >= 2
    assert any("amount" in e for e in err.errors)
    assert any("additional_information" in e for e in err.errors)

    # Verify failed container properties
    failed_res = err.failed_result
    assert failed_res.extraction_status == "FAILED"
    assert failed_res.ready_for_rule_engine is False
    assert len(failed_res.validation_errors) >= 2

    # Verify failure is persisted in DB with extraction_status='FAILED'
    db_rec = setup_db.query(ExtractionResultRecord).filter(ExtractionResultRecord.claim_id == claim_id).order_by(ExtractionResultRecord.id.desc()).first()
    assert db_rec is not None
    assert db_rec.extraction_status == "FAILED"
    assert len(db_rec.validation_errors) >= 2
