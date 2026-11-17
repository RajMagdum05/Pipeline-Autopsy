# 04: Audit of `pipeline-autopsy` (the engine)

**Runtime evidence (16 Nov 2026):**
- `pytest tests packages/autopsy-sdk/tests` → **86 passed** (SQLite).
- Runtime probes post real OTel-SDK protobuf to `POST /v1/traces` through FastAPI's TestClient and then call the RCA and diagnosis routes. Scripts are in `reference/probes/`. Results are in `06_runtime_verification_log.md`.

**Verdict:** **keep the shell, replace the brain.**
- The ingestion route, the DB layer, the FastAPI app and the template-diagnosis code are reusable.
- Detectors, RCA, the agent and the SDK model of the world must be replaced. They reason over span nesting and span status only, and that produces wrong answers.

## Component status

Status key: ✅ working and verified · 🟡 implemented, not runtime-verified · 🟠 partial · ⚪ stub · ❌ broken / wrong · 🗄 legacy · ➖ missing

| Component | Path | Status | Evidence | Decision |
|---|---|---|---|---|
| FastAPI app, startup creates tables | `autopsy/main.py` | ✅ | Probes: tables are created on startup (`with TestClient(app)`) | Keep. Move from `on_event` to lifespan |
| OTLP ingest route (protobuf + JSON) | `api/routes.py:76` | ✅ / ❌ | Real protobuf accepted (200). Re-delivery deduplicated (second post persisted 0 spans). **Also registered at `/v1/traces/v1/traces`** | Repair |
| Trace / span ID normalization | `adapters/otlp_adapter.py:52 _parse_hex_id` | ❌ | Protobuf → `MessageToDict` gives base64. 8-byte span IDs (12 base64 chars) are **not** decoded and are stored lower-cased (`ql/w/x4t/zi=`). Trace IDs (24 chars) are decoded. A malformed `traceId:"zz"` is accepted | Repair (A2.1) |
| Execution grouping | `otlp_adapter.py:185` | ❌ | Reads `execution.id` only from **resource** attributes. Producers set it on spans, so every trace becomes `exec-<traceid>` | Repair (read span attributes first) |
| Span/event persistence | `services/ingestion_service.py`, `db/models.py` (`autopsy_spans`, `autopsy_events`) | ✅ | List attributes and `autopsy.check` events with numeric values are preserved (probe 3) | Keep |
| Partial success, gzip, size limits, 429 | — | ➖ | Not implemented | Build (A2.1) |
| Reconstruction (tree, orphans, duplicates) | `services/reconstruction_service.py` | 🟡 | Detects `ORPHAN_SPAN`, `DUPLICATE_SPAN_ID`, `EMPTY_TRACE`. Covered by unit tests | Keep the ideas. Replaced by the core's `validate_trace` + lineage |
| Lineage / data-flow graph | — | ➖ | No code reads `input.artifact_ids` / `output.artifact_ids` | Build (core) |
| Contract validation | — | ➖ | No detector reads `stage.name` or `stage.status` | Build (core) |
| Detectors | `detectors/detectors.py` (ErrorStatus, Exception, Timeout, DependencyFailure, StructuralTelemetry, ExplicitValidation) | ❌ | Probe B: `stage.status=failed` with OTel OK yields **NO_FAILURES**. `ExplicitValidationDetector` looks for `validation.error` / `schema.valid`, which no producer emits | Replace with core observation families |
| Root-cause engine | `services/root_cause_service.py` | ❌ | Probes A and C: **root span `claim_processing` reported as root cause, `rule_engine` reported as downstream impact** | Replace with the core RCA |
| Finding persistence | `autopsy_failures`, `autopsy_evidence`, `autopsy_incidents` | 🟡 | Written by the old engine | Replace with `observations` / `findings` tables |
| LLM diagnosis | `services/diagnosis_service.py:303 LLMDiagnosisService` | 🟠 | Gemini call. The "consistency" guard only rejects text containing *all three* of "success", "no errors" and "no failure", or naming no known service | Replace with the guarded explanation step (Phase 5). The LLM must never choose the cause |
| Deterministic diagnosis builder | `diagnosis_service.py:167 DeterministicDiagnosisBuilder` | 🟡 | Produces text from candidates | Refactor → template explanation |
| "Agent" | `services/agent_service.py` | 🟠 | A fixed sequence of tool calls. Its only LLM use is the diagnosis call above | Remove from the active path (Phase 8 may build a real bounded investigator) |
| RAG / knowledge | — | ➖ | pgvector image, no use | Build later as keyed playbooks. No vectors |
| Evaluation | — | ➖ | No golden dataset in the repo (the reference golden tests live in the Project docs) | Build (P0.3) |
| Auth: API keys, projects, multi-tenancy | `api/auth.py`, `services/credential_service.py`, `autopsy_projects`, `autopsy_api_keys` | 🟡 | Tests pass. **Internal routes (`/failures`, `/root-cause`, `/diagnose`, `/investigate`, `/reconstruction`) have no auth dependency at all.** `AUTOPSY_REQUIRE_API_KEY` defaults to false | Freeze. Use one static key for the MVP. Revisit in X7.2 |
| Customer REST API | `/api/v1/dashboard`, `/api/v1/executions/...` | 🟡 | Tests pass | Replace with the trimmed API (26_api_spec.md) |
| Product UI | — | ➖ | `website/` is marketing only | Build (Phase 3) |
| DB config | `db/database.py` | ❌ (risky) | Socket-probes Postgres and **silently falls back to SQLite**. The Dockerfile even sets `AUTOPSY_DATABASE_URL=sqlite:////app/storage/autopsy.db` | Repair: fail fast unless the URL says sqlite |
| Docker | `Dockerfile` (python 3.11), `docker-compose.yml` (pgvector, host port 5433) | 🟡 | Not run in this audit (no Docker in the audit sandbox) | Repair: postgres:16-alpine, host port 5434 |
| Manual scripts | `autopsy/scripts/manual_*.py` | 🗄 | 7 ad-hoc scripts | Remove |
| Legacy | `legacy/` (early prototype, monorepo scripts, 4.4 MB `autopsy.db`) | 🗄 | Not imported | Remove from git (it stays in history) |
| SDK | `packages/autopsy-sdk/` | 🟠 | See `05_sdk_shared_docs_website.md` | Replace |
| Example customer app | `examples/customer_app/sample_customer_app.py` | 🗄 | Uses the old SDK | Replace with a toy pipeline (A2.7) |

## The three verified correctness failures

1. **Wrong origin (probe A).** A trace has stages document_processing → information_extraction → rule_engine (raises `ValueError`) as siblings under a root span. The RCA returns `ROOT_CAUSE_IDENTIFIED`, candidate `claim_processing`, relationship `UPSTREAM_DEPENDENCY_PROPAGATION`, downstream `[rule_engine]`. The root span is blamed because the exception propagated into it.
2. **Silent failure invisible (probe B).** `rule_engine` sets `stage.status=failed` but does not raise. The result is `NO_FAILURES`.
3. **Bad upstream data invisible (probe C).** Extraction marks `validation.status=FAILED` and the rule engine then raises. The result is the same as A: extraction is never mentioned.

**Root cause of all three:** the engine infers causality from *call nesting* (parent/child). In a pipeline, failure travels through *data*: stage A's output becomes stage B's input. The design fixes this with a lineage graph built from artifact IDs. See `03_architecture/23_diagnosis_core_algorithm.md`.
