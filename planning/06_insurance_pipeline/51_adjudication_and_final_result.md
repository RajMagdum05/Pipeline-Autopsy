# 51: Adjudication and final result (the missing business stages)

## Design goals

- **Deterministic.** The same inputs always produce the same decision.
- **Versioned:** `RULES_VERSION = "adjudication-rules-v1"`.
- **Explainable:** every rule cites the fact fields it used.
- **Conservative:** if a rule cannot be evaluated, the claim is referred, not guessed.
- **Domain logic stays here.** None of this goes into Autopsy.

## Inputs

| Input | Source |
|---|---|
| Claim form | `claims` row: `policy_number`, `policyholder_name`, `incident_date`, `claimed_amount` (external input `claim_form`) |
| Policy facts | Accepted `validated_facts` of the policy document: `policy_number`, `policyholder_name`, `insured_member_name`, `coverage_start`, `coverage_end`, `sum_insured`, `currency` |
| Proof facts | Accepted `validated_facts` of each proof. Hospital bill: `patient_name`, `invoice_date`, `admission_date`, `discharge_date`, `total`, `currency`. Discharge summary: `admission_date`, `discharge_date`, `patient_name`. Other types are used only for completeness |

These field names come from `information_extraction/schemas.py` `ALLOWED_FIELDS`. Fields that are repeatable or conflicting are not used by v1 rules; their presence makes the rule `not_evaluable`.

## Rules v1

| Rule ID | Logic | fail ⇒ | not_evaluable when |
|---|---|---|---|
| `rule.policy_number_match` | normalized claim-form policy number == policy facts `policy_number` | REJECT | policy number missing |
| `rule.policyholder_match` | normalized name equality (casefold, collapse whitespace) of claim form vs policy `policyholder_name` or any `insured_member_name` | REFER | names missing |
| `rule.incident_in_coverage` | `coverage_start ≤ incident_date ≤ coverage_end` | REJECT | any date missing or not canonical |
| `rule.service_in_coverage` | each accepted bill's `admission_date` (else `invoice_date`) within coverage | REJECT | no date on any bill |
| `rule.financial_proof_present` | ≥ 1 accepted `hospital_bill` | REFER | — |
| `rule.currency_consistent` | bill currency == policy currency | REFER | currency missing |
| `rule.amount_within_bills` | `claimed_amount ≤ Σ accepted bill totals` (same currency, tolerance per existing currency table) | REFER | totals missing |
| `rule.amount_within_sum_insured` | `claimed_amount ≤ sum_insured` | REJECT (excess) | sum insured missing |
| `rule.patient_is_insured` | bill `patient_name` matches policyholder or an insured member | REFER | name missing |

**Decision:**
- Any REJECT fail → `REJECTED`.
- Otherwise, any REFER fail or any `not_evaluable` → `MANUAL_REVIEW`.
- Otherwise → `APPROVED`, with `payable_amount = claimed_amount`. Deductibles and copayment are out of scope for v1; record that in the decision note.

**Preconditions (stage fails before the rules run):**
- The policy is not accepted. This normally cannot happen, because the run stops earlier.
- No accepted proof at all.

In both cases the stage raises `AdjudicationInputMissing` (data class) with a `rules.input_complete` check targeting the missing kind.

## Output artifact `decision`

```json
{"decision": "REJECTED", "rules_version": "adjudication-rules-v1", "payable_amount": null,
 "rules": [{"rule_id": "rule.service_in_coverage", "result": "fail",
            "inputs": [{"artifact_id": "art_…", "field": "admission_date"},
                       {"artifact_id": "art_…", "field": "coverage_start"}],
            "reason_code": "SERVICE_BEFORE_COVERAGE"}],
 "note": "Deductible/copay not applied in v1"}
```

Values stay in the business DB. The artifact holds *references*. At E2, `decision` may be uploaded; it contains no PII, only IDs, codes and enums.

## Persistence

A new table `adjudication_results`: `id`, `run_id`, `claim_id`, `rules_version`, `decision`, `payable_amount`, `rules` (JSON), `inputs_checksum`, `created_at`. It is added as migration `005_adjudication.sql`, following the existing numbering. Replays with the same `config_version` and inputs return the stored result.

## Telemetry (T4.4)

- Stage span `adjudication`. Inputs: every accepted `validated_facts` ID + `claim_form` ID. Output: `decision`.
- **One `pipeline.check` per rule**, with **`kind=decision_rule`**:
  - `id` = rule ID;
  - `result`: pass, fail, or skip (not_evaluable);
  - `action=continued`;
  - **`target_artifact_id` = the validated_facts artifact whose field drove the rule**, and `field` = that field.
- **A REJECTED or MANUAL_REVIEW decision is a business outcome, not a pipeline fault.** The stage status stays `success`, and the Autopsy core treats `decision_rule` checks as *context* (`info` observations), never as anomalies. This was tested in the reference core: fan-out cases **f6** (clean rejection → `NO_ISSUE_DETECTED`) and **f7** (rejection caused by an OCR misread → origin `document_processing@bill`, adjudication *tainted*).
- Only checks that signal a **pipeline fault** use other kinds. Examples: `rules.input_complete` (kind `schema`, the stage cannot run) and `final.matches_decision` (kind `rule`, the output contradicts its input).
- The explanation layer cites the failed decision rule ("rejected by `rule.service_in_coverage` on the bill's `admission_date`") next to the upstream origin. That gives the engineer the full chain.

## Final result (B4.3)

| Field | Spec |
|---|---|
| Responsibility | Turn the decision into the claim's final status and a customer-safe message; update `claims.claim_status` |
| In / out | `decision` → `claim_result` `{decision, payable_amount, message_code}` |
| Checks | `final.matches_decision`: `claim_result.decision == decision.decision`, target = claim_result |
| API | `GET /claims/{id}/result` (owner token) returns the decision, the reasons (rule IDs → safe messages) and the run ID. The UI shows it, plus an "Open in Autopsy" link (T4.7) |
| Tests | Mapping table; mismatch check (fault `final_mismatch`) |

## Tests (B4.1–B4.3)

1. Each rule: pass, fail and not_evaluable.
2. Decision aggregation table.
3. Same inputs give the same output (determinism).
4. Replay returns the stored result.
5. API end to end with mocked Gemini and fixture documents: synthetic policy + bill → APPROVED; a bill with an out-of-coverage date → REJECTED.
