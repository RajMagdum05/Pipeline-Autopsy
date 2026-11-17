# 52: Insurance pipeline instrumentation plan

## Bootstrap (T4.1)

- **Location:** `backend/app/observability/setup.py`, called from `main.py` lifespan **before** routers handle requests.
- **Provider:** creates the OTel SDK `TracerProvider(Resource(service.name="insurance-pipeline-api", service.version, deployment.environment.name))`.
- **Exporters**, from environment variables:
  - `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`: Autopsy, `http://autopsy:8080/v1/traces` in compose.
  - `OTEL_EXPORTER_OTLP_HEADERS=authorization=Bearer …`.
  - Optional `JAEGER_OTLP_ENDPOINT` adds a second `BatchSpanProcessor` (ADR-20).
  - `OTEL_SDK_DISABLED=true` in tests that do not need spans.
- **Pipeline identity:** `autopsy.set_pipeline("insurance-claims", "2.0.0")`.
- **Remove** `app/telemetry/` and replace its two call sites (`quality_validator.py:277`, `content_service.py:596`) and `pdf_inspector.py:114`.
- **Requirements:** `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, and `autopsy-sdk` (local path `../../autopsy-sdk` for dev; Docker build context = repo root).
- **Tests:** use `autopsy_sdk.testing.InMemoryCapture` fixtures (no network).

## Per stage: spans, artifacts, checks

| Stage (span) | Inputs → outputs (artifact kinds) | Operation spans | Checks (`pipeline.check`) | Key attributes |
|---|---|---|---|---|
| **run** `claim_run` | — | — | — | `pipeline.run.items` (doc UUID:role), `pipeline.run.trigger`, `pipeline.run.outcome`, `pipeline.entity.id` = claim UUID (`claims.id`, not the human `claim_id` if that is guessable or PII). **Run id = `document_processing_runs.id`** |
| `document_processing` (per doc, per attempt) | `source_document` → `page_text` | `file_validation`, `text_extraction` (per page: `pipeline.item.index/count`, `pipeline.ocr.method`), `quality_gate` | `document.file_valid` (schema), `ocr.quality` (threshold; observed e.g. `low_conf_ratio=0.62;min_chars_ok=true`, expected `<=0.5`), `ocr.retry_exhausted` (action=review) | `pipeline.stage.attempt`, `pipeline.stage.version=ocr-quality-v2`, engine + version, config version |
| `content_classification` | `page_text` → `classification` | `generate_content <model>` (GenAI attrs) | `classification.evidence_quotes` (grounding), `classification.matches_declared` (classification; observed=detected type, expected=declared type) | `pipeline.prompt.version=content-classification-v1` |
| `information_extraction` | `page_text`, `classification` → `document_facts` | one `generate_content` span per batch (`pipeline.item.index`=batch) | `extraction.page_coverage` | `pipeline.prompt.version=document-extraction-v2`, `pipeline.schema.version=document-facts-v1` |
| `extraction_validation` | `document_facts`, `page_text` → `validated_facts` | — | one per `ValidationCheck`: `extraction.<check_id>` with result pass/fail/skip, `field` = issue field path, target = `document_facts` | `pipeline.stage.version=basic-extraction-validation-v1` |
| `adjudication` | all `validated_facts`, `claim_form` → `decision` | — | `rules.input_complete` (schema, fault); each rule as `decision_rule` (context) | `pipeline.stage.version=adjudication-rules-v1` |
| `final_result` | `decision` → `claim_result` | — | `final.matches_decision` (rule) | — |

## Artifact contents (what is hashed; what may be uploaded at E2)

| Kind | Canonical content hashed (never in spans) | E2 upload |
|---|---|---|
| `source_document` | `{"sha256": <file checksum>}` | No (it already is only a hash) |
| `claim_form` | `{"claim_id_hash": …, "fields_checksum": …}` | No |
| `page_text` | `[{page, method, text}]` of the accepted attempt | **Redacted excerpt** only |
| `classification` | Classification payload | No (enum data, low value) |
| `document_facts` | Extraction payload (fields, states, quotes) | Yes, after `redact()` (names masked except where needed for grounding: controlled by `AUTOPSY_EVIDENCE_KEEP_FIELDS`) |
| `validated_facts` | Accepted facts only | Optional |
| `decision` | Decision JSON (IDs, codes) | Yes |
| `claim_result` | `{decision, payable_amount, message_code}` | Yes |

## Error mapping to `pipeline.error.class`

| Exception in the pipeline | Class |
|---|---|
| `DocumentProcessingError` for file/size/MIME/checksum/limits | data |
| "Tesseract executable or language data unavailable" | infra (subclass it, or map by an error code) |
| Gemini timeout, 429, 5xx, `ServiceUnavailable` | infra |
| Pydantic or schema validation of model output | data |
| Gate decisions (`HUMAN_REVIEW_REQUIRED`, classification mismatch, validation review) | data, with `error.type=GateBlocked` + check `action=review` or `blocked` |

**Recommended small refactor in T4.2:** give `DocumentProcessingError` an optional `error_class` and `code`, so mapping does not rely on message text.

## Span-contract tests (one per stage instrumentation task)

- A healthy fixture claim (policy + bill) produces exactly the expected set of stage spans, roles, items and attempts.
- Every stage span passes `assert_contract(spans, manifest)` with grade A.
- Lineage is complete: every consumed kind has an input ID that some earlier stage output.
- **No attribute value contains fixture PII.** The fixture names, policy number and amounts are grepped across all exported attributes and event attributes. This is the privacy test.
- Failure fixtures produce the expected checks and error classes.
