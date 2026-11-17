"""Owner-authenticated endpoint for the complete claim workflow."""

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.claim_document_intake.auth import require_claim_access
from app.document_processing.schemas import ProcessClaimRequest
from app.orchestrator.schemas import ClaimRunResponse
from app.orchestrator.service import AdjudicationReplayConflict, claim_run_service
from app.shared.database import get_db


router = APIRouter(prefix="/claims", tags=["claim run"])


@router.post("/{claim_id}/process", response_model=ClaimRunResponse)
def process_claim(claim_id: str, request: ProcessClaimRequest,
                  authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    require_claim_access(db, claim_id, authorization)
    try:
        return claim_run_service.process_claim(db, claim_id, request.config_version)
    except AdjudicationReplayConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
