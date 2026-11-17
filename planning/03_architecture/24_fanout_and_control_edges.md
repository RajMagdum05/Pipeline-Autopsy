# 24: Per-document diagnosis (fan-out) and control edges

**Status:** new in this audit. Prototype in `planning/reference/rca_fanout.py` (about 120 lines). Tests in `test_fanout.py`: **8/8 pass**, together with the original 29 (37/37).

## Why it is needed

The earlier design assumed one document per claim, with each stage running once. Your rebuilt pipeline does this instead:

- It processes **one policy and up to three proofs**.
- **Each document** goes through document_processing → classification → extraction → validation.
- **Proofs only start after the policy passes**. A policy failure marks every proof `BLOCKED` (`claim_service.py:162`).
- Adjudication, to be built, consumes **all** accepted documents.

Without fan-out, a bad hospital bill would make "information_extraction" fail as a whole, and the policy and discharge summary would look implicated. Blocked proofs would look like "missing stages" (grade B) instead of "not executed because of the policy".

## Model

1. **The manifest declares scope.** `scope: item` means once per document; `scope: run` means once per claim run.
2. **Item-scoped stages may declare `requires`** (a control edge). Example: `document_processing` requires `extraction_validation` of the item with role `policy`. The edge says "wait for that stage to pass". It carries no data.
3. **Stage spans carry `pipeline.stage.item_id`** (the claim-document UUID, which is opaque) **and `pipeline.stage.item_role`** (`policy` | `proof`).
4. **The run span carries `pipeline.run.items`.** This is a list of `item_id:role` strings, so Autopsy also knows about documents that never started (blocked proofs).

## Algorithm (expand, then reuse the unchanged RCA)

```
for each item-scoped manifest stage S, for each item i (respecting item_roles filter):
    instance "S@i": consumes kind@i, produces kind@i and a synthetic "gate:S@i"
    for each requires {stage R, item_role r}: consume "gate:R@j" for every item j with role r (j ≠ i)
for each run-scoped stage: consume every kind@i produced by item-scoped producers
rewrite span stage names to "S@i" (from pipeline.stage.item_id) and artifact kinds to "kind@i" (from the producer's item)
gate kinds are treated as external (no artifact → no lineage-gap warnings)
topologically sort instances (control edges cut across expansion order)
upstream(S) = ALL producers of its consumed kinds (not just the first)
run the reference diagnose() unchanged
```

## Tested scenarios

| Test | Scenario | Result |
|---|---|---|
| f1 | Healthy policy + bill + discharge | NO_ISSUE_DETECTED, grade A |
| f2 | Bill OCR misreads the year (OCR check warn), adjudication fails | Origin `document_processing@bill`; policy and discharge untouched |
| f3 | Policy fails its OCR gate (blocked) | Origin `document_processing@pol`; both proofs and adjudication `not_executed` |
| f4 | Gemini 503 while classifying the bill | Origin `content_classification@bill` SERVICE_EXECUTION_FAILURE; bill extraction `not_executed` |
| f5 | Extraction invents a bill total | Origin `information_extraction@bill` SOURCE_EVIDENCE_CONTRADICTION |
| f6 | **Clean rejection**: the claim really is outside coverage; a rule fails (`check.kind=decision_rule`) | NO_ISSUE_DETECTED (a business outcome is not a pipeline fault) |
| f7 | Same rejection, but the bill OCR misread the year (quality check warned) | Origin `document_processing@bill`; adjudication and final_result *tainted*; policy and discharge untouched |

| f8 | Bill classification hits a 503; adjudication runs with the policy facts only and fails | adjudication *propagated*, **supported, strong**, caused_by `extraction_validation@bill` (rule R4 "starved") |

**Changes made to the reference core (16 Nov 2026).** f8: rule R4 was generalised from "no inputs" to "starved". f6/f7: checks with `kind=decision_rule` become `info` observations (family `decision`). They are kept as explanation context and are never anomalies. Without this, every correct rejection would be reported as a data fault.

## Known limits (accepted for MVP)

- Items must be known up front (`pipeline.run.items`). Dynamic splitting, such as one PDF split into components, is out of scope; your README already says segmentation is not implemented.
- Page-level fan-out *inside* a document is modelled as `operation` spans (`pipeline.item.index` / `pipeline.item.count`), not as stage instances. Page problems surface through the document's quality check.
- When P0.3 ports this, `rca_fanout.py` should become a proper `core/fanout.py`. In particular, `upstream_stages` must become a parameter, not a monkey-patch.
