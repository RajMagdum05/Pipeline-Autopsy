from decimal import Decimal
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, Base, engine
from app.models import Claim

client = TestClient(app)


def setup_module():
    Base.metadata.create_all(bind=engine)


def test_create_claim_direct_orm():
    db = SessionLocal()
    try:
        new_claim = Claim(
            customer_name="Rahul Sharma",
            claim_amount=Decimal("50000.00"),
            status="processing",
        )
        db.add(new_claim)
        db.commit()
        db.refresh(new_claim)

        assert new_claim.id is not None
        assert new_claim.customer_name == "Rahul Sharma"
        assert Decimal(str(new_claim.claim_amount)) == Decimal("50000.00")
        assert new_claim.status == "processing"
    finally:
        db.close()


def test_create_claim_api_endpoint():
    payload = {
        "customer_name": "Priya Patel",
        "claim_amount": 75000.50,
        "status": "processing"
    }
    response = client.post("/claims", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["id"] is not None
    assert data["customer_name"] == "Priya Patel"
    assert data["claim_amount"] == "75000.50"
    assert data["status"] == "processing"


def test_get_claims_api():
    response = client.get("/claims")
    assert response.status_code == 200
    claims = response.json()
    assert isinstance(claims, list)
    assert len(claims) >= 1


def test_get_claim_by_id_api():
    # First create a claim
    post_res = client.post("/claims", json={"customer_name": "Amit Kumar", "claim_amount": 12000.00})
    assert post_res.status_code == 201
    claim_id = post_res.json()["id"]

    # Fetch by ID
    get_res = client.get(f"/claims/{claim_id}")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["id"] == claim_id
    assert data["customer_name"] == "Amit Kumar"


def test_get_claim_not_found():
    res = client.get("/claims/9999999")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"]


def test_create_claim_validation_error():
    # Negative amount should fail validation
    res = client.post("/claims", json={"customer_name": "Test Invalid", "claim_amount": -500})
    assert res.status_code == 422


if __name__ == "__main__":
    test_create_claim_direct_orm()
    test_create_claim_api_endpoint()
    test_get_claims_api()
    test_get_claim_by_id_api()
    test_get_claim_not_found()
    test_create_claim_validation_error()
    print("All claim unit tests passed!")
