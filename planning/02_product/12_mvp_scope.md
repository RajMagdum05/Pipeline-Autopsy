# 12: MVP scope

## The MVP must demonstrate these 8 things

| # | Requirement | Proven by (milestone / test) |
|---|---|---|
| 1 | An insurance claim executes end to end: intake → documents → adjudication → final result | B4.3 + T4.7 e2e |
| 2 | The execution produces useful, contract-v3 telemetry | SDK test "spans pass `validate_trace` with grade A" (S1.1); insurance span-contract tests (T4.2–T4.4) |
| 3 | Autopsy receives it over standard OTLP/HTTP | A2.1 integration test with real SDK protobuf |
| 4 | Autopsy reconstructs the run: stage instances per document, lineage, control edges | P0.3 golden + fan-out tests; A2.6 `/graph` contract test |
| 5 | A detector identifies a real, deliberately injected problem | T4.6 fault injection; T4.7 recorded cases |
| 6 | Autopsy identifies the originating stage using trace evidence | Demo pair: `ocr_misread` vs `extraction_hallucinate` give different origins for the same symptom |
| 7 | It produces a finding with cause, classification, confidence and evidence links | `/diagnosis` response + L1 eval |
| 8 | A UI shows the run and the diagnosis | U3.2 + Playwright smoke |

The **explanation layer** (template text) ships with the MVP. The **LLM explanation** is *MVP+1*: the product is complete without it. A finding is never blocked by an LLM.

## In MVP

- Trace contract v3 and the manifest format.
- autopsy-sdk v2 (Python): `run`, `stage`, `operation`, `record_artifact`, `check`, optional `configure`.
- Autopsy:
  - OTLP/HTTP ingest (protobuf and JSON);
  - manifest registry;
  - evidence store (E2);
  - worker;
  - deterministic core;
  - findings API;
  - React UI;
  - template explanations;
  - one static API key.
- Insurance pipeline:
  - adjudication v1 (deterministic rules);
  - final result;
  - claim-run orchestration;
  - instrumentation;
  - fault injection.
- Toy (non-insurance) pipeline example.
- Evaluation: golden core tests, recorded L1 cases, CI.
- Root `docker compose up` for everything. Jaeger is optional.

## MVP+1 (immediately after)

- Guarded LLM explanations (Gemini) with template fallback, plus L2 evals.
- Playbooks (keyed retrieval) and feedback with past-case signatures.
- Collector fan-out profile and docs.

## Later (only with evidence of need)

| Item | Trigger to start it |
|---|---|
| Per-project API keys, key rotation UI | A second real user or deployment outside your laptop |
| Retention and deletion jobs | Any non-synthetic data |
| Log-based event ingestion (`/v1/logs`) | When the OTel Python SDK deprecates `add_event` in a release you use |
| GenAI / OpenInference / Langfuse attribute aliasing | When integrating a pipeline instrumented by those libraries |
| Investigator agent (LangGraph or plain loop) | L1 shows ≥ 20% of real cases end `possible` or `insufficient` and a bounded tool loop measurably raises them |
| Vector retrieval | ≥ 200 confirmed cases, and keyed plus full-text retrieval misses relevant ones in an eval |
| Pull importer from Jaeger / Tempo | A user who cannot add an exporter |
| Async job queue for the insurance pipeline | Request timeouts with realistic documents |

## Never (for this product)

- An LLM choosing the root cause, the classification or the confidence.
- Autopsy reading producer databases.
- Raw documents, prompts or PII in span attributes.
