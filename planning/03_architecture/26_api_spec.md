# 26: Autopsy HTTP API (target)

All routes require `Authorization: Bearer <AUTOPSY_API_KEY>`. The header `x-autopsy-api-key` is also accepted. Exceptions: `/health` and the static files under `/ui/*`. The UI calls the API through the same origin, using the key from its configuration. A proper login for the MVP UI is out of scope; the stack is local.

## Ingest

| Method | Path | Body | Success | Errors |
|---|---|---|---|---|
| POST | `/v1/traces` | OTLP `ExportTraceServiceRequest` (`application/x-protobuf` or `application/json`, optional `Content-Encoding: gzip`) | `200` + OTLP `ExportTraceServiceResponse` (protobuf or JSON to match the request). `partial_success{rejected_spans, error_message}` is set only when some spans were rejected | 400 malformed · 401 · 413 > 10 MB · 415 · 503 + `Retry-After` |
| POST | `/v1/artifacts` | `{id, execution_id, pipeline, version, stage, item_id, kind, content_type, content \| content_b64, redacted, redaction}` | `201` created, `200` duplicate | 403 kind not allowed at this evidence level · 413 > 5 MB · 422 ID mismatch (checked only when `redacted=false`) or bad ID format |
| PUT | `/v1/pipelines/{name}/versions/{version}` | manifest YAML or JSON | `200` | 422 `{problems:[...]}` with every issue |
| GET | `/v1/pipelines` | — | list | |

## Read

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/executions?pipeline=&verdict=&entity_id=&limit=50&cursor=` | Newest first: id, entity, pipeline, version, started_at, verdict, grade, origin stage(s) |
| GET | `/v1/executions/{id}` | Status, timings, grade, verdict, trace ids, Jaeger link if configured |
| GET | `/v1/executions/{id}/graph` | `{nodes:[{id:"stage@item", stage, item_id, item_role, role, status, attempts}], edges:[{from,to,kind,artifact_ids,type:"data"|"control",tainted}]}` |
| GET | `/v1/executions/{id}/diagnosis` | Verdict, grade, findings, observations, explanation. `409 {status}` if not diagnosed yet |
| GET | `/v1/executions/{id}/spans` | Normalized spans (for the evidence pane / raw view) |
| GET | `/v1/artifacts/{id}` | Metadata + masked content (E2 only) |
| POST | `/v1/executions/{id}/diagnose` | Re-queue the diagnosis |
| POST | `/v1/findings/{id}/feedback` | `{verdict: confirmed\|rejected, comment}` (MVP+1) |
| DELETE | `/v1/executions/{id}` | Delete the run's spans, evidence and findings |
| GET | `/health` | `{db: ok, worker: alive, queue_depth}` |

## Example: `GET /v1/executions/{id}/diagnosis`

```json
{
  "execution_id": "7f3c…", "pipeline": "insurance-claims", "version": "2.0.0", "entity_id": "c0a1…",
  "verdict": "ROOT_CAUSE_IDENTIFIED", "trace_grade": "A",
  "findings": [
    {"id": "f_01", "stage": "document_processing", "item_id": "bill-uuid", "role": "origin",
     "classification": "OUTPUT_CONTRACT_VIOLATION", "confidence": "supported", "severity": "warn",
     "link": null, "caused_by": [], "evidence": ["obs_004"], "note": null, "seen_before": 0},
    {"id": "f_05", "stage": "adjudication", "item_id": null, "role": "propagated",
     "classification": "INVALID_UPSTREAM_INPUT", "confidence": "supported", "severity": "fail",
     "link": "strong", "caused_by": ["extraction_validation@bill-uuid"], "evidence": ["obs_009"]}
  ],
  "observations": [
    {"id": "obs_004", "family": "check", "code": "ocr.quality", "result": "warn",
     "stage": "document_processing@bill-uuid", "span_id": "a1b2c3d4e5f60718",
     "artifact_id": "art_9f2c…", "field": null,
     "detail": "observed='low_confidence_ratio=0.62' expected='<=0.5'"}
  ],
  "explanation": {"source": "template", "summary": "…", "narrative": [], "remediation": []}
}
```

## Routes deleted in A2.6

- `/v1/traces/v1/traces`
- `/v1/traces/{id}/reconstruction`, `/failures`, `/root-cause`, `/diagnose`, `/investigate`
- `/v1/executions/{id}/investigate`
- `/api/v1/dashboard` and `/api/v1/executions/*`
