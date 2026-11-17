# 41: autopsy-sdk v2 design

## Purpose

`autopsy-sdk` is a **thin semantic layer** over the standard OpenTelemetry API. It makes it a few lines of code to emit contract-v3 spans: run, stage, attempt, item, artifact IDs, checks, error class. It is **not** a tracing system.

## Package boundaries and distribution

| Item | Decision |
|---|---|
| Location | Repo root `autopsy-sdk/` (moved from `pipeline-autopsy/packages/`; required so the insurance Docker build can install it; blocker B5) |
| Name / import | `autopsy-sdk` / `import autopsy_sdk as autopsy` |
| Runtime dependency | `opentelemetry-api>=1.25` only |
| Optional extras | `[configure]` → `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`; `[upload]` → `httpx` |
| Python | ≥ 3.10 (insurance uses 3.12 in Docker; your Windows venv uses 3.14) |
| First release language | **Python only.** Both of our pipelines are Python, and the target AI-pipeline ecosystem is mostly Python. Other languages can still emit the contract with plain OTel; the contract is language-neutral |
| Versioning | SemVer. `autopsy.sdk.version` and `autopsy.schema.version="pipeline-trace/3"` go on the run span |

## Public API (complete)

```python
import autopsy_sdk as autopsy

autopsy.set_pipeline(name="insurance-claims", version="2.0.0")         # once at startup (or env AUTOPSY_PIPELINE_NAME/VERSION)

with autopsy.run(entity_id=claim_uuid, items={doc_id: "policy", ...},  # opens the run span
                 run_id=None, trigger="api", previous_run_id=None) as run:
    src = autopsy.artifact_id(kind="source_document", content={"sha256": doc.checksum}, item_id=doc_id)

    with autopsy.stage("document_processing", item_id=doc_id, item_role="policy",
                       inputs=[src], attempt=1) as st:
        pages = extract_text(...)
        pt = st.record_artifact(kind="page_text", content=pages_json)          # returns id; appends to outputs
        st.check("ocr.quality", kind="threshold", result="warn", action="continued",
                 target=pt, observed="low_conf_ratio=0.62", expected="<=0.5")
        with st.operation("tesseract_page", attributes={"pipeline.item.index": 3}):
            ...
        st.set_status("partial")                                               # optional; default success

    run.set_outcome("success")                                                 # optional; default derived
```

| Function | Behaviour |
|---|---|
| `run(...)` | Starts a span with `pipeline.span.role=execution`, a new UUID run ID (unless given), `pipeline.run.items`, trigger, and a link to the previous run. On exit sets `pipeline.run.outcome`. If an exception escapes: `failed`, re-raised |
| `stage(name, ...)` | Starts a child span with `role=stage`, name, attempt, item, inputs. **Status is set only on exit**: `success`, `failed` if an exception escapes, or an explicit `set_status`. Never `running` |
| exception in stage | Span status Error (description = `safe_message(exc)`, ≤ 500 chars, PII-masked), `error.type` = class name, `pipeline.error.class` from the mapping below, then **re-raise unchanged** |
| `record_artifact(kind, content, item_id=None)` | Computes the ID locally (contract §2), appends it to `pipeline.artifact.output_ids`, returns it. If evidence upload is enabled and the kind is allowed, enqueues a redacted copy (non-blocking) |
| `artifact_id(kind, content, item_id)` | Pure function; same algorithm. Used for inputs that came from elsewhere (e.g. uploaded files) |
| `st.add_input(id)` | For inputs discovered mid-stage |
| `check(id, kind, result, action, target=None, field=None, observed=None, expected=None)` | Adds a span event `pipeline.check`. `observed`/`expected` are truncated to 64 chars. Outside any stage it is ignored, with one warning |
| `operation(name, attributes=None)` | Child span with `role=operation`. Errors recorded the same way, re-raised |
| `propagate.submit(executor, fn, *a)` | Runs `fn` with the current context attached; detaches in `finally` |
| `configure(...)` | **Optional, greenfield only.** See below |
| `flush(timeout)` | Flushes the uploader (and the provider if `configure()` created it) |

### Default `pipeline.error.class` mapping

Overridable per stage: `stage(..., error_classes={MyError: "data"})`.

| Class | Exceptions |
|---|---|
| infra | `TimeoutError`, `ConnectionError`, `OSError`, `httpx.TransportError`, HTTP 408/429/5xx, class names containing `Timeout`, `RateLimit`, `Unavailable`, `ResourceExhausted`, `ServerError` |
| data | `ValueError`, `KeyError`, `TypeError`, `json.JSONDecodeError`, `pydantic.ValidationError`, `autopsy.DataError`, `autopsy.GateBlocked` |
| unknown | everything else |

### Never break the host

Every SDK call is wrapped. An internal SDK error logs one WARNING and the pipeline continues. Exceptions raised by *your* code always propagate unchanged.

## What the SDK does NOT do

- It does not create or replace a TracerProvider (except in `configure()`, and even then it never overrides an existing one).
- It does not export spans itself; the application's OTel exporter does.
- It does not decide failures, does not diagnose, and does not call Autopsy for anything except the optional evidence upload.
- It does not capture prompts, documents or extracted values.
- It does not auto-instrument frameworks; use the standard OTel instrumentors for that.

## Integration code

### A. A company that already uses OpenTelemetry

```python
# unchanged: their existing provider/exporter setup (or opentelemetry-instrument)
import autopsy_sdk as autopsy
autopsy.set_pipeline("claims", "3.1.0")

def process_claim(claim):
    with autopsy.run(entity_id=claim.uuid):
        with autopsy.stage("extract", inputs=[autopsy.artifact_id("document", {"sha256": claim.doc_sha})]) as st:
            facts = extractor.run(claim)
            st.record_artifact("facts", facts)
            for r in validator.check(facts):                       # their existing validation
                st.check(r.code, kind="rule", result="fail" if not r.ok else "pass",
                         action="continued", field=r.path)
        ...
```

To send a copy to Autopsy, either change nothing in code and add the Collector exporter (`40_integration_options.md`), or set:

```bash
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=https://autopsy.example.com/v1/traces
OTEL_EXPORTER_OTLP_HEADERS="authorization=Bearer <key>"
```

This works only if Autopsy is their *only* trace destination. Otherwise use the Collector, or add a second processor in code:

```python
from opentelemetry import trace
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(
    OTLPSpanExporter(endpoint="https://autopsy.example.com/v1/traces",
                     headers={"authorization": "Bearer <key>"})))
```

### B. A company starting from scratch

```python
import autopsy_sdk as autopsy
autopsy.configure(service_name="claims-api", environment="development",
                  endpoint="http://localhost:8080", api_key="dev-key",
                  extra_otlp_endpoint="http://localhost:4318/v1/traces")   # optional Jaeger
autopsy.set_pipeline("claims", "0.1.0")
```

`configure()` behaves as follows:

- If no SDK provider is set, it creates `TracerProvider(Resource(service.*, deployment.environment.name))` with a `BatchSpanProcessor(OTLPSpanExporter(...))`.
- If a provider already exists, it **adds** a processor and logs that it did so. It never replaces the provider.
- It wraps exporters in the existing `SafeSpanExporter` idea.

## Async and concurrency

- `contextvars`-based: `await` and `create_task` keep context.
- Threads need `propagate.submit`.
- Stage objects are not thread-safe. Use one `stage()` per worker.

## Configuration and secrets

Environment variables:

| Variable | Purpose |
|---|---|
| `AUTOPSY_PIPELINE_NAME`, `AUTOPSY_PIPELINE_VERSION` | Pipeline identity |
| `AUTOPSY_ENDPOINT`, `AUTOPSY_API_KEY` | Upload and `configure()` |
| `AUTOPSY_ENABLED=false` | Turns every call into a no-op |
| `AUTOPSY_EVIDENCE_LEVEL`, `AUTOPSY_EVIDENCE_KINDS` | Evidence upload |

The key is never logged.

## Offline / local development

- With no provider configured, spans are no-ops (standard OTel behaviour). The pipeline runs normally.
- `autopsy_sdk.testing.InMemoryCapture()` captures spans in tests. It is built on `InMemorySpanExporter`.
- `autopsy_sdk.testing.assert_contract(spans, manifest)` runs the same `validate_trace` logic as the Autopsy core. It is vendored, so it does not import Autopsy.

## Tests (S1.1 acceptance)

1. A stage that exits normally has `success` and every required attribute.
2. An escaped exception gives `failed`, the class is mapped, the message is sanitized, and the exception is re-raised.
3. A `record_artifact` ID equals the contract formula, and the ID is in `output_ids`.
4. Same content with a different kind or item gives a different ID.
5. A check event has all required fields, with `observed` truncated.
6. Nested `stage` inside `stage` raises `AutopsyUsageError` in strict mode and is treated as an operation otherwise.
7. With no provider configured, there are no exceptions and no output.
8. `AUTOPSY_ENABLED=false` produces zero spans.
9. **Emitted spans pass `assert_contract` with grade A** against the toy manifest.
10. `configure()` with an existing provider adds a processor and does not replace the provider.
11. Uploader: Autopsy unreachable means the pipeline still finishes. Retries are bounded (3 attempts, 0.5/1/2 s), then the upload is dropped with a log line.

## Example in a generic non-insurance pipeline

See `pipeline-autopsy/examples/toy_pipeline/run.py` (A2.7): fetch → summarize → publish, with `--fault short_body|publish_timeout|none`.
