from datetime import date
from decimal import Decimal
from hashlib import sha256
import secrets
from uuid import uuid4

from sqlalchemy.orm import Session

from app.claim_document_intake.models import Claim, ClaimDocument, Document, IntakeClaim
from app.claim_document_intake.storage import (
    StoredDocument,
    UploadPayload,
    remove_saved_files,
    save_original_upload,
)
from app.shared.database import PROJECT_ROOT


class ClaimIntakeService:
    def create_claim(
        self,
        db: Session,
        *,
        policyholder_name: str,
        age: int,
        policy_number: str,
        incident_date: date,
        description: str,
        claimed_amount: Decimal,
        uploads: list[UploadPayload],
    ) -> IntakeClaim:
        public_id = f"CLM-{uuid4().hex.upper()}"
        access_token = secrets.token_urlsafe(32)
        claim = IntakeClaim(
            claim_id=public_id,
            policyholder_name=policyholder_name.strip(),
            age=age,
            policy_number=policy_number.strip(),
            incident_date=incident_date,
            description=description.strip(),
            claimed_amount=claimed_amount,
            claim_status="RECEIVED",
            access_token_hash=sha256(access_token.encode("utf-8")).hexdigest(),
        )
        # Returned once to the submitting client; only its hash is persisted.
        claim._claim_access_token = access_token
        saved_paths: list[str] = []
        try:
            db.add(claim)
            db.flush()
            legacy_claim = Claim(
                customer_name=claim.policyholder_name,
                claim_amount=claim.claimed_amount,
                status="RECEIVED",
            )
            db.add(legacy_claim)
            db.flush()
            claim.legacy_id = legacy_claim.id

            legacy_documents = []
            for upload in uploads:
                stored: StoredDocument = save_original_upload(public_id, upload)
                saved_paths.append(stored.storage_path)
                claim.documents.append(ClaimDocument(
                    document_slot=stored.document_slot,
                    document_type=stored.document_type,
                    original_file_name=stored.original_file_name,
                    stored_file_name=stored.stored_file_name,
                    storage_path=stored.storage_path,
                    mime_type=stored.mime_type,
                    file_size_bytes=stored.file_size_bytes,
                    checksum_sha256=stored.checksum_sha256,
                    uploaded_at=stored.uploaded_at,
                ))
                legacy_documents.append(Document(
                    claim_id=legacy_claim.id,
                    document_type=stored.document_type,
                    file_name=stored.original_file_name,
                    file_path=str((PROJECT_ROOT / stored.storage_path).resolve()),
                    ocr_status="pending",
                ))
            db.add_all(legacy_documents)
            db.commit()
            db.refresh(claim)
            return claim
        except Exception:
            db.rollback()
            remove_saved_files(saved_paths)
            raise


claim_intake_service = ClaimIntakeService()
