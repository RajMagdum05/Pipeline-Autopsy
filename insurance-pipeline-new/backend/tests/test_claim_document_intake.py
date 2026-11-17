from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.claim_document_intake.models import Claim, ClaimDocument, ClaimDocumentVersion, Document, IntakeClaim
from app.claim_document_intake import storage
from app.main import app
from app.shared.database import Base, get_db
from app.document_processing.models import ProcessedDocument, ProcessingRun, SemanticArtifact
import app.claim_document_intake.service as intake_service


POLICY_PDF = b"%PDF-1.4\npolicy document\n%%EOF"
PROOF_PDF = b"%PDF-1.7\nhospital bill\n%%EOF"


def _form():
    return {
        "policyholder_name": "Asha Rao",
        "age": "42",
        "policy_number": "POL-101",
        "incident_date": (date.today() - timedelta(days=2)).isoformat(),
        "description": "Hospital admission for acute condition.",
        "claimed_amount": "12500.50",
    }


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(storage, "LOCAL_DOCUMENT_ROOT", tmp_path / "storage" / "claims")
    monkeypatch.setattr(intake_service, "PROJECT_ROOT", tmp_path)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr("app.main.init_db", lambda: None)
    return TestClient(app), factory, engine


def test_legacy_frontend_upload_creates_existing_rows_and_stores_files(tmp_path, monkeypatch):
    client, factory, engine = _client(tmp_path, monkeypatch)
    try:
        response = client.post(
            "/api/v1/claims",
            data={**_form(), "document_1_type": "hospital_bill"},
            files={
                "policy_document": ("policy.pdf", POLICY_PDF, "application/pdf"),
                "document_1": ("bill.pdf", PROOF_PDF, "application/pdf"),
            },
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["claim_status"] == "RECEIVED"
        assert result["claim_id"].startswith("CLM-")
        assert len(result["document_ids"]) == 2
        assert [row["document_slot"] for row in result["documents"]] == [0, 1]
        for doc, expected in zip(result["documents"], (POLICY_PDF, PROOF_PDF)):
            path = tmp_path / doc["storage_path"]
            assert path.read_bytes() == expected
            assert doc["checksum_sha256"] == sha256(expected).hexdigest()

        with factory() as db:
            claim = db.query(IntakeClaim).filter_by(claim_id=result["claim_id"]).one()
            assert claim.policyholder_name == "Asha Rao"
            assert claim.claim_status == "RECEIVED"
            assert db.query(ClaimDocument).filter_by(claim_id=claim.claim_id).count() == 2
            legacy = db.get(Claim, claim.legacy_id)
            assert legacy.customer_name == "Asha Rao"
            assert legacy.status == "RECEIVED"
            assert db.query(Document).filter_by(claim_id=claim.legacy_id).count() == 2
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_claims_alias_accepts_one_generic_document(tmp_path, monkeypatch):
    client, factory, engine = _client(tmp_path, monkeypatch)
    try:
        response = client.post(
            "/claims",
            data=_form(),
            files=[("documents", ("bill.pdf", PROOF_PDF, "application/pdf"))],
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert len(result["document_ids"]) == 1
        assert result["documents"][0]["document_type"] == "other_supporting_document"
        assert len(result["claim_access_token"]) >= 40
        with factory() as db:
            claim = db.query(IntakeClaim).filter_by(claim_id=result["claim_id"]).one()
            assert claim.access_token_hash == sha256(result["claim_access_token"].encode()).hexdigest()
            assert claim.access_token_hash != result["claim_access_token"]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_document_status_requires_claim_token_and_returns_each_selected_role(tmp_path, monkeypatch):
    client, _, engine = _client(tmp_path, monkeypatch)
    try:
        response = client.post("/claims", data=_form(), files=[
            ("policy_document", ("policy.pdf", POLICY_PDF, "application/pdf")),
            ("documents", ("other.pdf", PROOF_PDF, "application/pdf")),
        ])
        assert response.status_code == 201, response.text
        created = response.json()
        url = f"/claims/{created['claim_id']}/documents/status"
        assert client.get(url).status_code == 404
        status_response = client.get(url, headers={"Authorization": f"Bearer {created['claim_access_token']}"})
        assert status_response.status_code == 200, status_response.text
        docs = status_response.json()["documents"]
        assert [doc["declared_type"] for doc in docs] == ["policy_document", "other_supporting_document"]
        assert [doc["status"] for doc in docs] == ["waiting_for_text_processing"] * 2
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_status_returns_only_currently_validated_facts_per_document(tmp_path, monkeypatch):
    client, factory, engine = _client(tmp_path, monkeypatch)
    try:
        created_response = client.post("/claims", data={**_form(), "document_1_type": "hospital_bill"}, files={
            "policy_document": ("policy.pdf", POLICY_PDF, "application/pdf"),
            "document_1": ("bill.pdf", PROOF_PDF, "application/pdf"),
        })
        assert created_response.status_code == 201, created_response.text
        created = created_response.json()
        now = datetime.now(timezone.utc)
        with factory() as db:
            claim = db.query(IntakeClaim).filter_by(claim_id=created["claim_id"]).one()
            run = ProcessingRun(claim_id=claim.claim_id, config_version="synthetic-test", status="REVIEW_REQUIRED", started_at=now, completed_at=now)
            db.add(run)
            db.flush()
            for intake_doc, legacy_doc in zip(claim.documents, db.query(Document).filter_by(claim_id=claim.legacy_id).order_by(Document.id).all()):
                role = intake_doc.document_type
                processed = ProcessedDocument(run_id=run.id, document_id=legacy_doc.id, intake_document_id=intake_doc.id,
                    claim_id=claim.claim_id, role=role, attempt_number=1, checksum_sha256=intake_doc.checksum_sha256,
                    status="COMPLETED" if role == "policy_document" else "REVIEW_REQUIRED",
                    disposition="ACCEPTED" if role == "policy_document" else "HUMAN_REVIEW_REQUIRED",
                    started_at=now, completed_at=now, configuration={})
                db.add(processed)
                db.flush()
                base = dict(processed_document_id=processed.id, claim_id=claim.claim_id, document_id=legacy_doc.id,
                    input_checksum_sha256=intake_doc.checksum_sha256, attempt_number=1, model_id="synthetic",
                    schema_version="test-schema", started_at=now, completed_at=now)
                db.add(SemanticArtifact(**base, artifact_kind="classification", status="accepted",
                    payload={"detected_type": role, "subtype": "schedule" if role == "policy_document" else "invoice"}, prompt_version="test-classifier"))
                extracted_fact = {"field_name": "policy_number" if role == "policy_document" else "total",
                    "raw_value": "SYN-1", "normalized_value": None, "field_status": "found",
                    "evidence": [{"page_number": 1, "quote": "SYN-1"}], "warning": None}
                good = role == "policy_document"
                db.add(SemanticArtifact(**base, artifact_kind="extraction", status="complete" if good else "review_required",
                    payload={"document_type": role, "detected_type": role,
                        "subtype": "schedule" if good else "invoice", "facts": [extracted_fact], "warnings": []},
                    prompt_version=f"document-extraction-v2/{role}"))
                db.add(SemanticArtifact(**base, artifact_kind="application_validation", status="passed" if good else "review_required",
                    payload={"status": "passed" if good else "review_required", "reasons": [] if good else ["Synthetic evidence validation failed."]},
                    prompt_version="application-validation-v1"))
            db.commit()
        headers = {"Authorization": f"Bearer {created['claim_access_token']}"}
        response = client.get(f"/claims/{created['claim_id']}/documents/status", headers=headers)
        assert response.status_code == 200, response.text
        policy, proof = response.json()["documents"]
        assert policy["status"] == "complete"
        assert policy["extracted_facts"][0]["field_name"] == "policy_number"
        assert proof["status"] == "review_required"
        assert proof["extracted_facts"] is None
        assert proof["validation_reasons"] == ["Synthetic evidence validation failed."]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_replacement_archives_prior_version_and_requires_explicit_supported_type(tmp_path, monkeypatch):
    client, factory, engine = _client(tmp_path, monkeypatch)
    try:
        response = client.post("/claims", data={**_form(), "document_1_type": "hospital_bill"}, files={
            "policy_document": ("policy.pdf", POLICY_PDF, "application/pdf"),
            "document_1": ("bill.pdf", PROOF_PDF, "application/pdf"),
        })
        created = response.json()
        document_id = created["document_ids"][1]
        headers = {"Authorization": f"Bearer {created['claim_access_token']}"}
        url = f"/claims/{created['claim_id']}/documents/{document_id}"
        invalid = client.put(url, headers=headers, data={"document_type": "policy_document"},
            files={"file": ("replacement.pdf", PROOF_PDF, "application/pdf")})
        assert invalid.status_code == 409
        replaced = client.put(url, headers=headers, data={"document_type": "other_supporting_document"},
            files={"file": ("new-bill.pdf", b"%PDF-1.7\nreplacement\n%%EOF", "application/pdf")})
        assert replaced.status_code == 200, replaced.text
        assert replaced.json()["version_number"] == 2
        with factory() as db:
            document = db.query(ClaimDocument).filter_by(id=UUID(document_id)).one()
            old = db.query(ClaimDocumentVersion).filter_by(claim_document_id=document.id).one()
            assert document.document_type == "other_supporting_document"
            assert document.version_number == 2
            assert old.version_number == 1
            assert old.document_type == "hospital_bill"
            assert (tmp_path / old.storage_path).read_bytes() == PROOF_PDF
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_invalid_file_signature_is_rejected_before_rows_or_files(tmp_path, monkeypatch):
    client, factory, engine = _client(tmp_path, monkeypatch)
    try:
        response = client.post(
            "/claims",
            data=_form(),
            files=[("documents", ("bill.pdf", b"not really a pdf", "application/pdf"))],
        )
        assert response.status_code == 422
        with factory() as db:
            assert db.query(IntakeClaim).count() == 0
            assert db.query(Claim).count() == 0
        assert not (tmp_path / "storage" / "claims").exists()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
