# 🎬 Demo Flow & Execution Guide

This document outlines how to run and verify both independent systems.

---

## 1. Insurance Pipeline Demo Flow

The goal of the insurance pipeline is to accept and process an insurance claim, producing structured traces viewable in an OTLP trace backend.

### Running the Trace Generator:
1. Start the trace backend and database:
   ```bash
   cd insurance-pipeline
   docker compose up phoenix postgres -d
   ```
2. Start the pipeline API:
   ```bash
   uvicorn app.main:app --port 8000 --reload
   ```
3. Submit a claim or execute the trace generator.
4. View the resulting parent-child trace in the Phoenix UI at [http://localhost:6006](http://localhost:6006).

---

## 2. Pipeline Autopsy Diagnostic Demo Flow

The goal of Pipeline Autopsy is to ingest traces, reconstruct the DAG, and display findings.

### Running Autopsy:
1. Start the Autopsy engine and database:
   ```bash
   cd pipeline-autopsy
   docker compose up --build -d
   ```
2. Autopsy listens for OTLP traces at `http://localhost:8080/v1/traces`.
3. Ingest a trace and inspect the diagnostic post-mortem via:
   - Interactive docs: [http://localhost:8080/docs](http://localhost:8080/docs)
   - Diagnostic endpoints: `GET /v1/executions/{execution_id}/diagnosis`
