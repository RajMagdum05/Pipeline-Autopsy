# 40: How a real insurance company adopts Autopsy

## The situation

An insurer already runs its own claims pipeline. It has its own services, a tracing backend (say Jaeger, Tempo or Datadog), probably an OpenTelemetry Collector, and strict data rules. Autopsy must slot in **without** a rebuild, **without** replacing their backend, and **without** access to their databases.

## Options compared

| Criterion | 1. Their SDK exporter → Autopsy OTLP endpoint | 2. **Their Collector adds a second exporter → Autopsy** | 3. Export from their backend → Autopsy | 4. Autopsy SDK instruments stages | 5. **Hybrid: standard OTel + optional SDK helpers** |
|---|---|---|---|---|---|
| Integration effort | Low (env vars) | **Low (about 10 lines of YAML)** | Medium (API scripts per backend) | Medium (code) | Low → medium, gradual |
| Customer code changes | None (if already OTel) | **None** | None | Yes, in stage code | Only where richer evidence is wanted |
| Infra changes | Egress from each service | Collector config | Batch job | None | Collector config |
| Data ownership / control | Per service, bypasses central redaction | **Central: their redaction and sampling apply** | Only what the backend kept | Per service | Central |
| Security | Key in every service | **Key only in the Collector** | Backend credentials needed | Key in services (or via Collector) | Key in the Collector |
| Latency to diagnosis | Seconds | Seconds (+ tail-sampling wait) | Minutes to hours | Seconds | Seconds |
| Reliability if Autopsy is down | SDK queue (2048 spans) drops when full; app unaffected | Exporter queue (1000 batches) retries up to 5 min, then drops; **other exporters unaffected** | Decoupled | Like option 1 | Like option 2 |
| Sampling implications | Head sampling may drop failures | **Tail sampling can keep all errors** | Post-sampling only | Like option 1 | Like option 2 |
| Vendor lock-in | None (OTLP) | None | Backend-specific API | Low (SDK only *adds* attributes; spans are standard) | Low |
| Compatibility | Any OTel language | Any OTel language | Per backend | Python first | Any language for spans; helpers in Python |
| Operational burden | Low | Low | High | Low | Low |
| Diagnosis quality | E0 unless stages are marked | E0 unless stages are marked | E0 | E1/E2 | **E0 → E1 → E2 as they adopt** |

## Recommendation

**Default: option 5, delivered through option 2.**

1. **Day 1 (no code):**
   - Add an `otlphttp/autopsy` exporter to the customer's Collector traces pipeline.
   - Register a manifest that maps their existing span names to stages, using `match` rules on span names (X7.5).
   - Autopsy already gives E0 diagnoses: infra failures, propagation, blocked work, structural gaps.
2. **Week 1 (small code):** add `autopsy-sdk` helpers around their stage functions. They emit `pipeline.stage.*` and artifact IDs. Lineage then becomes exact.
3. **Week 2:** emit existing validation results as `pipeline.check` (E1). Silent failures become visible.
4. **Optional:** allow E2 evidence for selected kinds after a privacy review.

**Fallbacks:**
- Option 1 for teams without a Collector.
- Option 3 for backfill and pilots (G8.2, optional).

**Our own demo** uses option 1 + SDK. The insurance pipeline exports directly to Autopsy and, optionally, to Jaeger as a second exporter. X7.1 adds a Collector profile to demonstrate option 2.

## Example: Collector config the customer adds

```yaml
exporters:
  otlphttp/autopsy:
    endpoint: https://autopsy.example.com          # Autopsy serves /v1/traces
    headers:
      authorization: "Bearer ${env:AUTOPSY_API_KEY}"
    compression: gzip
    sending_queue: {enabled: true, queue_size: 1000}
    retry_on_failure: {enabled: true, max_elapsed_time: 300s}
processors:
  tail_sampling:
    decision_wait: 60s
    policies:
      - {name: errors, type: status_code, status_code: {status_codes: [ERROR]}}
      - {name: failed_runs, type: string_attribute, string_attribute: {key: pipeline.run.outcome, values: [failed, partial, blocked]}}
      - {name: baseline, type: probabilistic, probabilistic: {sampling_percentage: 10}}
  redaction:
    allow_all_keys: true
    blocked_values: ["[0-9]{12,16}", "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+"]   # card/ID numbers, emails
service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, tail_sampling, redaction, batch]
      exporters: [otlp/jaeger, otlphttp/autopsy]      # existing backend + Autopsy
```

The `tail_sampling` and `redaction` processors are in the Collector-contrib distribution. X7.1 verifies this file in a compose profile.

## The four ways of sending telemetry, in plain words

| Phrase | Meaning |
|---|---|
| Instrumenting with OpenTelemetry directly | Your code (or auto-instrumentation) creates spans with the OTel API. Spans exist, but carry no pipeline meaning |
| Using the Autopsy SDK | Thin helpers that create the *same* OTel spans, plus the contract attributes (stage, attempt, item, artifact IDs, checks). No new tracing system |
| Sending telemetry to Autopsy | An OTLP exporter whose endpoint is Autopsy |
| Sending to your backend and routing a copy to Autopsy | One exporter to Jaeger/Tempo, a second to Autopsy, usually configured in the Collector |
