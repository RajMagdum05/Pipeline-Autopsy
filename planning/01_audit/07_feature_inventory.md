# 07: Current-state feature inventory and reuse decisions

## How to read this table

**Decisions:**
- **Keep:** correct as is.
- **Repair:** the approach is good but the code is broken or incomplete.
- **Refactor:** the behaviour is good but the structure needs changing.
- **Replace:** the approach is wrong.
- **Remove:** the code is obsolete.
- **Build:** the feature does not exist yet.

**Status:**
- ✅ working and verified
- 🟡 implemented, not runtime-verified
- 🟠 partial
- ⚪ stub only
- ❌ broken or wrong
- ➖ missing

Task IDs refer to `08_roadmap/70_task_list.md`.

## Insurance pipeline (producer)

| Capability | Location | Status | Evidence | Decision | Work (task) |
|---|---|---|---|---|---|
| Claim intake API + file validation + storage | `insurance-pipeline-new/backend/app/claim_document_intake/` | ✅ | 6 tests pass | Keep | Rename folder (P0.1) |
| Owner-token access to claim status | `claim_document_intake/auth.py` | ✅ | `test_document_status_requires_claim_token...` | Keep | — |
| File validation, PyMuPDF/Tesseract extraction, hybrid routing | `document_processing/*` | ✅ | 23 tests + real-Tesseract test | Keep | Instrument (T4.2) |
| OCR quality gate with retry (≤2) | `quality_validator.py`, `claim_service.py:319` | ✅ | `test_retry_exhaustion_requires_human_review...` | Keep | Emit `ocr.quality` checks (T4.2) |
| Policy-first gate blocking proofs | `claim_service.py:162` | ✅ | `test_missing_or_failed_policy_blocks_proof_processing` | Keep | Model as a control edge (C1.1) |
| Gemini classification + quote verification | `information_extraction/content_service.py:272` | ✅ (mocked) / live demo recorded | tests + `demo_documents/` | Keep | `gen_ai` spans + checks (T4.3) |
| Gemini extraction (7 schemas, batching) | `content_service.py:316`, `schemas.py` | ✅ (mocked) / live demo recorded | tests | Keep | T4.3 |
| Deterministic extraction validation | `content_service.py` ≈520–620 | ✅ | 20 tests in `test_document_content.py` | Keep | Emit checks (T4.3) |
| Adjudication / rule engine | `rule_engine_decision/` | ⚪ | Docstring only | Build | B4.1, B4.2 |
| Final result | `final_result/` | ⚪ | Docstring only | Build | B4.3 |
| Claim-run orchestration | `orchestrator/` | ⚪ | Docstring only | Build | B4.2 |
| Telemetry helpers | `telemetry/span_helpers.py` | ❌ | No provider, so spans are discarded; status `running` at start | Replace | T4.1 |
| Trace export | — | ➖ | No SDK or exporter in requirements | Build | T4.1 |
| Fault injection for demos and evals | — | ➖ | — | Build | T4.6 |
| Insurance UI (create claim, documents status) | `insurance-pipeline-new/frontend` | ✅ (builds) | `npm run build` OK | Keep | Decision view (B4.3), Autopsy link (T4.7) |
| Docker compose (API + Postgres + UI) | `insurance-pipeline-new/docker-compose.yml` | 🟡 | Not run (no Docker) | Repair | Model env consistency; SDK build context (T4.1) |
| Old pipeline | `insurance-pipeline-old/` | ❌ | Import errors | Remove (archive) | P0.1 |

## Autopsy (engine)

| Capability | Location | Status | Evidence | Decision | Work |
|---|---|---|---|---|---|
| FastAPI app and lifespan | `autopsy/main.py` | ✅ | probes | Keep | A2.1 (switch `on_event` to lifespan) |
| OTLP/HTTP ingest (protobuf + JSON) | `api/routes.py:76`, `adapters/otlp_adapter.py` | ✅ / ❌ | Probe 3b: span-ID bug | Repair | A2.1 |
| Idempotent re-delivery | `ingestion_service.py` | ✅ | Probe 4 | Keep | — |
| Execution ID from span attributes | `otlp_adapter.py:185` | ❌ | Reads resource only | Repair | A2.1 |
| OTLP partial_success, gzip, limits, 429 | — | ➖ | — | Build | A2.1 |
| Span tree reconstruction (orphans, duplicates) | `reconstruction_service.py` | 🟡 | unit tests | Replace (subsumed by core) | P0.3 / A2.5 |
| Lineage graph from artifacts | — | ➖ | — | Build | P0.3 |
| Contract validation and trace grade | — | ➖ | — | Build | P0.3, C1.2 |
| Detectors (status, exception, timeout, validation) | `detectors/detectors.py` | ❌ | Probe B | Replace | P0.3 |
| Root-cause analysis | `services/root_cause_service.py` | ❌ | Probes A, C | Replace | P0.3, A2.5 |
| Per-document (fan-out) diagnosis | — | ➖ | Prototype 8/8 in `reference/` | Build | P0.3 |
| Artifact evidence store | — | ➖ | — | Build | A2.3 |
| Manifest registry | `autopsy_pipelines` table exists (unused for manifests) | 🟠 | — | Build | A2.4 |
| Diagnosis worker / job queue | — | ➖ | Diagnosis only runs on manual POST | Build | A2.5 |
| Findings API | `/api/v1/executions/...` | 🟡 | tests | Replace | A2.6 |
| Template (deterministic) explanation | `DeterministicDiagnosisBuilder` | 🟡 | tests | Refactor | E5.1 |
| LLM explanation | `LLMDiagnosisService` | 🟠 | Weak guard | Replace | E5.2, E5.3 |
| "Agent" investigation | `agent_service.py` | 🟠 | Fixed script | Remove (active path) | A2.6. A real bounded investigator is optional in G8.1 |
| Playbooks / knowledge | — | ➖ | — | Build | K6.1 |
| Feedback on findings | — | ➖ | — | Build | K6.2 |
| Evaluation (golden, L1/L2) | Project docs only | 🟠 | 29/29 re-run | Build in repo | P0.3, T4.7, E5.4 |
| API keys / projects / multi-tenancy | `api/auth.py`, `credential_service.py` | 🟡 | tests; internal routes unauthenticated | Refactor later | MVP: static key (A2.1); X7.2 |
| Product UI | — | ➖ | — | Build | U3.1–U3.3 |
| DB connection | `db/database.py` | ❌ (risky) | Silent SQLite fallback | Repair | A2.1 |
| Docker (pgvector, port 5433) | `docker-compose.yml`, `Dockerfile` | 🟡 | not run | Repair | A2.1 |
| Website | `website/` | 🟡 | marketing | Keep, frozen (compose profile) | A2.1 |
| Manual scripts, `legacy/` | | 🗄 | unused | Remove | P0.1 |

## SDK and contract

| Capability | Location | Status | Decision | Work |
|---|---|---|---|---|
| SDK v0.1 | `pipeline-autopsy/packages/autopsy-sdk` | 🟠 | Replace with v2 at repo root `autopsy-sdk/` | S1.1, S1.2 |
| Trace contract v1 | `shared-docs/TRACE_CONTRACT.md` | 🟠 | Replace with v3 | C1.1 |
| Pipeline manifest | — | ➖ | Build | C1.1, A2.4 |
| Collector integration path | — | ➖ | Build (docs + compose profile) | X7.1 |

## Repository

| Capability | Status | Decision | Work |
|---|---|---|---|
| Rebuild committed to git | ❌ | Repair | P0.1 |
| `.gitignore` covers `node_modules`, DBs, caches, venvs, storage | ❌ | Repair | P0.1 |
| CI | ➖ | Build | P0.2 |
| `CLAUDE.md` standing rules | ➖ | Build | P0.2 |
