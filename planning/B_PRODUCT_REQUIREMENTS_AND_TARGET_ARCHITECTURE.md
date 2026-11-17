# Deliverable B: Product requirements and target architecture (summary)

## Product

Autopsy reads the trace of one pipeline run and states, with evidence:

- the **origin** stage;
- the **affected** stages: propagated, tainted, or not executed;
- the **confidence**;
- the **next step**.

It abstains when the evidence is too thin. Users and workflows are in `02_product/10_product_definition_and_users.md`.

## Boundaries

- The producer owns business logic and data.
- The SDK adds contract labels to standard OTel spans.
- Autopsy owns diagnosis only.
- Content leaves the producer only at evidence level E2, after redaction.

→ `02_product/11_system_boundaries.md`

## MVP

The 8 required capabilities. The LLM explanation is MVP+1. → `02_product/12_mvp_scope.md`

## Target architecture

→ `03_architecture/20_target_architecture.md`

- **Both systems are modular monoliths.**
- **Autopsy layers:**
  - ingest (OTLP/HTTP)
  - PostgreSQL + evidence volume
  - in-process worker
  - pure deterministic core: validate → expand fan-out → lineage → detectors → trace-back → RCA rules
  - template explanation (LLM optional, guarded)
  - read API
  - React UI
- **Causality comes from artifact lineage + manifest + control edges, never from span nesting** (ADR-03).
- The core is specified by 37 passing tests. → `03_architecture/23_diagnosis_core_algorithm.md`, `24_fanout_and_control_edges.md`

## Components, data and API

| Topic | File |
|---|---|
| Components | `03_architecture/22_autopsy_components.md` |
| Tables | `03_architecture/25_data_model.md` |
| HTTP API | `03_architecture/26_api_spec.md` |
| Explanation and guardrails | `27_explanation_llm_guardrails.md` |
| Playbooks; no vector DB | `28_knowledge_playbooks.md` |
| Evaluation | `29_evaluation_framework.md` |

## Frontend information architecture

Runs list → Run investigation (lineage graph + findings + evidence) → Pipelines. → `07_frontend/60_autopsy_ui.md`

## Technology decisions

20 ADRs: OTLP push, Collector fan-out default, lineage causality, deterministic RCA, evidence levels, Postgres + JSONB, plain Python (no LangGraph), keyed playbooks (no vectors), in-process worker, thin SDK, span-event checks, `pipeline.*` namespace, per-item stages, React + SVG, SQL migrations, static key, sync runs, deterministic adjudication, Jaeger optional. → `03_architecture/21_architecture_decisions.md`
