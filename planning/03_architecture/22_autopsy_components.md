# 22: Autopsy components (what each does, and where it lives)

Each component lists the same fields: what it does, why, inputs/outputs, location, dependencies, failure handling, tests, acceptance, and phase.

## 1. Ingestion (OTLP/HTTP)

- **Does:** accepts `ExportTraceServiceRequest` as protobuf or JSON, gzip allowed, then normalizes and upserts spans.
- **Why:** this is the only door telemetry comes in through.
- **In:** HTTP body. **Out:** rows in `spans`, `executions`, plus a job upsert.
- **Where:** `autopsy/ingest/otlp.py` (refactored from `adapters/otlp_adapter.py` and `services/ingestion_service.py`). Route in `api/routes_ingest.py`.
- **Deps:** `opentelemetry-proto`, `protobuf`.
- **Failure handling:**
  - Bad encoding → `400`.
  - Body over `AUTOPSY_MAX_BODY_BYTES` (10 MB) → `413`.
  - Wrong content type → `415`.
  - Invalid IDs (not 32/16 hex after decoding) → that span is rejected and counted in `partial_success.rejected_spans`, with a message.
  - Overload → `503` + `Retry-After`.
  - Missing or wrong key → `401`.
- **Tests:**
  - real SDK protobuf with list attributes and events;
  - base64 → hex IDs;
  - JSON with hex IDs;
  - re-delivery idempotent;
  - partial success;
  - gzip;
  - run-id resolution order.
- **Accept:** a span exported by the OTel SDK has identical hex IDs in Autopsy and in Jaeger.
- **Phase:** A2.1.

## 2. Normalization / contract adapter

- **Does:** maps stored spans to the core's internal shape `{span_id, parent, name, status, start, end, attrs, events}`. It maps v3 attribute names to internal names and accepts v1 aliases. Later it also accepts GenAI, OpenInference and log-based events.
- **Why:** the core must not care about wire formats or naming history.
- **Where:** `autopsy/core/normalize.py`. It is pure: a dict in, a dict out.
- **Tests:** a v1 → v3 alias table, and run-id resolution (span attr → resource attr → `trace:<id>`).
- **Phase:** C1.2.

## 3. Contract validation and trace grade

- **Does:** structural checks that produce a grade.
  - **C** (cannot diagnose): no or several run spans, missing identity, a cycle.
  - **B** (diagnose, cap confidence): orphans, missing artifacts, lineage gaps, status mismatch, unknown stage, an expected stage missing with no reason.
  - **A** otherwise.
- **Where:** `core/contract.py`. Ported from `rca_reference.validate_trace` and extended with item checks.
- **Accept:** golden cases 12 and 13 and the mutation tests.
- **Phase:** P0.3, extended in C1.2.

## 4. Execution identity and grouping

- **Rule:** one run = one `pipeline.run.id` = (normally) one trace.
- If spans of one run span several traces (async hops), group them by `pipeline.run.id`.
- A re-run is a *new* run that links to the previous run through `pipeline.run.previous_id` plus a span link.
- `pipeline.entity.id` groups runs of one business entity.
- **Where:** `ingest/` (assigns `execution_id` at upsert) and `api/read` (lists by entity).
- **Phase:** A2.1.

## 5. Graph reconstruction (stages + lineage + fan-out)

- **Does:**
  1. Expands item-scoped manifest stages per item.
  2. Picks the final attempt of each stage instance.
  3. Maps producer[artifact] → stage instance.
  4. Builds manifest edges, instance edges, and control (gate) edges.
  5. Topologically sorts.
- **Where:** `core/lineage.py` and `core/fanout.py`.
- **Accept:** fan-out tests f1–f5.
- **Phase:** P0.3.

## 6. Detectors (observations, never conclusions)

| Family | Source | Examples |
|---|---|---|
| execution | stage spans | `stage_failed` (with `error.class` from the deepest failing span in the final attempt), `stage_partial`, `retried`, `handled_operation_error` |
| check | `pipeline.check` events | Any `warn`/`fail`. "About" = the producer of the target artifact, else the reporting stage |
| contract | E2 artifact vs manifest JSON Schema | `schema.required`, `schema.pattern` |
| consistency | E2 artifact vs its upstream artifact | `grounded_fields`, `equals_upstream` (pass results kept for trace-back) |
| derived | trace-back | `bad_value_traced_to_input` |
| structural | contract validation | orphan, gap, truncated attributes (`droppedAttributesCount > 0`) |
| decision | `pipeline.check` with `kind=decision_rule` | business rule outcomes. Always `info`, used as explanation context |

- **Where:** `core/detectors.py`, `core/validators.py` (with a registry that packs can extend).
- **Phase:** P0.3.

## 7. Root-cause hypothesis ranking (RCA rules)

The ordered rule table R0–R11 assigns each stage instance a role (`origin`, `propagated`, `tainted`, `not_executed`, `healthy`), a classification, a confidence and a link strength. Full detail is in `23_diagnosis_core_algorithm.md`.

- **Where:** `core/rca.py`. **Phase:** P0.3.

## 8. Downstream impact analysis

This is part of the RCA walk:

- *propagated*: failed because of bad input or a stopped upstream;
- *tainted*: succeeded on bad data;
- *not_executed*: blocked by an upstream failure or a gate.

## 9. Evidence assembly and provenance

- Every finding lists observation IDs.
- Every observation points to a `span_id`, an `artifact_id` (+ field), or both, and keeps the `reported_by` stage.
- An **evidence bundle** for explanation adds short, masked excerpts (≤ 300 chars, ≤ 12) from E2 artifacts only.
- **Where:** `explain/bundle.py`. **Phase:** E5.1 (bundle). Provenance fields come in P0.3.

## 10. Artifact evidence store (optional E2)

- `POST /v1/artifacts`: the server recomputes the ID.
  - ID mismatch → `422` (recomputed only for non-redacted uploads; redacted excerpts keep the original ID and are flagged `redacted=true`).
  - Over 5 MB → `413`.
  - Duplicate → `200`, no rewrite.
  - Kind not allow-listed for the pipeline → `403`.
- Blobs are stored at `{AUTOPSY_BLOB_DIR}/{execution_id}/{id}` with retention days per pipeline.
- **Where:** `autopsy/artifacts/`. **Phase:** A2.3.

## 11. Manifest registry

- `PUT /v1/pipelines/{name}/versions/{version}` with a YAML or JSON body.
- Validation rules:
  - each kind is produced by at most one stage;
  - consumed kinds are produced earlier or are external;
  - `requires` refers to an item-scoped stage;
  - validators exist;
  - schemas compile;
  - no cycles.
- On failure: `422` listing *every* problem.
- **Where:** `autopsy/manifests/`. **Phase:** A2.4.

## 12. Diagnosis worker

- One asyncio loop started in the FastAPI lifespan. It polls `diagnosis_jobs` every second.
- A job becomes runnable 5 s after the run span arrives, or 10 min after the last span if no run span ever arrives (diagnosed as incomplete).
- If referenced evidence is missing on the first attempt (E2 pipelines only), it re-queues once after 30 s.
- An exception marks the job failed and stores the traceback; the loop continues.
- **Where:** `autopsy/worker/`. **Phase:** A2.5.

## 13. Finding model and persistence

Tables `observations`, `findings`, `explanations` (see `25_data_model.md`). A re-diagnosis replaces them for that execution in one transaction.

## 14. Explanation (template; LLM in MVP+1)

`23_diagnosis_core_algorithm.md` §6 and `27_explanation_llm_guardrails.md`.

## 15. Guardrails

| Layer | Guardrails |
|---|---|
| Ingestion | auth, size, ID validation, PII mask |
| Explanation output | G1–G9, deterministic |
| Producer gates | live in the producer, emitted as checks |

## 16. Knowledge retrieval

Keyed playbooks (`28_knowledge_playbooks.md`). **Phase:** K6.1.

## 17. Evaluation framework

L0 unit, L1 golden + recorded, L2 explanation, L3 live fault injection (`29_evaluation_framework.md`).

## 18. APIs and UI

See `26_api_spec.md` and `07_frontend/60_autopsy_ui.md`.

## What is removed from the active path (A2.6)

- `services/root_cause_service.py`
- `services/failure_detection_service.py`
- `detectors/detectors.py`
- `services/agent_service.py`
- the old `/api/v1/*` and `/v1/traces/{id}/*` routes
- the duplicate `/v1/traces/v1/traces`

Git history keeps them. `credential_service.py` and the projects/keys tables stay, frozen, for X7.2.
