# 34: Hard cases: retries, timeouts, fan-out, async work, sampling

| Case | Representation | What Autopsy does |
|---|---|---|
| **Stage retry** (e.g. OCR attempt 2 at 300 DPI) | A new stage span with the same `pipeline.stage.name` (+ item) and `pipeline.stage.attempt=2`. Inputs and outputs are recorded per attempt | Final attempt decides; earlier attempts produce an `info retried` observation. An error on attempt 1 that succeeded on attempt 2 is **never** an origin (golden case 02) |
| **Page-level OCR retry inside a stage** | Operation spans per page with `pipeline.item.index` and a page attempt attribute; the quality result is emitted as a check on the stage | Surfaced through the stage's `ocr.quality` check |
| **LLM transient retry** (`GEMINI_MAX_ATTEMPTS` ≤ 2) | **One** GenAI operation span covering all attempts (GenAI convention); add `pipeline.retry.count` | If it ultimately fails: stage failed, `error.class=infra` |
| **Timeout** | Stage or operation span with status Error, `error.type=TimeoutError` (or the provider's class), `pipeline.error.class=infra` | Rule R1 → `SERVICE_EXECUTION_FAILURE` |
| **Cancellation** | `error.type=Cancelled`, `pipeline.error.class=infra`, `pipeline.stage.status=failed` | Same as timeout |
| **Gate blocks the flow** | The stage ends `failed`, `error.type=GateBlocked`, `pipeline.error.class=data`, with a `pipeline.check` (`action=blocked`) naming the target artifact | Origin is the producer of the target artifact (could be the same stage) |
| **Gate warns, flow continues** | `pipeline.check` with `result=warn`, `action=continued`; stage `success` | Origin with severity `warn`; downstream consumers become *tainted* |
| **Per-document fan-out** | Stage spans per item (`pipeline.stage.item_id`); run span lists `pipeline.run.items` | Per-instance diagnosis (`03_architecture/24`) |
| **Control dependency** (policy gate) | Manifest `requires`; no span needed for blocked items | Blocked items appear as `not_executed`, caused by the gate stage |
| **Cached replay** (same `config_version`, same checksums) | A run span with `pipeline.run.trigger=cache_hit`, `pipeline.run.outcome` copied, and no stage spans | Execution marked `cache_hit`. No diagnosis (it links to the original run via `pipeline.run.previous_id`) |
| **Re-run of a claim** | New `pipeline.run.id`, `pipeline.run.previous_id`, and a span link to the previous root | UI shows the run history per entity |
| **Async hop / queue** (not in the MVP) | Inject `traceparent` into message headers; the consumer starts a span **linked** to the producer context (messaging convention). Same `pipeline.run.id` | Grouping by run ID works across traces |
| **Threads** | SDK `propagate.submit(executor, fn)` attaches and detaches context | Prevents false parent links |
| **Long human wait** (not in the MVP) | End the run (`outcome=partial`); resumption is a new linked run | |
| **Sampling** | Recommend tail sampling: keep ERROR, keep `pipeline.run.outcome != success`, keep latency > SLO, sample 10% of successes | Incomplete trace → grade B/C; a missing expected stage is flagged, so a sampling gap is never mistaken for a pipeline fault |
| **Clock skew** | — | The core never orders by timestamp; it uses the manifest and lineage |
| **Duplicate delivery** | Exporter retries can resend | Upsert on (trace_id, span_id) (verified idempotent, probe 4) |
| **Attribute truncation** | OTLP `droppedAttributesCount` | Structural warn `attribute_truncated` |
