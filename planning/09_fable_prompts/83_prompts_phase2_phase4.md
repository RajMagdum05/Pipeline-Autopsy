# 83: Prompt drafts, Phase 2 (Autopsy service), Phase 3 (UI), Phase 4 (Insurance)

These are **drafts**. Before sending each one:

1. Read the previous task's report.
2. Update file names, test counts and interfaces.
3. Fill the "Previous task result" line.

---

## A2.1: Ingestion repair + config hardening

> **For you:** this fixes the scrambled span IDs (verified bug) and makes Autopsy behave like a standard OTLP receiver. Afterwards, IDs in Autopsy match the IDs Jaeger shows for the same span. Verify by running the new protobuf round-trip test.

```text
Task A2.1: OTLP ingestion repair and config hardening.
Previous task result: <S1.1 report: SDK path, test counts>.
Read: planning/01_audit/04_autopsy_engine.md (ingest rows), 06_runtime_verification_log.md (probes 3b, 4, 4b),
planning/03_architecture/22_autopsy_components.md §1, 26_api_spec.md (Ingest), 04_telemetry/30 §9.
In scope: pipeline-autopsy/autopsy/adapters/otlp_adapter.py (move to autopsy/ingest/otlp.py; keep a shim import if tests need it),
autopsy/services/ingestion_service.py, the /v1/traces route in autopsy/api/routes.py, autopsy/api/auth.py, autopsy/db/database.py,
autopsy/main.py (lifespan instead of on_event), pipeline-autopsy/Dockerfile, pipeline-autopsy/docker-compose.yml, tests.
Requirements
1. IDs: protobuf->MessageToDict gives base64 for bytes; decode to lowercase hex for trace (16 bytes) and span/parent (8 bytes).
   Accept hex strings from OTLP/JSON. Any other length/charset -> reject that span (counted in partial_success).
2. Run id: v3 span attr pipeline.run.id, v1 execution.id, resource attrs, else "trace:<trace_id>" (use core/normalize.py).
3. Response: OTLP ExportTraceServiceResponse in the request's encoding; partial_success only when rejections > 0.
4. Content-Encoding gzip; 413 when body > AUTOPSY_MAX_BODY_BYTES (default 10 MiB); 415 for other content types.
5. Remove the duplicate route /v1/traces/v1/traces.
6. Auth: AUTOPSY_API_KEY required by default for /v1/* (Bearer or x-autopsy-api-key); keep /health open. Update existing
   tests to send the key via a fixture.
7. database.py: no socket probing, no silent SQLite fallback; startup raises a clear error if the URL is missing/unreachable
   unless it starts with "sqlite".
8. Compose: postgres:16-alpine; host port 5434; website service under profile "website". Dockerfile: python:3.12-slim;
   remove the sqlite AUTOPSY_DATABASE_URL default.
Tests: real OTel SDK spans encoded with opentelemetry.exporter.otlp.proto.common.trace_encoder.encode_spans -> POST ->
stored span_id/parent/trace_id equal format(ctx.span_id,'016x') etc.; list attrs + events preserved; JSON hex; gzip;
partial success with one invalid span; 401/413/415; duplicate delivery persists 0 new spans; startup failure without DB.
Acceptance: all tests green; report the before/after IDs for one span.
Process: plan first.
```

## A2.2: New schema + migration runner

```text
Task A2.2: Autopsy schema v2 via numbered SQL migrations.
Read: planning/03_architecture/25_data_model.md, ADR-16.
In scope: autopsy/db/migrations/001_core.sql, autopsy/db/migrate.py (apply in order, record in schema_migrations, idempotent),
autopsy/db/models.py (add new SQLAlchemy models beside old ones), ingest code to fill normalized span columns, tests.
Requirements: SQL must run on PostgreSQL 16 and SQLite (keep types portable; JSON column type with JSONB variant on PG).
Ingest writes role, stage_name, item_id, attempt, status, status_message, error_type, error_class, dropped_* from v3/v1 attrs.
Tests: migrate twice -> no error, one row per version; ingest of an SDK-produced stage span fills the columns.
Acceptance: green. Report table list.
```

## A2.4: Manifest registry + CLI (before A2.3)

```text
Task A2.4: Manifest registry API and CLI.
Read: planning/04_telemetry/32_pipeline_manifest_spec.md, 26_api_spec.md.
In scope: autopsy/manifests/ (service), routes PUT /v1/pipelines/{name}/versions/{version} and GET /v1/pipelines,
autopsy-sdk/autopsy_sdk/cli.py with entry point `autopsy` (`autopsy register FILE --endpoint URL --key KEY`), tests.
Requirements: validation via core/manifest.validate_manifest; 422 {problems:[...]} lists all problems; same version with
different content -> 409; YAML and JSON bodies.
Acceptance: both shared-docs manifests register (200); a broken one returns all problems; CLI test against TestClient.
```

## A2.3: Evidence artifact endpoints

```text
Task A2.3: Evidence artifact store.
Read: planning/04_telemetry/33_artifacts_privacy_retention.md, 26_api_spec.md (artifacts), 31 §2 (artifact id).
In scope: autopsy/artifacts/ (store + service), routes POST /v1/artifacts and GET /v1/artifacts/{id}, tests.
Requirements: allow-list from the registered manifest evidence.kinds_allowed and level E2 (403 otherwise); recompute id with
core.contract.artifact_id when redacted=false (422 on mismatch); id format check always; 5 MiB cap (413); duplicate -> 200 no
rewrite; blobs at AUTOPSY_BLOB_DIR/{execution_id}/{id}; GET returns metadata + content with PII mask applied.
Acceptance: tests for every listed status code; content round-trips.
```

## A2.5: Diagnosis worker + persistence

> **For you:** this is where Autopsy starts answering on its own. Afterwards, sending a trace is enough: about 5 seconds later the run has a verdict.

```text
Task A2.5: Diagnosis worker and persistence.
Read: planning/03_architecture/22_autopsy_components.md §12-13, 25_data_model.md.
In scope: autopsy/worker/jobs.py, runner.py; autopsy/core_adapter.py (DB rows -> core inputs: spans, artifacts dict,
manifest, items from run span pipeline.run.items); main.py lifespan starts the loop; ingest upserts diagnosis_jobs; tests.
Requirements: run span arrival -> job run_after = now + AUTOPSY_SETTLE_SECONDS (default 5); spans without a run span ->
run_after = last span + AUTOPSY_INCOMPLETE_TIMEOUT_SECONDS (600); E2 pipelines with missing referenced artifacts: re-queue once
(+30 s); exceptions -> job failed with traceback, loop continues; results replace observations/findings in one transaction;
executions.verdict/trace_grade/diagnosed_at set; unregistered pipeline -> status unregistered, no diagnosis.
Tests (settle = 0): healthy fixture -> NO_ISSUE_DETECTED; fan-out f2-shaped fixture -> origin document_processing@<item>;
grade-C fixture -> INSUFFICIENT_EVIDENCE; re-queue; exception isolation; re-diagnosis replaces rows.
Acceptance: green. Process: plan first.
```

## A2.6: Read API + removal of the old engine

```text
Task A2.6: Read API and removal of the old diagnosis engine.
Read: planning/03_architecture/26_api_spec.md (Read + Routes deleted), 22 §"What is removed".
In scope: autopsy/api/routes_read.py (new), autopsy/api/routes.py (delete old routes), delete
services/root_cause_service.py, failure_detection_service.py, reconstruction_service.py, agent_service.py, detectors/,
domain/ modules only used by them, their tests; old tables dropped via migration 002 (keep autopsy_projects, autopsy_api_keys).
Keep services/diagnosis_service.py DeterministicDiagnosisBuilder file (moved to autopsy/explain/legacy_template.py) for E5.1.
Requirements: endpoints exactly as specified incl. 404/409; graph JSON nodes/edges with data vs control edges.
Acceptance: contract tests per route; grep for deleted module names returns nothing; report deleted test count and reasons.
```

## A2.7: Toy pipeline + end-to-end → M1

> **For you:** milestone M1. A tiny non-insurance pipeline sends traces over the network and Autopsy diagnoses three scenarios correctly. Run `python examples/toy_pipeline/run.py --fault short_body` yourself with Autopsy running, then `curl` the diagnosis.

```text
Task A2.7: Toy pipeline and end-to-end over HTTP (Milestone M1).
Read: planning/04_telemetry/32 (toy manifest), 41_sdk_design.md, 29_evaluation_framework.md (recorded cases).
In scope: pipeline-autopsy/examples/toy_pipeline/{run.py,README.md}; pipeline-autopsy/tests/e2e/test_toy_e2e.py;
AUTOPSY_RECORD_DIR support in ingest (write trace.json, artifacts/, manifest.yaml, draft expected.yaml); pipeline-autopsy/evals/run_l1.py;
recorded cases evals/golden/toy_*; CI step running run_l1.py.
Requirements: run.py uses only autopsy_sdk + autopsy_sdk.configure; no network except Autopsy; faults none|short_body|publish_timeout.
Acceptance: none -> NO_ISSUE_DETECTED; short_body -> origin fetch OUTPUT_CONTRACT_VIOLATION; publish_timeout -> origin publish
SERVICE_EXECUTION_FAILURE; run_l1.py exits 0. Draft expected.yaml files must be shown in the report for my review; I approve before commit.
```

## U3.1 → U3.3: Autopsy UI → M2

> **For you:** this is the screen you will demo. Read `planning/07_frontend/60_autopsy_ui.md` first. After U3.2, open the `short_body` run and check that `fetch` is red and its evidence says `schema.minLength`.

```text
Task U3.1: Autopsy UI scaffold and runs list.
Read: planning/07_frontend/60_autopsy_ui.md (IA, Page 1), 26_api_spec.md.
In scope: pipeline-autopsy/ui/ (Vite React TS, React Router, plain CSS), dev proxy to :8080, Vitest setup.
Acceptance: npm run build OK; Vitest list test; with toy recordings ingested, list shows 3 runs and correct badges (screenshot in report).
```

```text
Task U3.2: Run investigation page.
Read: 60_autopsy_ui.md Page 2 (layout, colours with labels, interactions, states).
In scope: ui/src/pages/RunPage.tsx and components (Graph.tsx deterministic SVG layout: columns = manifest order, rows = items +
"claim" row; data edges solid, control edges dashed; data-role/data-stage/data-item-role attributes on boxes), EvidencePane, FindingsList.
Acceptance: Vitest layout test on a fan-out fixture graph JSON; short_body run shows fetch as ORIGIN with schema.minLength evidence (screenshot).
```

```text
Task U3.3: Serve UI from FastAPI + Docker multi-stage + Playwright smoke (Milestone M2).
In scope: pipeline-autopsy/Dockerfile (node build stage -> copy ui/dist), main.py static mount at /ui with SPA fallback,
ui/playwright.config.ts + tests, CI job.
Acceptance: docker compose up; http://localhost:8080/ui shows runs; Playwright test from 60 §Tests passes in CI.
```

---

## B4.1: Adjudication rules engine (business track; can start after P0.2)

> **For you:** this is the claim decision, written as plain readable rules with no AI. Read `planning/06_insurance_pipeline/51_adjudication_and_final_result.md`. Review the rule table yourself, because it is business logic you own.

```text
Task B4.1: Adjudication rules engine (pure functions).
Read: planning/06_insurance_pipeline/51_adjudication_and_final_result.md; insurance-pipeline/backend/app/information_extraction/schemas.py (ALLOWED_FIELDS).
In scope: rename backend/app/rule_engine_decision/ -> backend/app/adjudication/; adjudication/schemas.py, rules.py, service.py
(pure: inputs = claim form dict + policy facts + list of proof facts; output = Decision model); tests/test_adjudication_rules.py.
Requirements: rules v1 exactly as the table; RULES_VERSION="adjudication-rules-v1"; repeatable/conflicting fields -> not_evaluable;
each rule result lists input references (document id + field); Decimal for money; currency tolerance reuse from content_service.
Must remain unchanged: all existing modules and tests. No DB/API changes.
Acceptance: per rule pass/fail/not_evaluable tests; aggregation table tests; determinism test; existing 56 tests still pass.
```

## B4.2: Claim-run orchestrator + persistence

```text
Task B4.2: POST /claims/{id}/process orchestrating document stages + adjudication.
Read: 50_target_workflow.md, 51 (Persistence), backend/app/document_processing/claim_service.py.
In scope: backend/app/orchestrator/service.py + api.py, database/migrations/005_adjudication.sql, adjudication persistence,
main.py router include, tests/test_claim_run.py (mock Gemini via the existing test patterns).
Requirements: reuse ClaimDocumentProcessingService unchanged; after a COMPLETED/PARTIAL run with accepted policy + ≥1 accepted
proof, build adjudication inputs from accepted validated facts and claims row; persist adjudication_results keyed by run_id;
blocked policy -> no adjudication, response status BLOCKED; replay with same config_version -> stored result.
Acceptance: APPROVED fixture, REJECTED (out-of-coverage bill) fixture, blocked-policy fixture, replay fixture; all old tests green.
```

## B4.3: Final result + result API + UI decision panel

```text
Task B4.3: Final result stage, GET /claims/{id}/result, UI decision panel.
Read: 51 (Final result), 07_frontend/61_insurance_ui_changes.md.
In scope: backend/app/final_result/, result endpoint (owner token like documents/status), claims.claim_status update,
frontend ClaimDocumentsPage.tsx: "Process claim" uses /process; decision panel.
Acceptance: mapping tests; 401/404 without token; frontend build; manual: process fixture claim in UI -> APPROVED (screenshot).
```

## T4.1: Telemetry bootstrap + run span

> **For you:** after this task, the insurance pipeline sends real traces for the first time. If `JAEGER_OTLP_ENDPOINT` is set and Jaeger is running, you can see them there.

```text
Task T4.1: Insurance telemetry bootstrap with autopsy-sdk.
Read: planning/06_insurance_pipeline/52_instrumentation_plan.md (Bootstrap), 41_sdk_design.md, 31 contract.
In scope: backend/app/observability/setup.py, main.py, backend/requirements.txt (opentelemetry-sdk,
opentelemetry-exporter-otlp-proto-http, autopsy-sdk via local path), backend/Dockerfile + docker-compose.yml (build context = repo
root so ../autopsy-sdk installs), delete backend/app/telemetry/, replace its call sites in quality_validator.py,
content_service.py, pdf_inspector.py with autopsy_sdk.operation (behaviour unchanged), orchestrator wraps the claim run in autopsy.run().
Requirements: run id = document_processing_runs.id; entity id = claims UUID; pipeline.run.items from resolved documents;
outcome at end; no exporter env -> app runs (no-op); privacy test: export with InMemoryCapture on fixture claim and assert none
of the fixture's name/policy number/amount strings occur in any attribute or event value.
Acceptance: tests green incl. privacy test; docker compose build OK (manual).
```

## T4.2 / T4.3 / T4.4: Instrument the stages

```text
Task T4.2: Instrument document_processing per document and attempt.
Read: 52 (table rows run + document_processing; error mapping), 34 (retries), 31.
In scope: backend/app/document_processing/claim_service.py (wrap per document/attempt in autopsy.stage, record page_text artifact,
emit ocr.quality / document.file_valid / ocr.retry_exhausted checks), DocumentProcessingError optional error_class/code,
tests/test_document_processing_spans.py.
Acceptance: healthy fixture spans pass assert_contract grade A with the insurance manifest; retry fixture has attempts 1 and 2;
blocked-policy fixture: no proof stage spans and run items list the proofs; all previous tests green.
```

```text
Task T4.3: Instrument classification, extraction, validation.
Read: 52 rows 3-5, 30 §5 (GenAI attributes), 31.
In scope: backend/app/information_extraction/content_service.py (stage spans, GenAI operation spans per request/batch without any
content, checks: classification.evidence_quotes, classification.matches_declared, extraction.page_coverage, one extraction.<check_id>
per ValidationCheck with field + target), tests.
Acceptance: mocked Gemini fixtures produce expected spans/checks; mismatch fixture -> matches_declared fail; hallucinated quote fixture ->
extraction.quote_support fail with field and target; lineage complete (contract test); privacy test still green.
```

```text
Task T4.4: Instrument adjudication and final result.
Read: 51 (Telemetry), 52.
In scope: orchestrator/adjudication/final_result instrumentation, tests.
Acceptance: each rule emitted as kind=decision_rule with target validated_facts artifact + field; rules.input_complete and
final.matches_decision checks; contract test grade A on healthy fixture.
```

## T4.5: Evidence levels + redacted excerpts

```text
Task T4.5: Evidence levels and redacted excerpts.
Read: 33 (§2, §3, §5), 52 (artifact contents table).
In scope: backend/app/observability/evidence.py (excerpt builder: lines containing any extracted value ± 80 chars; facts redaction),
wiring to autopsy_sdk uploader via record_artifact, env AUTOPSY_EVIDENCE_LEVEL / AUTOPSY_EVIDENCE_KINDS, tests.
Acceptance: E1 -> zero uploads; E2 -> only allowed kinds; excerpt contains value lines only; masks applied (fake HTTP server).
```

## T4.6: Fault injection

```text
Task T4.6: Fault injection and FakeGemini.
Read: 53_fault_injection_and_demo.md (Mechanism, Scenarios 1-9).
In scope: backend/app/faults.py (hook registry; pipeline.fault.name on run span only), hook call sites, FakeGemini
(tests + demo; recorded responses from demo_documents/gemini_demo_results.json), demo_documents fixtures for scenarios, tests.
Acceptance: each scenario produces its business outcome from table 53; faults inert unless FAULT_INJECTION_ENABLED=true (test).
```

## T4.7: Root compose + e2e + golden recordings → M3

> **For you:** milestone M3, the MVP demo. You will run `scripts\demo.ps1`, see two REJECTED claims, and open both in Autopsy to see different red boxes. **You** approve each `expected.yaml`.

```text
Task T4.7: Root docker-compose, insurance -> Autopsy e2e, golden recordings (Milestone M3).
Read: 53 (headline demo, recording), 72 (definition of done), 61 (Open in Autopsy link).
In scope: root docker-compose.yml (include both stacks; network; jaeger profile; one-shot "register" service that registers
shared-docs/manifests/insurance-claims.yaml), insurance env wiring to http://autopsy:8080/v1/traces with key,
tests/e2e/test_insurance_scenarios.py (scenarios 1-9, FakeGemini, E2 profile), evals/golden/ins_* recordings,
frontend "Open in Autopsy" link, scripts/demo.ps1 + demo.sh.
Acceptance: verdicts match 53 for all 9 scenarios; demo script prints two different origins for the same REJECTED symptom;
run_l1.py green in CI; draft expected.yaml files shown in the report for my approval before commit.
Process: plan first.
```
