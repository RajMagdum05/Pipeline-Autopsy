# 02: Audit of `insurance-pipeline-new` (the active producer)

**Verdict:** this is the best code in the repository. **Keep it.** Two things are missing:

- **Business completion:** a decision stage and a final result.
- **Telemetry that leaves the process:** today it never does.

**Runtime evidence:**
- `pytest` gives **56 passed** in 5.9 s on 16 Nov, with Tesseract 5.3.4 installed.
- `npm run build` succeeds.
- Your recorded live Gemini demo (`demo_documents/gemini_demo_summary.md`) shows 9/9 + 12/12 fields correct on synthetic PDFs.

## 1. Real execution path (traced statically, confirmed by tests)

```
POST /claims (multipart form)                         claim_document_intake/api.py:74 create_claim
  ├─ validate form fields, file signature, size ≤ 10 MB, policy must be PDF   storage.py:51-60
  ├─ write files  storage/claims/<claim_id>/, sha256 checksum stored          storage.py:107,127
  ├─ rows: claims, claim_documents, legacy claims/documents
  └─ returns claim_id, document_ids, status RECEIVED, opaque owner token (hash stored)  auth.py

POST /claims/{claim_id}/documents/process  {config_version}     document_processing/api.py:15
  └─ ClaimDocumentProcessingService (claim_service.py)
       _documents_for_claim: resolve roles; exactly 1 policy_document, ≥1 proof     :49-85
       create document_processing_runs row (unique RUNNING per claim)               :297
       POLICY FIRST:
         _validate_file: path inside storage root, size, checksum, MIME, page/pixel limits  :87-133
         _check_ocr: decide native vs OCR; Tesseract + language availability             :135-160
         extract text (PyMuPDF native / Tesseract / hybrid), normalize                   evidence_extractor.py, normalizer.py
         quality gate per page → ACCEPTED / RETRY_REQUIRED / HUMAN_REVIEW / FAILED       quality_validator.py
         OCR retry: OCR_MAX_ATTEMPTS ≤ 2, forced OCR at 300 DPI on retry pages          :319-354
         DocumentContentService.process_and_persist                                     content_service.py:458
           classify (Gemini, prompts/classification_v1.txt) + local quote verification
           declared type vs detected type gate → mismatch blocks the document
           extract (Gemini, extraction_v2/base.txt + one type template, ≤4 pages/24k chars per batch)
           application validation (deterministic) → ExtractionValidationReport
           persist classification / extraction / validation in document_semantic_artifacts
       if policy not accepted → every proof row = BLOCKED (_record_blocked_proofs)     :162-169
       EACH PROOF (independently, same steps) → run status COMPLETED or PARTIAL
GET /claims/{id}/documents/status (Bearer owner token) → only currently-validated facts
```

Mapping this path to stages, in contract terms, gives 4 per-document stages: document_processing, content_classification, information_extraction, extraction_validation. There is also one control dependency: proofs wait for the policy. See `06_insurance_pipeline/50_target_workflow.md`.

## 2. Stage-by-stage audit

### 2.1 Claim intake

| Field | Analysis |
|---|---|
| Purpose | Accept the claim form and up to 4 documents with declared types |
| Entry point | `claim_document_intake/api.py:74` (`POST /claims`, alias `/api/v1/claims`) |
| Inputs | Policyholder name, age, policy number, incident date, description, claimed amount; files + `document_type` per slot |
| Outputs | `claim_id`, `document_ids`, status `RECEIVED`, owner token |
| Dependencies | Local disk, DB |
| Validation | Field validation (`_validate_claim_fields`); file signature check (test `test_invalid_file_signature_is_rejected_before_rows_or_files`); 10 MB cap; policy must be PDF |
| Failure behavior | HTTP 4xx before any row or file is written |
| Retry | None (client resubmits) |
| Persistence | `claims`, `claim_documents` (with sha256), legacy `claims`/`documents`, `claim_document_versions` on replacement |
| Telemetry | **None** |
| Tests | 6 tests in `test_claim_document_intake.py` |
| Gaps | Name and policy number are PII and are stored in plaintext, which is expected for a business DB but must never reach telemetry. No rate limits. |

### 2.2 Document processing (file validation + text extraction + quality gate)

| Field | Analysis |
|---|---|
| Purpose | Turn each stored file into page text with per-page quality metrics |
| Entry point | `claim_service.py` → `DocumentLoader`, `OCREvidenceExtractor`, `OCRNormalizer`, `quality_validator.py` |
| Inputs | Stored file + checksum + declared role |
| Outputs | `processed_documents` and `processed_document_pages` rows (raw text, layout, engine, confidences, disposition) |
| Dependencies | PyMuPDF, Tesseract executable + `eng` data, Pillow |
| Validation | Path traversal, size, checksum vs intake, MIME vs extension, password-protected or zero-page PDF, page and pixel limits; quality thresholds (15 chars, 3 words, confidence 60/35, low-confidence ratio 0.5, suspicious-char ratio 0.02), all recorded per attempt |
| Failure behavior | `DocumentProcessingError` → document `FAILED`. Policy failure blocks proofs. A proof failure only affects that proof (run `PARTIAL`) |
| Retry | Page-level OCR retry, at most 2 attempts, at 300 DPI. When exhausted the result is `HUMAN_REVIEW_REQUIRED`. Each attempt is a separate `attempt_number` row |
| Persistence | Per document, per attempt, per page. Uploaded files are read-only |
| Telemetry | `quality_validator.py:277` opens `stage_span("ocr_validation")` and `pdf_inspector.py:114` opens `pdf_verification`. **Both go to the no-op global tracer, because no TracerProvider is configured.** |
| Tests | 23 in `test_document_processing.py` + 7 in `test_ocr_quality.py` (includes a real-Tesseract ground-truth test) |
| Gaps | Runs synchronously inside the HTTP request (the README says so). No hard timeout on PyMuPDF. Quality metrics exist but are not emitted as checks |

### 2.3 Content classification (Gemini)

| Field | Analysis |
|---|---|
| Purpose | Confirm the document is what the user declared |
| Entry point | `content_service.py:272 classify` |
| Inputs | Page-labelled text of the current accepted attempt |
| Outputs | Classification artifact (`detected_type`, subtype, disposition, evidence quotes) |
| Dependencies | Gemini via `google-genai`. `GEMINI_MODEL` defaults to `gemini-3.8-flash` (`.env.example` and code) but to `gemini-2.5-flash` in `docker-compose.yml`, an inconsistency to fix |
| Validation | Strict Pydantic schema; quotes verified locally against page text (`_check_quotes`); declared vs detected type gate |
| Failure behavior | Mismatch, ambiguity or unsupported content blocks extraction for that document. A provider failure blocks progression |
| Retry | `GEMINI_MAX_ATTEMPTS` ≤ 2 for transient errors; concurrency semaphore 3; queue timeout 10 s |
| Persistence | `document_semantic_artifacts` (kind = classification) |
| Telemetry | None |
| Tests | Mocked Gemini, e.g. `test_classification_preserves_declared_type_and_detects_mismatch`, `test_hallucinated_quote_and_page_reference_require_review` |
| Gaps | Accuracy is not measured (the README says so honestly) |

### 2.4 Information extraction (Gemini)

| Field | Analysis |
|---|---|
| Purpose | Extract typed facts with quotes and page references |
| Entry point | `content_service.py:316 extract` |
| Inputs | Accepted classification + page text, batched (`page_batches`: ≤4 pages, ≤24,000 chars, never truncated) |
| Outputs | `DocumentExtraction` per type (7 schemas), fields with `found / missing / conflicting` states |
| Dependencies | Gemini, JSON-Schema response adapter (`gemini-json-schema-v4`) |
| Validation | Strict Pydantic; allowed-field catalog per type (`schemas.py:157`); oversized page goes to review |
| Failure behavior | Extraction failed or review is persisted; it never reaches "accepted facts" |
| Retry | Same transient retry as 2.3 |
| Persistence | `document_semantic_artifacts` (kind = extraction) |
| Telemetry | None. LLM calls carry no `gen_ai.*` spans |
| Tests | e.g. `test_each_supported_type_selects_its_own_prompt_and_schema`, `test_two_same_type_documents_are_sent_in_independent_requests`, `test_page_batches_are_bounded_and_never_truncate` |
| Gaps | Prompt-injection defense is partial: document text is JSON-quoted (`test_document_text_is_json_quoted_to_prevent_forged_page_delimiters`) but there is no explicit injection scan |

### 2.5 Extraction validation (deterministic)

| Field | Analysis |
|---|---|
| Purpose | Decide whether the extracted facts are usable |
| Entry point | Inside `content_service.py` (≈ lines 520–620), not in the `extraction_validation/` package |
| Inputs | Extraction + page text + checksum |
| Outputs | `ExtractionValidationReport`: overall disposition `accepted | review_required | extraction_failed`, plus per-check `pass | fail | not_evaluated` with issue codes |
| Checks | Strict structure, allowed field names, field state/value consistency, page coverage, exact quote support, raw value present in quote, canonical dates, Decimal amounts, explicit currency, policy/bill date ordering, bill arithmetic (with currency tolerances) |
| Failure behavior | Review or failure stops the document. Policy review blocks all proofs |
| Persistence | Same transaction as the accepted extraction (`document_semantic_artifacts`, kind = application_validation) |
| Telemetry | `stage_span("information_extraction_validation")` with `validation.status`, `validation.result`, `validation.rule_id`. **Discarded (no provider).** |
| Tests | e.g. `test_raw_fact_value_must_appear_in_its_supported_evidence`, `test_bill_arithmetic_requires_explicit_currency_and_respects_tolerance` |
| Gaps | **This is exactly the kind of evidence Autopsy needs** (check id, result, field path). It only has to be emitted as `pipeline.check` events |

### 2.6 Policy retrieval

There is none. The policy is a user-uploaded document that is extracted like the others. **Decision:** keep it that way for the MVP. "Retrieval" from a policy admin system is out of scope.

### 2.7 Rule engine / adjudication: **MISSING**

`backend/app/rule_engine_decision/__init__.py` contains only a docstring. Designed in `06_insurance_pipeline/51_adjudication_and_final_result.md`.

### 2.8 Final result: **MISSING**

`backend/app/final_result/__init__.py` contains only a docstring.

### 2.9 Orchestrator: **MISSING**

`backend/app/orchestrator/__init__.py` contains only a docstring. Processing is triggered by the document-processing route only.

## 3. Cross-cutting

| Concern | Finding |
|---|---|
| Error handling | Consistent `DocumentProcessingError` with user-safe messages; technical errors are stored separately |
| Idempotency | Same `config_version` + same checksums returns the same run (`test_repeated_completed_request_reuses_same_run`). **Consequence for telemetry:** a cached replay does no work, so it must emit at most a tiny run span marked `pipeline.run.trigger=cache_hit` |
| Concurrency | Unique partial index: one RUNNING run per claim |
| Secrets | Gemini key server-side via `.env` / environment. `.env` is git-ignored |
| PII | Raw page text and extracted facts are in the business DB, which is fine. **They must never be copied into span attributes** |
| DB | Silent SQLite fallback when `DATABASE_URL` is unset (dev convenience, risky in Docker). Compose sets it explicitly |
| Telemetry | `telemetry/span_helpers.py` sets `stage.status="running"` at span start and uses un-namespaced keys (`stage.*`, `execution.*`). It will be **replaced by the autopsy-sdk** |

## 4. Can one claim run end to end today?

- **Intake → document processing → validated facts: yes**, with mocked Gemini in tests, and with live Gemini in your demo runner (native-text PDFs only, no DB).
- **Decision and final result: no.** These stages do not exist.
- **Trace to Autopsy: no.** There is no exporter.

## 5. Reuse decision

**Keep.** Then:

- **Build:** adjudication, final result, claim-run orchestration.
- **Refactor:** move validation out of `content_service.py` into `extraction_validation/` *only if* it makes instrumentation cleaner. This is optional and must not change behaviour.
- **Replace:** `telemetry/` with SDK calls.
- **Repair:** model-name inconsistency; make SQLite fallback explicit-only in Docker.
