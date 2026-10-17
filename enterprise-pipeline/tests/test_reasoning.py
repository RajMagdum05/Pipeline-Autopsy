import json
import os
from pathlib import Path
from dotenv import load_dotenv
import pytest

# Load environment variables
ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")
load_dotenv(".env")

from app.schemas import ExtractedClaimInformation
from app.services.reasoning_service import ReasoningServiceError, evaluate_claim_against_policy


sample_claim = ExtractedClaimInformation(
    patient_name="Rahul Sharma",
    hospital="City Orthopedic Hospital",
    diagnosis="Fracture",
    treatment="Surgery",
    date="2026-09-10",
    amount=75000,
)

sample_policy_chunks = [
    {
        "policy_name": "Health_Policy_2026",
        "chunk_text": (
            "Clause 2.4 - Orthopedic Benefits:\n"
            "Fracture surgery is covered.\n"
            "Surgical treatment for fractures is covered up to INR 1,00,000 per policy year."
        ),
    }
]


def test_reasoning_covered_claim():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        pytest.skip("Skipping Reasoning test: GEMINI_API_KEY is not set")

    try:
        result = evaluate_claim_against_policy(sample_claim, sample_policy_chunks)
        assert result.eligible is True
    except ReasoningServiceError as e:
        err_msg = str(e).lower()
        if any(k in err_msg for k in ["429", "503", "resource_exhausted", "unavailable", "quota"]):
            pytest.skip(f"Gemini API external service temporary issue: {e}")
        raise


def test_reasoning_over_limit_claim():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        pytest.skip("Skipping Reasoning test: GEMINI_API_KEY is not set")

    over_limit_claim = ExtractedClaimInformation(
        patient_name="Rahul Sharma",
        diagnosis="Fracture",
        treatment="Surgery",
        amount=150000,
    )
    try:
        result_over = evaluate_claim_against_policy(over_limit_claim, sample_policy_chunks)
        assert result_over.eligible is False
    except ReasoningServiceError as e:
        err_msg = str(e).lower()
        if any(k in err_msg for k in ["429", "503", "resource_exhausted", "unavailable", "quota"]):
            pytest.skip(f"Gemini API external service temporary issue: {e}")
        raise


def test_reasoning_uncertain_claim():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        pytest.skip("Skipping Reasoning test: GEMINI_API_KEY is not set")

    insufficient_chunks = ["Clause 9.1: Dental cleaning is covered up to INR 5,000."]
    try:
        result_uncertain = evaluate_claim_against_policy(sample_claim, insufficient_chunks)
        assert result_uncertain.eligible is None
    except ReasoningServiceError as e:
        err_msg = str(e).lower()
        if any(k in err_msg for k in ["429", "503", "resource_exhausted", "unavailable", "quota"]):
            pytest.skip(f"Gemini API external service temporary issue: {e}")
        raise


if __name__ == "__main__":
    pytest.main([__file__])
