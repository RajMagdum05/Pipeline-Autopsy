from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.database import get_db
from app.models import Claim
from app.schemas import ClaimCreate, ClaimResponse

router = APIRouter()
tracer = trace.get_tracer("enterprise_pipeline.claims")


@router.post("/claims", response_model=ClaimResponse, status_code=status.HTTP_201_CREATED)
def create_claim(claim_data: ClaimCreate, db: Session = Depends(get_db)):
    with tracer.start_as_current_span("create_claim") as span:
        span.set_attribute("customer_name", claim_data.customer_name)
        span.set_attribute("claim_amount", float(claim_data.claim_amount))
        span.set_attribute("status", claim_data.status)

        # Create SQLAlchemy ORM model instance
        new_claim = Claim(
            customer_name=claim_data.customer_name,
            claim_amount=claim_data.claim_amount,
            status=claim_data.status,
        )

        # Save to PostgreSQL database
        db.add(new_claim)
        db.commit()
        db.refresh(new_claim)

        span.set_attribute("claim_id", new_claim.id)
        span.set_status(Status(StatusCode.OK))

        # Return created claim
        return new_claim


@router.get("/claims", response_model=list[ClaimResponse])
def get_claims(db: Session = Depends(get_db)):
    with tracer.start_as_current_span("get_claims") as span:
        claims = db.query(Claim).order_by(Claim.id.asc()).all()
        span.set_attribute("claims_count", len(claims))
        span.set_status(Status(StatusCode.OK))
        return claims


@router.get("/claims/{claim_id}", response_model=ClaimResponse)
def get_claim(claim_id: int, db: Session = Depends(get_db)):
    with tracer.start_as_current_span("get_claim") as span:
        span.set_attribute("claim_id", claim_id)
        # Query database for claim matching claim_id
        claim = db.query(Claim).filter(Claim.id == claim_id).first()

        # Return 404 Not Found if claim does not exist
        if not claim:
            span.set_status(Status(StatusCode.ERROR, f"Claim with id {claim_id} not found"))
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Claim with id {claim_id} not found",
            )

        span.set_status(Status(StatusCode.OK))
        # Return found claim object
        return claim


