# 📋 Pipeline Autopsy — OpenTelemetry Trace Contract

This document defines the strict telemetry contract that any AI pipeline must follow to be observable, reconstructible, and diagnosable by **Pipeline Autopsy**.

> **Single Source of Truth**: The communication between any pipeline (such as `insurance-pipeline`) and `pipeline-autopsy` occurs exclusively via OpenTelemetry traces exported over OTLP following this specification. No shared code or databases exist.

---

## 1. Trace Hierarchy & Execution Model

Every AI pipeline execution must adhere to the following 1-to-1-to-Many hierarchy:

```
Business Entity (e.g., Claim, Order, Transaction)
  └── Execution Attempt (unique per run attempt)
        └── Root Trace (1 root trace per execution attempt)
              ├── Child Span: Stage 1
              ├── Child Span: Stage 2
              │     └── Sub-operation Span (optional)
              └── Child Span: Stage N
```

1. **One Root Trace per Execution**: Exactly one root span must be created for a single pipeline run attempt (e.g. `insurance_claim_execution`).
2. **Stable Entity ID**: Use a stable business identifier across repeated attempts:
   - Insurance: `claim_id`
   - Finance: `transaction_id`
   - Healthcare: `patient_case_id`
3. **Unique Execution ID**: Every single run attempt must generate a unique `execution_id` (e.g. UUID or monotonic run ID `EXEC-001`, `EXEC-002`).
4. **One Span per Stage**: Every major functional stage must execute inside its own child span.
5. **Parent-Child Hierarchy**: All stage spans must be direct or indirect children of the root execution span.

---

## 2. Required Span Attributes

Every span produced by any stage of the pipeline **MUST** contain these 8 required attributes:

| Attribute Key | Type | Description | Example |
|:---|:---|:---|:---|
| `pipeline.name` | `string` | Canonical name of the pipeline | `"insurance-pipeline"` |
| `pipeline.version` | `string` | Version of the executing pipeline | `"1.0.0"` |
| `execution.id` | `string` | Unique identifier for this execution attempt | `"exec_9872_attempt_1"` |
| `execution.entity_id` | `string` | Business entity identifier | `"CLM-2026-0042"` |
| `stage.name` | `string` | Canonical name of the stage | `"document_processing"` |
| `stage.status` | `string` | Execution outcome of the stage (`"success"`, `"failed"`, `"partial"`) | `"success"` |
| `input.artifact_ids` | `string[]` or `string` | List of artifact IDs consumed as input | `["art_raw_invoice_pdf"]` |
| `output.artifact_ids` | `string[]` or `string` | List of artifact IDs generated as output | `["art_ocr_text_json", "art_page_1_png"]` |

---

## 3. Recommended & Contextual Attributes

Where applicable, stages should record semantic attributes:

| Attribute Key | Type | Stage Applicable | Example |
|:---|:---|:---|:---|
| `stage.version` | `string` | All stages | `"1.2.0"` |
| `model.name` | `string` | LLM / Extraction stages | `"gemini-1.5-pro"`, `"gpt-4o"` |
| `model.version` | `string` | LLM / Extraction stages | `"002"` |
| `prompt.version` | `string` | LLM / Extraction stages | `"v2.4-medical-billing"` |
| `retrieval.query` | `string` | RAG / Policy retrieval stages | `"pre-existing condition waiting period cardiac"` |
| `retrieval.chunk_ids` | `string[]` | RAG / Policy retrieval stages | `["chunk_pol_441", "chunk_pol_442"]` |
| `error.type` | `string` | Failed stages | `"TimeoutError"`, `"SchemaValidationError"` |
| `error.message` | `string` | Failed stages | `"PyMuPDF failed to extract text from corrupted page 3"` |
| `validation.rule_id` | `string` | Validation / Rule stages | `"RULE_ROOM_RENT_LIMIT"` |
| `validation.result` | `string` | Validation / Rule stages | `"PASS"`, `"FAIL"`, `"MISSING_DATA"` |

---

## 4. Artifact Reference Rule (No Bloat in Traces)

Spans must remain lightweight and free of PII or large binary payloads.

### 🚫 Strictly Forbidden in Span Attributes:
- Full insurance documents or policy texts
- Full PDFs or image binary blobs
- Base64-encoded files
- Unredacted customer Personally Identifiable Information (PII)
- Massive LLM response payloads exceeding 4 KB

### ✅ Required Pattern:
Store large payloads in an external artifact store (filesystem, S3, MinIO) and record only the artifact pointer IDs inside the span:

```python
span.set_attribute("input.artifact_ids", ["ART-DOC-001"])
span.set_attribute("output.artifact_ids", ["ART-EXTRACTION-001", "ART-RENDERED-PG1"])
```

---

## 5. Telemetry Transport

1. **OTLP Standard**: All spans must be exported using the OpenTelemetry Protocol (`OTLP/HTTP` or `OTLP/gRPC`).
2. **Standard Payload**: Protobuf or JSON according to OpenTelemetry trace specification v1.
3. **Target Endpoints**:
   - Trace Collector / Storage: `http://localhost:4318/v1/traces` (HTTP) or `http://localhost:4317` (gRPC)
   - Arize Phoenix: `http://localhost:6006`
   - Pipeline Autopsy Ingestion: `http://localhost:8080/v1/traces`
