"""
The Collector — Stage 3 (receiving side).

Run it with:  uvicorn collector.main:app --reload

This is what an "Insurance Claims Platform" would be pointed at once they
buy Pipeline Autopsy. It has no idea what OCR, extraction, or RAG mean —
it just accepts trace events and, the moment a pipeline run reports its
final step, runs diagnosis automatically. No "Analyze" button anywhere —
that's a deliberate product constraint, not an oversight.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from . import root_cause, storage
from .schema import TraceEvent

app = FastAPI(title="Pipeline Autopsy — Collector", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    storage.init_db()


@app.post("/v1/trace", status_code=202)
def ingest_trace(event: TraceEvent) -> dict:
    storage.save_trace_event(event)

    if event.is_final_step:
        diagnosis = root_cause.diagnose(event.execution_id)
        return {"received": True, "diagnosis_triggered": True, "status": diagnosis.status}

    return {"received": True, "diagnosis_triggered": False}


@app.get("/v1/executions")
def list_executions() -> list[dict]:
    return storage.list_executions()


@app.get("/v1/executions/{execution_id}")
def get_execution(execution_id: str) -> dict:
    execution = storage.get_execution(execution_id)
    if execution is None:
        raise HTTPException(404, f"No execution '{execution_id}'")
    return {**execution, "steps": storage.get_trace_events(execution_id)}


@app.get("/v1/executions/{execution_id}/diagnosis")
def get_diagnosis(execution_id: str) -> dict:
    diagnosis = storage.get_diagnosis(execution_id)
    if diagnosis is None:
        raise HTTPException(404, f"No diagnosis yet for '{execution_id}' — has the pipeline finished running?")
    return diagnosis


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "autopsy": "watching"}
