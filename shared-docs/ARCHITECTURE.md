# 🏛️ Architecture & System Topology

## 1. High-Level Decoupled Architecture

The repository is structured into two completely independent projects connected only via standard OpenTelemetry traces:

```
+------------------------------------+
|         insurance-pipeline         |
|  - Processes insurance claims      |
|  - Runs document OCR & extraction  |
|  - Evaluates policy rules          |
|  - Emits OpenTelemetry OTLP spans  |
+------------------------------------+
                  │
                  │ OTLP (HTTP/gRPC)
                  ▼
+------------------------------------+
|      Trace Backend / Collector     |
|  - Arize Phoenix / Langfuse        |
|  - OpenTelemetry Collector / Jaeger|
+------------------------------------+
                  │
                  │ Trace Query / Ingestion
                  ▼
+------------------------------------+
|          pipeline-autopsy          |
|  - Ingests traces via /v1/traces   |
|  - Reconstructs execution DAG      |
|  - Validates stage outputs         |
|  - Pinpoints causal root defects   |
|  - Forensic Findings & UI          |
+------------------------------------+
```

---

## 2. Independence Rules

1. **Zero Direct Code Dependencies**: Neither project imports from the other.
2. **Dedicated Databases**:
   - `insurance-pipeline` has its own database (`insurance_pipeline` on port 5432).
   - `pipeline-autopsy` has its own database (`autopsy_db` on port 5433).
3. **Dedicated Docker Environments**: Each project has its own `Dockerfile` and `docker-compose.yml`.
4. **Dedicated Requirements**: Each project maintains its own isolated `requirements.txt`.
5. **Shared Documentation Only**: All inter-project knowledge is purely declarative Markdown stored in `/shared-docs/`. No Python code in `/shared-docs/`.
