# Pipeline Autopsy — System Architecture

## 1. Project Purpose

Pipeline Autopsy is an independent diagnostic system for multi-stage AI pipelines.

It does not execute business pipelines. It analyzes execution traces produced by AI pipelines, reconstructs what happened, detects suspicious or incorrect behavior, identifies downstream impact, and produces evidence-backed findings for engineers.

The first demonstration domain is an insurance claims pipeline, but Pipeline Autopsy must remain pipeline-agnostic.

## 2. Core Principle

The system is divided into two independent projects:

1. **Insurance Pipeline**
2. **Pipeline Autopsy**

They must never depend on each other’s code, database models, APIs, Docker setup, requirements, or business logic.

They connect only through a standard OpenTelemetry-based trace contract.

## 3. High-Level Architecture

```text
+---------------------------+
|   Insurance Pipeline      |
|---------------------------|
| - Processes claims        |
| - Runs AI/LLM stages      |
| - Creates OTel spans      |
| - Exports traces via OTLP |
+---------------------------+
              |
              | OTLP
              v
+---------------------------+
|  Trace Storage / Collector |
|---------------------------|
| - Phoenix / Langfuse      |
| - Optional OTel Collector |
| - Stores traces and spans |
+---------------------------+
              |
              | Trace query / ingestion
              v
+---------------------------+
|     Pipeline Autopsy      |
|---------------------------|
| - Reads traces            |
| - Reconstructs execution  |
| - Validates stages        |
| - Detects discrepancies   |
| - Tracks downstream impact|
| - Creates findings        |
+---------------------------+
```

## 4. Project Boundaries

### Insurance Pipeline

The insurance pipeline is responsible only for processing insurance claims.

It may include:

- Document processing
- Information extraction
- Policy retrieval using RAG
- AI-assisted claim decision
- Decision validation
- Claim persistence
- Claim APIs

It must also:

- Create one OpenTelemetry trace per claim execution.
- Create one span per major pipeline stage.
- Add required trace attributes.
- Export traces using OTLP.

It must not:

- Import Pipeline Autopsy code.
- Contain Autopsy validators.
- Contain Autopsy diagnosis logic.
- Contain Autopsy findings models.
- Contain Autopsy UI.
- Depend on Pipeline Autopsy being online.

### Pipeline Autopsy

Pipeline Autopsy is responsible only for diagnosing executions.

It may include:

- Trace ingestion or trace querying
- Execution reconstruction
- Execution graph building
- Generic validation rules
- Domain-specific validation plugins
- Discrepancy detection
- Downstream impact analysis
- Root-cause ranking
- Finding generation
- Finding storage
- Diagnosis UI

It must not:

- Process insurance claims.
- Retrieve insurance policies.
- Make claim decisions.
- Import insurance pipeline code.
- Depend on the insurance pipeline being online.
- Assume that every incoming trace belongs to insurance.

## 5. Independence Rules

These rules are mandatory.

1. `insurance-pipeline` must never import from `pipeline-autopsy`.
2. `pipeline-autopsy` must never import from `insurance-pipeline`.
3. Each project must have its own `requirements.txt`.
4. Each project must have its own `Dockerfile`.
5. Each project must have its own `docker-compose.yml`.
6. Each project must have its own database schema and models.
7. Each project must be independently runnable.
8. Each project must be independently deployable.
9. Shared knowledge must be documentation only, placed in `/shared-docs`.
10. No executable code may be placed in `/shared-docs`.

## 6. Data Flow

### Normal execution flow

```text
1. User submits an insurance claim.
2. Insurance pipeline starts one execution.
3. Pipeline creates a unique execution_id.
4. Pipeline creates an OpenTelemetry trace.
5. Each pipeline stage creates a child span.
6. Each span records timing, status, and relevant attributes.
7. Large artifacts are stored separately.
8. Spans reference artifacts using artifact IDs.
9. Pipeline exports spans using OTLP.
10. Trace backend stores the trace.
11. Pipeline Autopsy retrieves the trace.
12. Autopsy reconstructs the execution graph.
13. Autopsy applies validation and semantic checks.
14. Autopsy creates evidence-backed findings.
15. Engineers review findings in the Autopsy UI/API.
```

### Failure-analysis flow

```text
1. Autopsy receives or queries a trace.
2. It loads all spans for the execution.
3. It reconstructs the stage dependency graph.
4. It checks each stage’s status, inputs, outputs, and artifacts.
5. It applies generic and domain-specific validation rules.
6. It identifies suspicious or contradictory outputs.
7. It finds downstream stages that consumed suspicious values.
8. It ranks possible root causes.
9. It creates a finding with evidence, confidence, and uncertainty.
10. It stores the finding separately from the original trace.
```

## 7. Trace Model

### Claim, execution, trace, and span

```text
One claim → many executions
One execution → one trace
One trace → many spans
One span → one pipeline stage or operation
```

Example:

```text
CLAIM-001
├── EXEC-001 / trace-abc-123
│   ├── document_processing
│   ├── information_extraction
│   ├── policy_retrieval
│   ├── claim_decision
│   └── decision_validation
│
└── EXEC-002 / trace-def-456
    ├── document_processing
    ├── information_extraction
    ├── policy_retrieval
    ├── claim_decision
    └── decision_validation
```

A claim is the business object.  
An execution is one attempt to process that claim.  
A trace is the OpenTelemetry record of that attempt.  
A span is one stage inside that attempt.

## 8. Required Trace Contract

Any AI pipeline that wants to work with Pipeline Autopsy must follow this contract.

### Required behavior

1. Create exactly one root trace per pipeline execution.
2. Generate a unique `execution_id` for every execution attempt.
3. Use a stable `entity_id` for the business object.
   - Insurance: `claim_id`
   - Finance: `transaction_id`
   - Healthcare: `patient_case_id`
4. Create one span per major pipeline stage.
5. Maintain correct parent-child relationships.
6. Export spans using OTLP.
7. Store large or sensitive content outside spans.
8. Reference large content using artifact IDs.

### Required span attributes

Every span must include:

```text
pipeline.name
pipeline.version
execution.id
execution.entity_id
stage.name
stage.status
input.artifact_ids
output.artifact_ids
```

### Recommended span attributes

```text
stage.version
model.name
model.version
prompt.version
retrieval.query
retrieval.chunk_ids
error.type
error.message
validation.rule_id
validation.result
```

### Artifact rule

Large or sensitive data must not be stored directly in spans.

Do not store in spans:

- Full insurance documents
- Full PDFs
- Raw customer PII
- Full policy documents
- Very large LLM responses
- Base64-encoded files

Instead, store them in an artifact store and reference them:

```text
input.artifact_id = ART-DOC-001
output.artifact_id = ART-EXTRACTION-001
```

## 9. Autopsy Core Concepts

### Execution graph

Pipeline Autopsy reconstructs the execution as a directed graph:

```text
document_processing
    → information_extraction
        → policy_retrieval
            → claim_decision
                → decision_validation
```

### Finding

A finding is an evidence-backed diagnostic result.

Every finding should include:

```text
finding_id
execution_id
entity_id
trace_id
finding_type
root_cause_stage
affected_stage_ids
severity
confidence
uncertainty
evidence
recommended_action
created_at
status
```

### Failure categories

Pipeline Autopsy must distinguish:

```text
SERVICE_EXECUTION_FAILURE
OUTPUT_CONTRACT_VIOLATION
SOURCE_EVIDENCE_CONTRADICTION
INVALID_UPSTREAM_INPUT
INDEPENDENT_DOWNSTREAM_FAILURE
DOWNSTREAM_PROPAGATED_SUSPICION
INSUFFICIENT_EVIDENCE
NO_ISSUE_DETECTED
```

A successfully executed stage can still produce an incorrect output. Therefore, HTTP success or valid JSON does not mean the stage is semantically correct.

## 10. Technology Direction

### Insurance pipeline

- Python
- FastAPI
- OpenTelemetry SDK
- OTLP exporter
- PostgreSQL for business data
- Artifact store for documents and large outputs
- Phoenix or Langfuse for AI-friendly trace storage

### Pipeline Autopsy

- Python
- FastAPI
- PostgreSQL for findings, execution metadata, rules, and evaluation data
- Trace ingestion/query layer
- Artifact-reference lookup
- Deterministic validation engine
- Optional constrained LLM explanation layer
- Simple web UI for findings and execution timeline

### Trace backend

Initial recommendation:

- Phoenix or Langfuse for AI-native trace storage and visualization.

Future option:

- OpenTelemetry Collector plus Jaeger or Grafana Tempo for production-style distributed tracing.

## 11. Development Milestones

### Milestone 1: Independent trace generator

Build a minimal insurance-pipeline trace generator that creates:

```text
insurance_claim_execution
├── document_processing
├── information_extraction
├── policy_retrieval
├── claim_decision
└── decision_validation
```

Each span must include required attributes and export through OTLP.

Success condition: the trace can be viewed in Phoenix or Langfuse with correct parent-child structure.

### Milestone 2: Autopsy trace ingestion

Pipeline Autopsy can retrieve or receive one stored trace.

Success condition: Autopsy can identify the trace, execution ID, entity ID, and all spans.

### Milestone 3: Execution reconstruction

Autopsy reconstructs the parent-child execution graph.

Success condition: Autopsy can display the correct stage order and dependencies.

### Milestone 4: Generic validation

Autopsy applies schema, required-field, and cross-stage consistency checks.

Success condition: Autopsy can detect a missing or invalid field.

### Milestone 5: Semantic discrepancy detection

Autopsy compares extraction output with source-document evidence.

Example:

```text
Source: "Damage to the front bumper"
Extraction: "rear bumper"
```

Success condition: Autopsy creates a `SOURCE_EVIDENCE_CONTRADICTION` finding.

### Milestone 6: Downstream impact analysis

Autopsy identifies stages that consumed the suspicious value.

Success condition: Autopsy marks `policy_retrieval` and `claim_decision` as affected.

### Milestone 7: Evidence-backed findings

Autopsy creates a complete finding with evidence, confidence, uncertainty, and recommended action.

Success condition: every finding can be traced back to specific spans, artifacts, and validation rules.

## 12. What Pipeline Autopsy Is Not

Pipeline Autopsy is not:

- A tracing backend.
- A metrics dashboard.
- A logging platform.
- An insurance claim-processing engine.
- An automatic remediation system.
- A generic AI model evaluation platform.
- A replacement for OpenTelemetry, Jaeger, Tempo, Phoenix, or Langfuse.

Pipeline Autopsy is a diagnosis layer that consumes execution traces and produces evidence-backed findings.

## 13. Non-Negotiable Design Rule

The insurance pipeline produces traces.  
Pipeline Autopsy analyzes traces.

They must remain independently deployable, independently testable, and independently understandable.

No direct code dependency is allowed between them.
