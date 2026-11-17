from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.document_processing.exceptions import DocumentProcessingError
from app.document_processing.schemas import ProcessDocumentRequest, ProcessDocumentResponse
from app.document_processing.claim_service import claim_document_processing_service
from app.document_processing.schemas import ProcessClaimRequest, ProcessClaimResponse
from app.claim_document_intake.auth import require_claim_access
from app.shared.database import get_db

router = APIRouter(prefix="/documents", tags=["document processing"])
claim_router = APIRouter(prefix="/claims", tags=["document processing"])


@claim_router.post("/{claim_id}/documents/process", response_model=ProcessClaimResponse)
def process_claim_documents(claim_id: str, request: ProcessClaimRequest,
                            authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    try:
        require_claim_access(db, claim_id, authorization)
        return claim_document_processing_service.process_claim(db, claim_id, request.config_version)
    except HTTPException:
        raise
    except DocumentProcessingError as exc:
        return ProcessClaimResponse(run_id="", claim_id=claim_id, status="FAILED", error=str(exc))


@router.post("/process", response_model=ProcessDocumentResponse)
def process_document(request: ProcessDocumentRequest, db: Session = Depends(get_db)):
    # The legacy single-document route cannot enforce the policy-first gate.
    raise HTTPException(status_code=409, detail="Use POST /claims/{claim_id}/documents/process to process a claim policy-first.")
