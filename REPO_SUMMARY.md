# Project Context Map and Repo Summary

This document is a separate, condensed context file for understanding the Pipeline Autopsy repository and using it as research material for an LLM or future work.

---

## 1. One-line summary

Pipeline Autopsy is a forensic observability and diagnosis framework for multi-stage AI pipelines. It is built around the idea that AI systems should emit traceable execution data, and a separate analyzer should reconstruct the execution graph, validate stage outputs, identify anomalies, and explain root causes.

---

## 2. What the project is built on

This project is built on a few core principles:

- OpenTelemetry tracing
  - Each pipeline stage emits spans and parent-child relationships.
- Trace-based observability
  - The system does not depend on business logic internals; it inspects execution telemetry.
- Decoupled architecture
  - Producer project and analyzer project are intentionally separate.
- Shared contract documentation
  - `shared-docs/` defines the required telemetry and execution semantics.
- Forensic analysis
  - It analyzes execution evidence instead of raw logs alone.
- AI pipeline debugging
  - It is designed for multi-step AI workflows where errors can cascade downstream.

In simple terms:

- The pipeline produces evidence.
- Autopsy reads the evidence.
- The analysis layer tells you what failed and why.

---

## 3. Repository structure map

```text
RajMagdum05/Pipeline-Autopsy/
├── README.md
├── .env.example
├── .gitignore
├── insurance-pipeline/
│   ├── README.md
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── requirements.txt
│   ├── .env.example
│   ├── app/
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
│   ├── README.md
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── requirements.txt
│   ├── autopsy/
│   │   ├── main.py
│   │   ├── __init__.py
│   │   ├── README.md
│   │   ├── adapters/
│   │   ├── api/
│   │   ├── db/
│   │   ├── detectors/
│   │   ├── domain/
│   │   ├── scripts/
│   │   └── services/
│   ├── packages/
│   │   └── autopsy-sdk/
│   ├── examples/
│   ├── legacy/
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
├── REPO_CONTEXT.md
└── REPO_SUMMARY.md
```

---

## 4. Repo summary by project

### A. insurance-pipeline

This is the data-producing pipeline.

It is designed to simulate a real insurance claim processing system where a claim goes through stages such as:

- document intake
- document OCR / PDF processing
- information extraction
- policy retrieval
- business rule adjudication
- final result decision

The README explicitly describes the pipeline as:

```text
document_processing -> information_extraction -> rule_engine -> final_result
```

It includes modules for:

- OCR and document analysis
- PDF rendering and inspection
- extraction using Gemini
- rule-based claim adjudication
- OpenTelemetry trace creation and export

This project is not just a demo; it is structured as a production-style AI pipeline that creates telemetry for downstream diagnosis.

### B. pipeline-autopsy

This is the analysis and diagnosis engine.

It does not process insurance claims. It is designed to:

- ingest traces
- rebuild execution graphs
- detect incorrect or inconsistent states
- track downstream impact of upstream issues
- rank likely root causes
- write evidence-backed findings

This is the “forensics” layer of the system.

### C. shared-docs

This folder defines how the two projects talk to each other.

It contains the architecture and contract documents that specify:

- trace requirements
- stage relationships
- event semantics
- artifacts and IDs
- boundaries between projects
- expected pipeline execution model

Without this folder, the two projects would not be interoperable in a clean, standards-based way.

---

## 5. What exactly the project is working on

This repo is working on a specific AI systems challenge:

“Given a multi-stage AI pipeline, how can we tell what failed, why it failed, and which downstream stages were impacted?”

The solution is framed as:

- create a pipeline that emits structured telemetry
- reconstruct the pipeline execution graph from telemetry
- validate outputs and catch contradictions
- isolate root cause vs cascading downstream symptoms
- output findings with evidence and recommended actions

This is not a normal application service. It is a research/demo architecture for:

- AI system observability
- pipeline debugging
- root-cause analysis
- evidence-driven diagnosis
- AIOps for multi-step AI workflows

---

## 6. Design philosophy

The repository makes a very clear architectural statement:

- business execution and diagnostics must be separated
- the pipeline producer should not be tightly coupled to the analyzer
- both can be independently built and deployed
- shared understanding should live in a contract, not direct imports

This means the system is designed around clean boundaries and standards.

The repo intentionally says:

- no direct code dependency between projects
- no shared database schema or models
- each project has its own environment, stack, and runtime
- they connect only through telemetry and documentation

This is a strong systems design choice and a major learning point from the project.

---

## 7. What the repo is demonstrating

The repo demonstrates these concepts:

1. Multi-stage AI pipelines can be instrumented with standard tracing
2. Execution traces can be transformed into a causal graph
3. AI execution can be validated beyond just HTTP status or JSON validity
4. Incorrect outputs can be distinguished from downstream noise
5. Root cause analysis can be evidence-backed instead of guesswork
6. Diagnostic systems can be separated from business logic systems

This is a practical pattern for AI observability and diagnosis.

---

## 8. The key contract concepts

The shared-docs documents define the project’s interoperability contract.

Important concepts:

- One execution = one trace
- One trace = many spans
- One span = one stage or operation
- Each stage records status, inputs, outputs, artifact references
- Data too large or sensitive to be stored directly in the trace is stored elsewhere and referenced by ID

Example trace field ideas from the docs:

- `execution.id`
- `execution.entity_id`
- `stage.name`
- `stage.status`
- `input.artifact_ids`
- `output.artifact_ids`

This is the core contract that makes the autopsy engine usable.

---

## 9. The project’s end-to-end flow

```text
User submits insurance claim
        ↓
insurance-pipeline starts a claim execution
        ↓
OCR, extraction, policy retrieval, and rule evaluation run
        ↓
OpenTelemetry spans are generated for each stage
        ↓
Traces are exported via OTLP
        ↓
Pipeline Autopsy ingests the trace
        ↓
Autopsy reconstructs execution graph
        ↓
Autopsy checks for schema/logic/evidence inconsistencies
        ↓
Autopsy identifies root cause and downstream impact
        ↓
Autopsy produces findings with confidence and recommendations
```

---

## 10. Important findings categories in autopsy

The project mentions categories like:

- `SERVICE_EXECUTION_FAILURE`
- `OUTPUT_CONTRACT_VIOLATION`
- `SOURCE_EVIDENCE_CONTRADICTION`
- `INVALID_UPSTREAM_INPUT`
- `DOWNSTREAM_PROPAGATED_SUSPICION`
- `INSUFFICIENT_EVIDENCE`
- `NO_ISSUE_DETECTED`

This shows the project is focused not just on “error happened,” but on diagnosing the type and source of failure.

---

## 11. Best research lens

If you want to do deeper work on this repo, the most powerful research frame is:

- trace-based observability for AI systems
- execution graph reconstruction from telemetry
- root-cause analysis in multi-stage LLM pipelines
- domain-agnostic forensic diagnostics
- evidence-backed AI failure analysis

This repo is essentially a blueprint for engineering “AI debugging infrastructure.”

---

## 12. Best reading order for future research

1. `README.md`
2. `shared-docs/SYSTEM_ARCHITECTURE.md`
3. `shared-docs/TRACE_CONTRACT.md`
4. `insurance-pipeline/README.md`
5. `pipeline-autopsy/README.md`
6. `shared-docs/ARCHITECTURE.md`
7. `shared-docs/DEMO_FLOW.md`
8. actual code under `app/` and `autopsy/`

---

## 13. Final summary

This repository is built around one central idea:

AI systems need an execution diagnosis layer.

The project packages that idea into two separate systems:

- one system executes the business pipeline and emits telemetry
- one system reads the telemetry and explains what went wrong
- a shared documentation layer defines the exact contract between them

That is the real work of the project.

It is a strong example of:

- distributed tracing for AI systems
- decoupled architecture design
- LLM/AI pipeline observability
- forensic root-cause analysis
- evidence-driven debugging

---

This file is intended as a concise research context and architectural summary for further work on the repository.
