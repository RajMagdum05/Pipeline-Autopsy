# 20: Target architecture

## 1. Picture

```
 ┌──────────────────────────── PRODUCER (insurance-pipeline, or any customer pipeline) ───────────────────────────┐
 │  FastAPI app ── claim run orchestrator                                                                          │
 │     per document:  document_processing → content_classification → information_extraction → extraction_validation│
 │     per claim:     adjudication → final_result                                                                  │
 │        │ calls                                                                                                  │
 │        ▼                                                                                                        │
 │  autopsy-sdk (semantic layer, opentelemetry-api only)                                                           │
 │     run()  stage()  operation()  record_artifact()  check()                                                     │
 │        │ spans (standard OTel)                    │ optional redacted evidence (E2)                            │
 │  OpenTelemetry SDK: TracerProvider + BatchSpanProcessor + OTLP exporter(s)   (owned by the application)         │
 └────────┼──────────────────────────────────────────┼────────────────────────────────────────────────────────────┘
          │ OTLP/HTTP (protobuf)                     │ HTTPS POST /v1/artifacts
          │   option A: via customer's OTel Collector (fan-out: Jaeger/Tempo + Autopsy)   ← recommended for enterprises
          │   option B: direct exporter to Autopsy (+ optional 2nd exporter to Jaeger)   ← our local demo
          ▼                                          ▼
 ┌──────────────────────────────────────── AUTOPSY (modular monolith, port 8080) ─────────────────────────────────┐
 │ api/ingest   POST /v1/traces  (auth, size limits, ID validation, PII scan, partial_success)                      │
 │              POST /v1/artifacts  PUT /v1/pipelines/{name}/versions/{v}                                          │
 │        │                                                                                                        │
 │ PostgreSQL: executions, spans, artifacts(meta), manifests, jobs, observations, findings, explanations, feedback  │
 │ Disk volume: evidence blobs                                                                                     │
 │        │  worker (one asyncio task in-process; job runs after the run span arrives + 5 s settle)               │
 │        ▼                                                                                                        │
 │ core/  (PURE: no DB, no network, no LLM, no clock)                                                              │
 │   normalize → validate_trace (grade A/B/C) → expand fan-out → build stages + lineage                          │
 │   → detectors (execution, check, contract, consistency, structural) → trace_back → RCA rules → verdict          │
 │        │                                                                                                        │
 │ explain/  evidence bundle → template text  (MVP)                                                                │
 │           → [MVP+1] LLM draft → deterministic guardrails → retry once → else template                           │
 │ knowledge/ playbooks keyed by check id / error.type / classification (MVP+1)                                    │
 │        │                                                                                                        │
 │ api/read  GET /v1/executions, /{id}, /{id}/graph, /{id}/diagnosis; POST feedback                               │
 │ ui/       React app served at /ui  (run list, run page with lineage graph + evidence)                          │
 └────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
          ▲ optional deep link "Open in Jaeger"                       ▲ insurance UI shows "Open in Autopsy" link
```

## 2. The key ideas, in plain words

1. **Failure travels through data, not through function calls.** Every stage records the IDs of the artifacts it read and wrote. Autopsy connects "stage A wrote X" to "stage B read X" and gets a data-flow map called the **lineage graph**. Span parent/child links are used only to roll small operations up into their stage.
2. **Producers already know a lot. Let them say it.** Your pipeline already runs quality gates, quote verification and validation checks. Each becomes a `pipeline.check` event on the span: check id, result, which artifact and which field. These are Autopsy's best evidence, and they reveal problems that never raised an exception.
3. **Identity is not content.** An artifact ID is a hash, so it can always travel in the span. The artifact's *content* (OCR text, extracted facts) is private by default. It reaches Autopsy only if the customer opts in to evidence level E2, after redaction. Diagnosis works at every level; confidence drops when less is shared.
4. **Deterministic first.** The verdict comes from fixed rules in a pure function that is tested by golden cases. The LLM may later *describe* the verdict. It can never change it.
5. **Abstain honestly.** When the trace is too poor, the answer is `INSUFFICIENT_EVIDENCE`, or the confidence is capped at `possible`.

## 3. Why a modular monolith (for both systems)

| Option | Verdict |
|---|---|
| Modular monolith: one FastAPI process per system, clear packages, an in-process worker | **Selected.** One deployable unit, simple local dev, enough for thousands of runs per day |
| Microservices (ingest, worker, API, UI as separate services) | Rejected for now: network boundaries, more deployment work, no load that needs it |
| Serverless functions | Rejected: a long-lived worker and a local DB are simpler |

The *package* boundaries (`ingest`, `core`, `worker`, `explain`, `api`) are drawn so that any one of them can be split out later.

## 4. Repository layout after the plan

```
Pipeline_Autopsy/
├── CLAUDE.md                      standing rules for Fable
├── docker-compose.yml             includes both stacks, one network
├── .github/workflows/ci.yml
├── planning/                      this pack
├── shared-docs/
│   ├── TRACE_CONTRACT.md          v3
│   ├── MANIFEST_SPEC.md
│   └── manifests/insurance-claims.yaml, toy-summarizer.yaml
├── autopsy-sdk/                   moved from pipeline-autopsy/packages
│   ├── autopsy_sdk/  tests/  pyproject.toml
├── insurance-pipeline/            (was insurance-pipeline-new)
│   ├── backend/app/{claim_document_intake,document_processing,information_extraction,
│   │               extraction_validation,adjudication,final_result,orchestrator,observability,faults}
│   ├── database/migrations/  frontend/  docker-compose.yml
├── pipeline-autopsy/
│   ├── autopsy/{core,ingest,artifacts,manifests,worker,explain,knowledge,api,db}/  main.py
│   ├── ui/                        React app (Vite); built output served at /ui
│   ├── packs/insurance/           optional validators + playbooks
│   ├── playbooks/                 generic playbooks
│   ├── examples/toy_pipeline/
│   ├── evals/{golden/,run_l1.py,run_l2.py}
│   └── tests/{core,unit,integration,e2e}
└── archive/insurance-pipeline-v1/ (optional; or rely on git history)
```

Notes on the layout:

- `observability/` in the insurance backend is where the OpenTelemetry provider is bootstrapped. Stage code uses the SDK and never touches `observability/` directly.
- The old `adjudication/` naming replaces `rule_engine_decision/`, which is a stub today. Rename it in B4.1.
