from contextlib import asynccontextmanager
from typing import Optional, List
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.api.claims import router as claims_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.telemetry import init_telemetry
from app.database import engine, init_db
from app.stages import execute_claim_pipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables
    init_db()
    yield


app = FastAPI(
    title="Insurance Pipeline — Claims Adjudication & Trace Generator",
    description="Independent insurance claim processing pipeline producing OpenTelemetry OTLP traces.",
    version="1.0.0",
    lifespan=lifespan,
)

# Initialize OpenTelemetry with OTLP exporter, FastAPI, and SQLAlchemy auto-instrumentation
init_telemetry(
    service_name="insurance-pipeline",
    app=app,
    engine=engine,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(claims_router)
app.include_router(documents_router)


class ClaimExecutionRequest(BaseModel):
    raw_document_ids: Optional[List[str]] = None
    execution_id: Optional[str] = None


@app.post("/claims/{claim_id}/execute", tags=["Stages Execution"])
def run_stages_for_claim(
    claim_id: str,
    payload: Optional[ClaimExecutionRequest] = None,
):
    """
    Executes the 5-stage claim pipeline under a single root trace ('insurance_claim_execution')
    emitting parent-child OpenTelemetry spans via OTLP according to TRACE_CONTRACT.md.
    """
    doc_ids = payload.raw_document_ids if payload else None
    exec_id = payload.execution_id if payload else None
    return execute_claim_pipeline(
        claim_id=claim_id,
        raw_document_ids=doc_ids,
        execution_id=exec_id,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
