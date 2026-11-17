# 33: Artifacts, privacy and retention

## 1. What must never go into telemetry (spans, events, resource, baggage)

| Never | Why | What to send instead |
|---|---|---|
| Full documents, page images, base64 blobs | Size, PII, cost | `artifact_id` + `sha256` |
| OCR or page text | PII (names, diagnoses) | Quality metrics: char/word counts, confidence ratios, method (native/OCR/hybrid) |
| Extracted values (names, policy numbers, amounts, dates, diagnoses) | PII and health data | Field *paths*, field *states* (`found`/`missing`/`conflicting`), check results |
| Prompts and model responses | Contain document text | `pipeline.prompt.version`, `gen_ai.usage.*`, `finish_reasons` |
| Claim form fields | PII | `pipeline.entity.id` (an opaque UUID) |
| API keys, tokens, owner tokens | Credentials | Nothing |
| Raw exception messages from libraries that echo input | They may contain text | Sanitized message (SDK `safe_message`), `error.type` |

## 2. Evidence levels (chosen per pipeline in the manifest)

| Level | What Autopsy receives | What it can diagnose | Typical user |
|---|---|---|---|
| **E0** | Spans only (structure, status, `error.type`, `error.class`, artifact IDs) | Infra failures, propagation, not-executed impact, structural problems | A cautious first pilot |
| **E1** | E0 + `pipeline.check` events (no content) | Plus silent quality, grounding and rule failures, **using the producer's own checks** | **Recommended enterprise default** |
| **E2** | E1 + allow-listed, redacted artifact content uploaded to Autopsy | Plus independent re-validation (schemas, cross-artifact grounding) and evidence excerpts in the UI | Our synthetic demo; customers who approve it |

Lineage works at **every** level, because IDs are always in spans.

## 3. The artifact reference model

| Question | Answer |
|---|---|
| What is an artifact ID? | A deterministic hash (`31_trace_contract_v3.md` §2), computed by the SDK locally. No network call is needed to obtain it |
| Who stores the artifact? | The **producer**, in its own DB or storage, always. At E2 the SDK *also* uploads a redacted copy of allow-listed kinds to Autopsy |
| How does Autopsy retrieve it? | E2: from its own evidence store. Autopsy never reaches into producer storage. (A future "fetch from customer endpoint with customer credentials" mode is possible, but not planned) |
| How is access authorized? | E2 upload uses the pipeline's API key. Kinds outside `kinds_allowed` are rejected (403). Reading evidence requires the API key; with project keys (X7.2) only the owning project can read it |
| Tenant boundaries | MVP: one project. The `project_id` column exists everywhere so X7.2 can enforce it |
| Encryption | In transit: TLS when deployed (local demo uses HTTP). At rest: rely on disk/volume encryption in the MVP; per-project keys later if required |
| Retention / expiry / deletion | `expires_at` = created + `retention_days` (default 14). `DELETE /v1/executions/{id}` removes evidence. Retention job in X7.3 |
| Sanitized excerpts only? | Yes. An upload may be **redacted**: `redacted=true`, `redaction="excerpt"`. For insurance, `page_text` is uploaded as an excerpt: only the lines that contain any extracted value, ± 80 characters, after a `redact()` hook masks emails, phone numbers and ID numbers. The artifact keeps its original ID (computed over the full text). For redacted uploads the server cannot recompute the ID, so it checks the ID format and stores `redacted=true`. Validators treat redacted content as partial: grounding still works, because a hallucinated value has no matching line, so it is absent from the excerpt too |
| Artifact unavailable? | Spans still carry the ID. The core emits `artifact_not_found` (structural warn), the grade becomes B, and confidence is capped at `possible`. The worker retries once after 30 s in case the upload is still in flight |

## 4. Balancing usefulness against privacy and cost

- Start customers at **E1**. Your pipeline already computes rich checks (quote verification, validation report, OCR quality), so E1 alone supports most diagnoses: f2 is diagnosed from the `ocr.quality` check, f4 from `error.class=infra`.
- E2 adds *independent* verification. It is worth it for evaluation datasets and for synthetic or approved data.
- Cost: spans are small (no payloads). Evidence is capped at 5 MB per artifact (insurance excerpts are a few KB) and expires after 14 days.

## 5. Producer-side controls in insurance-pipeline (T4.5)

| Env var | Default | Meaning |
|---|---|---|
| `AUTOPSY_EVIDENCE_LEVEL` | `E1` | The upload ceiling. E2 also requires the manifest to allow it |
| `AUTOPSY_EVIDENCE_KINDS` | `page_text,document_facts,decision` | Local allow-list (intersected with the manifest's); `page_text` is always sent as a redacted excerpt |
| `OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT` | `4096` | Standard SDK safety net |
