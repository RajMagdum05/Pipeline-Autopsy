# ⚙️ Pipeline Autopsy Backend Service

Pipeline telemetry ingestion, evidence handling, deterministic diagnosis, and read APIs.

For complete documentation, system architecture, and full-stack setup, please refer to the [Root README](../README.md).

---

## 📦 Directory Overview

- **`api/`**: FastAPI ingestion, manifest, artifact, and schema-v2 read routes, plus API key authentication.
- **`db/`**: SQLAlchemy models (`models.py`), database session manager (`database.py`), and automated table bootstrap (`init_db.py`).
- **`core/`**: Deterministic graph reconstruction, contract checks, and diagnosis.
- **`explain/`**: Deterministic explanation template retained for the explanation bundle.
- **`artifacts/`** and **`manifests/`**: Evidence storage and pipeline manifest registration/validation.
- **`worker/`**: Background diagnosis scheduling and persistence.
- **`services/`**: Core engines:
  - `ingestion_service.py`: OTLP normalization, persistence, and diagnosis scheduling.
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
