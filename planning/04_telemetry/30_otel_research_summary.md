# 30: OpenTelemetry and observability research: what applies to us

All sources were accessed on **15 Nov 2026**. Each statement is tagged by type:
- **[STD]** a documented standard, with its stability level.
- **[VENDOR]** a vendor convention.
- **[REC]** our recommendation.

Versions: the semantic-conventions docs reference **semconv v1.45.0**. OTLP spec **1.11.1**. The GenAI conventions moved to a separate repository with no tagged release.

## 1. Data model, limits, status, errors

| Topic | Finding | Applies to us as |
|---|---|---|
| Span parts [STD] | Name, kind, timestamps, attributes, events, links, parent, status; grouped under a Resource (process identity) and an InstrumentationScope | **Run identity goes on spans, not on the Resource.** A Resource describes the process; this is why the old SDK had to build a provider per run |
| Attribute limits [STD] | Defaults: 128 attributes / events / links per span; value length unlimited. Env vars `OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT`, `OTEL_SPAN_*_COUNT_LIMIT`. OTLP carries `dropped*Count` | [REC] Producers set `OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT=4096`. Autopsy turns non-zero dropped counts into a structural observation |
| Status [STD] | `Unset` / `Ok` / `Error` (0/1/2). On failure, set Error plus a low-cardinality `error.type`; the description holds the message when it is not sensitive | [REC] **Primary failure signal = stage `pipeline.stage.status` + span status + `error.type`.** We drop the custom `error.message` attribute and use the status description, truncated and sanitized |
| Exceptions [STD, changing] | The `exception` span event (`exception.type/message/stacktrace`) is now being **deprecated in favour of log-based events** (OTel blog 2026, OTEP 4430). Existing data stays valid | [REC] Ingest span events now; accept log-based events later (X7.4). The SDK records exceptions with sanitized messages |

Sources:
- https://opentelemetry.io/docs/specs/otel/common/
- https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/
- https://opentelemetry.io/docs/specs/otel/trace/api/
- https://opentelemetry.io/docs/specs/otel/trace/exceptions/
- https://opentelemetry.io/blog/2026/deprecating-span-events/
- https://github.com/open-telemetry/opentelemetry-specification/blob/main/oteps/4430-span-event-api-deprecation-plan.md
- https://github.com/open-telemetry/opentelemetry-python/issues/4561

## 2. Context propagation

- [STD] W3C `traceparent` / `tracestate`. The default propagators are `tracecontext,baggage`. Baggage is not added to spans automatically, and it is visible downstream, so **no PII belongs in baggage**.
- [STD/Python] Context lives in `contextvars`. `await` and `asyncio.create_task` keep it. **Raw `ThreadPoolExecutor` threads do not inherit it.** Capture `context.get_current()`, then `attach`/`detach` in the worker. Forgetting `detach` leaks context and creates *false parent links*.
- [REC] The SDK provides `autopsy_sdk.propagate.submit(executor, fn)`. Gemini calls in your pipeline use a semaphore but no thread pool today, so this matters only if parallelism is added. Autopsy flags orphan spans as propagation problems, not pipeline problems.

Sources:
- https://opentelemetry.io/docs/specs/otel/trace/api/
- https://deepwiki.com/open-telemetry/opentelemetry-python/8-context-and-propagation (secondary)

## 3. Parent-child vs links

- [STD] Parent/child = synchronous containment. Links = causal relationships without nesting: batch, fan-in, async hand-off, or a new trace started from an old one.
- Messaging conventions (Development status) link consumers to each message's creation context.
- [REC] Within a claim run, use parent/child (run → stage → operation). Use **links** for re-runs (the new run links to the previous root) and for any future queue hand-off.

Sources:
- https://github.com/open-telemetry/opentelemetry-specification/blob/main/specification/overview.md
- https://opentelemetry.io/docs/specs/semconv/messaging/messaging-spans/

## 4. Semantic-convention stability and naming

| Convention | Status (v1.45.0) | Use |
|---|---|---|
| `service.name`, `service.version` | Stable | Resource |
| `deployment.environment.name` | Stable (replaces `deployment.environment`) | Resource |
| `error.type` | Stable | Failed spans |
| HTTP client/server | Stable since v1.23 | Auto-instrumentation (httpx/requests used by google-genai) |
| DB client core | Stable | Optional SQLAlchemy instrumentation |
| Messaging | Development | Not used in the MVP |
| GenAI | Development, moved repos June 2026 | LLM operation spans |

[STD] New conventions start in Development. `schema_url` identifies the version. Use a namespace you own for custom attributes.
[REC] Our namespace is `pipeline.*`; `autopsy.*` is reserved for SDK internals. Autopsy stores `schema_url` and normalizes known renames.

Sources:
- https://opentelemetry.io/docs/specs/semconv/resource/service/
- https://opentelemetry.io/docs/specs/semconv/registry/attributes/deployment/
- https://opentelemetry.io/docs/specs/semconv/how-to-write-conventions/
- https://github.com/open-telemetry/semantic-conventions/releases

## 5. GenAI conventions (Development, changing fast)

- [STD] Inference span: name `{gen_ai.operation.name} {gen_ai.request.model}`, kind CLIENT.
  - `gen_ai.operation.name`: required. Values include `generate_content` and `chat`.
  - `gen_ai.provider.name`: required; well-known values include `gcp.gemini` and `gcp.vertex_ai`. It replaced `gen_ai.system`.
  - `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.response.finish_reasons`, `gen_ai.usage.input_tokens/output_tokens`, `gen_ai.output.type`.
  - A span covers the logical operation including automatic retries.
- [STD] Prompt and response content capture is **opt-in**. It goes on the span or on the `gen_ai.client.inference.operation.details` log event, or is uploaded externally and referenced.
- [VENDOR] OpenInference (`openinference.span.kind`, `llm.token_count.*`), Langfuse (`langfuse.observation.*`; Cloud became v4-only on 16 Nov 2026), LangSmith (own run tree; not verified).
- [REC]
  - Gemini calls are `operation` spans with the GenAI attributes above.
  - **No prompt or response content in telemetry.** Prompt *version* IDs go in `pipeline.prompt.version`.
  - Use `finish_reasons` as a detector signal: a `max_tokens` finish means truncated JSON, which leads to a validation failure.
  - Autopsy keeps an alias table for `gen_ai.system`, OpenInference and Langfuse names (X7.4).

Sources:
- https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md
- https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/client-inference.md
- https://arize-ai.github.io/openinference/spec/semantic_conventions.html
- https://langfuse.com/integrations/native/opentelemetry

## 6. Retries

- [STD] HTTP: one span per attempt, with `http.request.resend_count`. DB and GenAI: one logical span covers all retries. No generic two-level model exists (semconv issue #4212).
- [REC] Stage retries are represented as separate stage spans with `pipeline.stage.attempt` = 1, 2, …. The core uses the final attempt and records earlier ones as `retried` info. LLM transient retries stay inside one GenAI operation span, as the standard says. "Succeeded after retries" is a degradation, not a failure.

Sources:
- https://opentelemetry.io/docs/specs/semconv/http/http-spans/
- https://github.com/open-telemetry/semantic-conventions/issues/4212

## 7. Fan-out, batch, long-running work

- [STD] Use parent/child for fan-out and links for fan-in and batches.
- [VENDOR] Temporal's OTel plugin emits workflow and activity spans, with deterministic IDs on replay.
- [REC] Model per-document stage instances with `pipeline.stage.item_id` (see `03_architecture/24`). Page-level work is operation spans with `pipeline.item.index/count`. Keep one trace per claim run; a long human-review wait starts a new linked run.

Source: https://docs.temporal.io/develop/python/platform/observability

## 8. Sampling (critical for forensics)

- [STD] Head sampling decides before the outcome is known. Tail sampling (Collector-contrib `tail_sampling`) waits `decision_wait` (default 30 s) and supports `status_code`, latency, attribute and composite policies. It needs all spans of a trace on one Collector instance.
- [REC] Autopsy needs **100% of failed and slow runs plus a baseline of successes**. The recommended policies are: keep `status_code: ERROR`, keep `pipeline.run.outcome != success`, keep latency > SLO, and sample 10% of the rest probabilistically. Set `decision_wait` longer than the longest run. Autopsy detects incomplete traces and grades them down.

Source: https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/processor/tailsamplingprocessor/README.md

## 9. Collector and OTLP transport

- [STD] OTLP/gRPC on 4317. OTLP/HTTP on 4318, paths `/v1/traces`, `/v1/logs` and `/v1/metrics`, encoded as protobuf or JSON.
- [STD] OTLP/JSON specifics: **hex** `traceId`/`spanId`, integer enums, lowerCamelCase keys, 64-bit integers as strings.
- [STD] Partial success: when some spans are rejected, set `partial_success.rejected_spans` and a message; leave it unset on full success.
- [STD] Pipelines are receivers → processors (`memory_limiter` first, then sampling and redaction, then `batch`) → **multiple exporters**. That is how a copy goes to a second backend. Redaction uses the `redaction`, `attributes` and `transform` (OTTL) processors. Auth uses `bearertokenauth` or `headers`.
- [STD] Resiliency: the sending queue (1000 batches by default) retries with exponential backoff (5 s → 30 s, up to 300 s) and drops data when full. A persistent queue (`file_storage`) is alpha.
- [REC] Autopsy's ingest implements protobuf + JSON + gzip + partial_success + 429/503 with `Retry-After`. **It must convert protobuf `MessageToDict` base64 IDs to hex.** This is today's bug.

Sources:
- https://opentelemetry.io/docs/specs/otlp/
- https://opentelemetry.io/docs/collector/resiliency/
- https://github.com/open-telemetry/opentelemetry-collector/blob/main/exporter/exporterhelper/README.md

## 10. Sensitive data

- [STD] "Handling sensitive data" (updated 14 Jan 2026): minimize at the source, and use the Collector as a defence layer (redaction allow-list, hashing).
- [REC]
  - **Never in telemetry:** documents, page images, OCR text, prompts and completions, extracted values, names, policy numbers, claim descriptions.
  - **Allowed:** artifact IDs and hashes, counts, quality metrics, check IDs, field *paths*, rule IDs, enum outcomes, model and prompt versions.
  - Redact in the SDK first, then apply a Collector allow-list as the safety net.

Sources:
- https://opentelemetry.io/docs/security/handling-sensitive-data/
- https://opentelemetry.io/docs/security/config-best-practices/

## 11. Correlation with logs and artifacts

- [STD] Logs carry `trace_id` and `span_id` as hex (the Python logging instrumentation adds `otelTraceID` / `otelSpanID`).
- [REC] Join artifacts by `pipeline.artifact` IDs and `sha256` across runs, so Autopsy can say "this same document failed in N runs".

Source: https://opentelemetry.io/docs/specs/otel/compatibility/logging_trace_context/

## 12. Retention and storage

- [VENDOR] Tempo's `block_retention` defaults to 14 days.
- [REC] Autopsy keeps raw spans 30 days, evidence 14 days, and findings long-term (`03_architecture/25`). The Postgres hot-columns + JSONB vs columnar choice is engineering judgement; no vendor-neutral benchmark was found.

Source: https://grafana.com/docs/tempo/latest/configuration/

## 13. How platforms present traces

- [VENDOR] Jaeger: waterfall, trace graph, critical-path highlighting. Phoenix: span-kind icons and agent graphs. Langfuse: nested typed observations with input/output panes. Honeycomb, Datadog and Grafana were not verified.
- [REC] Our UI differs on purpose. Its *primary* view is a **stage lineage graph coloured by RCA role**, plus evidence. The waterfall is secondary (link out to Jaeger).

Sources:
- https://www.jaegertracing.io/docs/2.dev/deployment/frontend-ui/
- https://arize.com/docs/ax/concepts/otel-openinference/span-kinds

## 14. RCA research and the limits of LLMs

- Dapper (Google, 2010): aggressive sampling, about 1 in 1024. It was designed for latency debugging, not forensics.
- MicroRank (WWW '21) and TraceRCA (IWQoS '21): spectrum methods that need normal and abnormal traces. RCAEval (2025): TraceRCA AC@1 0.66 on Train-Ticket RE2; methods are generally "moderate".
- OpenRCA (ICLR 2025): the best LLM agent solved **11.34%**. A 2026 preprint (arXiv:2602.09937, not peer reviewed) found 3.9–12.5% fully-correct runs, hallucinated interpretation in 71.2%, and **symptom-mistaken-for-cause in 39.9%**.
- [REC] Deterministic RCA decides. A spectrum comparison across runs can come later as a secondary signal. An LLM only narrates.

Sources:
- https://dl.acm.org/doi/10.1145/3442381.3449905
- https://arxiv.org/pdf/2412.17015
- https://hyper.ai/en/papers/iclr__2025__M4qNIzQYpd
- https://www.usenix.org/system/files/atc22-zhang-zhizhou.pdf

## 15. Integration patterns

See `05_integration/40_integration_options.md`. The research recommends the Collector second exporter as the default, with a direct exporter as fallback and backend pull for backfill.

Source: https://langfuse.com/faq/all/existing-otel-setup

## 16. Python SDK specifics

- [STD] The application owns the `TracerProvider` and can add several span processors; each receives every span. BatchSpanProcessor defaults: queue 2048, batch 512, 5 s delay, 30 s timeout. Exporter config via `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS` and `OTEL_EXPORTER_OTLP_PROTOCOL`.
- [STD] Libraries depend only on `opentelemetry-api` and call `trace.get_tracer(__name__)`. They never set the global provider.
- [REC] `autopsy-sdk` follows the library rule. Its optional `configure()` *adds* a processor to an existing provider and warns instead of overriding.

Source: https://opentelemetry-python.readthedocs.io/en/latest/sdk/environment_variables.html

## 17. Agents vs workflows

- Anthropic, "Building effective agents" (Dec 2024): workflows (predefined code paths) suit well-defined tasks; start with the simplest solution.
- [REC] Use a plain Python pipeline. No LangGraph in the MVP (ADR-07). No vector DB (ADR-08).

## Rapidly changing items to watch

- Span events → log events.
- GenAI attribute names (no stable release yet).
- Collector persistent-queue maturity.
- Langfuse v4 cutover (16 Nov 2026).
