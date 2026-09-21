from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import claims, documents, health
from app.telemetry import init_telemetry
from app.database import engine

# Initialize FastAPI application
app = FastAPI(title="Enterprise Pipeline")

# Initialize OpenTelemetry with OTLP exporter, FastAPI, and SQLAlchemy auto-instrumentation
init_telemetry(
    service_name="enterprise-ocr-service",
    app=app,
    engine=engine,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(claims.router)
app.include_router(documents.router)
