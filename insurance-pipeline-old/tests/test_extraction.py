import json
import os
from pathlib import Path
from dotenv import load_dotenv
import pytest

# Load environment variables from .env file if available
ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")
load_dotenv(".env")

from app.services.extraction_service import ExtractionServiceError, extract_claim_information

SAMPLE_OCR_TEXT = """
HEALTH INSURANCE CLAIM RECEIPT
--------------------------------------------------
Hospital Name: City General Hospital
Date of Admission: 2026-08-14
Patient Name: Rahul Sharma
Attending Physician: Dr. A. K. Verma

Medical Diagnosis: Acute Appendicitis
Treatment Provided: Emergency Appendectomy Surgery & Post-Op Care
Total Hospitalization Bill Amount: $45,500.00
Payment Status: Unpaid / Claim Submitted
--------------------------------------------------
"""

SAMPLE_PARTIAL_OCR_TEXT = """
RECEIPT #8812
Patient: Alice Smith
Date: 2026-09-01
Amount Paid: $1,200.00
(No hospital or diagnosis listed on this receipt fragment)
"""


def test_extraction_missing_api_key_or_live_extraction():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    if not api_key:
        with pytest.raises(ExtractionServiceError) as exc_info:
            extract_claim_information(SAMPLE_OCR_TEXT)
        assert "GEMINI_API_KEY environment variable is not set" in str(exc_info.value)
    else:
        try:
            extracted_data = extract_claim_information(SAMPLE_OCR_TEXT)
            assert extracted_data.patient_name is not None
            assert extracted_data.amount is not None
        except ExtractionServiceError as e:
            err_msg = str(e).lower()
            if any(k in err_msg for k in ["429", "503", "resource_exhausted", "unavailable", "quota"]):
                pytest.skip(f"Gemini API external service temporary issue: {e}")
            raise


def test_partial_extraction():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        pytest.skip("Skipping live LLM test: GEMINI_API_KEY not set")

    try:
        partial_data = extract_claim_information(SAMPLE_PARTIAL_OCR_TEXT)
        assert partial_data.patient_name == "Alice Smith"
    except ExtractionServiceError as e:
        err_msg = str(e).lower()
        if any(k in err_msg for k in ["429", "503", "resource_exhausted", "unavailable", "quota"]):
            pytest.skip(f"Gemini API external service temporary issue: {e}")
        raise


if __name__ == "__main__":
    pytest.main([__file__])
