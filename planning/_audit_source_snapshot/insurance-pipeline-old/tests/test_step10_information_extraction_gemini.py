import os
import json
import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal

from app.schemas import OCRResult, OCRPage, OCRLine, OCRWord, ClaimExtractionResult
from app.services.extraction_service import (
    build_claim_extraction_input,
    format_llm_prompt_from_payload,
    validate_extraction_response,
    extract_claim_from_validated_ocr,
    ExtractionConfigError,
    ExtractionAPIError,
    ExtractionValidationError,
    ExtractionServiceError,
)
from app.prompts import EXTRACTION_PROMPT_VERSION, build_gemini_extraction_prompt
from app.database import Base, engine, SessionLocal
from app.models import Claim, Document, ExtractionResultRecord


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    yield db
    db.close()


def test_scenario_a_normal_extraction_multi_doc(setup_db):
    """
    Test A. Normal extraction:
    - Multiple documents under one claim ID
    - Validated OCR inputs
    - Live/Mocked Gemini request
    - Exactly one claim-level extraction result returned
    """
    claim_id = 901
    existing = setup_db.query(Claim).filter(Claim.id == claim_id).first()
    if not existing:
        claim = Claim(id=claim_id, customer_name="Rahul Sharma", claim_amount=Decimal("75000.00"), status="processing")
        setup_db.add(claim)
        setup_db.commit()

    doc1_ocr = OCRResult(
        document_id=101,
        engine="pymupdf",
        pages=[
            OCRPage(
                document_id=101,
                page_number=1,
                raw_text="HEALTH INSURANCE CLAIM INVOICE #INV-901\nPatient: Rahul Sharma\nHospital: Metro Hospital\nDate: 2026-09-15\nAmount: $75,000.00",
                extraction_method="DIRECT_TEXT",
                status="DIRECT_TEXT",
            )
        ],
    )

    doc2_ocr = OCRResult(
        document_id=102,
        engine="tesseract",
        pages=[
            OCRPage(
                document_id=102,
                page_number=1,
                raw_text="CLINICAL SUMMARY\nPatient: Rahul Sharma\nDiagnosis: Acute Appendicitis\nTreatment: Laparoscopic Appendectomy",
                extraction_method="TESSERACT_OCR",
                status="OCR_REQUIRED",
            )
        ],
    )

    documents = [
        {"id": 101, "claim_id": claim_id, "document_type": "invoice", "file_name": "medical_invoice.pdf", "ocr_result": doc1_ocr},
        {"id": 102, "claim_id": claim_id, "document_type": "clinical_summary", "file_name": "clinical_summary.pdf", "ocr_result": doc2_ocr},
    ]

    res = extract_claim_from_validated_ocr(claim_id=claim_id, documents=documents, db_session=setup_db)

    assert res.claim_id == claim_id
    assert res.patient_name == "Rahul Sharma"
    assert res.hospital == "Metro Hospital"
    assert res.diagnosis == "Acute Appendicitis"
    assert res.treatment == "Laparoscopic Appendectomy"
    assert res.date == "2026-09-15"
    assert float(res.amount) == 75000.0


def test_scenario_b_additional_information():
    """
    Test B. Additional Information:
    - Verifies useful information not covered by predefined fields (e.g. invoice_number) has a place in additional_information.
    """
    claim_id = 902
    doc_ocr = OCRResult(
        document_id=201,
        engine="pymupdf",
        pages=[
            OCRPage(
                document_id=201,
                page_number=1,
                raw_text="INVOICE #INV-8812\nPatient: Sunita Patel\nHospital: Apollo Hospital\nDate: 2026-09-01\nAmount: $12,500.00",
                extraction_method="DIRECT_TEXT",
                status="DIRECT_TEXT",
            )
        ],
    )
    documents = [
        {"id": 201, "claim_id": claim_id, "document_type": "invoice", "file_name": "inv.pdf", "ocr_result": doc_ocr}
    ]

    res = extract_claim_from_validated_ocr(claim_id=claim_id, documents=documents)
    assert "invoice_number" in res.additional_information
    assert res.additional_information["invoice_number"] == "INV-8812"


def test_scenario_c_source_references():
    """
    Test C. Source References:
    - Verifies extracted values retain document ID and page number references.
    """
    claim_id = 903
    doc_ocr = OCRResult(
        document_id=301,
        engine="pymupdf",
        pages=[
            OCRPage(
                document_id=301,
                page_number=2,
                raw_text="Patient: Vikram Singh\nDiagnosis: Fracture Femur\nAmount: $35,000.00",
                extraction_method="DIRECT_TEXT",
                status="DIRECT_TEXT",
            )
        ],
    )
    documents = [
        {"id": 301, "claim_id": claim_id, "document_type": "discharge_summary", "file_name": "summary.pdf", "ocr_result": doc_ocr}
    ]

    res = extract_claim_from_validated_ocr(claim_id=claim_id, documents=documents)
    assert len(res.source_references) >= 3
    for ref in res.source_references:
        assert ref.document_id == 301
        assert ref.page_number == 2


def test_scenario_d_invalid_response_schema_validation():
    """
    Test D. Invalid Response:
    - Verifies schema validation catches malformed JSON and incorrect types.
    """
    # 1. Non-JSON string
    with pytest.raises(ExtractionValidationError) as exc1:
        validate_extraction_response("This is plain text prose from LLM, not JSON.")
    assert any("Response is not valid JSON" in e for e in exc1.value.errors)

    # 2. Invalid additional_information type
    bad_dict = {
        "claim_id": 101,
        "patient_name": "Test",
        "additional_information": "Should be a dict, not a string!",
    }
    with pytest.raises(ExtractionValidationError) as exc2:
        validate_extraction_response(bad_dict)
    assert any("additional_information" in e for e in exc2.value.errors)

    # 3. Invalid non-numeric amount
    bad_amt = {
        "claim_id": 101,
        "patient_name": "Test",
        "amount": "NOT_A_NUMBER",
    }
    with pytest.raises(ExtractionValidationError) as exc3:
        validate_extraction_response(bad_amt)
    assert any("amount" in e for e in exc3.value.errors)


def test_scenario_e_missing_api_key():
    """
    Test E. Missing API Key:
    - Verifies clear ExtractionConfigError failure when GEMINI_API_KEY is not configured.
    """
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ExtractionConfigError) as exc:
            extract_claim_from_validated_ocr(claim_id=1, documents=[], allow_fallback=False)
        assert "GEMINI_API_KEY environment variable is missing" in str(exc.value)


def test_scenario_f_gemini_api_failure():
    """
    Test F. Gemini/API Failure:
    - Verifies controlled failure handling (ExtractionAPIError) when all Gemini model calls fail.
    """
    doc_ocr = OCRResult(
        document_id=401,
        engine="pymupdf",
        pages=[
            OCRPage(
                document_id=401,
                page_number=1,
                raw_text="Patient: Test Patient Amount: $100",
                extraction_method="DIRECT_TEXT",
                status="DIRECT_TEXT",
            )
        ],
    )
    documents = [{"id": 401, "claim_id": 904, "ocr_result": doc_ocr}]

    with patch("app.services.extraction_service.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("API connection timeout 504")
        mock_client_cls.return_value = mock_client

        with pytest.raises(ExtractionAPIError) as exc:
            extract_claim_from_validated_ocr(claim_id=904, documents=documents, allow_fallback=False)
        assert "Gemini API execution failed" in str(exc.value)


def test_scenario_g_security_key_never_printed():
    """
    Test G. Security:
    - Verifies the API key is never printed in log outputs or exception error strings.
    """
    secret_key = "SECRET_GEMINI_KEY_99999"
    with patch.dict(os.environ, {"GEMINI_API_KEY": secret_key}):
        doc_ocr = OCRResult(
            document_id=501,
            engine="pymupdf",
            pages=[OCRPage(document_id=501, page_number=1, raw_text="Test", status="DIRECT_TEXT")],
        )
        documents = [{"id": 501, "claim_id": 905, "ocr_result": doc_ocr}]

        with patch("app.services.extraction_service.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.models.generate_content.side_effect = Exception(f"Failed with key {secret_key}")
            mock_client_cls.return_value = mock_client

            with pytest.raises(ExtractionAPIError) as exc:
                extract_claim_from_validated_ocr(claim_id=905, documents=documents, allow_fallback=False)

            err_str = str(exc.value)
            assert secret_key not in err_str
            assert "[REDACTED_API_KEY]" in err_str


def test_scenario_h_database_storage(setup_db):
    """
    Test H. Database Storage:
    - Verifies validated extraction result is persisted in the database under ExtractionResultRecord.
    """
    claim = Claim(customer_name="Rahul Sharma", claim_amount=Decimal("75000.00"), status="processing")
    setup_db.add(claim)
    setup_db.commit()
    setup_db.refresh(claim)

    doc_ocr = OCRResult(
        document_id=601,
        engine="pymupdf",
        pages=[
            OCRPage(
                document_id=601,
                page_number=1,
                raw_text="INVOICE #99001 Patient: Rahul Sharma Hospital: Metro Hospital Date: 2026-09-15 Amount: $75,000.00",
                extraction_method="DIRECT_TEXT",
                status="DIRECT_TEXT",
            )
        ],
    )
    documents = [{"id": 601, "claim_id": claim.id, "ocr_result": doc_ocr}]

    res = extract_claim_from_validated_ocr(claim_id=claim.id, documents=documents, db_session=setup_db)

    db_record = setup_db.query(ExtractionResultRecord).filter(ExtractionResultRecord.claim_id == claim.id).first()
    assert db_record is not None
    assert db_record.claim_id == claim.id
    assert db_record.extraction_status in ("VALIDATED", "SUCCESS")
