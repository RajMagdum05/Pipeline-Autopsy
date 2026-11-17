# 29: Evaluation framework (how we prove diagnosis works)

Evaluation is the **specification**, not a final phase. Golden cases are written before or with the code they test.

## Levels

| Level | What | Where | LLM? | When |
|---|---|---|---|---|
| L0 | Unit tests: validators, guardrails, SDK, adapters, rules engine | `*/tests/unit` | No | Every push |
| L1a | Core golden + mutation tests (29 + 8 fan-out/decision today) | `pipeline-autopsy/tests/core/` | No | Every push, **blocks merge** |
| L1b | Recorded cases: real OTLP + evidence + manifest + `expected.yaml`, replayed through ingest → worker → API | `pipeline-autopsy/evals/golden/<case>/`, `evals/run_l1.py` | No | Every push, blocks merge |
| L2 | Explanation quality (guardrail pass, fallback rate, faithfulness) | `evals/run_l2.py` | Yes | Manual / nightly |
| L3 | Live end to end with fault injection across both services | `tests/e2e` (docker compose) | Optional (Gemini mocked by default) | Before a demo or release |

## Recorded case layout

```
evals/golden/ins_04_ocr_misread_bill_date/
  trace.json        OTLP JSON exactly as received (recorded via AUTOPSY_RECORD_DIR)
  artifacts/        E2 evidence blobs
  manifest.yaml
  expected.yaml
```

```yaml
verdict: ROOT_CAUSE_IDENTIFIED
trace_grade: A
origins: ["document_processing@<bill item>"]
findings:
  "document_processing@<bill item>": {role: origin, classification: OUTPUT_CONTRACT_VIOLATION, confidence: supported}
  adjudication: {role: propagated}
must_not_blame: ["*@<policy item>", "*@<discharge item>"]
required_evidence_codes: [ocr.quality]
```

Item IDs are stable in recordings because fault-injection runs use fixed seeded documents.

## Initial case set

| Source | Cases |
|---|---|
| Core (synthetic, already passing) | 21 golden + 8 mutation + 8 fan-out/decision |
| Toy pipeline (recorded, A2.7) | `toy_healthy`, `toy_short_body` (origin fetch), `toy_publish_timeout` (origin publish, infra) |
| Insurance (recorded, T4.7) | healthy; `policy_ocr_fail` (proofs not executed); `ocr_misread_bill_date`; `extraction_hallucinate_total`; `classification_mismatch`; `gemini_unavailable`; `rule_input_missing_field`; `final_mismatch` |

## Metrics and gates

| Metric | Gate |
|---|---|
| Origin accuracy on L1 | 100% (any regression fails CI) |
| Classification accuracy | 100% on L1 |
| Impacted-stage precision and recall | 100% on L1 |
| False positives on healthy cases | 0 |
| Correct abstention (grade C / `possible` where expected) | 100% |
| "Never confidently wrong" under mutation | All mutation tests |

These gates are 100% because L1 cases are *specifications*. Accuracy on unseen real-world traces is a different question. It is measured later with feedback data (K6.2), and is reported as a number, not gated.

## Rules for Fable

- Never edit `expected.yaml` or `tests/core/test_golden.py` to make a test pass.
- If an expectation looks wrong, stop and report it with reasoning.
