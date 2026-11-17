from datetime import date, timedelta
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.database.init_db import init_db
from app.database.models import ClaimDocument, IntakeClaim
from app.api.v1.claims import router
from app.api.documents import router as documents_router
from app.storage import local_document_storage


POLICY_PDF = b"%PDF-1.4\npolicy bytes exactly as uploaded\n%%EOF"
PROOF_PDF = b"%PDF-1.7\nproof bytes exactly as uploaded\n%%EOF"


def _form_data(**overrides):
    data = {
        "policyholder_name": "Test Policyholder",
        "age": "42",
        "policy_number": "POLICY-TEST-42",
        "incident_date": (date.today() - timedelta(days=2)).isoformat(),
        "description": "A test incident description.",
        "claimed_amount": "12500.50",
    }
    data.update(overrides)
    return data


def _file(name: str, content: bytes = PROOF_PDF, mime: str = "application/pdf"):
    return (name, content, mime)


def _files(proof_count: int = 0):
    files = {"policy_document": _file("policy-original.pdf", POLICY_PDF)}
    for slot in range(1, proof_count + 1):
        files[f"document_{slot}"] = _file(f"proof-original-{slot}.pdf")
    return files


def _types(proof_count: int = 0):
    return {f"document_{slot}_type": "hospital_bill" for slot in range(1, proof_count + 1)}


def _text_pdf(text: str) -> bytes:
    import pymupdf

    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), text)
    content = pdf.tobytes()
    pdf.close()
    return content


def _make_client(tmp_path, monkeypatch, *, session_factory_override=None):
    project_root = tmp_path / "project"
    storage_root = project_root / "database" / "local_doc_storage" / "claims"
    monkeypatch.setattr(local_document_storage, "_PROJECT_ROOT", project_root)
    monkeypatch.setattr(local_document_storage, "LOCAL_DOCUMENT_ROOT", storage_root)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = session_factory_override or sessionmaker(bind=engine, expire_on_commit=False)

    app = FastAPI()
    app.include_router(router)
    app.include_router(documents_router)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), factory, storage_root, engine


def test_claim_and_policy_metadata_are_created(tmp_path, monkeypatch):
    client, factory, storage_root, engine = _make_client(tmp_path, monkeypatch)
    try:
        response = client.post("/api/v1/claims", data=_form_data(), files=_files())
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["claim_id"].startswith("CLM-")
        assert payload["claim_status"] == "submitted"
        assert len(payload["documents"]) == 1
        policy = payload["documents"][0]
        assert policy["document_slot"] == 0
        assert policy["document_type"] == "policy_document"
        assert policy["file_size_bytes"] == len(POLICY_PDF)
        assert (storage_root / payload["claim_id"] / "policy_document.pdf").read_bytes() == POLICY_PDF
        with factory() as db:
            claim = db.query(IntakeClaim).filter_by(claim_id=payload["claim_id"]).one()
            assert claim.policyholder_name == "Test Policyholder"
            assert claim.age == 42
            assert claim.policy_number == "POLICY-TEST-42"
            assert claim.incident_date == date.fromisoformat(_form_data()["incident_date"])
            assert claim.description == "A test incident description."
            assert claim.claimed_amount == Decimal("12500.50")
            assert claim.legacy_id is not None
            assert db.query(ClaimDocument).filter_by(claim_id=payload["claim_id"]).count() == 1
            from app.database.models import Claim, Document
            legacy_claim = db.query(Claim).filter_by(id=claim.legacy_id).one()
            assert legacy_claim.customer_name == claim.policyholder_name
            assert db.query(Document).filter_by(claim_id=claim.legacy_id).count() == 1
    finally:
        client.close()
        engine.dispose()


def test_one_two_and_three_proof_files_create_only_used_slots(tmp_path, monkeypatch):
    for count in (1, 2, 3):
        case = tmp_path / str(count)
        case.mkdir()
        client, factory, storage_root, engine = _make_client(case, monkeypatch)
        try:
            response = client.post(
                "/api/v1/claims",
                data={**_form_data(), **_types(count)},
                files=_files(count),
            )
            assert response.status_code == 201, response.text
            docs = response.json()["documents"]
            assert len(docs) == count + 1
            assert [doc["document_slot"] for doc in docs] == list(range(count + 1))
            proof_docs = docs[1:]
            assert [doc["stored_file_name"] for doc in proof_docs] == [
                f"document_{slot}.pdf" for slot in range(1, count + 1)
            ]
            assert all(doc["document_type"] == "hospital_bill" for doc in proof_docs)
            for slot, doc in enumerate(proof_docs, start=1):
                path = case / "project" / doc["storage_path"]
                assert path.read_bytes() == PROOF_PDF
                assert doc["file_size_bytes"] == len(PROOF_PDF)
                assert doc["checksum_sha256"]
            with factory() as db:
                assert db.query(ClaimDocument).filter_by(claim_id=response.json()["claim_id"]).count() == count + 1
        finally:
            client.close()
            engine.dispose()


def test_single_file_in_later_form_slot_is_compacted(tmp_path, monkeypatch):
    client, _, _, engine = _make_client(tmp_path, monkeypatch)
    try:
        response = client.post(
            "/api/v1/claims",
            data={**_form_data(), "document_3_type": "repair_estimate"},
            files={"policy_document": _file("policy.pdf", POLICY_PDF), "document_3": _file("repair.pdf")},
        )
        assert response.status_code == 201
        docs = response.json()["documents"]
        assert [doc["document_slot"] for doc in docs] == [0, 1]
        assert docs[1]["stored_file_name"] == "document_1.pdf"
        assert docs[1]["document_type"] == "repair_estimate"
    finally:
        client.close()
        engine.dispose()


def test_document_metadata_has_hash_mime_and_exact_size(tmp_path, monkeypatch):
    client, _, storage_root, engine = _make_client(tmp_path, monkeypatch)
    try:
        response = client.post(
            "/api/v1/claims",
            data={**_form_data(), **_types(1)},
            files=_files(1),
        )
        assert response.status_code == 201
        for item, expected in zip(response.json()["documents"], (POLICY_PDF, PROOF_PDF)):
            saved = storage_root / response.json()["claim_id"] / item["stored_file_name"]
            assert saved.read_bytes() == expected
            import hashlib

            assert item["checksum_sha256"] == hashlib.sha256(expected).hexdigest()
            assert item["file_size_bytes"] == len(expected)
            assert item["mime_type"] == "application/pdf"
            assert item["original_file_name"]
    finally:
        client.close()
        engine.dispose()


def test_uploaded_proof_requires_valid_type(tmp_path, monkeypatch):
    client, _, _, engine = _make_client(tmp_path, monkeypatch)
    try:
        missing = client.post(
            "/api/v1/claims",
            data=_form_data(),
            files={"policy_document": _file("policy.pdf", POLICY_PDF), "document_1": _file("proof.pdf")},
        )
        invalid = client.post(
            "/api/v1/claims",
            data={**_form_data(), "document_1_type": "unknown"},
            files={"policy_document": _file("policy.pdf", POLICY_PDF), "document_1": _file("proof.pdf")},
        )
        assert missing.status_code == 422
        assert invalid.status_code == 422
    finally:
        client.close()
        engine.dispose()


def test_unused_document_type_is_rejected(tmp_path, monkeypatch):
    client, _, _, engine = _make_client(tmp_path, monkeypatch)
    try:
        response = client.post(
            "/api/v1/claims",
            data={**_form_data(), "document_2_type": "hospital_bill"},
            files=_files(),
        )
        assert response.status_code == 422
    finally:
        client.close()
        engine.dispose()


def test_missing_policy_document_is_rejected(tmp_path, monkeypatch):
    client, _, _, engine = _make_client(tmp_path, monkeypatch)
    try:
        response = client.post("/api/v1/claims", data=_form_data())
        assert response.status_code == 422
    finally:
        client.close()
        engine.dispose()


def test_more_than_three_proof_files_is_rejected(tmp_path, monkeypatch):
    client, _, storage_root, engine = _make_client(tmp_path, monkeypatch)
    try:
        files = _files(3)
        files["document_4"] = _file("extra.pdf")
        response = client.post(
            "/api/v1/claims",
            data={**_form_data(), **_types(3)},
            files=files,
        )
        assert response.status_code == 422
        assert not storage_root.exists() or not any(storage_root.iterdir())
    finally:
        client.close()
        engine.dispose()


def test_file_extension_and_mime_must_match_content(tmp_path, monkeypatch):
    client, _, storage_root, engine = _make_client(tmp_path, monkeypatch)
    try:
        response = client.post(
            "/api/v1/claims",
            data=_form_data(),
            files={"policy_document": _file("policy.jpg", POLICY_PDF, "image/jpeg")},
        )
        assert response.status_code == 422
        assert not storage_root.exists() or not any(storage_root.iterdir())
    finally:
        client.close()
        engine.dispose()


def test_upload_larger_than_ten_mib_is_rejected(tmp_path, monkeypatch):
    client, _, storage_root, engine = _make_client(tmp_path, monkeypatch)
    try:
        oversized = b"%PDF-1.4\n" + (b"x" * (10 * 1024 * 1024))
        response = client.post(
            "/api/v1/claims",
            data=_form_data(),
            files={"policy_document": _file("policy.pdf", oversized)},
        )
        assert response.status_code == 422
        assert not list(storage_root.iterdir()) if storage_root.exists() else True
    finally:
        client.close()
        engine.dispose()


def test_claim_list_and_detail_include_document_metadata(tmp_path, monkeypatch):
    client, _, _, engine = _make_client(tmp_path, monkeypatch)
    try:
        created = client.post(
            "/api/v1/claims",
            data={**_form_data(), **_types(1)},
            files=_files(1),
        )
        claim_id = created.json()["claim_id"]
        listed = client.get("/api/v1/claims")
        detail = client.get(f"/api/v1/claims/{claim_id}")
        absent = client.get("/api/v1/claims/CLM-00000000000000000000000000000000")
        assert listed.status_code == 200 and len(listed.json()) == 1
        assert detail.status_code == 200 and detail.json()["claim_id"] == claim_id
        assert len(detail.json()["documents"]) == 2
        assert absent.status_code == 404
    finally:
        client.close()
        engine.dispose()


def test_database_failure_rolls_back_files_and_rows(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    sessions = []

    def failing_factory():
        db = factory()
        def fail_commit():
            raise RuntimeError("simulated database failure")

        db.commit = fail_commit
        sessions.append(db)
        return db

    project_root = tmp_path / "project"
    storage_root = project_root / "database" / "local_doc_storage" / "claims"
    monkeypatch.setattr(local_document_storage, "_PROJECT_ROOT", project_root)
    monkeypatch.setattr(local_document_storage, "LOCAL_DOCUMENT_ROOT", storage_root)
    app = FastAPI()
    app.include_router(router)
    app.include_router(documents_router)

    def override_get_db():
        db = failing_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/claims",
            data={**_form_data(), **_types(1)},
            files=_files(1),
        )
        assert response.status_code == 500
        with factory() as db:
            assert db.query(IntakeClaim).count() == 0
            assert db.query(ClaimDocument).count() == 0
        assert not storage_root.exists() or not any(storage_root.iterdir())
    finally:
        client.close()
        engine.dispose()


def test_file_write_failure_rolls_back_and_removes_prior_file(tmp_path, monkeypatch):
    client, factory, storage_root, engine = _make_client(tmp_path, monkeypatch)
    import app.services.claim_service as claim_service_module

    original_save = local_document_storage.save_original_upload
    call_count = 0

    def fail_on_second(claim_id, payload):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OSError("simulated disk failure")
        return original_save(claim_id, payload)

    monkeypatch.setattr(claim_service_module.local_document_storage, "save_original_upload", fail_on_second)
    try:
        response = client.post(
            "/api/v1/claims",
            data={**_form_data(), **_types(1)},
            files=_files(1),
        )
        assert response.status_code == 500
        with factory() as db:
            assert db.query(IntakeClaim).count() == 0
            assert db.query(ClaimDocument).count() == 0
        assert not storage_root.exists() or not any(storage_root.iterdir())
    finally:
        client.close()
        engine.dispose()


def test_intake_runs_existing_ocr_and_returns_persisted_page_text(tmp_path, monkeypatch):
    client, factory, _, engine = _make_client(tmp_path, monkeypatch)
    policy = _text_pdf("POLICY OCR SAMPLE")
    bill = _text_pdf("HOSPITAL BILL OCR SAMPLE 1234")
    try:
        response = client.post(
            "/api/v1/claims",
            data={**_form_data(), "document_1_type": "hospital_bill"},
            files={
                "policy_document": _file("policy.pdf", policy),
                "document_1": _file("bill.pdf", bill),
            },
        )
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["legacy_id"] > 0
        documents_response = client.get(f"/claims/{payload['legacy_id']}/documents")
        assert documents_response.status_code == 200
        documents = documents_response.json()
        assert len(documents) == 2
        assert all(document["ocr_status"] == "completed" for document in documents)
        recognized_text = " ".join(
            page["raw_text"]
            for document in documents
            for page in document["ocr_result"]["pages"]
        )
        assert "POLICY OCR SAMPLE" in recognized_text
        assert "HOSPITAL BILL OCR SAMPLE 1234" in recognized_text
        with factory() as db:
            from app.database.models import OCRResultRecord
            assert db.query(OCRResultRecord).count() == 2
    finally:
        client.close()
        engine.dispose()


def test_invalid_pdf_is_recorded_as_ocr_failure(tmp_path, monkeypatch):
    client, _, _, engine = _make_client(tmp_path, monkeypatch)
    malformed_pdf = b"%PDF-1.4\nnot a valid PDF document\n%%EOF"
    try:
        response = client.post(
            "/api/v1/claims",
            data=_form_data(),
            files={"policy_document": _file("policy.pdf", malformed_pdf)},
        )
        assert response.status_code == 201, response.text
        legacy_id = response.json()["legacy_id"]
        documents = client.get(f"/claims/{legacy_id}/documents").json()
        assert documents[0]["ocr_status"] == "failed"
        assert documents[0]["ocr_result"]["status"] == "failed"
        assert documents[0]["ocr_result"]["errors"]
    finally:
        client.close()
        engine.dispose()


def test_init_db_preserves_existing_integer_claim_table_as_legacy():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE claims (id INTEGER PRIMARY KEY, customer_name TEXT NOT NULL, "
                "claim_amount NUMERIC(10,2) NOT NULL, status TEXT NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO claims (id, customer_name, claim_amount, status) "
                "VALUES (77, 'Legacy Customer', 123.45, 'processing')"
            )
            connection.exec_driver_sql(
                "CREATE TABLE documents (id INTEGER PRIMARY KEY, claim_id INTEGER NOT NULL "
                "REFERENCES claims(id), document_type TEXT NOT NULL, file_name TEXT NOT NULL, file_path TEXT NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO documents (id, claim_id, document_type, file_name, file_path) "
                "VALUES (88, 77, 'hospital_bill', 'bill.pdf', 'storage/claims/77/bill.pdf')"
            )

        init_db(engine)
        inspector = inspect(engine)
        assert inspector.has_table("legacy_claims")
        assert inspector.has_table("claims")
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT id, customer_name FROM legacy_claims WHERE id = 77")
            ).one()
            fk = connection.exec_driver_sql("PRAGMA foreign_key_list(documents)").all()
            document = connection.execute(
                text("SELECT id, claim_id FROM documents WHERE id = 88")
            ).one()
        assert row.id == 77
        assert row.customer_name == "Legacy Customer"
        assert any(item[2] == "legacy_claims" for item in fk)
        assert document.id == 88 and document.claim_id == 77
    finally:
        engine.dispose()
