import json
import os
from pathlib import Path
from dotenv import load_dotenv
import pytest

# Load environment variables
ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")
load_dotenv(".env")

from app.database import SessionLocal
from app.models import PolicyChunk
from app.services.rag_service import RAGServiceError, index_policy_document, search_policy_knowledge

SYNTHETIC_POLICY_TEXT = """
HEALTH INSURANCE POLICY SCHEME 2026 - SECTION A: SURGICAL COVERAGE

Clause 1.1: General Surgical Benefits
This policy covers medically necessary inpatient surgical procedures performed at network hospitals. Pre-authorization is required for non-emergency surgeries at least 48 hours prior to admission.

Clause 1.2: Orthopedic & Fracture Surgery Coverage
Fracture treatments and emergency orthopedic surgeries (including bone pin insertion, alignment, and reduction) are covered 100% up to a maximum benefit limit of $60,000 per policy year.

Clause 1.3: Exclusions & Non-Covered Treatments
Cosmetic procedures, elective plastic surgeries, dental bleaching, and experimental therapies are strictly excluded from coverage. Room rent is capped at $500 per day for standard private rooms.
"""


def test_rag_service():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        pytest.skip("Skipping RAG test: GEMINI_API_KEY is not set")

    db = SessionLocal()
    try:
        db.query(PolicyChunk).delete()
        db.commit()
    finally:
        db.close()

    indexed_count = index_policy_document("Health_Policy_2026", SYNTHETIC_POLICY_TEXT)
    assert indexed_count > 0

    sample_query = "Is fracture surgery covered and what is the maximum amount?"
    retrieved_chunks = search_policy_knowledge(query=sample_query, top_k=2)
    assert len(retrieved_chunks) > 0


if __name__ == "__main__":
    pytest.main([__file__])
