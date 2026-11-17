"""Owner-authenticated customer result endpoint."""

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.adjudication.models import AdjudicationResult
from app.adjudication.schemas import Decision
from app.claim_document_intake.auth import require_claim_access
from app.document_processing.models import ProcessingRun
from app.final_result.schemas import ClaimResult
from app.final_result.service import build_final_result
from app.shared.database import get_db


router = APIRouter(prefix="/claims", tags=["claim result"])


@router.get("/{claim_id}/result", response_model=ClaimResult)
def get_claim_result(claim_id: str, authorization: str | None = Header(default=None),
                     db: Session = Depends(get_db)):
    require_claim_access(db, claim_id, authorization)
    latest_run = (db.query(ProcessingRun).filter_by(claim_id=claim_id)
                  .order_by(ProcessingRun.started_at.desc(), ProcessingRun.id.desc()).first())
    record = (db.query(AdjudicationResult).filter_by(claim_id=claim_id, run_id=latest_run.id).one_or_none()
              if latest_run else None)
    if record is None:
        raise HTTPException(status_code=409, detail="A final claim result is not available yet.")
    decision = Decision(decision=record.decision, rules_version=record.rules_version,
        payable_amount=record.payable_amount, rules=record.rules)
    return build_final_result(decision, claim_id=claim_id, run_id=str(record.run_id))
