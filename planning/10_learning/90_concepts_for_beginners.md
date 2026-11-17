# 90: Concepts, in plain language

You do not need to memorise this. Come back to a term when a task uses it.

## The core telemetry words

| Term | Plain meaning | In our project |
|---|---|---|
| **Telemetry** | Data a program emits about what it is doing | Spans from the insurance pipeline |
| **OpenTelemetry (OTel)** | The industry-standard, vendor-neutral way to create and send telemetry | Both systems use it, so Autopsy can read any OTel pipeline |
| **Trace** | The full story of one request or run, as a tree of steps | One claim run = one trace |
| **Span** | One timed step in a trace: a name, start and end time, a status, and key/value labels | `document_processing` for the hospital bill is one span |
| **Attribute** | A key/value label on a span | `pipeline.stage.name = "document_processing"` |
| **Event** | A timestamped note inside a span | `pipeline.check` = "OCR quality warned" |
| **Status** | OK, Error, or Unset | Error means the step failed |
| **Parent/child** | A span started inside another span is its child | The run span is the parent of the stage spans |
| **Link** | A "related to" pointer between spans that are not nested | A re-run links to the previous run |
| **Resource** | Labels describing the *process* that emits spans (service name, environment) | `service.name = insurance-pipeline-api` |
| **Semantic conventions** | Standard attribute names everyone agrees on | `error.type`, `gen_ai.request.model` |
| **SDK (OTel SDK)** | The library that actually records spans and sends them | Configured once in `observability/setup.py` |
| **Exporter** | The part that sends spans somewhere | The OTLP exporter sends to Autopsy (and optionally Jaeger) |
| **OTLP** | The OTel network format: protobuf or JSON over HTTP or gRPC | `POST /v1/traces` on Autopsy |
| **Collector** | A standalone OTel program that receives, filters and forwards telemetry | Enterprises use it to send a copy to Autopsy |
| **Sampling** | Keeping only some traces to save cost | Autopsy needs every *failed* trace kept (tail sampling) |
| **Jaeger** | An open-source trace viewer | Optional; shows the raw waterfall |

## Our project's own words

| Term | Plain meaning |
|---|---|
| **Pipeline** | A sequence of stages that turns input into a result (documents → decision) |
| **Stage** | One named step in the pipeline (document_processing, adjudication, …) |
| **Run (execution)** | One execution of the pipeline for one claim |
| **Item** | One document within a run. Some stages run once per item |
| **Artifact** | A piece of data a stage produces or uses (page text, extracted facts, decision) |
| **Artifact ID** | A fingerprint (hash) of an artifact. It can travel in telemetry without revealing the content |
| **Lineage** | Which artifact each stage read and wrote, which tells us how data flowed |
| **Check** | A test a stage ran on data, with its result (pass/warn/fail) |
| **Manifest** | A small YAML file describing the stages and what each consumes and produces |
| **Evidence level E0/E1/E2** | How much the customer shares: spans only / + checks / + redacted content |
| **Observation** | A fact Autopsy noticed ("stage failed", "check warned", "value not in source") |
| **Finding** | Autopsy's conclusion about a stage: origin, propagated, tainted or not executed |
| **Origin (root cause)** | The stage where the problem started |
| **Propagated** | Failed, but because of bad input from upstream |
| **Tainted** | Did not fail, but worked on bad data, so its output is suspect |
| **Not executed** | Never ran because an earlier stage stopped the flow |
| **Confidence** | `supported` (direct evidence) / `possible` (indirect) / `insufficient` |
| **Trace grade A/B/C** | How complete the telemetry is. C means "cannot diagnose" |
| **Golden case** | A saved scenario with the known correct diagnosis, used as a test |
| **Guardrail** | An automatic check that blocks unsafe or unsupported output |
| **Fault injection** | Deliberately breaking something, to test that Autopsy catches it |

## Why "root cause" is hard, with a story

A claim is rejected because "the treatment date is outside coverage".

- **Story A:** the scanned bill was blurry. OCR read 2025 as 2024. The AI faithfully copied 2024. The rules correctly rejected it.
- **Story B:** the scan was perfect and the page says 2025, but the AI wrote 2024.

The symptom is the same (REJECTED) and the trace shapes are identical, but the fix is different: rescan in A, fix the AI in B. Autopsy separates them by checking whether "2024" actually appears in the page text (lineage + grounding) and whether the OCR quality check warned. That is the whole product in one example.

## Deterministic vs LLM

- **Deterministic code:** the same input always gives the same output, and you can write a test for it. Autopsy uses this to *decide*.
- **LLM:** flexible and good with language, but it can be wrong in confident-sounding ways. Research found the best AI agents correctly diagnose only about 11% of complex failures by themselves. We use LLMs only to *phrase* explanations, and every sentence is checked.

## Architecture words

| Term | Meaning |
|---|---|
| Modular monolith | One deployable program with clean internal modules (vs many small services) |
| API | The HTTP endpoints programs call |
| Migration | A numbered script that changes database tables |
| CI | A robot (GitHub Actions) that runs the tests on every push |
| Docker / compose | Packages each service with its dependencies; one command starts them all |
| Worker | A background loop that does work after a request has returned |
