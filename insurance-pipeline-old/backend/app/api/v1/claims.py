from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.claim_intake_schemas import ClaimCreatedResponse, ClaimResponse
from app.database import get_db
from app.models import Document
from app.pipeline_services.ocr import OCRApplicationService
from app.services.claim_service import ClaimService
from app.storage.local_document_storage import (
    PROOF_DOCUMENT_TYPES,
    MAX_UPLOAD_BYTES,
    UploadPayload,
    UploadValidationError,
    validate_upload,
)

router = APIRouter(prefix="/api/v1/claims", tags=["claim intake"])
claim_service = ClaimService()


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
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    return UploadPayload(
        original_file_name=upload.filename or "",
        mime_type=canonical_mime,
        content=content,
        document_type=document_type,
        document_slot=slot,
    )


def _validate_claim_fields(
    *,
    policyholder_name: str,
    age: int,
    policy_number: str,
    incident_date: date,
    description: str,
    claimed_amount: Decimal,
) -> None:
    if not policyholder_name.strip():
        raise HTTPException(status_code=422, detail="Policyholder name is required.")
    if age < 0 or age > 120:
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


@router.post("", response_model=ClaimCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_claim(
    request: Request,
    policyholder_name: str = Form(...),
    age: int = Form(...),
    policy_number: str = Form(...),
    incident_date: date = Form(...),
    description: str = Form(...),
    claimed_amount: Decimal = Form(...),
    policy_document: UploadFile = File(...),
    document_1: UploadFile | None = File(default=None),
    document_1_type: str | None = Form(default=None),
    document_2: UploadFile | None = File(default=None),
    document_2_type: str | None = Form(default=None),
    document_3: UploadFile | None = File(default=None),
    document_3_type: str | None = Form(default=None),
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

    # Reject extra, repeated, or unrecognized uploaded file fields rather than silently ignoring them.
    form = await request.form()
    file_items = [
        (key, value)
        for key, value in form.multi_items()
        if hasattr(value, "filename") and hasattr(value, "read")
    ]
    if len(file_items) > 4:  # Required policy document plus at most three proof documents.
        raise HTTPException(status_code=422, detail="At most three proof documents may be uploaded.")
    allowed_file_fields = {"policy_document", "document_1", "document_2", "document_3"}
    if any(key not in allowed_file_fields for key, _ in file_items):
        raise HTTPException(status_code=422, detail="Only policy_document and document_1 through document_3 are accepted.")
    if sum(1 for key, _ in file_items if key == "policy_document") != 1:
        raise HTTPException(status_code=422, detail="Exactly one policy document is required.")
    if any(sum(1 for item_key, _ in file_items if item_key == key) > 1 for key in allowed_file_fields):
        raise HTTPException(status_code=422, detail="Each document slot accepts only one file.")

    policy_payload = await _read_upload(
        policy_document,
        document_type="policy_document",
        slot=0,
        is_policy=True,
    )
    proof_fields = [
        (1, document_1, _optional_type(document_1_type)),
        (2, document_2, _optional_type(document_2_type)),
        (3, document_3, _optional_type(document_3_type)),
    ]
    proof_payloads: list[UploadPayload] = []
    for source_slot, upload, document_type in proof_fields:
        if upload is None:
            if document_type is not None:
                raise HTTPException(
                    status_code=422,
                    detail=f"document_{source_slot}_type must be omitted when document_{source_slot} is not uploaded.",
                )
            continue
        if document_type is None:
            raise HTTPException(status_code=422, detail=f"document_{source_slot}_type is required for its uploaded file.")
        if document_type not in PROOF_DOCUMENT_TYPES:
            raise HTTPException(status_code=422, detail=f"Unsupported document_{source_slot}_type.")

        # Slots are compacted by upload order, so an upload in form slot 3 alone becomes stored slot 1.
        compact_slot = len(proof_payloads) + 1
        proof_payloads.append(
            await _read_upload(
                upload,
                document_type=document_type,
                slot=compact_slot,
                is_policy=False,
            )
        )

    try:
        claim = claim_service.create_claim(
            db,
            policyholder_name=policyholder_name,
            age=age,
            policy_number=policy_number,
            incident_date=incident_date,
            description=description,
            claimed_amount=claimed_amount,
            uploads=[policy_payload, *proof_payloads],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to save the claim and documents.") from exc

    # Feed the already stored originals into the existing OCR application service.
    # OCR owns loading, extraction, normalization, and persistence; this route only
    # connects the new intake records to that established document pipeline.
    pipeline_documents = (
        db.query(Document)
        .filter(Document.claim_id == claim.legacy_id)
        .order_by(Document.id.asc())
        .all()
    )
    ocr_service = OCRApplicationService()
    for document in pipeline_documents:
        try:
            ocr_service.process_document(document_id=document.id, db=db)
            db.refresh(document)
        except Exception as exc:
            document.ocr_status = "failed"
            document.ocr_result = {
                "document_id": document.id,
                "status": "failed",
                "engine": "unknown",
                "errors": [str(exc)],
                "pages": [],
            }
            db.commit()
            db.refresh(document)

    return ClaimCreatedResponse(
        claim_id=claim.claim_id,
        claim_status=claim.claim_status,
        legacy_id=claim.legacy_id,
        documents=claim.documents,
    )


@router.get("", response_model=list[ClaimResponse])
def list_claims(db: Session = Depends(get_db)):
    return claim_service.list_claims(db)


@router.get("/{claim_id}", response_model=ClaimResponse)
def get_claim(claim_id: str, db: Session = Depends(get_db)):
    claim = claim_service.get_claim(db, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found.")
    return claim
