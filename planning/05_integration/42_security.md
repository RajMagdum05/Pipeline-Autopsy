# 42: Security and enterprise integration (first version)

| Concern | MVP (local demo) | Next version (X7.2 / X7.3) | Must not block later |
|---|---|---|---|
| Authentication | One static key, `AUTOPSY_API_KEY`, **required by default**. Accepted as `Authorization: Bearer` or `x-autopsy-api-key`. Today's `AUTOPSY_REQUIRE_API_KEY=false` default is removed | Per-project keys, reusing the frozen `credential_service.py` (hashed keys, prefix lookup) | Every table has `project_id`; the key resolves to a project |
| Credential rotation | Restart with a new env value | Two active keys per project, revoke endpoint, `last_used_at` | Keys are compared as hashes, never logged |
| TLS | Not used (localhost) | Terminate TLS at a reverse proxy (Caddy/Nginx) or a platform load balancer | Autopsy only binds HTTP behind a proxy |
| Tenant isolation | Single project `default` | Every query filtered by `project_id`; tests prove cross-project reads return 404 | Same as above |
| Artifact read authorization | Requires the API key | Project-scoped. Optional per-kind "visible in UI" flag | `artifacts.project_id` |
| Data minimization / redaction | Contract forbids content attributes; SDK masks messages; ingestion PII scan masks values and records `pii_in_span`; E2 kinds allow-listed per manifest | Collector `redaction` processor in the documented config | — |
| Rate limits | — | Token bucket per key (simple in-process), `429` + `Retry-After` | Exporters already back off on 429/503 |
| Payload limits | Body 10 MB (413), artifact 5 MB (413), ≤ 4 KB per attribute value (truncate + structural warn) | Configurable per project | — |
| Auditability | Request log line: key prefix, route, status, span counts. Never bodies or keys | Audit table for key and manifest changes and deletions | — |
| Retention and deletion | Defaults documented; `DELETE /v1/executions/{id}` | Daily retention job: spans 30 d, evidence 14 d or the manifest value, findings 1 y | `expires_at` columns |
| Customer-controlled routing and egress | Customer chooses Collector fan-out vs direct; the evidence level is chosen by the customer in the manifest *and* capped by the producer env (`AUTOPSY_EVIDENCE_LEVEL`) | — | Autopsy never initiates connections to the customer |
| Autopsy unavailable | The producer is unaffected: SDK upload is non-blocking and drops after bounded retries; OTel exporter queues drop when full | Collector persistent queue (alpha) is optional | Spans are best-effort; diagnosis of affected runs shows grade B/C |
| Unauthenticated internal routes (today) | **Deleted** in A2.6 | — | — |
| Secrets in the repo | `.env` git-ignored at the root and in each service; keys only in env | Secret manager when deployed | — |
| Prompt injection via documents | The explanation step has no tools; evidence is delimited; guardrails G4–G6 (MVP+1) | — | — |
