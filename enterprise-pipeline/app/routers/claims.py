from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.database import get_db
from app.models import Claim, ExtractionResultRecord, RuleEvaluationRecord
from app.schemas import ClaimCreate, ClaimResponse
from app.services.pipeline_orchestrator import run_claim_pipeline

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


@router.post("/claims/{claim_id}/process")
def process_claim_endpoint(claim_id: int, db: Session = Depends(get_db)):
    """
    Triggers the end-to-end enterprise claim pipeline execution for the given claim.
    """
    with tracer.start_as_current_span("process_claim_endpoint") as span:
        span.set_attribute("claim_id", claim_id)
        claim = db.query(Claim).filter(Claim.id == claim_id).first()
        if not claim:
            span.set_status(Status(StatusCode.ERROR, f"Claim with id {claim_id} not found"))
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Claim with id {claim_id} not found",
            )
        try:
            result = run_claim_pipeline(claim_id=claim_id, db=db)
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Pipeline execution failed: {str(exc)}",
            )


@router.get("/claims/{claim_id}/execution")
def get_claim_execution(claim_id: int, db: Session = Depends(get_db)):
    """
    Retrieves the latest persisted pipeline execution results (extraction and rule decision) for a claim.
    """
    with tracer.start_as_current_span("get_claim_execution") as span:
        span.set_attribute("claim_id", claim_id)
        claim = db.query(Claim).filter(Claim.id == claim_id).first()
        if not claim:
            span.set_status(Status(StatusCode.ERROR, f"Claim with id {claim_id} not found"))
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Claim with id {claim_id} not found",
            )

        extraction = (
            db.query(ExtractionResultRecord)
            .filter(ExtractionResultRecord.claim_id == claim_id)
            .order_by(ExtractionResultRecord.id.desc())
            .first()
        )

        rule_eval = (
            db.query(RuleEvaluationRecord)
            .filter(RuleEvaluationRecord.claim_id == claim_id)
            .order_by(RuleEvaluationRecord.id.desc())
            .first()
        )

        if not extraction and not rule_eval:
            span.set_status(Status(StatusCode.OK))
            return None

        span.set_status(Status(StatusCode.OK))
        return {
            "claim_id": claim_id,
            "customer_name": claim.customer_name,
            "status": claim.status,
            "extraction": {
                "claim_id": extraction.claim_id if extraction else claim_id,
                "execution_id": extraction.execution_id if extraction else "",
                "source_document_ids": extraction.source_document_ids if extraction else [],
                "extraction_prompt_version": extraction.extraction_prompt_version if extraction else "v1.0.0",
                "extraction_model": extraction.extraction_model if extraction else "gemini-2.5-flash",
                "extraction_status": extraction.extraction_status if extraction else "NONE",
                "extracted_data": extraction.extracted_data if extraction else {},
                "validation_errors": extraction.validation_errors if extraction else [],
            } if extraction else None,
            "decision": {
                "claim_id": rule_eval.claim_id if rule_eval else claim_id,
                "execution_id": rule_eval.execution_id if rule_eval else "",
                "decision": rule_eval.decision if rule_eval else claim.status,
                "decision_reason": rule_eval.decision_reason if rule_eval else "",
                "total_rules": rule_eval.total_rules if rule_eval else 0,
                "passed_rules": rule_eval.passed_rules if rule_eval else 0,
                "failed_rules": rule_eval.failed_rules if rule_eval else 0,
                "missing_data_rules": rule_eval.missing_data_rules if rule_eval else 0,
                "evaluated_rules": rule_eval.evaluated_rules if rule_eval else [],
            } if rule_eval else None,
        }



