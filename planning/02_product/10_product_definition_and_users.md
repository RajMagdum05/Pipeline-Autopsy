# 10: Product definition and users

## One sentence

**Pipeline Autopsy** reads the execution trace of one run of a multi-stage AI or software pipeline. It answers, with evidence:

- whether anything went wrong, including problems no stage reported as an error;
- which stage the problem *originated* in;
- which stages were only *affected*;
- how sure it is;
- what to do next.

## The analogy

The SDK is a flight recorder installed in the plane. Autopsy is the crash investigator who reads the recorder after every flight. The insurance pipeline is just the plane we fly for the demo. Autopsy never flies the plane; it does not run claims. It never reads the airline's private records; it does not read the customer's database. It reads only what the recorder was allowed to capture.

## What Autopsy is not

It is not:

- a tracing backend (Jaeger, Tempo);
- a log platform;
- a metrics dashboard;
- an LLM-observability product (Langfuse, Phoenix);
- a claims system;
- a chatbot.

It sits **on top of** standard OpenTelemetry data. It may run beside any of those tools.

## Users and workflows

### U1: Integrating engineer (one-off setup, about 1 day)

| | |
|---|---|
| Problem | "Our claims pipeline fails or produces wrong results, and Jaeger only shows red spans, not *why*." |
| Configures | 1. A **pipeline manifest**: stages, what each consumes and produces, optional artifact schemas and consistency rules. 2. OTLP export to Autopsy: a Collector exporter, or env vars. 3. Optionally, the SDK, to mark stages, artifacts and checks. |
| Sees | An onboarding page with telemetry arriving, a contract-compliance report (which required attributes are missing on which spans) and a first diagnosed run |
| Actions | Register manifest, rotate key, choose the evidence level (E0/E1/E2) |
| Autopsy must provide | OTLP endpoint, manifest validation with precise errors, compliance report, SDK + docs, toy example |

### U2: Investigating engineer (daily)

| | |
|---|---|
| Problem | "Claim CLM-42 was rejected / failed. Is it the OCR, the LLM, the rules, or the input?" |
| Configures | Nothing |
| Sees | 1. A run list with a verdict badge. 2. A run page: lineage graph with the origin in red and affected stages coloured. 3. Each finding: classification, confidence and evidence (the span, the check, an artifact excerpt). 4. Remediation |
| Actions | Open evidence, follow the link to Jaeger, re-run diagnosis, mark a finding confirmed or rejected |
| Autopsy must provide | Deterministic origin and impact with evidence links, honest `INSUFFICIENT_EVIDENCE`, fast page (< 2 s) |

### U3: Platform administrator (occasional)

| | |
|---|---|
| Problem | Control access, cost and data exposure |
| Configures | API keys, retention, evidence level per pipeline, payload limits |
| Sees | Ingestion volume, rejected-span counts, key usage |
| Actions | Create or revoke keys, delete a run's data |
| Autopsy must provide | MVP: one static key + env config. Later: per-project keys, retention jobs, a deletion API (X7.2, X7.3) |

### U4: Reviewer / operator (QA, team lead)

| | |
|---|---|
| Problem | "Are the diagnoses right? Which failure patterns are recurring?" |
| Sees | Findings with feedback state; "seen N times before" per failure signature |
| Actions | Confirm or reject; filter by verdict, origin stage or classification |
| Autopsy must provide | Feedback storage, signatures, evaluation numbers in the README |

## The product promise, made testable

| Promise | Test that proves it |
|---|---|
| Finds the originating stage, not the loudest one | Golden cases 03, 04, 10 (`reference/test_golden.py`) |
| Sees failures no stage raised | Case 08 (downstream "tainted"), case 17 (warning only) |
| Separates independent failures | Case 07 (`MULTIPLE_ROOT_CAUSES`) |
| Isolates a bad document among several | Fan-out case f2 (`reference/test_fanout.py`) |
| Explains blocked work as impact, not failure | Cases 11 and f3 |
| Says "I can't tell" instead of guessing | Cases 12, 13 and all 8 mutation tests |
| Works for non-insurance pipelines | Case 14 (toy) and the A2.7 toy pipeline end to end |
