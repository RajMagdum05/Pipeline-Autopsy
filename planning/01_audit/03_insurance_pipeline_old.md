# 03: Audit of `insurance-pipeline-old` (and the GitHub `insurance-pipeline/`)

**Verdict:** **Remove from the active path. Archive it.** Keep it in git history (and optionally under `archive/`) as a source of ideas only.

## Evidence

| Check | Result | How |
|---|---|---|
| Collect tests (local `insurance-pipeline-old`) | **36 collection errors, 0 tests run** | `pytest tests` → `NameError: name 'Optional' is not defined` at `backend/app/pipeline_services/ocr/orchestrator.py:37` |
| Same on GitHub `insurance-pipeline/` @ `3d2c621` | **Same NameError** | `app/pipeline_services/ocr/orchestrator.py` imports `Union` but not `Optional` |
| After adding the missing import in a scratch copy (not in your repo) | 90 passed, 26 failed, 6 errors | The 6 errors are `ModuleNotFoundError: app.storage` (a module referenced by `services/claim_service.py` that does not exist). The failures include Gemini-dependent tests, page rendering, telemetry end-to-end |

## What it had that matters

| Idea | Where | Carried into the plan? |
|---|---|---|
| Stage spans with `pipeline.name`, `execution.id`, `stage.name`, `stage.status`, artifact-ID lists | `backend/app/telemetry/span_helpers.py`, `attributes.py` | Yes, renamed into the namespaced v3 contract |
| OTLP export to Jaeger (`OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318/v1/traces`) | `docker-compose.yml`, `telemetry/tracer.py` | Yes, as an *optional second* destination |
| A rule engine (`pipeline_services/rule_engine/rule_engine_service.py`, 18 KB) | old | **Ideas only.** It worked on the old extraction shape. The new adjudication is designed from the new validated-facts shape |
| Span-contract tests (`test_*_span_contract.py`) | old tests | The pattern is reused: in-memory exporter + attribute assertions |
| Invented artifact IDs (`f"art_ocr_{doc.id}"`) | old orchestrator | **No.** Replaced by content-hash IDs |
| `stage.status="running"` set at start | old helpers | **No.** Status is set once, on exit |

## Why not repair it?

- `insurance-pipeline-new` already re-implements intake and document processing with stronger validation and passing tests.
- Two producer implementations would double every instrumentation task.
- The old rule engine targets a data shape that no longer exists.
