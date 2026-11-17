"""Full claim-run orchestration against isolated SQLite and synthetic facts."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

from fastapi.testclient import TestClient
from autopsy_sdk.testing import InMemoryCapture, assert_contract
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.adjudication.models import AdjudicationResult
from app.claim_document_intake.models import Claim, ClaimDocument, Document, IntakeClaim
from app.document_processing.models import ProcessedDocument, ProcessingRun, SemanticArtifact
from app.document_processing.schemas import ProcessClaimResponse
from app.main import app
from app.orchestrator.service import claim_run_service
from app.shared.database import Base, get_db


TOKEN = "synthetic-owner-token"


def fact(name, value):
    return {"field_name": name, "raw_value": str(value), "normalized_value": str(value), "field_status": "found"}


def setup(tmp_path, monkeypatch, *, run_status="PARTIAL", policy_accepted=True, bill_date=None, proof_type="hospital_bill"):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    today = date.today()
    claim_id = f"CLM-{uuid4().hex.upper()}"
    run_id = uuid4()
    policy_id, bill_id = uuid4(), uuid4()
    digest = "a" * 64
    with factory() as db:
        claim = IntakeClaim(
            claim_id=claim_id, legacy_id=None, policyholder_name="Asha Rao", age=42,
            policy_number="POL-101", incident_date=today - timedelta(days=2),
            description="Synthetic hospitalization fixture.", claimed_amount=Decimal("100.00"),
            access_token_hash=sha256(TOKEN.encode()).hexdigest(),
        )
        db.add(claim)
        db.flush()
        legacy = Claim(customer_name=claim.policyholder_name, claim_amount=claim.claimed_amount, status="RECEIVED")
        db.add(legacy)
        db.flush()
        claim.legacy_id = legacy.id
        policy_doc = ClaimDocument(claim_id=claim_id, document_slot=0, document_type="policy_document",
            original_file_name="policy.pdf", stored_file_name="policy.pdf", storage_path="synthetic/policy.pdf",
            mime_type="application/pdf", file_size_bytes=10, checksum_sha256=digest)
        bill_doc = ClaimDocument(claim_id=claim_id, document_slot=1, document_type=proof_type,
            original_file_name="proof.pdf", stored_file_name="proof.pdf", storage_path="synthetic/proof.pdf",
            mime_type="application/pdf", file_size_bytes=10, checksum_sha256=digest)
        db.add_all([policy_doc, bill_doc])
        db.flush()
        policy_storage = Document(claim_id=legacy.id, document_type="policy_document", file_name="policy.pdf", file_path="synthetic/policy.pdf")
        bill_storage = Document(claim_id=legacy.id, document_type=proof_type, file_name="proof.pdf", file_path="synthetic/proof.pdf")
        db.add_all([policy_storage, bill_storage])
        db.flush()
        run = ProcessingRun(id=run_id, claim_id=claim_id, config_version="test-config", status=run_status,
                            started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc))
        db.add(run)
        db.flush()

        policy_attempt = ProcessedDocument(run_id=run_id, document_id=policy_storage.id,
            intake_document_id=policy_doc.id, claim_id=claim_id, role="policy_document",
            checksum_sha256=digest, status="COMPLETED" if policy_accepted else "REVIEW_REQUIRED",
            disposition="ACCEPTED" if policy_accepted else "HUMAN_REVIEW_REQUIRED")
        bill_attempt = ProcessedDocument(run_id=run_id, document_id=bill_storage.id,
            intake_document_id=bill_doc.id, claim_id=claim_id, role=proof_type,
            checksum_sha256=digest, status="COMPLETED", disposition="ACCEPTED")
        db.add_all([policy_attempt, bill_attempt])
        db.flush()

        if policy_accepted:
            policy_facts = [fact("policy_number", "POL-101"), fact("policyholder_name", "Asha Rao"),
                fact("coverage_start", (today - timedelta(days=30)).isoformat()),
                fact("coverage_end", (today + timedelta(days=30)).isoformat()), fact("sum_insured", "50000"),
                fact("currency", "INR")]
            _add_accepted_artifacts(db, policy_attempt, claim_id, policy_storage.id, digest,
                "policy_document", {"facts": policy_facts})
        if proof_type == "hospital_bill":
            payment_facts = [fact("admission_date", (bill_date or today - timedelta(days=1)).isoformat()),
                fact("invoice_date", today.isoformat()), fact("total", "150.00"),
                fact("currency", "INR"), fact("patient_name", "Asha Rao")]
        else:
            payment_facts = [fact("patient_name", "Asha Rao")]
        _add_accepted_artifacts(db, bill_attempt, claim_id, bill_storage.id, digest, proof_type,
                                {"facts": payment_facts})
        db.commit()

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr("app.main.init_db", lambda: None)

    class ReusedProcessingService:
        def process_claim(self, db, requested_claim_id, config_version, **kwargs):
            assert requested_claim_id == claim_id
            assert config_version.startswith("test-config")
            return ProcessClaimResponse(run_id=str(run_id), claim_id=claim_id, status=run_status)

    monkeypatch.setattr(claim_run_service, "document_service", ReusedProcessingService())
    return TestClient(app), factory, engine, claim_id


def _add_accepted_artifacts(db, attempt, claim_id, document_id, digest, declared_type, extraction_fields):
    now = datetime.now(timezone.utc)
    shared = {"processed_document_id": attempt.id, "claim_id": claim_id,
              "document_id": document_id, "input_checksum_sha256": digest,
              "attempt_number": 1, "model_id": "synthetic", "started_at": now, "completed_at": now}
    db.add_all([
        SemanticArtifact(**shared, artifact_kind="classification", status="accepted",
            payload={"detected_type": declared_type, "disposition": "accepted"},
            prompt_version="test-classification", schema_version="test-v1"),
        SemanticArtifact(**shared, artifact_kind="extraction", status="complete",
            payload={"detected_type": declared_type, "document_type": declared_type, **extraction_fields},
            prompt_version="test-extraction", schema_version="test-v1"),
        SemanticArtifact(**shared, artifact_kind="application_validation", status="passed",
            payload={"status": "accepted", "disposition": "accepted"},
            prompt_version="test-validation", schema_version="test-v1"),
    ])


def post_process(client, claim_id):
    return client.post(f"/claims/{claim_id}/process", json={"config_version": "test-config"},
                       headers={"Authorization": f"Bearer {TOKEN}"})


def test_fault_header_is_recorded_only_on_run_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("FAULT_INJECTION_ENABLED", "true")
    client, factory, engine, claim_id = setup(tmp_path, monkeypatch, run_status="PARTIAL")
    try:
        with InMemoryCapture() as capture:
            response = client.post(
                f"/claims/{claim_id}/process", json={"config_version": "test-config"},
                headers={"Authorization": f"Bearer {TOKEN}",
                         "X-Autopsy-Fault": "ocr_misread_bill_date"},
            )
        assert response.status_code == 200, response.text
        execution = next(span for span in capture.spans
                         if span.attributes.get("pipeline.span.role") == "execution")
        assert execution.attributes["pipeline.fault.name"] == "ocr_misread_bill_date"
        assert all("pipeline.fault.name" not in span.attributes for span in capture.spans
                   if span is not execution)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_full_claim_run_adjudicates_accepted_partial_run(tmp_path, monkeypatch):
    client, factory, engine, claim_id = setup(tmp_path, monkeypatch, run_status="PARTIAL")
    try:
        with InMemoryCapture() as capture:
            response = post_process(client, claim_id)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "PARTIAL"
        assert body["decision"]["decision"] == "APPROVED"
        assert body["decision"]["rules_version"] == "adjudication-rules-v1"
        assert body["decision"]["payable_amount"] == "100.00"
        with factory() as db:
            result = db.query(AdjudicationResult).filter_by(claim_id=claim_id).one()
            assert result.decision == "APPROVED"
            assert len(result.inputs_checksum) == 64
            assert db.query(IntakeClaim).filter_by(claim_id=claim_id).one().claim_status == "APPROVED"
        final = client.get(f"/claims/{claim_id}/result", headers={"Authorization": f"Bearer {TOKEN}"})
        assert final.status_code == 200, final.text
        assert final.json()["decision"] == "APPROVED"
        assert final.json()["run_id"] == body["run_id"]
        spans = capture.spans
        assert len(spans) == 1
        run_span = spans[0]
        assert run_span.attributes["pipeline.run.id"] == body["run_id"]
        assert run_span.attributes["pipeline.run.outcome"] == "partial"
        pii_values = ("Asha Rao", "POL-101", "100.00", "150.00")
        exported_values = [repr(value) for value in run_span.attributes.values()]
        exported_values.extend(
            repr(value)
            for event in run_span.events
            for value in event.attributes.values()
        )
        for pii in pii_values:
            assert all(pii not in value for value in exported_values)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_out_of_coverage_bill_is_rejected(tmp_path, monkeypatch):
    client, factory, engine, claim_id = setup(tmp_path, monkeypatch, run_status="COMPLETED",
        bill_date=date.today() - timedelta(days=40))
    try:
        response = post_process(client, claim_id)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["decision"]["decision"] == "REJECTED"
        service_rule = next(row for row in body["decision"]["rules"] if row["rule_id"] == "rule.service_in_coverage")
        assert service_rule["reason_code"] == "SERVICE_BEFORE_COVERAGE"
        final = client.get(f"/claims/{claim_id}/result", headers={"Authorization": f"Bearer {TOKEN}"})
        assert final.status_code == 200
        assert final.json()["reasons"][0]["rule_id"] == "rule.service_in_coverage"
        with factory() as db:
            assert db.query(IntakeClaim).filter_by(claim_id=claim_id).one().claim_status == "REJECTED"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_blocked_policy_never_creates_adjudication_result(tmp_path, monkeypatch):
    client, factory, engine, claim_id = setup(tmp_path, monkeypatch, run_status="REVIEW_REQUIRED", policy_accepted=False)
    try:
        with InMemoryCapture() as capture:
            response = post_process(client, claim_id)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "BLOCKED"
        assert response.json()["decision"] is None
        spans = capture.spans
        assert len(spans) == 1
        assert "proof" in spans[0].attributes["pipeline.run.items"][1]
        assert all("pipeline.span.role" not in span.attributes or span.attributes["pipeline.span.role"] != "stage"
                   for span in spans)
        final = client.get(f"/claims/{claim_id}/result", headers={"Authorization": f"Bearer {TOKEN}"})
        assert final.status_code == 409
        with factory() as db:
            assert db.query(AdjudicationResult).filter_by(claim_id=claim_id).count() == 0
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_same_run_and_inputs_replay_persisted_decision(tmp_path, monkeypatch):
    client, factory, engine, claim_id = setup(tmp_path, monkeypatch, run_status="COMPLETED")
    try:
        first = post_process(client, claim_id)
        second = post_process(client, claim_id)
        assert first.status_code == second.status_code == 200
        assert first.json()["decision"] == second.json()["decision"]
        with factory() as db:
            assert db.query(AdjudicationResult).filter_by(claim_id=claim_id).count() == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_full_claim_run_requires_owner_token(tmp_path, monkeypatch):
    client, _, engine, claim_id = setup(tmp_path, monkeypatch, run_status="COMPLETED")
    try:
        response = client.post(f"/claims/{claim_id}/process", json={"config_version": "test-config"})
        assert response.status_code == 404
        result_response = client.get(f"/claims/{claim_id}/result")
        assert result_response.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


@pytest.mark.parametrize(
    "bill_offset_days,expected_decision,expected_rule,force_retry,block_policy",
    [(0, "APPROVED", "pass", False, False), (-40, "REJECTED", "fail", False, False),
     (0, None, None, True, False), (0, None, None, False, True)],
)
def test_claim_run_executes_document_pipeline_with_mocked_gemini(
    tmp_path, monkeypatch, bill_offset_days, expected_decision, expected_rule, force_retry, block_policy,
):
    """Exercise the real PDF/OCR/persistence path while stubbing Gemini responses."""
    import pymupdf

    from app.claim_document_intake import storage
    from app.document_processing.claim_service import ClaimDocumentProcessingService

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    project_root = tmp_path / "project"
    document_root = project_root / "storage" / "claims"
    monkeypatch.setattr(storage, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(storage, "LOCAL_DOCUMENT_ROOT", document_root)
    today = date.today()
    claim_id = f"CLM-{uuid4().hex.upper()}"
    claim_dir = document_root / claim_id
    claim_dir.mkdir(parents=True)

    coverage_start = (today - timedelta(days=30)).isoformat()
    coverage_end = (today + timedelta(days=30)).isoformat()
    bill_date = (today + timedelta(days=bill_offset_days)).isoformat()
    policy_text = f"POLICY SCHEDULE number POL-101 policyholder Asha Rao coverage {coverage_start} through {coverage_end} currency INR sum insured 50000."
    bill_text = f"HOSPITAL BILL patient Asha Rao admission {bill_date} total INR 150.00 invoice {today.isoformat()}."

    def write_pdf(path, text):
        pdf = pymupdf.open()
        page = pdf.new_page()
        page.insert_text((40, 60), text)
        pdf.save(path)
        pdf.close()

    policy_path, bill_path = claim_dir / "policy.pdf", claim_dir / "bill.pdf"
    write_pdf(policy_path, policy_text)
    write_pdf(bill_path, bill_text)

    with factory() as db:
        claim = IntakeClaim(claim_id=claim_id, policyholder_name="Asha Rao", age=42,
            policy_number="POL-101", incident_date=today - timedelta(days=1),
            description="Synthetic hospitalization fixture.", claimed_amount=Decimal("100.00"),
            access_token_hash=sha256(TOKEN.encode()).hexdigest())
        db.add(claim)
        db.flush()
        legacy = Claim(customer_name=claim.policyholder_name, claim_amount=claim.claimed_amount, status="RECEIVED")
        db.add(legacy)
        db.flush()
        claim.legacy_id = legacy.id
        for slot, kind, path in ((0, "policy_document", policy_path), (1, "hospital_bill", bill_path)):
            content = path.read_bytes()
            relative_path = path.relative_to(project_root).as_posix()
            intake_doc = ClaimDocument(claim_id=claim_id, document_slot=slot, document_type=kind,
                original_file_name=path.name, stored_file_name=path.name, storage_path=relative_path,
                mime_type="application/pdf", file_size_bytes=len(content), checksum_sha256=sha256(content).hexdigest())
            db.add(intake_doc)
            db.flush()
            db.add(Document(claim_id=legacy.id, document_type=kind, file_name=path.name, file_path=str(path.resolve())))
        db.commit()

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr("app.main.init_db", lambda: None)

    processor = ClaimDocumentProcessingService()
    if force_retry:
        # Keep policy quality normal and apply a deterministic high threshold only
        # to the shorter bill so the real retry path runs twice for that document.
        validate_file = processor._validate_file

        def validate_with_bill_retry(item):
            if item[3] != "policy_document":
                processor.quality_config.min_character_count = 250
            return validate_file(item)

        processor._validate_file = validate_with_bill_retry

    def mock_gemini_and_persist(db, processed, normalized, *, declared_type, checksum):
        values = (
            [("policy_number", "POL-101"), ("policyholder_name", "Asha Rao"),
             ("coverage_start", coverage_start), ("coverage_end", coverage_end),
             ("sum_insured", "50000"), ("currency", "INR")]
            if declared_type == "policy_document" else
            [("admission_date", bill_date), ("invoice_date", today.isoformat()),
             ("total", "150.00"), ("currency", "INR"), ("patient_name", "Asha Rao")]
        )
        facts = [{"field_name": name, "raw_value": value, "normalized_value": value,
                  "field_status": "found", "evidence": [{"page_number": 1, "quote": value}]}
                 for name, value in values]
        now = datetime.now(timezone.utc)
        shared = {"processed_document_id": processed.id, "claim_id": processed.claim_id,
                  "document_id": processed.document_id, "input_checksum_sha256": checksum,
                  "attempt_number": processed.attempt_number, "model_id": "synthetic-gemini",
                  "started_at": now, "completed_at": now}
        db.add_all([
            SemanticArtifact(**shared, artifact_kind="classification", status="accepted",
                payload={"detected_type": declared_type, "disposition": "accepted"},
                prompt_version="mock-classification", schema_version="mock-v1"),
            SemanticArtifact(**shared, artifact_kind="extraction", status="complete",
                payload={"detected_type": declared_type, "document_type": declared_type, "facts": facts},
                prompt_version="mock-extraction", schema_version="mock-v1"),
            SemanticArtifact(**shared, artifact_kind="application_validation", status="passed",
                payload={"status": "accepted", "disposition": "accepted"},
                prompt_version="mock-validation", schema_version="mock-v1"),
        ])
        db.flush()
        return "content_mismatch" if block_policy and declared_type == "policy_document" else "accepted"

    processor.content_service.process_and_persist = mock_gemini_and_persist
    monkeypatch.setattr(claim_run_service, "document_service", processor)
    try:
        client = TestClient(app)
        with InMemoryCapture() as capture:
            response = client.post(f"/claims/{claim_id}/process", json={"config_version": "mocked-gemini"},
                headers={"Authorization": f"Bearer {TOKEN}"})
        assert response.status_code == 200, response.text
        body = response.json()
        spans = capture.spans
        assert spans and any(span.attributes.get("pipeline.span.role") == "execution" for span in spans)
        manifest = {"stages": [{"name": "document_processing", "scope": "item"}]}
        assert assert_contract(spans, manifest) == "A"
        document_stages = [span for span in spans if span.attributes.get("pipeline.span.role") == "stage"]
        assert document_stages
        assert all(span.attributes["pipeline.stage.name"] == "document_processing" for span in document_stages)
        if force_retry:
            proof_attempts = sorted(
                span.attributes["pipeline.stage.attempt"] for span in document_stages
                if span.attributes["pipeline.stage.item_role"] == "proof"
            )
            assert proof_attempts == [1, 2]
            assert body["status"] == "REVIEW_REQUIRED"
            assert any(
                event.attributes.get("pipeline.check.id") == "ocr.retry_exhausted"
                for span in spans for event in span.events
            )
        elif block_policy:
            run_span = next(span for span in spans if span.attributes.get("pipeline.span.role") == "execution")
            assert body["status"] == "BLOCKED"
            assert any(item.endswith(":proof") for item in run_span.attributes["pipeline.run.items"])
            assert [span.attributes["pipeline.stage.item_role"] for span in document_stages] == ["policy"]
        else:
            assert body["status"] == "COMPLETED", body
            assert body["decision"]["decision"] == expected_decision
            service_rule = next(row for row in body["decision"]["rules"] if row["rule_id"] == "rule.service_in_coverage")
            assert service_rule["result"] == expected_rule
        pii_values = ("Asha Rao", "POL-101", "100.00", "150.00")
        exported_values = []
        for span in spans:
            exported_values.extend(repr(value) for value in span.attributes.values())
            exported_values.extend(
                repr(value)
                for event in span.events
                for value in event.attributes.values()
            )
        for pii in pii_values:
            assert all(pii not in value for value in exported_values)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
