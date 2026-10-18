# ⚙️ Pipeline Autopsy Backend Service

Core observability, telemetry normalization, DAG reconstruction, failure detection, and autonomous investigation service.

For complete documentation, system architecture, and full-stack setup, please refer to the [Root README](../README.md).

---

## 📦 Directory Overview

- **`api/`**: FastAPI routing layer (`routes.py`), request/response Pydantic schemas (`schemas.py`), and API key authentication (`auth.py`).
- **`db/`**: SQLAlchemy models (`models.py`), database session manager (`database.py`), and automated table bootstrap (`init_db.py`).
- **`detectors/`**: Modular failure detection heuristics:
  - `ErrorStatusDetector`
  - `ExceptionDetector`
  - `TimeoutDetector`
  - `DependencyFailureDetector`
  - `StructuralTelemetryDetector`
  - `ExplicitValidationDetector`
- **`domain/`**: Pure domain data models, taxonomies, and enums (`enums.py`, `execution.py`, `failure.py`, `evidence.py`).
- **`services/`**: Core engines:
  - `ingestion_service.py`: Standard OpenTelemetry (OTLP/HTTP & Protobuf) normalization and persistence.
  - `reconstruction_service.py`: Deterministic DAG graph builder (`ExecutionGraph`, `ExecutionNode`).
  - `failure_detection_service.py`: Heuristic detector runner and finding aggregator.
  - `root_cause_service.py`: Upstream causal attribution engine and impact graph generator.
  - `diagnosis_service.py`: Deterministic diagnosis builder and Gemini LLM reasoning service.
  - `agent_service.py`: Autonomous ReAct forensic investigation agent and controlled tools.
  - `credential_service.py`: Tenant project onboarding and SHA-256 API key management.

---

## 🚀 Running the Service

```bash
# Start required databases
docker compose -f ../docker-compose.yml up -d

# Activate virtual environment
source ../venv/bin/activate  # or ..\venv\Scripts\activate on Windows

# Start FastAPI server
uvicorn autopsy.main:app --host 127.0.0.1 --port 8080 --reload
```

Interactive API documentation will be available at:  
👉 **`http://localhost:8080/docs`**
