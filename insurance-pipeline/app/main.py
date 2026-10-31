from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.claims import router as claims_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.telemetry import init_telemetry
from app.database import engine, init_db


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
