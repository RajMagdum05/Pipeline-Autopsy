# 31: Trace contract v3 (`pipeline-trace/3`)

This file is the source for `shared-docs/TRACE_CONTRACT.md` (task C1.1).

- **Standards first.** Where an OpenTelemetry semantic convention fits, we use it.
- **Custom attributes are namespaced** under `pipeline.*`. They are needed because OTel defines no pipeline-stage, artifact-lineage or check semantics.
- **`autopsy.*`** is reserved for SDK internals.

## 1. Shape of one run

```
run span            pipeline.span.role=execution   (one per run; root of the trace)
 ├─ stage span      pipeline.span.role=stage       (one per stage attempt; per item if item-scoped)
 │   ├─ operation   pipeline.span.role=operation   (LLM call, OCR page, DB write, HTTP …; any depth)
 │   └─ events      pipeline.check                 (zero or more, on stage or operation spans)
 └─ stage span …
```

## 2. Field table

**Location key:** R = resource · S = span attribute · E = span event · L = span link · St = span status · A = artifact store · DB = producer business DB

### Identity and grouping

| Field | Loc | Type | Req | Producer | Why Autopsy needs it | Sensitive? | Limits |
|---|---|---|---|---|---|---|---|
| `service.name` [semconv] | R | string | **req** | app | Which deployable emitted the span | no | low cardinality |
| `service.version` [semconv] | R | string | rec | app | Correlate regressions with builds | no | |
| `deployment.environment.name` [semconv] | R | string | rec | app | Separate dev, staging and prod baselines | no | `development`/`staging`/`production`/`test` |
| `pipeline.name` | S (all) | string | **req** | SDK | Selects the manifest | no | `[a-z0-9-]+`, ≤ 64 |
| `pipeline.version` | S (all) | string | **req** | SDK | Selects the manifest version | no | semver |
| `pipeline.run.id` | S (all) | string | **req** | SDK | Groups spans into one run, even across traces | no | UUID/ULID; new per run |
| `pipeline.entity.id` | S (all) | string | opt | app | Groups runs of one business object | **must be opaque** (UUID, not a policy number or name) | ≤ 64 |
| `pipeline.span.role` | S (all) | enum | **req** | SDK | Separates run / stage / operation | no | `execution`, `stage`, `operation` |
| trace_id / span_id / parent_span_id | OTLP | hex | **req** | OTel | Containment, roll-up | no | 32/16 hex |

### Run span only

| Field | Loc | Type | Req | Why | Values |
|---|---|---|---|---|---|
| `pipeline.run.items` | S | string[] | req if any item-scoped stage | Knows documents that never started (blocked) | `"<item_id>:<role>"` |
| `pipeline.run.trigger` | S | enum | opt | Explains cached replays and re-runs | `api`, `rerun`, `cache_hit`, `test` |
| `pipeline.run.outcome` | S | enum | **req** at end | Tail-sampling key; run summary | `success`, `failed`, `partial`, `blocked` |
| `pipeline.run.previous_id` | S + L | string + link | opt | Links a re-run to its predecessor | |

### Stage span

| Field | Loc | Type | Req | Why Autopsy needs it | Values / limits |
|---|---|---|---|---|---|
| `pipeline.stage.name` | S | string | **req** | Must exist in the manifest | snake_case |
| `pipeline.stage.status` | S | enum | **req**, set once on exit | The outcome even when OTel status is OK (silent failures) | `success`, `failed`, `partial`, `skipped` |
| `pipeline.stage.attempt` | S | int | **req** | Final attempt decides; earlier ones = `retried` | ≥ 1 |
| `pipeline.stage.item_id` | S | string | req if scope=item | Per-document diagnosis | opaque ID |
| `pipeline.stage.item_role` | S | string | rec | Control edges (policy gate) | e.g. `policy`, `proof` |
| `pipeline.stage.version` | S | string | opt | E.g. validator, prompt bundle or rules version | |
| `pipeline.artifact.input_ids` | S | string[] | **req** (may be empty) | **Lineage: what this stage read** | ≤ 64 ids |
| `pipeline.artifact.output_ids` | S | string[] | **req** (may be empty) | **Lineage: what this stage wrote** | ≤ 64 ids |
| span status | St | Error/Ok | req when failed | Standard failure flag | description = sanitized message ≤ 500 chars |
| `error.type` [semconv] | S | string | req when failed | Low-cardinality failure kind | exception class or stable code |
| `pipeline.error.class` | S | enum | req when failed | Separates independent infra faults from data-caused failures (RCA R1 vs R3/R8) | `infra`, `data`, `unknown` |

### Operation spans (examples)

| Field | Loc | Req | Why | Notes |
|---|---|---|---|---|
| `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.response.finish_reasons`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.output.type` [semconv, Development] | S | rec for LLM calls | Model identity, truncation (`max_tokens`), cost | `gcp.gemini`, `generate_content`, `json` |
| `pipeline.prompt.id`, `pipeline.prompt.version` | S | rec for LLM calls | Which prompt template version | e.g. `classification_v1`, `document-extraction-v2` |
| `pipeline.schema.id`, `pipeline.schema.version` | S | rec | Which output schema | e.g. `document-facts-v1` |
| `pipeline.item.index`, `pipeline.item.count` | S | opt | Page fan-out inside a stage | |
| `http.*`, `db.*` [semconv] | S | auto | Infra evidence | from auto-instrumentation |

### Checks (event `pipeline.check`)

| Field | Type | Req | Why | Limits |
|---|---|---|---|---|
| `pipeline.check.id` | string | **req** | Stable identity; playbook key | e.g. `ocr.quality`, `classification.matches_declared`, `extraction.quote_support`, `rule.coverage_period` |
| `pipeline.check.kind` | enum | **req** | Type of evidence. **`decision_rule` = business outcome (e.g. not covered): context only, never treated as a fault** | `schema`, `threshold`, `rule`, `grounding`, `classification`, `safety`, `decision_rule` |
| `pipeline.check.result` | enum | **req** | | `pass`, `warn`, `fail`, `skip` |
| `pipeline.check.action` | enum | **req** | Did the gate stop the flow? | `blocked`, `continued`, `review` |
| `pipeline.check.target_artifact_id` | string | rec | **Which artifact is bad.** It may be an *input*; the producer of that input is then implicated | |
| `pipeline.check.field` | string | opt | Field-level trace-back | **path only**, e.g. `facts.admission_date` |
| `pipeline.check.observed` | string | opt | Short evidence | ≤ 64 chars, **numbers, enums or codes only, never document text** |
| `pipeline.check.expected` | string | opt | | ≤ 64 chars |
| `pipeline.check.rule_version` | string | opt | | |

Only `warn` and `fail` checks are needed for diagnosis. `pass` checks are optional, but they help: they show coverage, and the core uses passes for trace-back.

### Artifacts (never in spans except as IDs)

| Field | Where | Notes |
|---|---|---|
| `artifact_id` | spans (lists), checks | `"art_" + sha256(run_id ‖ 0x00 ‖ kind ‖ 0x00 ‖ item_id ‖ 0x00 ‖ canonical_bytes)[:16]` (hex) |
| canonical bytes | — | dict/list → `json.dumps(sort_keys=True, ensure_ascii=False, separators=(",",":")).encode()`; str → UTF-8; bytes as is |
| `kind`, `content_type`, `size_bytes`, `sha256` (full content hash), `stage`, `item_id`, `schema` | A | Uploaded only at evidence level E2 |

**Why `run_id` + `kind` + `item_id` are in the hash:** the earlier pretest found that identical payloads (`{"decision":"approved"}`) from two stages collided and broke lineage. Including the item also prevents two identical blank pages in different documents from colliding.

## 3. Naming, cardinality and versioning rules

1. Keys are lowercase dot-separated; enum values are lowercase snake_case.
2. **No high-cardinality free text in attribute values used for grouping** (`check.id`, `error.type`, `stage.name`). IDs (run, entity, item, artifact) are high-cardinality by design. They are fine as attributes, but must not be metric labels.
3. The contract version is announced by the SDK as `autopsy.schema.version = "pipeline-trace/3"` on the run span.
4. **Compatibility:**
   - Adding an optional field is a minor change.
   - Renaming or removing a field, or changing an enum, is a major change.
   - Autopsy accepts the current major version plus a v1 alias map.
5. **v1 → v3 aliases accepted by Autopsy ingestion** (C1.2):

| v1 | v3 |
|---|---|
| `execution.id` | `pipeline.run.id` |
| `execution.entity_id` | `pipeline.entity.id` |
| `stage.name` | `pipeline.stage.name` |
| `stage.status` | `pipeline.stage.status` |
| `input.artifact_ids` | `pipeline.artifact.input_ids` |
| `output.artifact_ids` | `pipeline.artifact.output_ids` |
| `autopsy.role` | `pipeline.span.role` |
| `stage.attempt` | `pipeline.stage.attempt` |
| `error.class` | `pipeline.error.class` |
| event `autopsy.check` (with `check.*`) | event `pipeline.check` (with `pipeline.check.*`) |

## 4. Validation behaviour (what Autopsy does with violations)

| Violation | Effect |
|---|---|
| No run span, more than one run span, a cycle, or a stage span without name/status | Grade **C**, verdict `INSUFFICIENT_EVIDENCE`, structural observations listed |
| Orphan span, missing attempt or ID lists, invalid status value, unknown stage, referenced artifact missing (E2), lineage gap, span ERROR but stage success, expected stage missing with no explanation | Grade **B**, confidence capped at `possible` |
| Attribute truncated (dropped counts > 0) | Structural `warn` |
| PII pattern in an attribute value | Value masked before storage, structural `warn pii_in_span` |
| Unknown `pipeline.name` (no manifest registered) | Stored, execution `unregistered`, no diagnosis |

## 5. Example (one stage span, as OTLP/JSON)

```json
{"traceId":"4bf92f3577b34da6a3ce929d0e0e4736","spanId":"00f067aa0ba902b7","parentSpanId":"a2fb4a1d1a96d312",
 "name":"information_extraction","kind":1,"startTimeUnixNano":"1794700000000000000","endTimeUnixNano":"1794700004200000000",
 "status":{"code":2,"message":"Extraction validation failed"},
 "attributes":[
  {"key":"pipeline.name","value":{"stringValue":"insurance-claims"}},
  {"key":"pipeline.version","value":{"stringValue":"2.0.0"}},
  {"key":"pipeline.run.id","value":{"stringValue":"0193f1c2-…"}},
  {"key":"pipeline.entity.id","value":{"stringValue":"6f0e…"}},
  {"key":"pipeline.span.role","value":{"stringValue":"stage"}},
  {"key":"pipeline.stage.name","value":{"stringValue":"information_extraction"}},
  {"key":"pipeline.stage.status","value":{"stringValue":"failed"}},
  {"key":"pipeline.stage.attempt","value":{"intValue":"1"}},
  {"key":"pipeline.stage.item_id","value":{"stringValue":"bill-7c1e…"}},
  {"key":"pipeline.stage.item_role","value":{"stringValue":"proof"}},
  {"key":"pipeline.artifact.input_ids","value":{"arrayValue":{"values":[{"stringValue":"art_1a2b3c4d5e6f7a8b"},{"stringValue":"art_9c8d7e6f5a4b3c2d"}]}}},
  {"key":"pipeline.artifact.output_ids","value":{"arrayValue":{"values":[{"stringValue":"art_0f1e2d3c4b5a6978"}]}}},
  {"key":"error.type","value":{"stringValue":"ExtractionValidationFailed"}},
  {"key":"pipeline.error.class","value":{"stringValue":"data"}}],
 "events":[{"name":"pipeline.check","timeUnixNano":"1794700004100000000","attributes":[
  {"key":"pipeline.check.id","value":{"stringValue":"extraction.quote_support"}},
  {"key":"pipeline.check.kind","value":{"stringValue":"grounding"}},
  {"key":"pipeline.check.result","value":{"stringValue":"fail"}},
  {"key":"pipeline.check.action","value":{"stringValue":"review"}},
  {"key":"pipeline.check.target_artifact_id","value":{"stringValue":"art_0f1e2d3c4b5a6978"}},
  {"key":"pipeline.check.field","value":{"stringValue":"facts.total"}}]}]}
```
