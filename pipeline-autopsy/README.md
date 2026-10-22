# 🔬 Pipeline Autopsy

An independent, pipeline-agnostic diagnostic engine for multi-stage AI systems.

Pipeline Autopsy does **not** process insurance claims or business logic. Its only responsibility is to ingest execution traces produced by AI pipelines via standard OpenTelemetry OTLP, reconstruct execution graphs, detect suspicious or contradictory behavior, perform root-cause analysis, and create evidence-backed findings for engineers.

> **Independence Rule**: This project has zero knowledge of the insurance pipeline's database, internal models, or APIs. It connects only via the standard OpenTelemetry trace contract defined in `/shared-docs/TRACE_CONTRACT.md`.

---

## 🏗️ Core Responsibilities

1. **Trace Ingestion**: Ingests raw OpenTelemetry OTLP protobuf/JSON traces from any pipeline via `POST /v1/traces`.
2. **Execution Graph Reconstruction**: Reconstructs execution DAGs and stage ordering from span parent-child relationships.
3. **Validation & Anomaly Detection**: Runs generic validation rules, schema checks, and evidence discrepancy checks.
4. **Root-Cause Analysis**: Distinguishes upstream root failures from cascading downstream symptoms.
5. **Findings**: Produces evidence-backed diagnostic reports with confidence scores and recommended remediation.

---

## 🚀 Running Independently

### Option 1: Running with Docker Compose (Recommended)

Starts the Pipeline Autopsy engine on port 8080, its dedicated PostgreSQL database, and the documentation website:

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Launch container stack
docker compose up --build
```

- **Autopsy REST API & Docs**: [http://localhost:8080/docs](http://localhost:8080/docs)
- **OTLP Trace Ingestion Endpoint**: `http://localhost:8080/v1/traces`
- **Marketing & Docs Website**: [http://localhost:3000](http://localhost:3000)

### Option 2: Running Locally with Python

```bash
# 1. Create and activate a Python virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env

# 4. Start the engine
uvicorn autopsy.main:app --host 127.0.0.1 --port 8080 --reload
```

---

## ⚙️ Configuration (`.env`)

| Variable | Description | Default |
|:---|:---|:---|
| `AUTOPSY_DATABASE_URL` | PostgreSQL connection string or SQLite fallback | `postgresql+psycopg://autopsy_admin:changeme@localhost:5433/autopsy_db` |
| `GEMINI_API_KEY` | Google Gemini API key for forensic investigation reasoning | Required for LLM forensic agent |

---

## 🧪 Testing

Run all unit and integration tests:

```bash
pytest tests/
```
