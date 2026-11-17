# 53: Fault injection and demo scenarios

## Mechanism (T4.6)

- Fault injection is enabled only when `FAULT_INJECTION_ENABLED=true`. It is never enabled in production configs.
- The fault is chosen per run with the header `X-Autopsy-Fault: <name>` on `POST /claims/{id}/process`, or with the field `fault` in the body in tests.
- **Location:** `backend/app/faults.py`. It is a registry of small hook functions that are called at named points:
  - `after_text_extraction(item, pages, metrics)`
  - `before_llm(stage, item)`
  - `after_extraction(item, facts)`
  - `validator_overrides(item)`
  - `after_adjudication(decision)`
- Hooks are no-ops unless a fault is active. Each fault records `pipeline.fault.name` **on the run span only**. That attribute is used for evaluation labelling, and **the Autopsy core never reads it** (enforced by a grep test in the core).
- **Deterministic:** fixture documents live in `insurance-pipeline/demo_documents/`. Gemini is replaced by a `FakeGemini` that returns recorded responses (from `gemini_demo_results.json`) in e2e and CI. A live-Gemini variant is manual only.

## Scenarios

Run setup: policy (synthetic schedule, coverage 2025-01-01 → 2025-12-31) + hospital bill (admission 2025-03-02, total 1200 INR) + discharge summary.

| # | Fault | What happens in the pipeline | Business outcome | Expected Autopsy verdict | Evidence level needed |
|---|---|---|---|---|---|
| 1 | `none` | Healthy | APPROVED | `NO_ISSUE_DETECTED` | E0+ |
| 2 | `clean_rejection` (uses a bill that really is dated 2024) | Correct pipeline | REJECTED (`rule.service_in_coverage`) | `NO_ISSUE_DETECTED` (a business outcome) | E1+ |
| 3 | **`ocr_misread_bill_date`** | OCR text for the bill changes `2025-03-02` → `2024-03-02`; page quality metrics degraded to warn | REJECTED (`rule.service_in_coverage`) | Origin **`document_processing@bill`**, OUTPUT_CONTRACT_VIOLATION, supported (`ocr.quality` warn); extraction, validation, adjudication and final_result tainted | E1+ |
| 4 | **`extraction_wrong_date_uncaught`** | Clean OCR; extraction returns `2024-03-02` with a fabricated quote; `validator_overrides` disables `extraction.quote_support` for this field, simulating a validator coverage gap | REJECTED (`rule.service_in_coverage`) | **E2:** origin **`information_extraction@bill`**, SOURCE_EVIDENCE_CONTRADICTION, supported (Autopsy's own `grounded_fields` finds the value absent from the page excerpt). **E1:** `NO_ISSUE_DETECTED`. This is an honest limit: with no content shared and the producer check disabled, nothing can see it | E2 |
| 5 | `extraction_hallucinate_caught` | Extraction returns a value not in the text; the producer's quote check fails → bill validation `review_required` → no accepted financial proof | Adjudication fails (`AdjudicationInputMissing`) | Origin `information_extraction@bill` (check `extraction.quote_support` fail targets document_facts); extraction_validation@bill propagated; adjudication propagated (starved, strong; rule R4); final_result not_executed | E1+ |
| 6 | `policy_ocr_unreadable` | Policy page text below quality thresholds after 2 attempts → human review | Run blocked | Origin `document_processing@pol`; both proofs, adjudication and final_result `not_executed` | E0+ |
| 7 | `gemini_unavailable` | Classification of the bill raises a 503-type error | Adjudication fails (no financial proof) | Origin `content_classification@bill`, SERVICE_EXECUTION_FAILURE; bill extraction and validation not_executed; adjudication propagated (starved, strong; tested as case f8) | E0+ |
| 8 | `classification_mismatch` | The bill file actually contains a discharge summary | Bill blocked; adjudication fails | Origin `content_classification@bill` (check `classification.matches_declared` fail). Playbook: the declared type is wrong, ask for re-upload. Known limit: external-input mistakes are attributed to the first stage that detects them | E1+ |
| 9 | `final_mismatch` | Final result flips the decision | Wrong status | Origin `final_result`, SOURCE_EVIDENCE_CONTRADICTION (`final.matches_decision`) | E1+ (E2 also re-checks) |

## The headline demo (2 minutes)

1. Submit the same claim twice, with faults **3** and **4** (E2 profile).
2. Insurance UI: both claims show **REJECTED, reason: service date outside coverage**.
3. Jaeger: both traces look the same. All stage spans are OK; the adjudication span records a failed rule.
4. Autopsy UI:
   - Run 3: the **bill's document_processing** box is red; the evidence is "OCR quality warn on page 1".
   - Run 4: the **bill's information_extraction** box is red; the evidence is "value 2024-03-02 not present in page text".
5. The message: *same symptom, different root cause, proven with evidence.* Policy and discharge-summary boxes stay green in both runs.

## Recording golden cases (T4.7)

Run each scenario with `AUTOPSY_RECORD_DIR=pipeline-autopsy/evals/golden`. Autopsy then writes `trace.json`, `artifacts/`, `manifest.yaml` and a draft `expected.yaml`. **You review and approve every `expected.yaml` by hand.** Fable must not generate the expectations and then test against them without your review.
