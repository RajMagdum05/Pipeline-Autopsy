# Deliverable C: Telemetry and integration design (summary)

| Topic | Summary | File |
|---|---|---|
| Research | OTel data model, limits, status/errors, propagation, links, semconv stability, GenAI (Development, moved June 2026), retries, sampling, Collector, OTLP/JSON, sensitive data, retention, UI patterns, RCA research and LLM limits. Cited, with access date 15 Nov 2026 | `04_telemetry/30_otel_research_summary.md` |
| Contract v3 | Standard attributes where they exist (`service.*`, `deployment.environment.name`, `error.type`, `gen_ai.*`); `pipeline.*` for run/stage/item/attempt/artifact lineage/error class; `pipeline.check` events; content-hash artifact IDs; v1 aliases; validation → grade A/B/C | `04_telemetry/31_trace_contract_v3.md` |
| Manifest | Stages, scope (item/run), `requires` control edges, consumes/produces, evidence level and allowed kinds, schemas, consistency rules | `04_telemetry/32_pipeline_manifest_spec.md` |
| Privacy | Never in telemetry: documents, text, values, prompts, PII, secrets. Evidence levels E0/E1/E2; redacted excerpts; retention 14 d evidence / 30 d spans | `04_telemetry/33_artifacts_privacy_retention.md` |
| Hard cases | Retries, timeouts, gates, fan-out, control edges, cached replays, re-runs, async, threads, sampling, clock skew, duplicates, truncation | `04_telemetry/34_retries_fanout_async_sampling.md` |
| Integration | 5 options compared. **Default: standard OTel + optional SDK helpers, routed as a copy via the customer's Collector**; direct exporter as fallback; backend pull for backfill | `05_integration/40_integration_options.md` |
| SDK | Thin semantic layer on `opentelemetry-api`; `run/stage/operation/record_artifact/check`; optional `configure()` that never replaces a provider; evidence uploader; testing helpers | `05_integration/41_sdk_design.md` |
| Security | Static key (MVP) → per-project keys; limits; PII masking; retention; failure behaviour when Autopsy is down | `05_integration/42_security.md` |
| Onboarding | Register manifest → add exporter → optional SDK → first run → compliance → E1/E2 | `05_integration/43_customer_onboarding.md` |
| Insurance instrumentation | Stage-by-stage spans, artifacts, checks, error mapping, privacy test | `06_insurance_pipeline/52_instrumentation_plan.md` |
