# 84: Prompt drafts, Phases 5–7 (after the MVP)

These are drafts. Adapt each one to the actual state after M3.

## E5.1: Evidence bundle + template explanation

```text
Task E5.1: Evidence bundle and deterministic template explanation.
Read: planning/03_architecture/27_explanation_llm_guardrails.md (MVP: template), 22 §9.
In scope: autopsy/explain/bundle.py, template.py (refactor from explain/legacy_template.py), persistence to explanations
(source="template"), included in GET /diagnosis, UI summary card shows text + "template" tag; snapshot tests.
Acceptance: snapshot tests on 3 recorded cases (toy_short_body, ins_ocr_misread_bill_date, ins_policy_ocr_unreadable);
excerpts ≤300 chars, ≤12, masked.
```

## E5.2: Output guardrails

```text
Task E5.2: Deterministic output guardrails G1-G9.
Read: 27 (guardrail table, prompt-injection defence).
In scope: autopsy/explain/guardrails.py (pure functions returning violation lists), tests/unit/test_guardrails.py with
10 adversarial drafts (wrong origin, invented number, fake playbook, unknown stage, missing evidence id, injected instruction
text claiming a different root cause, PII, over-length, wrong claim_type, unknown artifact id) and 3 good drafts.
Acceptance: 10/10 rejected with the right violation codes; 3/3 accepted; no network.
```

## E5.3: LLM explanation with fallback

```text
Task E5.3: Guarded Gemini explanation with template fallback (plain Python, no frameworks).
Read: 27 (flow, output schema, model choice), ADR-07, ADR-09.
In scope: autopsy/explain/llm.py (google-genai, temperature 0, JSON schema, 20 s timeout, AUTOPSY_LLM_MODEL required),
autopsy/explain/service.py (attempt loop: draft -> guardrails -> retry once with violations -> template), worker hook
(only when findings exist), explanations table fields (model, tokens, latency, guardrail_log), tests with a fake LLM.
Acceptance: fake bad twice -> template; no key -> template; good -> llm; healthy run -> 0 LLM calls (counter); timeout -> template.
```

## E5.4: L2 runner

```text
Task E5.4: evals/run_l2.py measuring explanation quality.
Read: 27 (How we measure it), 29.
Acceptance: prints the metrics table over recorded cases with findings; runs manually with a key; numbers recorded in README.
```

## K6.1: Playbooks

```text
Task K6.1: Keyed playbook retrieval.
Read: planning/03_architecture/28_knowledge_playbooks.md.
In scope: autopsy/knowledge/playbooks.py (loader from playbooks/ and packs/*/playbooks/, scoring table, Postgres FTS fallback with
SQLite LIKE fallback in tests), 8 starter playbooks, bundle + template + UI remediation.
Acceptance: ins_ocr_misread_bill_date -> pb_ocr_low_quality; toy_publish_timeout -> pb_upstream_timeout; unknown -> none.
```

## K6.2: Feedback and past cases

```text
Task K6.2: Feedback API/UI and failure signatures.
Read: 28 (Past cases), 25 (signature), 60 (feedback buttons).
Acceptance: confirm finding; re-ingest same recorded case -> seen_before = 1; reject leaves it 0.
```

## X7.1: Collector fan-out profile

```text
Task X7.1: OpenTelemetry Collector profile demonstrating the enterprise path.
Read: planning/05_integration/40_integration_options.md (Collector config).
In scope: deploy/otelcol/config.yaml (otelcol-contrib image), root compose profile "collector", insurance env switch to export to
the collector, e2e test.
Acceptance: scenarios 1, 3, 6 give the same verdicts via the collector; a test span carrying an email-like value arrives masked in Autopsy.
```

## X7.2 – X7.5

Write these prompts when the trigger in `02_product/12_mvp_scope.md` ("Later") occurs. Use the template in `81_prompt_template.md`, and the objectives and acceptance criteria in `08_roadmap/70_task_list.md` Phase 7.
