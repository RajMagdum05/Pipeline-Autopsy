# 🏥 Enterprise Claims Reference Pipeline

A full-scale enterprise AI reference pipeline demonstrating automated insurance claim adjudication with real-time OpenTelemetry instrumentation to **Pipeline Autopsy**.

For full documentation and system architecture, see the [Root README](../README.md).

---

## 🔄 Pipeline Stages

```
1. Document Ingestion ──> 2. OCR & Normalization ──> 3. OCR Validation
                                                          │
   5. Business Decision <── 4. Rule Engine <── 4. LLM Entity Extraction
```

| Stage ID | Stage Name | Description | Instrumentation |
|:---|:---|:---|:---|
| `document_ingestion` | Document Ingestion | Verifies and stages incoming claims files | OpenTelemetry Span |
| `ocr_extraction` | OCR & Normalization | PyMuPDF text & Tesseract visual extraction | OpenTelemetry Span |
| `ocr_quality_validation`| OCR Validation | Validates character density, confidence & readability | OpenTelemetry Span |
| `gemini_information_extraction`| LLM Extraction | Gemini 1.5 Pro structured billing & diagnosis extraction | OpenTelemetry Span |
| `extraction_validation`| Schema Validation | Asserts JSON schema contracts and field constraints | OpenTelemetry Span |
| `rule_engine_evaluation`| Rule Engine | Independent deterministic business & policy rules | OpenTelemetry Span |
| `claim_decision` | Business Verdict | Final adjudication decision and approval rationale | OpenTelemetry Span |

---

## 🚀 Running the Pipeline

```bash
# Activate virtual environment
source ../venv/bin/activate  # or ..\venv\Scripts\activate on Windows

# Install pipeline dependencies
pip install -r requirements.txt

# Start the enterprise pipeline server (runs on port 8000 by default)
uvicorn app.main:app --port 8000 --reload
```
