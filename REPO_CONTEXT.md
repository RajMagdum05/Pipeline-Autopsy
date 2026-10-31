# Pipeline Autopsy Repository Context

This file captures the full architectural and project context of the repository at:
https://github.com/RajMagdum05/Pipeline-Autopsy

It is intended to help with further research and understanding of what the project is building, how it is structured, and which files are important.

---

## 1. Repository Purpose

This repository is not a single application. It contains two independently designed projects connected only through OpenTelemetry traces and a shared specification layer.

The core idea is:

- `insurance-pipeline` generates execution traces for an insurance claims workflow.
- `pipeline-autopsy` ingests those traces and diagnoses what went wrong.
- `shared-docs` defines the contract that keeps both systems independent but compatible.

This is a trace-driven forensic debugging architecture for AI pipelines.

---

## 2. High-Level Architecture

```text
+-------------------------------+
|     insurance-pipeline        |
|  - processes insurance claims |
|  - OCR + extraction + rules   |
|  - emits OpenTelemetry traces |
+---------------+---------------+
                | OTLP / trace export
                v
+-------------------------------+
| Trace Backend / Collector      |
| Phoenix / Langfuse / OTLP     |
+---------------+---------------+
                | trace query / ingestion
                v
+-------------------------------+
|      pipeline-autopsy         |
|  - ingest traces              |
|  - reconstruct execution DAG  |
|  - detect anomalies           |
|  - root cause analysis        |
|  - findings generation        |
+-------------------------------+
```

Important design rule from the repo:

- `insurance-pipeline` and `pipeline-autopsy` must never import each other directly.
- They should be independently runnable.
- They should be connected only via telemetry contracts and documentation.

---

## 3. Top-Level Repository Structure

```text
/
├── README.md
├── .env.example
├── .gitignore
├── insurance-pipeline/
├── pipeline-autopsy/
├── shared-docs/
├── storage/
└── ...
```

### Top-level role map

1. `insurance-pipeline/`
   - Independent claim processing pipeline
   - Business workflow implementation
   - Generates trace data

2. `pipeline-autopsy/`
   - Independent diagnostic and forensic analysis engine
   - Reads traces and identifies defects

3. `shared-docs/`
   - Shared architecture and interoperability contract
   - Defines trace attributes, execution semantics, design boundaries

4. `storage/`
   - Storage-related data folders for claims and telemetry examples

---

## 4. Root README Summary

The root README states this repository contains:

- one project that processes insurance claims
- one project that diagnoses AI execution traces
- shared documentation connecting them only via a documented protocol

This is intentionally a decoupled workspace, not a monolith.

---

## 5. Project 1: insurance-pipeline

### Purpose

This project is a production-grade insurance claim adjudication pipeline. It handles the end-to-end business process of:

- submitting a claim
- extracting claim information from documents
- reading OCR output
- extracting structured data
- retrieving policy data
- running deterministic adjudication logic
- producing a final result
- exporting OpenTelemetry traces

### Core pipeline flow

```text
document_processing (OCR) -> information_extraction (Gemini) -> rule_engine (Adjudication) -> final_result
```

### Core responsibilities

- document intake and validation
- OCR or PDF extraction
- evidence extraction and quality checking
- structured information extraction with LLM
- rule-based decision logic
- execution tracing with OpenTelemetry

### Important files and folders

```text
insurance-pipeline/
├── .env.example
├── .gitignore
├── Dockerfile
├── README.md
├── docker-compose.yml
├── requirements.txt
├── app/
├── frontend/
├── legacy/
├── tests/
└── ...
```

### `app/` contents

```text
insurance-pipeline/app/
├── __init__.py
├── main.py
├── schemas.py
├── api/
├── database/
├── models/
├── pipeline_services/
├── prompts/
├── services/
├── telemetry/
```

### `app/pipeline_services/` summary

This is the main execution logic folder and includes the services described in the README:

```text
insurance-pipeline/app/pipeline_services/
├── ocr/
│   ├── document_loader.py
│   ├── pdf_inspector.py
│   ├── page_renderer.py
│   ├── image_preprocessor.py
│   ├── pymupdf_extractor.py
│   ├── tesseract_provider.py
│   ├── normalizer.py
│   ├── quality_validator.py
│   ├── persistence_service.py
│   ├── evidence_extractor.py
│   └── orchestrator.py
├── extraction/
│   └── extraction_service.py
├── rule_engine/
│   └── rule_engine_service.py
├── orchestrator/
│   └── pipeline_orchestrator.py
```

### What those services do

- `ocr/`
  - handles input docs
  - verifies file integrity
  - inspects PDFs
  - renders pages
  - cleans images
  - extracts text
  - normalizes OCR output
  - validates quality
  - stores OCR results
  - records evidence

- `extraction/`
  - uses Google Gemini to extract patient details, dates, diagnosis codes, amounts, etc.
  - validates output using Pydantic schema

- `rule_engine/`
  - evaluates policy and claim logic
  - applies deterministic adjudication rules
  - produces final decision

- `orchestrator/`
  - runs the full claim-processing pipeline under a root OpenTelemetry trace
  - coordinates state and persistence

### Runtime and tech stack

The project is intended to run as:

- FastAPI app
- Python backend
- PostgreSQL for business data
- OpenTelemetry SDK
- OTLP export
- Phoenix or Langfuse for trace viewing
- Google Gemini for extraction

### Ports and services

- Insurance API: `http://localhost:8000/docs`
- Phoenix trace UI: `http://localhost:6006`

### Launch

Docker Compose:

```bash
cd insurance-pipeline
docker compose up --build
```

Local Python:

```bash
cd insurance-pipeline
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

---

## 6. Project 2: pipeline-autopsy

### Purpose

This project is a diagnostic engine for multi-stage AI systems. It does not process claims. It does not implement business logic. Instead it:

- ingests execution traces
- reconstructs parent-child span relationships
- builds execution graphs
- validates outputs and stage behavior
- detects anomalies
- performs root cause analysis
- generates findings and recommendations

### Core responsibilities

1. Trace ingestion
2. Execution DAG reconstruction
3. Validation and discrepancy detection
4. Downstream impact analysis
5. Root cause ranking
6. Evidence-backed finding generation

### Important files and folders

```text
pipeline-autopsy/
├── .env.example
├── Dockerfile
├── README.md
├── docker-compose.yml
├── requirements.txt
├── autopsy/
├── examples/
├── legacy/
├── packages/
├── tests/
├── website/
└── ...
```

### `autopsy/` folder

```text
pipeline-autopsy/autopsy/
├── README.md
├── __init__.py
├── main.py
├── adapters/
├── api/
├── db/
├── detectors/
├── domain/
├── scripts/
├── services/
├── __pycache__/
```

### `autopsy` component map

- `api/`
  - APIs for trace ingestion and analysis

- `db/`
  - database layer for findings, metadata, execution data

- `detectors/`
  - rules for anomaly detection and schema checks

- `domain/`
  - domain models for traces, stages, findings, execution graphs

- `services/`
  - orchestration and processing logic

- `adapters/`
  - adapters to receive or normalize telemetry inputs

- `scripts/`
  - operational utilities

### Runtime and tech stack

The project is designed to use:

- FastAPI
- Python
- PostgreSQL
- OpenTelemetry trace ingestion
- execution reconstruction algorithms
- validation engine
- optional LLM-based forensic explanation
- web UI for findings review

### Ports and services

- Autopsy API: `http://localhost:8080/docs`
- OTLP ingestion endpoint: `http://localhost:8080/v1/traces`
- Autopsy website: `http://localhost:3000`

### Launch

Docker Compose:

```bash
cd pipeline-autopsy
docker compose up --build
```

Local Python:

```bash
cd pipeline-autopsy
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn autopsy.main:app --host 127.0.0.1 --port 8080 --reload
```

---

## 7. Project 3: shared-docs

This directory stores the architecture contract and shared understanding between the two isolated projects.

### Files

```text
shared-docs/
├── ARCHITECTURE.md
├── DEMO_FLOW.md
├── SYSTEM_ARCHITECTURE.md
├── TRACE_CONTRACT.md
├── learning/
```

### What each important doc covers

#### `ARCHITECTURE.md`
- high-level decoupled architecture
- shows how insurance pipeline and autopsy are connected through OTLP traces
- defines and visualizes the system topology

#### `SYSTEM_ARCHITECTURE.md`
- most important design document
- defines project boundaries and independence rules
- explains execution flow
- describes required trace contract
- lists milestones
- explains what Pipeline Autopsy is not

#### `TRACE_CONTRACT.md`
- defines required span attributes
- standardizes execution model
- explains artifacts and references
- tells what must be included in telemetry for Autopsy to analyze it correctly

#### `DEMO_FLOW.md`
- likely explains how the demo is intended to work end to end

#### `learning/`
- learning or supporting materials for the system

---

## 8. Storage Folder

```text
storage/
├── claims/
└── test_telemetry/
```

This likely stores example claim artifacts, trace samples, or test telemetry that supports demos or local validation.

---

## 9. Core Trace Contract Concepts

The repo emphasizes a standard contract between producer and consumer systems.

### Fundamental model

```text
One claim -> many executions
One execution -> one trace
One trace -> many spans
One span -> one stage or operation
```

### Required span attributes

The docs say each span should include:

- `pipeline.name`
- `pipeline.version`
- `execution.id`
- `execution.entity_id`
- `stage.name`
- `stage.status`
- `input.artifact_ids`
- `output.artifact_ids`

### Artifact rule

Large or sensitive data should not be stored directly in spans. Instead use artifact IDs and store the data elsewhere.

Examples of data not to place in spans:

- full PDFs
- PII
- raw policy docs
- large LLM outputs
- base64 blobs

---

## 10. Example Execution Flow

The repo describes an end-to-end pipeline flow like this:

```text
1. User submits an insurance claim.
2. Insurance pipeline starts one execution.
3. Pipeline generates execution_id.
4. Pipeline creates one OpenTelemetry trace.
5. Each stage emits spans.
6. Large artifacts are stored separately.
7. Trace is exported via OTLP.
8. Trace backend stores the trace.
9. Pipeline Autopsy retrieves the trace.
10. Autopsy reconstructs the execution graph.
11. Autopsy validates stages.
12. Autopsy detects contradictions and suspicious outputs.
13. Autopsy ranks root causes.
14. Autopsy creates evidence-backed findings.
```

---

## 11. Finding Model in Autopsy

The autopsy docs define a finding as an evidence-backed diagnostic result. A finding should include:

- finding_id
- execution_id
- entity_id
- trace_id
- finding_type
- root_cause_stage
- affected_stage_ids
- severity
- confidence
- uncertainty
- evidence
- recommended_action
- created_at
- status

### Example finding categories

- `SERVICE_EXECUTION_FAILURE`
- `OUTPUT_CONTRACT_VIOLATION`
- `SOURCE_EVIDENCE_CONTRADICTION`
- `INVALID_UPSTREAM_INPUT`
- `INDEPENDENT_DOWNSTREAM_FAILURE`
- `DOWNSTREAM_PROPAGATED_SUSPICION`
- `INSUFFICIENT_EVIDENCE`
- `NO_ISSUE_DETECTED`

This tells you the engine is meant to reason over evidence, not just report raw errors.

---

## 12. Why This Repo Matters

This project demonstrates a deeper engineering concept:

- AI systems often fail in ways that are not visible in individual service logs.
- The execution path across stages matters.
- Trace telemetry can reveal what happened and why.
- A diagnosis layer can identify upstream root causes and downstream impacts.

This is relevant to:

- AI observability
- MLOps and AIOps
- LLM pipeline debugging
- root-cause analysis
- trace-based forensic engineering
- multi-stage AI validation

---

## 13. What This Repo Is Not

The docs explicitly say this project is not:

- a general metrics dashboard
- a tracing backend itself
- a logging platform
- a claim processing app in the autopsy project
- a replacement for OpenTelemetry, Jaeger, Tempo, Phoenix, or Langfuse

The autopsy engine is a diagnosis layer, not the original execution system.

---

## 14. Best Files to Read First

If you are doing research, this is the best reading order:

1. `README.md`
2. `shared-docs/SYSTEM_ARCHITECTURE.md`
3. `shared-docs/TRACE_CONTRACT.md`
4. `shared-docs/ARCHITECTURE.md`
5. `insurance-pipeline/README.md`
6. `pipeline-autopsy/README.md`
7. `shared-docs/DEMO_FLOW.md`

These are the most important documents for understanding the system.

---

## 15. Research Directions

Based on the repo, the strongest research themes are:

- OpenTelemetry tracing for LLM pipelines
- parent-child execution graph reconstruction
- semantic validation of AI outputs
- evidence-based root-cause analysis
- artifact tracking and trace contracts
- observability for multi-stage AI systems

---

## 16. Final Summary

This repository is a two-part system:

- `insurance-pipeline` = produces execution data and business processing results
- `pipeline-autopsy` = analyzes traces to find root causes and detect failures
- `shared-docs` = defines the technical contract and design boundaries

It is a practical example of building a forensic analysis system for AI-driven workflows using standard tracing and execution semantics.

---

## 17. File Inventory Snapshot

```text
RajMagdum05/Pipeline-Autopsy/
├── README.md
├── .env.example
├── .gitignore
├── insurance-pipeline/
│   ├── .env.example
│   ├── .gitignore
│   ├── Dockerfile
│   ├── README.md
│   ├── docker-compose.yml
│   ├── requirements.txt
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── schemas.py
│   │   ├── api/
│   │   ├── database/
│   │   ├── models/
│   │   ├── pipeline_services/
│   │   ├── prompts/
│   │   ├── services/
│   │   └── telemetry/
│   ├── frontend/
│   ├── legacy/
│   └── tests/
├── pipeline-autopsy/
│   ├── .env.example
│   ├── Dockerfile
│   ├── README.md
│   ├── docker-compose.yml
│   ├── requirements.txt
│   ├── autopsy/
│   │   ├── README.md
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── adapters/
│   │   ├── api/
│   │   ├── db/
│   │   ├── detectors/
│   │   ├── domain/
│   │   ├── scripts/
│   │   ├── services/
│   │   └── __pycache__/
│   ├── examples/
│   ├── legacy/
│   ├── packages/
│   │   └── autopsy-sdk/
│   ├── tests/
│   └── website/
├── shared-docs/
│   ├── ARCHITECTURE.md
│   ├── DEMO_FLOW.md
│   ├── SYSTEM_ARCHITECTURE.md
│   ├── TRACE_CONTRACT.md
│   └── learning/
├── storage/
│   ├── claims/
│   └── test_telemetry/
└── ...
```

This file can be used as a working context document when continuing research or implementation work.

---

## 18. Short thesis statement

This repository is a demonstration of building a diagnosis layer for AI pipelines using trace-based observability. The core goal is to analyze how a multi-stage AI system executes, identify where it fails, and explain why the failure happened based on evidence rather than assumptions.

---

End of document.
