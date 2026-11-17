from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

# Load local server-side configuration before importing services that read it.
# Docker Compose can also inject the same variables directly from its host env.
load_dotenv()

import autopsy_sdk as autopsy
from app.claim_document_intake.api import router as intake_router
from app.document_processing.api import claim_router as claim_document_processing_router
from app.document_processing.api import router as document_processing_router
from app.final_result.api import router as claim_result_router
from app.orchestrator.api import router as claim_run_router
from app.observability.setup import configure_telemetry
from app.shared.database import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_telemetry()
    init_db()
    try:
        yield
    finally:
        autopsy.flush()
        autopsy.shutdown()


app = FastAPI(title="Insurance Claims Pipeline MVP", version="0.1.0", lifespan=lifespan)
app.include_router(intake_router)
app.include_router(document_processing_router)
app.include_router(claim_document_processing_router)
app.include_router(claim_run_router)
app.include_router(claim_result_router)
