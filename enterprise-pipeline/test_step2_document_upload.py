import io
from pathlib import Path
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal, Base, engine
from app.models import Claim, Document
from sqlalchemy import text

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def init_database():
    Base.metadata.create_all(bind=engine)


def test_upload_valid_pdf_to_existing_claim():
    # 1. Create an existing claim
    db = SessionLocal()
    claim = Claim(customer_name="Ramesh Gupta", claim_amount=Decimal("45000.00"), status="processing")
    db.add(claim)
    db.commit()
    db.refresh(claim)
    claim_id = claim.id
    db.close()

    # 2. Upload valid PDF
    pdf_bytes = b"%PDF-1.4\n%Test PDF Header\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    files = {
        "file": ("hospital_discharge.pdf", io.BytesIO(pdf_bytes), "application/pdf")
    }
    data = {
        "document_type": "Discharge Summary"
    }

    response = client.post(f"/claims/{claim_id}/documents", data=data, files=files)
    assert response.status_code == 201, response.text
    resp_json = response.json()

    # Verify response fields
    assert resp_json["id"] is not None
    assert resp_json["claim_id"] == claim_id
    assert resp_json["document_type"] == "Discharge Summary"
    assert resp_json["file_name"] == "hospital_discharge.pdf"
    assert "storage/claims" in resp_json["file_path"]

    # Verify physical file existence and exact byte match on disk
    saved_file_path = Path(resp_json["file_path"])
    assert saved_file_path.exists(), f"Saved file must exist at {saved_file_path}"
    assert saved_file_path.read_bytes() == pdf_bytes, "Saved file content must match uploaded content exactly"

    # Verify database persistence directly
    with engine.connect() as conn:
        doc_row = conn.execute(
            text("SELECT id, claim_id, document_type, file_name, file_path FROM documents WHERE id = :id"),
            {"id": resp_json["id"]}
        ).fetchone()
        assert doc_row is not None
        assert doc_row[0] == resp_json["id"]
        assert doc_row[1] == claim_id
        assert doc_row[2] == "Discharge Summary"
        assert doc_row[3] == "hospital_discharge.pdf"


def test_upload_valid_image_to_existing_claim():
    # 1. Create an existing claim
    db = SessionLocal()
    claim = Claim(customer_name="Sunita Rao", claim_amount=Decimal("12000.00"), status="processing")
    db.add(claim)
    db.commit()
    db.refresh(claim)
    claim_id = claim.id
    db.close()

    # 2. Upload valid PNG image
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    files = {
        "file": ("pharmacy_receipt.png", io.BytesIO(png_bytes), "image/png")
    }
    data = {
        "document_type": "Pharmacy Receipt"
    }

    response = client.post(f"/claims/{claim_id}/documents", data=data, files=files)
    assert response.status_code == 201, response.text
    resp_json = response.json()

    assert resp_json["claim_id"] == claim_id
    assert resp_json["document_type"] == "Pharmacy Receipt"
    assert resp_json["file_name"] == "pharmacy_receipt.png"

    # Verify physical file on disk
    saved_file_path = Path(resp_json["file_path"])
    assert saved_file_path.exists()
    assert saved_file_path.read_bytes() == png_bytes


def test_reject_upload_for_nonexistent_claim():
    fake_claim_id = 9999999
    files = {
        "file": ("bill.pdf", io.BytesIO(b"%PDF-1.4 sample"), "application/pdf")
    }
    data = {"document_type": "Bill"}

    response = client.post(f"/claims/{fake_claim_id}/documents", data=data, files=files)
    assert response.status_code == 404
    assert f"Claim with id {fake_claim_id} not found" in response.json()["detail"]


def test_reject_unsupported_file_extension():
    db = SessionLocal()
    claim = Claim(customer_name="Vikas Kumar", claim_amount=Decimal("5000.00"), status="processing")
    db.add(claim)
    db.commit()
    db.refresh(claim)
    claim_id = claim.id
    db.close()

    files = {
        "file": ("malicious_script.exe", io.BytesIO(b"MZ executable header"), "application/octet-stream")
    }
    data = {"document_type": "Investigation"}

    response = client.post(f"/claims/{claim_id}/documents", data=data, files=files)
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_get_documents_for_claim():
    db = SessionLocal()
    claim = Claim(customer_name="Anita Roy", claim_amount=Decimal("30000.00"), status="processing")
    db.add(claim)
    db.commit()
    db.refresh(claim)
    claim_id = claim.id
    db.close()

    # Upload two documents
    client.post(
        f"/claims/{claim_id}/documents",
        data={"document_type": "ID Proof"},
        files={"file": ("passport.jpg", io.BytesIO(b"\xff\xd8\xff\xe0 image data"), "image/jpeg")}
    )
    client.post(
        f"/claims/{claim_id}/documents",
        data={"document_type": "Hospital Bill"},
        files={"file": ("final_bill.pdf", io.BytesIO(b"%PDF-1.4 bill"), "application/pdf")}
    )

    # Get documents
    get_res = client.get(f"/claims/{claim_id}/documents")
    assert get_res.status_code == 200
    docs = get_res.json()
    assert len(docs) == 2
    assert docs[0]["file_name"] == "passport.jpg"
    assert docs[1]["file_name"] == "final_bill.pdf"
