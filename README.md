# 🔬 Pipeline Autopsy Workspace

This repository contains two completely independent, decoupled projects connected only through OpenTelemetry traces and a documented trace contract:

```
/
├── insurance-pipeline/    # Independent claims processing AI pipeline & trace generator
├── pipeline-autopsy/      # Independent generalized AI trace diagnosis & RCA engine
└── shared-docs/           # Standard trace contract, system architecture & documentation
```

---

## 📁 Repository Structure

### 1. [`/insurance-pipeline`](./insurance-pipeline)
- **Role**: Processes insurance claims through automated document processing, extraction, policy retrieval, and rule decisioning.
- **Telemetry**: Emits OpenTelemetry traces and spans over OTLP.
- **Independence**: Has its own database models, requirements, Docker setup, and tests. Contains zero Pipeline Autopsy code.
- **Details**: See [`insurance-pipeline/README.md`](./insurance-pipeline/README.md).

### 2. [`/pipeline-autopsy`](./pipeline-autopsy)
- **Role**: Diagnostic engine for multi-stage AI pipelines. Ingests execution traces, reconstructs DAGs, detects anomalies, and pinpoints root causes.
- **Independence**: Does not process claims. Has its own database, requirements, Docker setup, and tests. Contains zero insurance business logic in its core engine.
- **Details**: See [`pipeline-autopsy/README.md`](./pipeline-autopsy/README.md).

### 3. [`/shared-docs`](./shared-docs)
- **Trace Contract**: [`shared-docs/TRACE_CONTRACT.md`](./shared-docs/TRACE_CONTRACT.md) — Contract defining required span attributes, parent-child structure, and artifact reference rules.
- **System Architecture**: [`shared-docs/SYSTEM_ARCHITECTURE.md`](./shared-docs/SYSTEM_ARCHITECTURE.md) — Single source of truth for project boundaries and milestones.
- **Architecture Overview**: [`shared-docs/ARCHITECTURE.md`](./shared-docs/ARCHITECTURE.md).
- **Demo Flow**: [`shared-docs/DEMO_FLOW.md`](./shared-docs/DEMO_FLOW.md).

---

## ⚡ Quick Navigation

| Project | Command |
|:---|:---|
| **Insurance Pipeline** | `cd insurance-pipeline && docker compose up` |
| **Jaeger Trace UI** | Included in `insurance-pipeline/docker-compose.yml` |
| **Pipeline Autopsy Engine** | `cd pipeline-autopsy && docker compose up` |
| **Autopsy Website** | Included in `pipeline-autopsy/docker-compose.yml` |
