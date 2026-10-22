# 🏥 Insurance Pipeline

An independent, production-grade insurance claim adjudication AI pipeline. It processes submitted medical claims, extracts structured information, evaluates deterministic rules, and emits standard OpenTelemetry spans via OTLP.

> **Independence Rule**: This project is completely decoupled from any downstream diagnostics or UI. It generates standard OpenTelemetry traces according to `/shared-docs/TRACE_CONTRACT.md` and operates reliably whether Pipeline Autopsy is running or stopped.

---

## 🔄 Core Pipeline Stages

```
document_processing ──> information_extraction ──> policy_retrieval ──> claim_decision ──> decision_validation
```

1. **Document Processing**: Staging, PDF text extraction, rendering, and OCR preprocessing.
2. **Information Extraction**: LLM-assisted structured extraction of patient, billing, and diagnosis records.
3. **Policy Retrieval**: Policy term lookup and RAG similarity matching.
4. **Claim Decision**: Business adjudication and rule evaluation.
5. **Decision Validation**: Deterministic sanity checks and compliance guardrails.

---

## 🚀 Running Independently

### Option 1: Running with Docker Compose (Recommended)

Starts the Insurance Pipeline API, PostgreSQL database (with pgvector), and Arize Phoenix trace visualizer:

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Launch container stack
docker compose up --build
```

- **Pipeline API & Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Phoenix Trace Viewer**: [http://localhost:6006](http://localhost:6006)

### Option 2: Running Locally with Python

```bash
# 1. Create and activate a Python virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env

# 4. Start the application
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

---

## ⚙️ Configuration (`.env`)

| Variable | Description | Default |
|:---|:---|:---|
| `DATABASE_URL` | PostgreSQL connection string or SQLite fallback | `postgresql+psycopg://pipeline:changeme@localhost:5432/insurance_pipeline` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Target OTLP trace ingestion endpoint | `http://127.0.0.1:4318/v1/traces` |
| `GEMINI_API_KEY` | Google Gemini API key for structured extraction | Required for AI extraction stages |

---

## 🧪 Testing

Run all unit and integration tests:

```bash
pytest tests/
```
