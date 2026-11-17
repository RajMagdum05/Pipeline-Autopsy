from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

from app.database.models import Claim, ClaimDocument, Document, IntakeClaim
from app.repositories.claim_repository import ClaimRepository
from app.repositories.document_repository import DocumentRepository
from app.storage import local_document_storage
from app.storage.local_document_storage import StoredDocument, UploadPayload


class ClaimService:
    def __init__(
        self,
        claims: ClaimRepository | None = None,
        documents: DocumentRepository | None = None,
    ) -> None:
        self.claims = claims or ClaimRepository()
        self.documents = documents or DocumentRepository()

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
        claim_id = f"CLM-{uuid4().hex.upper()}"
        claim = IntakeClaim(
            claim_id=claim_id,
            policyholder_name=policyholder_name.strip(),
            age=age,
            policy_number=policy_number.strip(),
            incident_date=incident_date,
            description=description.strip(),
            claimed_amount=claimed_amount,
        )
        self.claims.add(db, claim)
        saved_paths: list[str] = []

        try:
            db.flush()
            legacy_claim = Claim(
                customer_name=claim.policyholder_name,
                claim_amount=claim.claimed_amount,
                status="submitted",
            )
            db.add(legacy_claim)
            db.flush()
            claim.legacy_id = legacy_claim.id

            records: list[ClaimDocument] = []
            pipeline_documents: list[Document] = []
            for upload in uploads:
                stored: StoredDocument = local_document_storage.save_original_upload(claim_id, upload)
                saved_paths.append(stored.storage_path)
                records.append(
                    ClaimDocument(
                        claim_id=claim_id,
                        document_slot=stored.document_slot,
                        document_type=stored.document_type,
                        original_file_name=stored.original_file_name,
                        stored_file_name=stored.stored_file_name,
                        storage_path=stored.storage_path,
                        mime_type=stored.mime_type,
                        file_size_bytes=stored.file_size_bytes,
                        checksum_sha256=stored.checksum_sha256,
                        uploaded_at=stored.uploaded_at,
                    )
                )
                pipeline_documents.append(
                    Document(
                        claim_id=legacy_claim.id,
                        document_type=stored.document_type,
                        file_name=stored.original_file_name,
                        file_path=str((local_document_storage.LOCAL_DOCUMENT_ROOT.parents[2] / stored.storage_path).resolve()),
                        ocr_status="pending",
                    )
                )
            self.documents.add_many(db, records)
            db.add_all(pipeline_documents)
            db.commit()
            return claim
        except Exception:
            db.rollback()
            local_document_storage.remove_saved_files(saved_paths)
            raise

    def list_claims(self, db: Session) -> list[IntakeClaim]:
        return self.claims.list(db)

    def get_claim(self, db: Session, claim_id: str) -> IntakeClaim | None:
        return self.claims.get_by_public_id(db, claim_id)
