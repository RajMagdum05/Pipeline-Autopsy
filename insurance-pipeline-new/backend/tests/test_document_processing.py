"""Synthetic, isolated tests for claim-scoped document processing.

The OCR routing tests mock the OCR call; they do not measure OCR accuracy.
"""
from datetime import date, datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

import pymupdf
import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.claim_document_intake import storage as intake_storage
from app.claim_document_intake.models import Claim, ClaimDocument, Document, IntakeClaim
from app.document_processing.claim_service import ClaimDocumentProcessingService
from app.document_processing.document_loader import DocumentLoader
from app.document_processing.evidence_extractor import EvidencePage, DetailedOCREvidenceResult
from app.document_processing.models import ProcessedDocument, ProcessedPage, ProcessingRun, SemanticArtifact
from app.document_processing.exceptions import DocumentProcessingError
from app.shared.database import Base


def _make_pdf(path: Path, text: str = "Claim policy document contains sufficient native text.", with_image=False):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    if with_image:
        image = Image.new("RGB", (120, 80), "white")
        output = BytesIO()
        image.save(output, format="PNG")
        page.insert_image(pymupdf.Rect(72, 120, 192, 200), stream=output.getvalue())
    doc.save(path)
    doc.close()


@pytest.fixture
def context(tmp_path, monkeypatch):
    root = tmp_path / "project"
    storage_root = root / "storage" / "claims"
    storage_root.mkdir(parents=True)
    monkeypatch.setattr(intake_storage, "PROJECT_ROOT", root)
    monkeypatch.setattr(intake_storage, "LOCAL_DOCUMENT_ROOT", storage_root)
    engine = create_engine(f"sqlite:///{(tmp_path / 'isolated.sqlite').as_posix()}")
    Base.metadata.create_all(engine)
    factory = lambda: Session(engine, expire_on_commit=False)
    claim_id = f"CLM-{uuid4().hex.upper()}"
    with factory() as db:
        intake = IntakeClaim(claim_id=claim_id, policyholder_name="Synthetic", age=35,
            policy_number="TEST", incident_date=date(2020, 1, 1), description="Synthetic test claim details.",
            claimed_amount=100, claim_status="RECEIVED")
        db.add(intake)
        db.flush()
        legacy = Claim(customer_name="Synthetic", claim_amount=100, status="RECEIVED")
        db.add(legacy)
        db.flush()
        intake.legacy_id = legacy.id
        db.commit()
    yield root, storage_root, engine, factory, claim_id
    engine.dispose()


def _add_document(context, role, slot, *, text=None, with_image=False, path_override=None):
    root, storage_root, _, factory, claim_id = context
    folder = storage_root / claim_id
    folder.mkdir(exist_ok=True)
    path = path_override or folder / ("policy_document.pdf" if role == "policy_document" else f"document_{slot}.pdf")
    _make_pdf(path, text or f"This synthetic {role} has enough content for extraction quality checks.", with_image)
    content = path.read_bytes()
    with factory() as db:
        claim = db.query(IntakeClaim).filter_by(claim_id=claim_id).one()
        intake_doc = ClaimDocument(claim_id=claim_id, document_slot=slot, document_type=role,
            original_file_name=path.name, stored_file_name=path.name,
            storage_path=path.relative_to(root).as_posix(), mime_type="application/pdf",
            file_size_bytes=len(content), checksum_sha256=sha256(content).hexdigest())
        db.add(intake_doc)
        db.flush()
        legacy_doc = Document(claim_id=claim.legacy_id, document_type=role, file_name=path.name,
            file_path=str(path.resolve()), ocr_status="pending")
        db.add(legacy_doc)
        db.commit()
        return intake_doc.id, legacy_doc.id, path


def _add_image_proof(context, slot=1):
    root, storage_root, _, factory, claim_id = context
    folder = storage_root / claim_id
    folder.mkdir(exist_ok=True)
    path = folder / f"document_{slot}.png"
    Image.new("RGB", (160, 80), "white").save(path, format="PNG")
    content = path.read_bytes()
    with factory() as db:
        claim = db.query(IntakeClaim).filter_by(claim_id=claim_id).one()
        intake_doc = ClaimDocument(claim_id=claim_id, document_slot=slot, document_type="hospital_bill",
            original_file_name=path.name, stored_file_name=path.name,
            storage_path=path.relative_to(root).as_posix(), mime_type="image/png",
            file_size_bytes=len(content), checksum_sha256=sha256(content).hexdigest())
        db.add(intake_doc)
        db.flush()
        legacy_doc = Document(claim_id=claim.legacy_id, document_type="hospital_bill",
            file_name=path.name, file_path=str(path.resolve()), ocr_status="pending")
        db.add(legacy_doc)
        db.commit()
        return intake_doc.id, path


def _sync_upload_metadata(context, intake_id, path, mime="application/pdf"):
    content = path.read_bytes()
    with context[3]() as db:
        record = db.query(ClaimDocument).filter_by(id=intake_id).one()
        record.file_size_bytes = len(content)
        record.checksum_sha256 = sha256(content).hexdigest()
        record.mime_type = mime
        db.commit()


class FakeExtractor:
    def __init__(self, on_call=None):
        self.calls = []
        self.on_call = on_call

    def extract_evidence(self, validated, **kwargs):
        self.calls.append(validated.file_name)
        if self.on_call:
            self.on_call(validated.file_name)
        page = EvidencePage(page_number=1, width=612, height=792,
            raw_text="Synthetic extracted text with enough useful words.",
            status="DIRECT_TEXT")
        return DetailedOCREvidenceResult(engine="pymupdf", file_name=validated.file_name, total_pages=1, pages=[page])


def _service(monkeypatch, extractor=None):
    service = ClaimDocumentProcessingService()
    if extractor is not None:
        service.extractor = extractor
    monkeypatch.setattr(service, "_check_ocr", lambda _: None)
    # These are OCR-routing tests. Semantic routing is separately mocked/tested.
    service.content_service.process_and_persist = lambda *args, **kwargs: "accepted"
    return service


def test_digital_pdf_native_text_is_extracted_and_reloadable(context):
    doc_id, _, path = _add_document(context, "policy_document", 0)
    _add_document(context, "hospital_bill", 1)
    service = ClaimDocumentProcessingService()
    with context[3]() as db:
        digest, validated = service._validate_file(service._documents_for_claim(db, context[4])[0])
        result = service.extractor.extract_evidence(validated)
        assert "synthetic" in result.pages[0].raw_text.lower()
        assert result.pages[0].status == "DIRECT_TEXT"
        assert digest == sha256(path.read_bytes()).hexdigest()


def test_policy_persisted_before_proof_extraction_and_proofs_separate(context, monkeypatch):
    policy_id, _, _ = _add_document(context, "policy_document", 0)
    proof_a, _, _ = _add_document(context, "hospital_bill", 1)
    proof_b, _, _ = _add_document(context, "medical_report", 2)
    engine = context[2]
    observed = []
    def verify_policy_saved(filename):
        if filename != "policy_document.pdf":
            with context[3]() as check:
                policy = check.query(ProcessedDocument).filter_by(intake_document_id=policy_id).one()
                assert policy.status == "COMPLETED"
                assert check.query(ProcessedPage).filter_by(processed_document_id=policy.id).count() == 1
            observed.append(filename)
    extractor = FakeExtractor(verify_policy_saved)
    service = _service(monkeypatch, extractor)
    original = {p: p.read_bytes() for p in context[1].rglob("*.pdf")}
    with context[3]() as db:
        response = service.process_claim(db, context[4])
    assert response.status == "COMPLETED"
    assert response.proof_document_ids == [str(proof_a), str(proof_b)]
    assert observed == ["document_1.pdf", "document_2.pdf"]
    assert all(path.read_bytes() == original[path] for path in original)
    with context[3]() as fresh:
        run = fresh.query(ProcessingRun).filter_by(id=__import__("uuid").UUID(response.run_id)).one()
        docs = fresh.query(ProcessedDocument).filter_by(run_id=run.id).all()
        assert {row.intake_document_id for row in docs} == {policy_id, proof_a, proof_b}
        assert fresh.query(ProcessedPage).count() == 3
        policy_page = fresh.query(ProcessedPage).join(ProcessedDocument).filter(
            ProcessedDocument.intake_document_id == policy_id).one()
        assert policy_page.confidence_score is None
        assert policy_page.confidence_source.startswith("unavailable: PyMuPDF")
        assert policy_page.disposition == "ACCEPTED"


def test_missing_or_failed_policy_blocks_proof_processing(context, monkeypatch):
    proof_id, _, _ = _add_document(context, "hospital_bill", 1)
    service = _service(monkeypatch, FakeExtractor())
    with context[3]() as db:
        result = service.process_claim(db, context[4])
    assert result.status == "FAILED"
    assert "policy_document" in result.error
    assert service.extractor.calls == []

    policy_id, _, _ = _add_document(context, "policy_document", 0, text="tiny")
    extractor = FakeExtractor()
    service = _service(monkeypatch, extractor)
    # Simulate a failed policy extraction. The exception is persisted on the policy attempt.
    def fail_policy(_, **kwargs):
        raise RuntimeError("synthetic failure")
    extractor.extract_evidence = fail_policy
    with context[3]() as db:
        result = service.process_claim(db, context[4], config_version="failed-policy-v2")
    assert result.status == "FAILED"
    assert result.failed_document_ids == [str(policy_id), str(proof_id)]
    assert extractor.calls == []
    with context[3]() as db:
        blocked = db.query(ProcessedDocument).filter_by(intake_document_id=proof_id).one()
        assert blocked.status == "BLOCKED"


def test_embedded_image_routes_hybrid_and_deduplicates_native_lines(tmp_path, monkeypatch):
    path = tmp_path / "hybrid.pdf"
    _make_pdf(path, with_image=True)
    service = ClaimDocumentProcessingService()
    monkeypatch.setattr(service.extractor, "_ocr_page", lambda image, number: EvidencePage(
        page_number=number, width=image.width, height=image.height,
        raw_text="Claim policy document contains sufficient native text.\nScanned image words", status="TESSERACT_OCR"))
    result = service.extractor.extract_evidence(service.loader.load_and_validate(path))
    assert result.pages[0].status == "HYBRID"
    assert result.pages[0].raw_text.count("Claim policy document") == 1
    assert "Scanned image words" in result.pages[0].raw_text


def test_mixed_pdf_routes_pages_independently(tmp_path, monkeypatch):
    path = tmp_path / "mixed.pdf"
    doc = pymupdf.open()
    text_page = doc.new_page()
    text_page.insert_text((72, 72), "This native page has enough useful policy words.")
    scanned_page = doc.new_page()
    image = Image.new("RGB", (120, 80), "white")
    image_bytes = BytesIO()
    image.save(image_bytes, format="PNG")
    scanned_page.insert_image(pymupdf.Rect(72, 72, 192, 152), stream=image_bytes.getvalue())
    doc.save(path)
    doc.close()
    extractor = ClaimDocumentProcessingService().extractor
    monkeypatch.setattr(extractor, "_ocr_page", lambda image, number: EvidencePage(
        page_number=number, width=image.width, height=image.height,
        raw_text="Synthetic scanned proof content with words", status="TESSERACT_OCR"))
    result = extractor.extract_evidence(DocumentLoader().load_and_validate(path))
    assert [page.status for page in result.pages] == ["DIRECT_TEXT", "TESSERACT_OCR"]
    assert result.engine == "hybrid"


def test_image_proof_uses_ocr_path_and_is_persisted_separately(context, monkeypatch):
    _add_document(context, "policy_document", 0)
    proof_id, image_path = _add_image_proof(context)
    service = _service(monkeypatch, FakeExtractor())
    with context[3]() as db:
        result = service.process_claim(db, context[4])
    assert result.status == "COMPLETED"
    assert result.proof_document_ids == [str(proof_id)]
    assert image_path.exists()


def test_blank_and_unreadable_pdf_pages_are_distinguished(tmp_path, monkeypatch):
    blank_path = tmp_path / "blank.pdf"
    blank = pymupdf.open()
    blank.new_page()
    blank.save(blank_path)
    blank.close()
    extractor = ClaimDocumentProcessingService().extractor
    blank_result = extractor.extract_evidence(DocumentLoader().load_and_validate(blank_path))
    assert blank_result.pages[0].status == "BLANK"

    noisy_path = tmp_path / "unreadable.pdf"
    random_pixels = Image.effect_noise((120, 80), 80).convert("RGB")
    image_bytes = BytesIO()
    random_pixels.save(image_bytes, format="PNG")
    pdf = pymupdf.open()
    pdf_page = pdf.new_page()
    pdf_page.insert_image(pymupdf.Rect(72, 72, 192, 152), stream=image_bytes.getvalue())
    pdf.save(noisy_path)
    pdf.close()
    monkeypatch.setattr(extractor, "_ocr_page", lambda image, number: EvidencePage(
        page_number=number, raw_text="", status="TESSERACT_OCR"))
    unreadable_result = extractor.extract_evidence(DocumentLoader().load_and_validate(noisy_path))
    assert unreadable_result.pages[0].status == "UNREADABLE"


def test_corrupt_and_encrypted_pdf_are_rejected(context, monkeypatch):
    policy_id, _, path = _add_document(context, "policy_document", 0)
    _add_document(context, "hospital_bill", 1)
    original = path.read_bytes()
    path.write_bytes(b"not a PDF")
    _sync_upload_metadata(context, policy_id, path)
    service = ClaimDocumentProcessingService()
    with context[3]() as db:
        with pytest.raises(Exception):
            service._validate_file(service._documents_for_claim(db, context[4])[0])
    path.write_bytes(original)
    encrypted = pymupdf.open()
    encrypted.new_page()
    encrypted.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
    encrypted.close()
    _sync_upload_metadata(context, policy_id, path)
    with context[3]() as db:
        with pytest.raises(Exception, match="password-protected"):
            service._validate_file(service._documents_for_claim(db, context[4])[0])


def test_checksum_mismatch_is_rejected_and_original_is_not_modified(context, monkeypatch):
    _, _, path = _add_document(context, "policy_document", 0)
    _, _, proof_path = _add_document(context, "hospital_bill", 1)
    original = path.read_bytes()
    path.write_bytes(original + b"tamper")
    service = _service(monkeypatch, FakeExtractor())
    with context[3]() as db:
        response = service.process_claim(db, context[4])
    assert response.status == "FAILED"
    assert "differs from its intake metadata" in response.error
    assert proof_path.exists()


def test_repeated_completed_request_reuses_same_run(context, monkeypatch):
    _add_document(context, "policy_document", 0)
    _add_document(context, "hospital_bill", 1)
    service = _service(monkeypatch, FakeExtractor())
    with context[3]() as db:
        first = service.process_claim(db, context[4])
    with context[3]() as db:
        second = service.process_claim(db, context[4])
    assert first.run_id == second.run_id
    with context[3]() as db:
        assert db.query(ProcessingRun).count() == 1


def test_changed_document_checksum_starts_new_run_with_same_config(context, monkeypatch):
    policy_id, _, policy_path = _add_document(context, "policy_document", 0)
    _add_document(context, "hospital_bill", 1)
    service = _service(monkeypatch, FakeExtractor())
    with context[3]() as db:
        first = service.process_claim(db, context[4], config_version="same-config-input-change")
    _make_pdf(policy_path, "Updated synthetic policy schedule with enough extracted document text.")
    _sync_upload_metadata(context, policy_id, policy_path)
    with context[3]() as db:
        second = service.process_claim(db, context[4], config_version="same-config-input-change")
    assert first.run_id != second.run_id
    assert second.status == "COMPLETED"


def test_new_configuration_creates_a_separate_preserved_run(context, monkeypatch):
    _add_document(context, "policy_document", 0)
    _add_document(context, "hospital_bill", 1)
    service = _service(monkeypatch, FakeExtractor())
    with context[3]() as db:
        first = service.process_claim(db, context[4], config_version="routing-v1")
    with context[3]() as db:
        second = service.process_claim(db, context[4], config_version="routing-v2")
    assert first.run_id != second.run_id
    with context[3]() as db:
        assert db.query(ProcessingRun).count() == 2
        assert db.query(ProcessedPage).count() == 4


def test_oversized_and_zero_byte_file_rejected(context, monkeypatch):
    _add_document(context, "policy_document", 0)
    proof_id, _, proof_path = _add_document(context, "hospital_bill", 1)
    monkeypatch.setenv("DOCUMENT_MAX_BYTES", "16")
    service = _service(monkeypatch, FakeExtractor())
    with context[3]() as db:
        response = service.process_claim(db, context[4], config_version="size-test")
    assert response.status == "FAILED"
    assert response.failed_document_ids[0] != str(proof_id)  # policy is checked first
    proof_path.write_bytes(b"")
    with context[3]() as db:
        with pytest.raises(Exception, match="empty"):
            service._validate_file(service._documents_for_claim(db, context[4])[1][0])


def test_proof_failure_is_document_scoped_and_run_is_partial(context, monkeypatch):
    _add_document(context, "policy_document", 0)
    proof_a, _, _ = _add_document(context, "hospital_bill", 1)
    proof_b, _, _ = _add_document(context, "medical_report", 2)
    extractor = FakeExtractor()
    original = extractor.extract_evidence
    def fail_one(validated, **kwargs):
        if validated.file_name == "document_1.pdf":
            raise RuntimeError("synthetic proof failure")
        return original(validated, **kwargs)
    extractor.extract_evidence = fail_one
    service = _service(monkeypatch, extractor)
    with context[3]() as db:
        result = service.process_claim(db, context[4])
    assert result.status == "PARTIAL", result.error
    assert result.failed_document_ids == [str(proof_a)]
    assert result.proof_document_ids == [str(proof_b)]
    with context[3]() as db:
        failed = db.query(ProcessedDocument).filter_by(intake_document_id=proof_a).one()
        assert failed.status == "TECHNICAL_FAILURE"


def test_missing_tesseract_blocks_policy_before_proofs(context, monkeypatch):
    policy_id, _, _ = _add_document(context, "policy_document", 0, with_image=True)
    proof_id, _, _ = _add_document(context, "hospital_bill", 1)
    monkeypatch.setitem(sys.modules, "pytesseract", None)
    service = ClaimDocumentProcessingService()
    with context[3]() as db:
        result = service.process_claim(db, context[4], config_version="ocr-runtime-test")
    assert result.status == "FAILED"
    assert set(result.failed_document_ids) == {str(policy_id), str(proof_id)}
    assert result.proof_document_ids == []


def test_missing_language_data_is_reported(context, monkeypatch):
    _, _, _ = _add_document(context, "policy_document", 0, with_image=True)
    _add_document(context, "hospital_bill", 1)
    service = ClaimDocumentProcessingService()
    monkeypatch.setitem(sys.modules, "pytesseract", SimpleNamespace(
        get_tesseract_version=lambda: "5.0", get_languages=lambda config="": ["eng"]))
    monkeypatch.setenv("TESSERACT_LANGUAGE", "hin")
    with context[3]() as db:
        policy = service._documents_for_claim(db, context[4])[0]
        _, validated = service._validate_file(policy)
    with pytest.raises(DocumentProcessingError, match="language data is unavailable"):
        service._check_ocr(validated)


def test_page_limit_rejects_without_calling_extractor(context, monkeypatch):
    _add_document(context, "policy_document", 0)
    _add_document(context, "hospital_bill", 1)
    monkeypatch.setenv("DOCUMENT_MAX_PAGES", "0")
    extractor = FakeExtractor()
    service = _service(monkeypatch, extractor)
    with context[3]() as db:
        result = service.process_claim(db, context[4], config_version="page-limit-test")
    assert result.status == "FAILED"
    assert extractor.calls == []


def test_active_run_prevents_duplicate_concurrent_run(context, monkeypatch):
    _add_document(context, "policy_document", 0)
    _add_document(context, "hospital_bill", 1)
    with context[3]() as db:
        db.add(ProcessingRun(claim_id=context[4], config_version="busy", status="RUNNING",
            started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)))
        db.commit()
    service = _service(monkeypatch, FakeExtractor())
    with context[3]() as db:
        with pytest.raises(DocumentProcessingError, match="already active"):
            service.process_claim(db, context[4], config_version="busy")
    with context[3]() as db:
        assert db.query(ProcessingRun).filter_by(claim_id=context[4]).count() == 1


def test_page_artifact_persistence_failure_marks_document_failed(context, monkeypatch):
    _add_document(context, "policy_document", 0)
    _add_document(context, "hospital_bill", 1)
    service = _service(monkeypatch, FakeExtractor())
    with context[3]() as db:
        commits = {"count": 0}
        def fail_once(session):
            commits["count"] += 1
            if commits["count"] == 3:
                raise RuntimeError("synthetic database persistence failure")
        event.listen(db, "before_commit", fail_once)
        result = service.process_claim(db, context[4], config_version="db-failure")
        assert result.status == "FAILED"
    with context[3]() as fresh:
        policy = fresh.query(ProcessedDocument).filter_by(role="policy_document").one()
        assert policy.status == "TECHNICAL_FAILURE"
        assert fresh.query(ProcessedPage).count() == 0


def test_retry_exhaustion_requires_human_review_and_blocks_policy_proofs(context, monkeypatch):
    policy_id, _, _ = _add_document(context, "policy_document", 0)
    proof_id, _, _ = _add_document(context, "hospital_bill", 1)
    monkeypatch.setenv("OCR_MAX_ATTEMPTS", "2")
    extractor = FakeExtractor()
    def persistently_short(validated, **kwargs):
        extractor.calls.append(validated.file_name)
        return DetailedOCREvidenceResult(engine="pymupdf", file_name=validated.file_name,
            total_pages=1, pages=[EvidencePage(page_number=1, width=612, height=792,
                raw_text="short", status="DIRECT_TEXT")])
    extractor.extract_evidence = persistently_short
    service = _service(monkeypatch, extractor)
    with context[3]() as db:
        result = service.process_claim(db, context[4], config_version="retry-review-v1")
    assert result.status == "REVIEW_REQUIRED", result.error
    assert set(result.failed_document_ids) == {str(policy_id), str(proof_id)}
    assert extractor.calls == ["policy_document.pdf", "policy_document.pdf"]
    with context[3]() as db:
        attempts = db.query(ProcessedDocument).filter_by(intake_document_id=policy_id).order_by(ProcessedDocument.attempt_number).all()
        assert [row.attempt_number for row in attempts] == [1, 2]
        assert attempts[0].disposition == "RETRY_REQUIRED"
        assert attempts[1].disposition == "HUMAN_REVIEW_REQUIRED"
        assert db.query(ProcessedDocument).filter_by(intake_document_id=proof_id).one().disposition == "BLOCKED"
        assert db.query(ProcessedPage).filter_by(processed_document_id=attempts[1].id).one().validation_reasons


def test_policy_content_gate_blocks_supporting_document_stage(context, monkeypatch):
    policy_id, _, _ = _add_document(context, "policy_document", 0)
    proof_id, _, _ = _add_document(context, "hospital_bill", 1)
    service = _service(monkeypatch, FakeExtractor())
    calls = []
    def require_review(db, processed, normalized, **kwargs):
        calls.append(kwargs["declared_type"])
        return "review_required"
    service.content_service.process_and_persist = require_review
    with context[3]() as db:
        result = service.process_claim(db, context[4], config_version="semantic-policy-block")
    assert result.status == "REVIEW_REQUIRED"
    assert calls == ["policy_document"]
    with context[3]() as db:
        assert db.query(ProcessedDocument).filter_by(intake_document_id=policy_id).one().status == "REVIEW_REQUIRED"
        assert db.query(ProcessedDocument).filter_by(intake_document_id=proof_id).one().disposition == "BLOCKED"


def test_semantic_artifacts_persist_separately_per_document_attempt(context, monkeypatch):
    policy_id, _, _ = _add_document(context, "policy_document", 0)
    proof_id, _, _ = _add_document(context, "hospital_bill", 1)
    service = _service(monkeypatch, FakeExtractor())
    from app.information_extraction.schemas import Classification, EvidenceQuote, HospitalBillExtraction
    from app.information_extraction.content_service import DocumentContentService
    semantic_service = DocumentContentService(model="synthetic-model")
    semantic_service.classify = lambda pages, declared: (Classification(
        detected_type=declared, subtype="schedule" if declared == "policy_document" else "invoice",
        disposition="accepted", evidence=[EvidenceQuote(page_number=1, quote="Synthetic extracted text"),
            EvidenceQuote(page_number=1, quote="enough useful words")]), {"processed_pages": [1], "batch_count": 1, "evidence_errors": []})
    semantic_service.extract = lambda pages, detected, subtype: (HospitalBillExtraction(
        subtype=subtype, facts=[], warnings=[]), {"status": "passed", "reasons": [], "processed_pages": [1],
            "batch_count": 1, "conflicting_fields": [], "consistency_warnings": []})
    service.content_service = semantic_service
    with context[3]() as db:
        result = service.process_claim(db, context[4], config_version="semantic-persistence")
    assert result.status == "COMPLETED"
    with context[3]() as db:
        rows = db.query(SemanticArtifact).order_by(SemanticArtifact.document_id, SemanticArtifact.artifact_kind).all()
        assert len(rows) == 6
        policy_document_id = db.query(ProcessedDocument).filter_by(intake_document_id=policy_id).one().document_id
        proof_document_id = db.query(ProcessedDocument).filter_by(intake_document_id=proof_id).one().document_id
        assert {row.document_id for row in rows} == {policy_document_id, proof_document_id}
        assert {row.artifact_kind for row in rows} == {"classification", "extraction", "application_validation"}
        assert all(row.input_checksum_sha256 and row.prompt_version and row.schema_version for row in rows)
        validations = [row for row in rows if row.artifact_kind == "application_validation"]
        assert all(row.payload["report"]["overall_disposition"] == "accepted" for row in validations)
        assert all(row.payload["report"]["validator_version"] for row in validations)
        assert all(row.payload["report"]["input_version"] == row.input_checksum_sha256 for row in validations)


def test_semantic_extraction_uses_persisted_pages_from_current_quality_accepted_attempt(context):
    from app.information_extraction.content_service import DocumentContentService
    from app.information_extraction.schemas import Classification, EvidenceQuote, HospitalBillExtraction
    from types import SimpleNamespace

    intake_id, legacy_id, path = _add_document(context, "hospital_bill", 1, text="Persisted hospital bill source.")
    digest = sha256(path.read_bytes()).hexdigest()
    now = datetime.now(timezone.utc)
    captured = {}
    service = DocumentContentService(model="synthetic-model")
    service.classify = lambda pages, declared: (
        Classification(detected_type=declared, subtype="invoice", disposition="accepted",
            evidence=[EvidenceQuote(page_number=1, quote="Persisted hospital bill source."),
                EvidenceQuote(page_number=1, quote="hospital bill source")]),
        {"processed_pages": [1], "batch_count": 1, "evidence_errors": []})
    def extract(pages, detected_type, subtype):
        captured["pages"] = pages
        return HospitalBillExtraction(subtype=subtype, facts=[], warnings=[]), {
            "status": "passed", "reasons": [], "processed_pages": [1], "batch_count": 1,
            "conflicting_fields": [], "consistency_warnings": []}
    service.extract = extract
    with context[3]() as db:
        run = ProcessingRun(claim_id=context[4], config_version="persisted-source-test", status="RUNNING", started_at=now)
        db.add(run)
        db.flush()
        processed = ProcessedDocument(run_id=run.id, document_id=legacy_id, intake_document_id=intake_id,
            claim_id=context[4], role="hospital_bill", attempt_number=1, checksum_sha256=digest,
            status="COMPLETED", disposition="ACCEPTED", started_at=now, completed_at=now, configuration={})
        db.add(processed)
        db.flush()
        db.add(ProcessedPage(processed_document_id=processed.id, page_number=1, status="COMPLETED",
            quality_status="PASS", extraction_method="DIRECT_TEXT", engine="pymupdf", disposition="ACCEPTED",
            started_at=now, completed_at=now, raw_text="Persisted hospital bill source.", layout={}))
        db.commit()
        assert service.process_and_persist(db, processed,
            SimpleNamespace(pages=[SimpleNamespace(page_number=1, raw_text="UNSAVED WRONG TEXT")]),
            declared_type="hospital_bill", checksum=digest) == "accepted"
    assert captured["pages"] == [{"page_number": 1, "text": "Persisted hospital bill source."}]
