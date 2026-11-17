from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.claim_document_intake import storage
from app.claim_document_intake.auth import require_claim_access
from app.claim_document_intake.models import ClaimDocument, ClaimDocumentVersion, Claim, Document, IntakeClaim, OCRResultRecord
from app.claim_document_intake.schemas import (ClaimCreatedResponse, ClaimResponse, ClaimDocumentStatusesResponse,
    DocumentReplacementResponse, DocumentStatusResponse)
from app.claim_document_intake.service import claim_intake_service
from app.claim_document_intake.storage import (
    MAX_UPLOAD_BYTES,
    PROOF_DOCUMENT_TYPES,
    UploadPayload,
    UploadValidationError,
    validate_upload,
    save_replacement_upload,
    remove_saved_files,
)
from app.document_processing.models import ProcessedDocument, ProcessingRun, SemanticArtifact
from app.shared.database import get_db


router = APIRouter(tags=["claim and document intake"])


async def _read_upload(upload: UploadFile, *, document_type: str, slot: int, is_policy: bool) -> UploadPayload:
    content = await upload.read(MAX_UPLOAD_BYTES + 1)
    try:
        _, canonical_mime = validate_upload(
            file_name=upload.filename,
            mime_type=upload.content_type,
            content=content,
            is_policy=is_policy,
        )
    except UploadValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return UploadPayload(
        original_file_name=upload.filename or "",
        mime_type=canonical_mime,
        content=content,
        document_type=document_type,
        document_slot=slot,
    )


def _validate_claim_fields(
    *, policyholder_name: str, age: int, policy_number: str, incident_date: date,
    description: str, claimed_amount: Decimal,
) -> None:
    if not policyholder_name.strip():
        raise HTTPException(status_code=422, detail="Policyholder name is required.")
    if not 0 <= age <= 120:
        raise HTTPException(status_code=422, detail="Age must be between 0 and 120.")
    if not policy_number.strip():
        raise HTTPException(status_code=422, detail="Policy number is required.")
    if incident_date > date.today():
        raise HTTPException(status_code=422, detail="Incident date cannot be in the future.")
    if len(description.strip()) < 10:
        raise HTTPException(status_code=422, detail="Description must be at least 10 characters.")
    if not claimed_amount.is_finite() or claimed_amount <= 0:
        raise HTTPException(status_code=422, detail="Claimed amount must be greater than zero.")
    if claimed_amount.as_tuple().exponent < -2 or claimed_amount >= Decimal("10000000000"):
        raise HTTPException(status_code=422, detail="Claimed amount must fit NUMERIC(12,2).")


def _optional_type(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


@router.post("/claims", response_model=ClaimCreatedResponse, status_code=status.HTTP_201_CREATED)
@router.post("/api/v1/claims", response_model=ClaimCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_claim(
    request: Request,
    policyholder_name: str = Form(...),
    age: int = Form(...),
    policy_number: str = Form(...),
    incident_date: date = Form(...),
    description: str = Form(...),
    claimed_amount: Decimal = Form(...),
    policy_document: UploadFile | None = File(default=None),
    document_1: UploadFile | None = File(default=None),
    document_1_type: str | None = Form(default=None),
    document_2: UploadFile | None = File(default=None),
    document_2_type: str | None = Form(default=None),
    document_3: UploadFile | None = File(default=None),
    document_3_type: str | None = Form(default=None),
    documents: list[UploadFile] | None = File(default=None),
    document_types: list[str] | None = Form(default=None),
    db: Session = Depends(get_db),
):
    _validate_claim_fields(
        policyholder_name=policyholder_name,
        age=age,
        policy_number=policy_number,
        incident_date=incident_date,
        description=description,
        claimed_amount=claimed_amount,
    )

    form = await request.form()
    uploaded = [(key, value) for key, value in form.multi_items() if hasattr(value, "filename") and hasattr(value, "read")]
    if len(uploaded) > 4:
        raise HTTPException(status_code=422, detail="At most four documents may be uploaded.")
    allowed_keys = {"policy_document", "document_1", "document_2", "document_3", "documents"}
    if any(key not in allowed_keys for key, _ in uploaded):
        raise HTTPException(status_code=422, detail="Unsupported upload field.")
    if any(sum(1 for found, _ in uploaded if found == key) > 1 for key in allowed_keys - {"documents"}):
        raise HTTPException(status_code=422, detail="Each named upload slot accepts one file.")

    uploads: list[UploadPayload] = []
    if policy_document is not None:
        uploads.append(await _read_upload(policy_document, document_type="policy_document", slot=0, is_policy=True))

    next_proof_slot = 1
    proof_fields = [
        (document_1, _optional_type(document_1_type)),
        (document_2, _optional_type(document_2_type)),
        (document_3, _optional_type(document_3_type)),
    ]
    for source_slot, (upload, document_type) in enumerate(proof_fields, start=1):
        if upload is None:
            if document_type is not None:
                raise HTTPException(status_code=422, detail=f"document_{source_slot}_type requires its document upload.")
            continue
        if document_type not in PROOF_DOCUMENT_TYPES:
            raise HTTPException(status_code=422, detail=f"Unsupported document_{source_slot}_type.")
        uploads.append(await _read_upload(upload, document_type=document_type, slot=next_proof_slot, is_policy=False))
        next_proof_slot += 1

    if documents:
        if document_types is not None and len(document_types) != len(documents):
            raise HTTPException(status_code=422, detail="Provide one document_type for each uploaded document.")
        types = document_types or ["other_supporting_document"] * len(documents)
        for upload, document_type in zip(documents, types):
            if document_type not in PROOF_DOCUMENT_TYPES:
                raise HTTPException(status_code=422, detail=f"Unsupported document_type: {document_type}")
            if next_proof_slot > 3:
                raise HTTPException(status_code=422, detail="At most three supporting documents may be uploaded.")
            uploads.append(await _read_upload(upload, document_type=document_type, slot=next_proof_slot, is_policy=False))
            next_proof_slot += 1
    elif document_types:
        raise HTTPException(status_code=422, detail="document_types requires uploaded documents.")

    if not uploads:
        raise HTTPException(status_code=422, detail="Upload at least one document.")
    try:
        claim = claim_intake_service.create_claim(
            db,
            policyholder_name=policyholder_name,
            age=age,
            policy_number=policy_number,
            incident_date=incident_date,
            description=description,
            claimed_amount=claimed_amount,
            uploads=uploads,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to save the claim and documents.") from exc
    return ClaimCreatedResponse(
        claim_id=claim.claim_id,
        claim_status=claim.claim_status,
        document_ids=[doc.id for doc in claim.documents],
        legacy_id=claim.legacy_id,
        documents=claim.documents,
        claim_access_token=claim._claim_access_token,
    )

@router.get("/claims/{claim_id}/documents/status", response_model=ClaimDocumentStatusesResponse)
def document_statuses(claim_id: str, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    claim = require_claim_access(db, claim_id, authorization)
    attempts = (db.query(ProcessedDocument, ProcessingRun.started_at)
        .join(ProcessingRun, ProcessingRun.id == ProcessedDocument.run_id)
        .filter(ProcessedDocument.claim_id == claim_id)
        .order_by(ProcessingRun.started_at.desc(), ProcessedDocument.attempt_number.desc()).all())
    latest = {}
    for attempt, started_at in attempts:
        latest.setdefault(attempt.intake_document_id, (attempt, started_at))
    result = []
    for document in sorted(claim.documents, key=lambda item: item.document_slot):
        attempt_info = latest.get(document.id)
        attempt = attempt_info[0] if attempt_info else None
        artifact = (db.query(SemanticArtifact).filter_by(processed_document_id=attempt.id, artifact_kind="classification").one_or_none()
                    if attempt is not None else None)
        extraction = (db.query(SemanticArtifact).filter_by(processed_document_id=attempt.id, artifact_kind="extraction").one_or_none()
                      if attempt is not None else None)
        validation = (db.query(SemanticArtifact).filter_by(processed_document_id=attempt.id, artifact_kind="application_validation").one_or_none()
                      if attempt is not None else None)
        payload = artifact.payload if artifact and isinstance(artifact.payload, dict) else {}
        extraction_payload = extraction.payload if extraction and isinstance(extraction.payload, dict) else {}
        validation_payload = validation.payload if validation and isinstance(validation.payload, dict) else {}
        raw_status = attempt.status if attempt else "WAITING_FOR_TEXT_PROCESSING"
        if attempt is not None and attempt.checksum_sha256 != document.checksum_sha256:
            raw_status = "WAITING_FOR_TEXT_PROCESSING"
            payload = {}
            artifact = None
            extraction = None
            extraction_payload = {}
            validation = None
            validation_payload = {}
        if raw_status == "BLOCKED":
            status_text = "waiting_policy_completion"
        elif raw_status in {"CONTENT_MISMATCH", "MISMATCH"} or (artifact and artifact.status == "mismatch"):
            status_text = "content_mismatch"
        elif raw_status in {"REVIEW_REQUIRED", "HUMAN_REVIEW_REQUIRED"} or (artifact and artifact.status == "review_required"):
            status_text = "review_required"
        elif raw_status == "UNREADABLE" or (artifact and artifact.status == "unreadable"):
            status_text = "unreadable"
        elif extraction and extraction.status == "failed":
            status_text = "extraction_failed" if validation_payload.get("status") == "extraction_failed" else "technical_failure"
        elif raw_status == "CLASSIFICATION_FAILED" or (artifact and artifact.status == "classification_failed"):
            status_text = "classification_failed"
        elif (extraction and extraction.status == "review_required") or (validation and validation.status == "review_required"):
            status_text = "review_required"
        elif raw_status in {"TECHNICAL_FAILURE", "FAILED"} or (artifact and artifact.status == "failed"):
            status_text = "technical_failure"
        elif raw_status in {"RUNNING", "CLASSIFYING", "CHECKING_DOCUMENT_TYPE"}:
            status_text = "checking_document_type"
        elif raw_status in {"EXTRACTING", "VALIDATING"}:
            status_text = "extracting" if raw_status == "EXTRACTING" else "validating"
        elif raw_status in {"EXTRACTION_PENDING", "PENDING", "RETRY_REQUIRED"}:
            status_text = "waiting_for_text_processing"
        elif extraction and extraction.status == "complete" and validation and validation.status == "passed" and artifact and artifact.status == "accepted":
            status_text = "complete"
        else:
            status_text = "waiting_for_text_processing"
        is_currently_validated = bool(
            attempt is not None and artifact is not None and extraction is not None and validation is not None
            and attempt.checksum_sha256 == document.checksum_sha256
            and artifact.status == "accepted" and extraction.status == "complete" and validation.status == "passed"
            and artifact.claim_id == claim.claim_id and extraction.claim_id == claim.claim_id and validation.claim_id == claim.claim_id
            and artifact.document_id == attempt.document_id and extraction.document_id == attempt.document_id and validation.document_id == attempt.document_id
            and artifact.input_checksum_sha256 == document.checksum_sha256
            and extraction.input_checksum_sha256 == document.checksum_sha256
            and validation.input_checksum_sha256 == document.checksum_sha256
            and payload.get("detected_type") == document.document_type
            and extraction_payload.get("detected_type") == document.document_type
            and extraction_payload.get("document_type") == document.document_type
        )
        if status_text == "complete" and not is_currently_validated:
            status_text = "review_required"
        result.append(DocumentStatusResponse(
            document_id=document.id, declared_type=document.document_type or "unknown",
            detected_type=payload.get("detected_type"), detected_subtype=payload.get("subtype"),
            status=status_text,
            extraction_status=("complete" if is_currently_validated else extraction.status if extraction else "not_started"),
            extraction_subtype=extraction_payload.get("subtype") if is_currently_validated else None,
            extracted_facts=extraction_payload.get("facts") if is_currently_validated else None,
            extraction_warnings=extraction_payload.get("warnings", []) if is_currently_validated else [],
            validation_reasons=validation_payload.get("reasons", []) if validation and validation.status != "passed" else [],
            validation_issues=(validation_payload.get("report") or {}).get("issues", []) if validation and validation.status != "passed" else [],
            input_checksum_sha256=attempt.checksum_sha256 if attempt else None,
            version_number=document.version_number,
        ))
    return ClaimDocumentStatusesResponse(claim_id=claim_id, documents=result)


@router.put("/claims/{claim_id}/documents/{document_id}", response_model=DocumentReplacementResponse)
async def replace_claim_document(
    claim_id: str, document_id: UUID, file: UploadFile = File(...), document_type: str = Form(...),
    authorization: str | None = Header(default=None), db: Session = Depends(get_db),
):
    claim = require_claim_access(db, claim_id, authorization)
    intake_doc = db.query(ClaimDocument).filter_by(id=document_id, claim_id=claim_id).one_or_none()
    if intake_doc is None:
        raise HTTPException(status_code=404, detail="Document not found for this claim.")
    allowed_types = PROOF_DOCUMENT_TYPES | {"policy_document"}
    if document_type not in allowed_types:
        raise HTTPException(status_code=422, detail="Select one of the supported document types.")
    other_policy = db.query(ClaimDocument.id).filter(ClaimDocument.claim_id == claim_id,
        ClaimDocument.document_type == "policy_document", ClaimDocument.id != intake_doc.id).first()
    if document_type == "policy_document" and other_policy:
        raise HTTPException(status_code=409, detail="This claim already has a policy document. Replace that document instead.")
    upload_payload = await _read_upload(file, document_type=document_type,
        slot=intake_doc.document_slot, is_policy=document_type == "policy_document")
    legacy_claim = db.query(Claim).filter_by(id=claim.legacy_id).one_or_none()
    if legacy_claim is None:
        raise HTTPException(status_code=404, detail="Document association not found.")
    old_path = (storage.PROJECT_ROOT / (intake_doc.storage_path or "")).resolve()
    legacy_doc = db.query(Document).filter_by(claim_id=legacy_claim.id, file_path=str(old_path)).one_or_none()
    if legacy_doc is None or not old_path.is_relative_to(storage.LOCAL_DOCUMENT_ROOT.resolve()):
        raise HTTPException(status_code=404, detail="Document association not found.")
    new_version = intake_doc.version_number + 1
    stored = save_replacement_upload(claim_id, intake_doc.document_slot, new_version, upload_payload)
    old_record = db.query(OCRResultRecord).filter_by(document_id=legacy_doc.id).one_or_none()
    db.add(ClaimDocumentVersion(
        claim_document_id=intake_doc.id, claim_id=claim_id, document_type=intake_doc.document_type,
        original_file_name=intake_doc.original_file_name, stored_file_name=intake_doc.stored_file_name,
        storage_path=intake_doc.storage_path, mime_type=intake_doc.mime_type,
        file_size_bytes=intake_doc.file_size_bytes, checksum_sha256=intake_doc.checksum_sha256,
        version_number=intake_doc.version_number, uploaded_at=intake_doc.uploaded_at,
        ocr_result=legacy_doc.ocr_result,
        ocr_record={"engine": old_record.engine, "engine_version": old_record.engine_version,
                    "result": old_record.result, "created_at": old_record.created_at,
                    "updated_at": old_record.updated_at} if old_record else None,
    ))
    if old_record:
        db.delete(old_record)
    intake_doc.document_type = document_type
    intake_doc.original_file_name = stored.original_file_name
    intake_doc.stored_file_name = stored.stored_file_name
    intake_doc.storage_path = stored.storage_path
    intake_doc.mime_type = stored.mime_type
    intake_doc.file_size_bytes = stored.file_size_bytes
    intake_doc.checksum_sha256 = stored.checksum_sha256
    intake_doc.uploaded_at = stored.uploaded_at
    intake_doc.version_number = new_version
    legacy_doc.document_type = document_type
    legacy_doc.file_name = stored.original_file_name
    legacy_doc.file_path = str((storage.PROJECT_ROOT / stored.storage_path).resolve())
    legacy_doc.ocr_status = "pending"
    legacy_doc.ocr_result = None
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        remove_saved_files([stored.storage_path])
        raise HTTPException(status_code=500, detail="Unable to save the replacement document.") from exc
    return DocumentReplacementResponse(document_id=intake_doc.id, declared_type=document_type,
        version_number=new_version, checksum_sha256=stored.checksum_sha256)


@router.get("/claims", response_model=list[ClaimResponse])
def list_claims(db: Session = Depends(get_db)):
    claims = db.query(IntakeClaim).order_by(IntakeClaim.created_at.desc()).all()
    return [_claim_response(claim) for claim in claims]


@router.get("/claims/{claim_id}", response_model=ClaimResponse)
def get_claim(claim_id: str, db: Session = Depends(get_db)):
    claim = db.query(IntakeClaim).filter_by(claim_id=claim_id).one_or_none()
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found.")
    return _claim_response(claim)


def _claim_response(claim: IntakeClaim) -> dict:
    return {
        "id": claim.id,
        "legacy_id": claim.legacy_id,
        "claim_id": claim.claim_id,
        "policyholder_name": claim.policyholder_name,
        "age": claim.age,
        "policy_number": claim.policy_number,
        "incident_date": claim.incident_date,
        "description": claim.description,
        "claimed_amount": claim.claimed_amount,
        "claim_status": claim.claim_status,
        "created_at": claim.created_at,
        "document_ids": [doc.id for doc in claim.documents],
        "documents": claim.documents,
    }
