# 27: Explanation, the LLM, and guardrails

## The rule

**The LLM never decides anything.**

- The origin, roles, classification, confidence and verdict are copied from the core's output into the published report *by code*.
- The LLM only writes prose about them.
- If the LLM output fails any check, the deterministic template is published instead.
- A finding is never blocked by the LLM.

## MVP: template explanation (E5.1)

This is built from the evidence bundle with fixed sentence patterns, for example:

> `document_processing (hospital bill)` is the origin — `OUTPUT_CONTRACT_VIOLATION`, `supported`. Evidence: check `ocr.quality` = warn (observed low-confidence ratio 0.62, expected ≤ 0.5). Affected: adjudication failed because it consumed facts derived from that page text.

It is a refactor of the existing `DeterministicDiagnosisBuilder` (`diagnosis_service.py:167`).

## MVP+1: guarded LLM explanation (E5.2, E5.3)

### Flow (plain Python, ADR-07)

```
bundle = build_bundle(diagnosis)                       # ids for everything; excerpts masked, ≤300 chars, ≤12
for attempt in (1, 2):
    draft = llm(bundle, violations_from_previous)      # Gemini, temperature 0, JSON schema, timeout 20 s
    violations = guardrails(draft, bundle)
    if not violations: publish(draft, source="llm"); break
else:
    publish(template(bundle), source="template")       # also on timeout / no API key / provider error
```

### What the LLM is asked to produce

```json
{"summary": "≤400 chars",
 "narrative": [{"about": "document_processing@bill-uuid", "claim_type": "origin|propagation|impact|context",
                "text": "≤600 chars", "evidence_ids": ["obs_004"]}],
 "remediation": [{"text": "…", "playbook_id": "pb_ocr_low_quality" }]}
```

### Deterministic guardrails (pure functions, applied in order)

| # | Check | Rejects, for example |
|---|---|---|
| G1 | Parses and matches the schema | Missing `narrative` |
| G2 | Every `evidence_ids` entry exists; every narrative item has at least one | `obs_099` |
| G3 | `about` is a stage instance in the bundle | `payment_service` |
| G4 | `claim_type` matches the RCA role: `origin` only for origins; `propagation` only for propagated/tainted; `impact` only for not_executed/tainted/propagated | Calling adjudication the origin |
| G5 | Every stage name, `art_…`, `obs_…` token in any text exists | Invented artifact |
| G6 | Every number and every quoted/backticked string appears in the bundle | Invented threshold "0.75" |
| G7 | `playbook_id` is one that was retrieved, or null | Fake playbook |
| G8 | No PII patterns (email, phone, 12/16-digit numbers) | — |
| G9 | Length limits | — |

### Prompt-injection defence

Artifact excerpts are untrusted. A scanned document can contain "ignore previous instructions". The defences:

1. Excerpts are passed inside `<evidence>` delimiters, and the system prompt says to treat them as data.
2. The explanation step has **no tools**.
3. The output must pass G1–G9. Because G4–G6 tie every claim to the bundle, an injected instruction cannot change the verdict or invent facts.

## Model choice

Use Gemini through `google-genai`, which both services already depend on. The model name comes from `AUTOPSY_LLM_MODEL`; there is no default, so it is set explicitly. If the variable or the key is missing, the template is always used.

## How we measure it (E5.4, L2)

| Metric | Target |
|---|---|
| Guardrail first-pass rate | ≥ 90% |
| Template fallback rate | < 5% |
| Faithfulness (a judge model labels each sentence as supported or not by the bundle) | ≥ 95% |
| Adversarial drafts (10 hand-written bad drafts) rejected | 10/10. Runs in CI without an LLM |
| Tokens and latency | Reported |
