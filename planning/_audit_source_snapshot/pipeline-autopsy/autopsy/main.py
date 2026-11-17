from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from autopsy.api.routes import router
from autopsy.db.init_db import init_autopsy_db

app = FastAPI(
    title="Pipeline Autopsy — Generalized Observability Engine",
    description="Independent telemetry ingestion, trace normalization, and failure analysis service",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
def startup_event():
    init_autopsy_db()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("autopsy.main:app", host="127.0.0.1", port=8080, reload=True)
