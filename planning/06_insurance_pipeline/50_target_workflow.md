# 50: Insurance pipeline target workflow (producer)

## Principles

- **Deterministic wherever possible.** LLMs are used only for content classification and extraction. Business decisions are versioned rules.
- **Observable by construction.** Each stage has one span per attempt (per document where it applies). Each gate emits a check.
- **Reproducible.** Every run records its config, prompt, schema, validator and rules versions. Fault injection is deterministic.
- **Privacy-safe.** Content stays in the business DB. Telemetry carries IDs, metrics and check results.
- **Not an agent.** It is a fixed workflow.

## Workflow

```
POST /claims                                   (intake; separate request; not part of the run trace)
POST /claims/{id}/process   {config_version}   NEW orchestrator endpoint = one run = one trace     (B4.2)
  run span (items = policy + proofs)
   ├─ per document, policy first:
   │    document_processing → content_classification → information_extraction → extraction_validation
   │    (proofs start only if the policy's extraction_validation is accepted)
   ├─ adjudication      (run-scoped; needs accepted policy + ≥1 accepted financial proof)   NEW (B4.1)
   └─ final_result      (run-scoped)                                                         NEW (B4.3)
The existing POST /claims/{id}/documents/process stays (it runs the document stages only); the UI moves to /process.
```

## Stage specifications

### S0: Claim intake (exists; out of the run trace)

| Field | Spec |
|---|---|
| 1 Responsibility | Accept the form and files; persist; issue an owner token |
| 2 In / out | multipart → `claim_id`, `document_ids`, `RECEIVED` |
| 3 Contract | existing Pydantic schemas |
| 4 Validations | existing (field rules, file signature, ≤ 10 MB, policy must be PDF) |
| 5 Failures | 4xx before any write |
| 6 Retry / timeout | Client resubmits |
| 7 Persistence | Existing tables + files |
| 8 Telemetry | None in the contract. The source_document artifact ID is derived later from the stored checksum. Optional: standard FastAPI HTTP span |
| 9 Tests | Existing 6 |
| 10 Done | Unchanged |

### S1: document_processing (exists; per document)

| Field | Spec |
|---|---|
| 1 | Validate the stored file; extract page text (native, OCR or hybrid); quality gate with ≤ 2 attempts |
| 2 | In: `source_document` (artifact ID = `artifact_id("source_document", {"sha256": checksum}, item)`). Out: `page_text` (canonical JSON of the pages of the accepted attempt: page number, method, text) |
| 3 | `processed_documents` / `processed_document_pages` |
| 4 | Existing file checks + quality thresholds (recorded per attempt) |
| 5 | `DocumentProcessingError` (data); Tesseract missing (infra); retry exhausted → `HUMAN_REVIEW_REQUIRED` (stage `failed`, `GateBlocked`, check `action=review`) |
| 6 | `OCR_MAX_ATTEMPTS` ≤ 2 → stage span per attempt (`pipeline.stage.attempt`) |
| 7 | Unchanged |
| 8 | Stage span; operation spans `pdf_inspection`, `text_extraction` (page fan-out via `pipeline.item.index/count`); checks `ocr.quality` (per document; observed = worst ratio/score), `document.file_valid` |
| 9 | Existing 30 + span-contract tests (T4.2) |
| 10 | A healthy document produces a grade-A stage span with page_text output; a low-quality document emits `ocr.quality warn/fail` |

### S2: content_classification (exists inside `content_service.classify`; per document)

| Field | Spec |
|---|---|
| 1 | Confirm detected type = declared type |
| 2 | In: `page_text`. Out: `classification` (`detected_type`, subtype, disposition, verified quote refs) |
| 4 | Strict schema; local quote verification; declared-vs-detected gate |
| 5 | Mismatch, ambiguity or unsupported → stage `failed` (`GateBlocked`, data); provider error → `failed` (infra) |
| 6 | Gemini transient retry inside one GenAI operation span |
| 8 | Stage span; GenAI operation span `generate_content <model>`; checks `classification.evidence_quotes`, `classification.matches_declared` (`observed=detected type`, `expected=declared type`; both are enums, not PII) |
| 10 | Mismatch yields a check fail targeting the classification artifact |

### S3: information_extraction (exists; per document)

| Field | Spec |
|---|---|
| 1 | Extract typed facts with evidence quotes |
| 2 | In: `page_text`, `classification`. Out: `document_facts` (canonical JSON of the extraction payload) |
| 4 | Strict Pydantic, allowed fields, no truncation |
| 5 | Provider/schema failure → failed (infra or data); oversized page → review |
| 6 | Same as S2 |
| 8 | Stage span; one GenAI operation span per batch (`pipeline.item.index` = batch number); check `extraction.page_coverage` |
| 10 | Facts artifact ID present in outputs; batches visible |

### S4: extraction_validation (exists inside `content_service`; per document)

| Field | Spec |
|---|---|
| 1 | Decide whether the facts are usable |
| 2 | In: `document_facts`, `page_text`. Out: `validated_facts` (accepted facts only; empty if not accepted) |
| 4 | The existing ExtractionValidationReport checks |
| 5 | `review_required` / `extraction_failed` → stage `failed` (`GateBlocked`, data) with check `action=review` |
| 8 | Stage span; **one `pipeline.check` per ValidationCheck** (`check.id = extraction.<check_id>`, result mapped pass/fail/skip (`not_evaluated`), `field` = path from issue, `target` = document_facts) |
| 10 | Each validation failure in the existing tests produces the matching check event |

### S5: adjudication (NEW; run-scoped)

See `51_adjudication_and_final_result.md`.

### S6: final_result (NEW; run-scoped)

See `51_adjudication_and_final_result.md`.

## Smallest target workflow (MVP)

Exactly the six stages above. No policy retrieval system, no human-review UI, no async queue, no fraud scoring.

## Required improvements, by goal

| Goal | Change | Task |
|---|---|---|
| Deterministic where it should be | Rules engine (B4.1); fixed config versions; seeded fault injection | B4.1, T4.6 |
| Observable | SDK instrumentation; checks from existing gates | T4.1–T4.4 |
| Reproducible | Record `config_version`, prompt/schema/validator/rules versions on stage spans; demo documents in the repo | T4.2–T4.4 |
| Testable | Pure rules functions; span-contract tests with `InMemoryCapture` | B4.1, T4.x |
| Safe with sensitive data | No content attributes; E1 default; redacted excerpts at E2 | T4.5 |
| Enough evidence for Autopsy | Artifact IDs passed between stages; checks with target and field | T4.2–T4.4 |
