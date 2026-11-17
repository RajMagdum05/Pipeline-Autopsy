import io
from pathlib import Path
from fastapi.testclient import TestClient
import pymupdf as fitz
from app.main import app
from app.database import SessionLocal, Base, engine
from app.models import Claim

client = TestClient(app)

def setup_module():
    Base.metadata.create_all(bind=engine)

def create_valid_pdf_bytes(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text, fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes

def test_document_upload_and_get():
    # 1. Create a claim in DB first
    db = SessionLocal()
    claim = Claim(customer_name="Test Customer", claim_amount=5000, status="processing")
    db.add(claim)
    db.commit()
    db.refresh(claim)
    claim_id = claim.id
    db.close()

    # 2. Test uploading valid PDF
    pdf_content = create_valid_pdf_bytes("MEDICAL REPORT DETAILS\nPatient: Test Customer")
    files = {
        "file": ("medical_report.pdf", io.BytesIO(pdf_content), "application/pdf")
    }
    data = {
        "document_type": "Medical Report"
    }

    response = client.post(f"/claims/{claim_id}/documents", data=data, files=files)
    assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
    res_data = response.json()
    assert res_data["claim_id"] == claim_id
    assert res_data["document_type"] == "Medical Report"
    assert res_data["file_name"] == "medical_report.pdf"
    assert res_data["ocr_status"] == "completed"
    assert res_data["ocr_result"] is not None

    # 3. Test GET /claims/{claim_id}/documents
    get_res = client.get(f"/claims/{claim_id}/documents")
    assert get_res.status_code == 200
    docs = get_res.json()
    assert len(docs) >= 1
    assert any(d["file_name"] == "medical_report.pdf" for d in docs)

    # 4. Test uploading unsupported file type
    txt_files = {
        "file": ("test.txt", io.BytesIO(b"hello world"), "text/plain")
    }
    bad_res = client.post(f"/claims/{claim_id}/documents", data=data, files=txt_files)
    assert bad_res.status_code == 400
    assert "Unsupported file type" in bad_res.json()["detail"]

    # 5. Test non-existent claim
    bad_claim_res = client.post("/claims/999999/documents", data=data, files=files)
    assert bad_claim_res.status_code == 404

    print(f"All document API tests passed successfully for claim_id={claim_id}!")

if __name__ == "__main__":
    test_document_upload_and_get()
