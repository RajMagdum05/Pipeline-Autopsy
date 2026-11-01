# 🏥 Insurance Pipeline

An independent, production-grade insurance claim adjudication AI pipeline. It processes submitted medical claims, extracts structured information, evaluates deterministic rules, and emits standard OpenTelemetry spans via OTLP.

> **Independence Rule**: This project is completely decoupled from any downstream diagnostics or UI. It generates standard OpenTelemetry traces according to `/shared-docs/TRACE_CONTRACT.md` and operates reliably whether Pipeline Autopsy is running or stopped.

---

## 🔄 Core Pipeline Services (`app/pipeline_services/`)

```
document_processing (OCR) ──▶ information_extraction (Gemini) ──▶ rule_engine (Adjudication) ──▶ final_result
```

All backend pipeline logic is organized into clean, dedicated service modules under `app/pipeline_services/`:

1. **`ocr/`**:
   - `document_loader.py`: Safe document ingestion, SHA-256 integrity validation, and MIME-type verification.
   - `pdf_inspector.py`: PDF structure inspection, embedded font/text stream detection, and page routing.
   - `page_renderer.py`: High-DPI image rendering for scanned or image-only PDF pages.
   - `image_preprocessor.py`: Grayscale conversion, adaptive thresholding, and noise reduction.
   - `pymupdf_extractor.py`: Fast direct text and word bounding box extraction for digital PDFs.
   - `tesseract_provider.py`: Fallback OCR for scanned pages and image files (PNG/JPG).
   - `normalizer.py`: Unifies raw text into canonical `OCRResult`, `OCRPage`, and `OCRLine` structures.
   - `quality_validator.py`: Page-by-page OCR quality checks to ensure unreadable pages do not reach the LLM.
   - `persistence_service.py`: Stores structured OCR results into the PostgreSQL/SQLite database.
   - `evidence_extractor.py`: Extracts word-level coordinates and line spans for auditability.
   - `orchestrator.py` (`OCRApplicationService`): Coordinates the complete document OCR lifecycle.

2. **`extraction/`**:
   - `extraction_service.py`: Uses Google Gemini to extract structured entities (patient details, diagnosis codes, dates, billing amounts) from validated OCR text, with Pydantic schema validation, sanity checks, retry handling, and source citations.

3. **`rule_engine/`**:
   - `rule_engine_service.py`: Deterministic adjudication evaluating 8 business rules (policy active, coverage limits, covered claim types, waiting periods, deductibles, co-pays, exclusions, and timely filing) to compute approval verdict and payout.

4. **`orchestrator/`**:
   - `pipeline_orchestrator.py` (`run_claim_pipeline`): Orchestrates the complete pipeline under a single root OpenTelemetry trace (`claim_processing`), managing execution state and database persistence.

---

## 🚀 Running Independently

### Option 1: Running with Docker Compose (Recommended)

Starts the Insurance Pipeline API, PostgreSQL database, and Jaeger trace backend:

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Launch container stack
docker compose up --build
```

- **Pipeline API & Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Jaeger trace UI**: [http://localhost:16687](http://localhost:16687)
- **OTLP receivers**: gRPC on `localhost:4327` and HTTP on `localhost:4328`.
- Traces are stored in the `jaeger_data` Docker volume using Badger, with a default 30-day span TTL. Set `JAEGER_TRACE_TTL` to change it (for example, `168h` for 7 days).
- `docker compose down` keeps the trace volume; `docker compose down -v` removes it.

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

## 🧪 Testing

Run all unit and integration tests:

```bash
pytest tests/
```
