# 23: Diagnosis core: how root cause is computed

**Status:** this is implemented as a reference in `planning/reference/rca_reference.py` plus `rca_fanout.py`, and **37/37 tests pass** (re-run 16 Nov 2026). P0.3 ports it into `pipeline-autopsy/autopsy/core/` without changing its behaviour.

**Changes from the Project reference (16 Nov 2026), both tested:** (1) `decision_rule` checks are context, not anomalies (cases f6, f7). (2) R4 "no inputs recorded" is generalised to "starved" (case f8).

**Signature:**

```python
diagnose(spans, artifacts, manifest, items) -> {verdict, trace_grade, findings, roles, observations}
```

It is a pure function: no database, no network, no LLM, no clock.

## 1. The five steps

```
1 VALIDATE   structural checks → grade A / B / C           (C → stop: INSUFFICIENT_EVIDENCE)
2 REBUILD    expand per-document stages; final attempt per stage instance;
             producer[artifact] = stage; lineage + manifest + control edges; topological order
3 OBSERVE    detectors emit facts only: execution, check, contract, consistency, structural
             (decision_rule checks → 'decision' info observations: context, never anomalies)
4 TRACE BACK if a bad field was copied verbatim from an input artifact, blame moves to that input's producer
5 DECIDE     walk stages in dependency order; first matching rule assigns role / classification / confidence
```

## 2. Vocabulary

| Term | Meaning |
|---|---|
| **Observation** | A fact with an id, family, code, result (`pass`/`info`/`warn`/`fail`), the stage it is *about*, a span and/or artifact, and optionally a field |
| **Anomaly** | An observation with result `warn` or `fail` (structural ones excluded) |
| **Implicated artifact** | An artifact with an anomalous check, contract, consistency or derived observation |
| **Tainted artifact** | An output of a non-healthy stage that is not itself implicated |
| **Origin** | The stage where the problem started |
| **Propagated** | Has anomalies, but they are explained by bad input or a stopped upstream |
| **Tainted (role)** | Had no anomaly itself, but consumed bad data. This is how "approved on wrong facts" is caught |
| **Not executed** | Never ran because something upstream stopped (failure or gate) |
| **Confidence** | `supported` (direct evidence, strong links, grade A) / `possible` (weak link, grade B, or derived-only evidence) / `insufficient` |

## 3. RCA rules (evaluated per stage instance, in dependency order; first match wins)

| # | Condition on stage S | Role | Classification | Confidence | Link |
|---|---|---|---|---|---|
| R0 | Not executed and an upstream stopped (failed, not executed, or gate) | not_executed | DOWNSTREAM_PROPAGATED_SUSPICION | supported* | strong |
| R0b | Not executed, nothing upstream explains it | (missing) | — | grade → B | — |
| R1 | Anomalies include an execution failure with `error.class=infra` | origin | SERVICE_EXECUTION_FAILURE | supported* | — |
| R2 | Anomalies include a consistency **fail** on S's own output (value not in its input) | origin | SOURCE_EVIDENCE_CONTRADICTION | supported* | — |
| R3 | Anomalies and S consumed an implicated or tainted input | propagated | INVALID_UPSTREAM_INPUT | supported* if the input failure is strong and the error is classified, else possible | strong/weak |
| R4 | Anomalies, and S is **starved**: an upstream stopped (failed or not executed) and none of S's inputs came from it. Example: adjudication got the policy facts but not the blocked bill's facts | propagated | DOWNSTREAM_PROPAGATED_SUSPICION | supported* | strong |
| R5 | Anomalies, an upstream is non-healthy but no artifact links them | propagated | DOWNSTREAM_PROPAGATED_SUSPICION | possible | weak |
| R6 | Direct contract/check failure on S, clean upstream | origin | OUTPUT_CONTRACT_VIOLATION | supported* | — |
| R7 | Only *derived* anomalies (blame traced back to S), clean upstream | origin | OUTPUT_CONTRACT_VIOLATION | possible (note: the source itself may be wrong) | — |
| R8 | `error.class=data` failure, clean upstream, no check flags the input | origin | INVALID_UPSTREAM_INPUT | possible (note: coverage gap, add a check upstream) | — |
| R9 | Any other failure, clean upstream | origin | SERVICE_EXECUTION_FAILURE | supported* | — |
| R10 | No anomalies but consumed bad input | tainted | DOWNSTREAM_PROPAGATED_SUSPICION | supported* if strong, else possible | strong/weak |
| R11 | Otherwise | healthy | — | — | — |

\* "supported" is capped to "possible" when the trace grade is B.

**Why R1/R2 come before R3:** a stage with its own fault is an origin *even when* its input was also bad. That is how two independent problems are reported (`MULTIPLE_ROOT_CAUSES`, golden case 07).

**Verdicts:**

| Verdict | When |
|---|---|
| `INSUFFICIENT_EVIDENCE` | Grade C |
| `NO_ISSUE_DETECTED` | No findings |
| `ROOT_CAUSE_IDENTIFIED` | Exactly 1 origin |
| `MULTIPLE_ROOT_CAUSES` | More than 1 origin |

## 4. The grounding test (trace-back): how blame moves upstream

When an extracted field is wrong, did the LLM *invent* it, or did it *copy* garbage that OCR produced?

- If the bad value **is not** in the page text, `grounded_fields` fails on extraction's output. Rule R2 then makes extraction the origin (`SOURCE_EVIDENCE_CONTRADICTION`).
- If the bad value **is** in the page text, grounding *passes*. A check or contract failure on that field then triggers trace-back: a derived observation lands on the page-text artifact's producer (document_processing). Extraction becomes *propagated*, and document_processing becomes the origin. The confidence is `supported` if an OCR quality check also fired, and `possible` if only derived evidence exists (golden case 15).

In your pipeline, the producer already does quote verification (`_check_quotes`, the `raw value present in quote` check). So at evidence level E1, extraction-validation checks carry this signal **without Autopsy seeing any text**. The producer emits `pipeline.check id=extraction.quote_support result=fail field=admission_date target=<facts artifact>`. At E2, Autopsy can re-verify independently.

## 5. Worked example in the new pipeline (fan-out case f2, tested)

```
Run: policy (pol) + hospital bill (bill) + discharge summary (disch); adjudication fails "admission before coverage start"
  document_processing@bill   check ocr.quality = warn   (page text says 2024-03-02; true value 2025-03-02)
  information_extraction@bill  facts.admission_date = 2024-03-02  → grounded in page text (copied faithfully)
  adjudication                 failed, error.class=data
Actual output of the reference code (verdict ROOT_CAUSE_IDENTIFIED, grade A):
  document_processing@bill      origin        OUTPUT_CONTRACT_VIOLATION        supported
  content_classification@bill   tainted       DOWNSTREAM_PROPAGATED_SUSPICION  possible  weak
  information_extraction@bill   tainted       DOWNSTREAM_PROPAGATED_SUSPICION  supported strong
  extraction_validation@bill    tainted       DOWNSTREAM_PROPAGATED_SUSPICION  supported strong
  adjudication                  propagated    INVALID_UPSTREAM_INPUT           supported strong
  final_result                  not_executed  DOWNSTREAM_PROPAGATED_SUSPICION  supported strong
  everything @pol and @disch    healthy (no finding)   ← isolation: other documents are not blamed
```

Extraction and validation are "tainted" (they ran fine on bad text), not "propagated", because no check on them failed. Adjudication failed after consuming the tainted facts, so it is "propagated".

Same symptom, different cause (case f5): the bill total is 9999 but the page says 1200. Grounding fails, so the result is: origin `information_extraction@bill` with `SOURCE_EVIDENCE_CONTRADICTION` (supported), `extraction_validation@bill` tainted, `adjudication` propagated, `final_result` not_executed. Both runs look the same in Jaeger: a red adjudication span. Only lineage plus checks tell them apart.

## 6. What trace order and structure cannot prove (and what we do about it)

| Limitation | Mitigation in this design |
|---|---|
| Parent/child = containment, not causation | Parent/child is used only to roll operations into stages; causality comes from lineage and checks |
| The first error by time may be a symptom of a silent upstream degradation | Quality checks and tainted propagation surface silent degradations; trace-back moves blame upstream |
| Clock skew across hosts | Order comes from the manifest and lineage, never from timestamps |
| Sampling or dropped spans can fake a "deepest error" | Incomplete traces are graded B/C; a missing expected stage lowers the grade |
| Lineage proves consumption, not that the value caused the failure | Confidence is `supported` only with a direct check, contract or consistency observation; otherwise `possible` with a note |
| Unclassified errors next to bad input could be independent infra faults | R3 hedges to `possible` when `error.class` is missing (case 21) |
| Grounding by string match misses reformatted values | Producers emit their own grounding checks (they know the formats); Autopsy validators normalize numbers and whitespace; dates are skipped in v1 |

## 7. Invariants (tested)

1. Every finding has evidence or a `caused_by` link (case 20).
2. Degrading a trace never makes a *different* origin `supported` (8 mutation tests).
3. A healthy run produces zero findings (cases 01, 02, f1). So does a correct business rejection (f6).
4. The run span's own error status is never evidence (case 10).
