from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_claims_lifecycle():
    # 1. Create a claim
    res = client.post("/claims/", json={
        "claim_number": "TEST-CLM-9999",
        "policy_number": "POL-9999",
        "claim_amount": 7500.0,
        "customer_name": "Dr. Sarah Jenkins",
        "claim_type": "Medical",
        "claim_description": "Emergency consultation and diagnostic lab work",
    })
    assert res.status_code == 201, f"Create failed: {res.status_code} {res.text}"
    claim_data = res.json()
    claim_id = claim_data["id"]
    print(f"[OK] Claim created successfully with ID: {claim_id}")

    # 2. Get the claim
    res = client.get(f"/claims/{claim_id}")
    assert res.status_code == 200, f"Get failed: {res.status_code} {res.text}"
    assert res.json()["customer_name"] == "Dr. Sarah Jenkins"
    print(f"[OK] Fetched claim {claim_id} verified")

    # 3. Delete the claim
    res = client.delete(f"/claims/{claim_id}")
    assert res.status_code == 200, f"Delete failed: {res.status_code} {res.text}"
    print(f"[OK] Deleted claim {claim_id}: {res.json()}")

    # 4. Verify 404
    res = client.get(f"/claims/{claim_id}")
    assert res.status_code == 404, f"Expected 404 but got: {res.status_code}"
    print(f"[OK] Verified claim {claim_id} no longer exists (404)")

    # 5. Create another claim and test bulk delete endpoint
    res = client.post("/claims/", json={
        "claim_number": "TEST-CLM-8888",
        "policy_number": "POL-8888",
        "claim_amount": 1200.0,
        "customer_name": "Mark Spencer",
    })
    assert res.status_code == 201
    bulk_res = client.delete("/claims")
    assert bulk_res.status_code == 200
    print(f"[OK] Bulk delete all claims succeeded: {bulk_res.json()}")

    print("\nALL CLAIMS LIFECYCLE TESTS PASSED 100%!")

if __name__ == "__main__":
    test_claims_lifecycle()
