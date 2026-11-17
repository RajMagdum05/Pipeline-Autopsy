"""Owner-authenticated endpoint for the complete claim workflow."""

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app import faults
from app.claim_document_intake.auth import require_claim_access
from app.document_processing.schemas import ProcessClaimRequest
from app.orchestrator.schemas import ClaimRunResponse
from app.orchestrator.service import AdjudicationReplayConflict, claim_run_service
from app.shared.database import get_db


router = APIRouter(prefix="/claims", tags=["claim run"])


@router.post("/{claim_id}/process", response_model=ClaimRunResponse)
def process_claim(claim_id: str, request: ProcessClaimRequest,
                  authorization: str | None = Header(default=None),
                  x_autopsy_fault: str | None = Header(default=None, alias="X-Autopsy-Fault"),
                  db: Session = Depends(get_db)):
    require_claim_access(db, claim_id, authorization)
    try:
        with faults.activate(x_autopsy_fault or request.fault) as active_fault:
            return claim_run_service.process_claim(
                db, claim_id, request.config_version, fault=active_fault,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AdjudicationReplayConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
