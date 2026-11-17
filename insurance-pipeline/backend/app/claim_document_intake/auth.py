"""Opaque claim-owner token checks for document status and replacement operations."""
from hashlib import sha256
import hmac

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.claim_document_intake.models import IntakeClaim


def require_claim_access(db: Session, claim_id: str, authorization: str | None) -> IntakeClaim:
    claim = db.query(IntakeClaim).filter_by(claim_id=claim_id).one_or_none()
    if claim is None or not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=404, detail="Claim not found or access denied.")
    token = authorization[7:].strip()
    if not claim.access_token_hash or not token:
        raise HTTPException(status_code=404, detail="Claim not found or access denied.")
    supplied = sha256(token.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(supplied, claim.access_token_hash):
        raise HTTPException(status_code=404, detail="Claim not found or access denied.")
    return claim
