# 25: Autopsy data model (PostgreSQL)

**Migrations:** numbered SQL files in `pipeline-autopsy/autopsy/db/migrations/NNN_*.sql`, applied at startup and recorded in `schema_migrations` (ADR-16). Tests may use SQLite only when `AUTOPSY_DATABASE_URL` explicitly says `sqlite`. Use the generic SQLAlchemy `JSON` type, which becomes JSONB on Postgres via a variant.

```
schema_migrations   version PK · applied_at

projects            id PK ('default') · name · created_at                 -- reserved for X7.2; one row in MVP
pipelines           (project_id, name, version) PK · manifest JSON · evidence_level (E0|E1|E2)
                    · evidence_kinds_allowed JSON · retention_days · registered_at
executions          id PK (= pipeline.run.id) · project_id · pipeline · version · entity_id
                    · trace_ids JSON · status (receiving|queued|diagnosed|failed|unregistered)
                    · verdict · trace_grade · run_outcome · started_at · ended_at · diagnosed_at
                    · previous_execution_id                                  IDX(pipeline, started_at), IDX(entity_id)
spans               (trace_id, span_id) PK · execution_id IDX · parent_span_id · name · kind
                    · role (execution|stage|operation|other) · stage_name · item_id · attempt
                    · status (UNSET|OK|ERROR) · status_message · error_type · error_class
                    · start_time · end_time · attrs JSON · events JSON · links JSON
                    · resource JSON · dropped_attributes · dropped_events
artifacts           id PK · execution_id IDX · stage · item_id · kind · content_type · size_bytes
                    · sha256 · blob_path · redacted BOOL · created_at · expires_at
diagnosis_jobs      execution_id PK · status (pending|running|done|failed) · reason (complete|timeout|manual)
                    · run_after · attempt · error · updated_at
observations        (execution_id, id) PK · family · code · result · stage · span_id · artifact_id
                    · field · reported_by · error_class · source_artifact_id · detail
findings            id PK · execution_id IDX · stage · item_id · role · classification · confidence
                    · severity · link · caused_by JSON · evidence JSON · note · signature
explanations        execution_id PK · source (template|llm) · summary · narrative JSON · remediation JSON
                    · guardrail_log JSON · model · tokens_in · tokens_out · latency_ms
playbooks           id PK · title · match JSON · body · pack                              (MVP+1)
feedback            id PK · finding_id · verdict (confirmed|rejected) · comment · created_at  (MVP+1)
```

## Why these columns

| Column | Reason |
|---|---|
| `spans.role`, `stage_name`, `item_id`, `attempt`, `status`, `error_class` as columns | The worker and the UI filter on them; they are cheap to index |
| `spans.attrs` / `events` / `links` as JSON | They vary per span; kept so the core sees exactly what the producer sent |
| `dropped_attributes`, `dropped_events` | OTLP reports SDK truncation; Autopsy surfaces it as a structural observation |
| `executions.trace_ids` | One run may span several traces (async hops) |
| `findings.signature` | `sha1(pipeline, origin stage *type*, classification, sorted evidence codes)[:12]`, used for "seen before" |

## Retention (MVP defaults, configurable)

| Data | Default | Why |
|---|---|---|
| Spans | 30 days | Autopsy is not the long-term trace store |
| Evidence artifacts | 14 days, or `retention_days` per pipeline | They may contain sensitive data |
| Observations, findings, explanations, feedback | Kept (1 year in X7.3) | Small, and they are the product's value |

Retention jobs are built in X7.3. In the MVP, document the defaults and provide a manual `DELETE /v1/executions/{id}`.

## What is dropped from today's schema

`autopsy_failures`, `autopsy_evidence`, `autopsy_incidents` and `autopsy_traces` are replaced. `autopsy_projects` / `autopsy_api_keys` are kept frozen for X7.2. The migration creates the new tables beside the old ones. Old tables are removed in A2.6 after the read API moves over.
