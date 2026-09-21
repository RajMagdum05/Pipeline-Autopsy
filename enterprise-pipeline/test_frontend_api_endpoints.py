"""
Verification test for Frontend API Endpoints (create claim, upload document, process claim, get execution).
"""
import os
import sys
from pathlib import Path
from fastapi.testclient import TestClient

# Ensure enterprise-pipeline is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.main import app
from app.database import get_db, SessionLocal
from app.models import Claim, Document

client = TestClient(app)

def test_frontend_pipeline_flow():
    print("=== Testing Frontend API Flow ===")
    
    # 1. Create a Claim
    resp = client.post("/claims", json={"customer_name": "Suresh Patel", "claim_amount": 55000.0, "status": "processing"})
    assert resp.status_code == 201, f"Create claim failed: {resp.text}"
    claim = resp.json()
    claim_id = claim["id"]
    print(f"1. Claim created: #{claim_id} ({claim['customer_name']}, INR {claim['claim_amount']})")
    
    # 2. Upload Document (use existing claim PDF from Artifact if available, or create a mock PDF)
    sample_pdf_path = Path(__file__).resolve().parents[1] / "Artifact" / "claim_101" / "medical_bill.pdf"
    if not sample_pdf_path.exists():
        # Fallback to creating a test PDF if not found
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "HOSPITAL INVOICE\nPatient: Suresh Patel\nPolicy: POL-998822\nHospital: Apollo Hospitals\nAdmission: 2024-01-10\nDischarge: 2024-01-12\nTotal Bill: INR 52000\nDiagnosis: Acute Appendicitis (K35.8)")
        sample_pdf_path = Path("test_sample_bill.pdf")
        doc.save(str(sample_pdf_path))
        doc.close()
    
    with open(sample_pdf_path, "rb") as f:
        upload_resp = client.post(
            f"/claims/{claim_id}/documents",
            data={"document_type": "Medical Bill"},
            files={"file": ("medical_bill.pdf", f, "application/pdf")},
        )
    assert upload_resp.status_code == 201, f"Upload document failed: {upload_resp.text}"
    uploaded_doc = upload_resp.json()
    print(f"2. Document uploaded: #{uploaded_doc['id']} ({uploaded_doc['file_name']})")
    
    # 3. Test Direct Document File Serving
    file_resp = client.get(f"/claims/{claim_id}/documents/{uploaded_doc['id']}/file")
    assert file_resp.status_code == 200, f"File serving failed: {file_resp.status_code}"
    print(f"3. Document file served successfully (Content-Type: {file_resp.headers.get('content-type')})")
    
    # 4. Test Process Claim Endpoint
    proc_resp = client.post(f"/claims/{claim_id}/process")
    assert proc_resp.status_code == 200, f"Process claim failed: {proc_resp.text}"
    proc_data = proc_resp.json()
    print(f"4. Pipeline Executed Successfully!")
    print(f"   Final Decision: {proc_data.get('decision', {}).get('decision')}")
    print(f"   Reason: {proc_data.get('decision', {}).get('decision_reason')}")
    print(f"   Total Rules: {proc_data.get('decision', {}).get('total_rules')}")
    print(f"   Passed Rules: {proc_data.get('decision', {}).get('passed_rules')}")
    assert "extraction" in proc_data
    assert "decision" in proc_data
    assert proc_data["claim_id"] == claim_id
    
    # 5. Test Get Execution History Endpoint
    exec_resp = client.get(f"/claims/{claim_id}/execution")
    assert exec_resp.status_code == 200, f"Get execution failed: {exec_resp.text}"
    exec_data = exec_resp.json()
    assert exec_data is not None
    assert exec_data["claim_id"] == claim_id
    assert exec_data["decision"]["decision"] == proc_data["decision"]["decision"]
    print(f"5. Execution History retrieved from DB successfully!")
    print("=== All Frontend API Endpoints Verified! ===")

if __name__ == "__main__":
    test_frontend_pipeline_flow()
