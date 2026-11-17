# 21: Architecture decisions (ADRs)

Format: the options considered, the selected option, why, the trade-offs, and when to revisit. "Now" means the decision applies in the MVP.

---

## ADR-01: How Autopsy receives telemetry

| Option A: OTLP/HTTP push to Autopsy | Option B: pull from the customer's tracing backend (Jaeger/Tempo API) | Option C: file upload of exported traces |
|---|---|---|

**Selected: A now. C for golden-case fixtures. B later, optional.**

**Why A:** OTLP is the vendor-neutral standard. Every OTel SDK and Collector can send it with configuration alone. Autopsy already has a working OTLP route.

**Trade-offs:** Autopsy must be reachable from the customer network (TLS, auth). Pull (B) only sees what the backend kept *after* sampling and retention, and every backend has its own API.

**Revisit:** when a user cannot add an exporter.

---

## ADR-02: Default enterprise integration path

| A: Collector fan-out (second exporter) | B: direct SDK exporter / second `BatchSpanProcessor` | C: backend export |
|---|---|---|

**Selected: A as the documented default. B for the local demo and for teams without a Collector.**

**Why:** with A the customer keeps their existing backend, sampling and redaction, and adds only a few lines of Collector YAML. Autopsy being down affects only Autopsy's exporter queue. See `05_integration/40_integration_options.md`.

**Trade-off:** tail sampling must keep every error trace complete, or Autopsy diagnoses fragments. Autopsy detects incomplete traces and lowers the grade.

---

## ADR-03: What defines causality between stages

| A: span parent/child nesting (today) | B: timestamp order | C: artifact lineage (output ID → input ID) + manifest order + explicit control edges |
|---|---|---|

**Selected: C.**

**Why:** nesting means containment, not data flow, and it produced the wrong answers in probes A and C. Order alone cannot separate independent failures. Lineage is an explicit causal statement made by the producer ("B read X, which A wrote").

**Trade-offs:** producers must pass artifact IDs; the SDK makes this one call. When lineage is missing, the core falls back to manifest order and caps confidence at `possible` (golden case 12).

**Limit, stated honestly:** lineage proves that B *consumed* A's output. It does not prove the value *caused* B's failure. That inference comes from checks and rules (ADR-04), and it is labelled with a confidence level.

---

## ADR-04: RCA method

| A: deterministic rule walk over the lineage graph (reference core) | B: statistical / spectrum ranking across many runs (TraceRCA, MicroRank) | C: LLM or agent decides |
|---|---|---|

**Selected: A now. B as an optional secondary signal later. C never decides.**

**Why:** A is explainable (every finding cites observations), reproducible, and testable in CI. It works on a single run. B needs many runs, including passing ones; in the RCAEval benchmark the best trace method reached AC@1 0.66, which makes it useful as a signal, not a verdict. C: in OpenRCA (ICLR 2025) the best LLM agent solved 11.34%, and a 2026 preprint found symptom-mistaken-for-cause in 39.9% of runs.

**Trade-off:** A only knows the patterns its rules encode. Unknown shapes produce `possible` or `insufficient` rather than wrong answers (enforced by the mutation tests).

---

## ADR-05: Artifacts: identity vs content

| A: Autopsy-owned store, content always uploaded (earlier v2 design) | B: content never leaves the customer; only check results | C: **ID always in spans; content optional by evidence level E0/E1/E2** |
|---|---|---|

**Selected: C.**

**Why:** lineage needs only IDs. Producer checks need no content sharing. Re-validation and grounding *by Autopsy* need content, which an insurer may not allow. C lets one product serve all three cases. For our demo (synthetic data) we use E2.

**Trade-off:** some detectors (contract, consistency) run only at E2. At E0/E1 the core relies on producer checks, and the grade or confidence reflects that.

---

## ADR-06: Trace and finding persistence

| A: PostgreSQL, normalized hot columns + JSONB attributes | B: all JSONB blobs | C: ClickHouse / columnar |
|---|---|---|

**Selected: A.**

**Why:** queries filter by run, stage, status and time, so these must be columns. Attributes vary per span, so they go in JSONB. Postgres is already used and well understood. The volume is thousands of runs per day.

**Trade-off:** beyond millions of spans per day, move raw spans to a columnar store and keep Postgres for findings. This is engineering judgement; no vendor-neutral benchmark exists (see the research summary).

---

## ADR-07: Orchestrating the diagnosis and explanation steps

| A: plain explicit Python functions | B: LangGraph state graph | C: LangChain agent |
|---|---|---|

**Selected: A.**

**Why:** the diagnosis is a fixed linear pipeline. Explanation is a loop with at most two LLM attempts and then a template, which is about 15 lines of Python. Anthropic's guidance ("Building effective agents", Dec 2024) recommends the simplest solution and notes that workflows beat agents for well-defined tasks.

**Cost of B:** a framework dependency, a new mental model for a beginner, and extra serialization, with no capability gained.

**Revisit:** only for the optional investigator (G8.1), and only if a plain bounded tool loop proves insufficient.

**Note:** this revises the earlier project notes, which proposed LangGraph for the whole flow.

---

## ADR-08: Remediation knowledge retrieval

| A: playbooks keyed by `check.id` / `error.type` / classification / stage + Postgres full-text | B: vector DB (pgvector) embeddings | C: none |
|---|---|---|

**Selected: A (MVP+1).**

**Why:** a playbook set of tens of items is exact-match territory. Exact matches are explainable and easy to evaluate.

**Revisit:** at ≥ 200 confirmed cases, when an eval shows misses. Switch the DB image from `pgvector/pgvector` to `postgres:16-alpine` now.

---

## ADR-09: LLM in the first MVP?

| A: no LLM; template explanation | B: LLM explanation, guarded, with template fallback | C: LLM diagnosis |
|---|---|---|

**Selected: A for MVP, B for MVP+1, C never.**

**Why:** the product's value is a correct origin with evidence, and the template already states it. B adds readability, but only after deterministic guardrails exist (G1–G9 in `27_explanation_llm_guardrails.md`).

---

## ADR-10: When diagnosis runs

| A: synchronously inside the ingest request | B: in-process worker + DB job table, triggered when the run span arrives + settle window | C: Celery/Redis/Kafka |
|---|---|---|

**Selected: B.**

**Why:** spans arrive in batches, possibly out of order, so we must wait for completeness. Ingest stays fast. No extra infrastructure. One worker means no locking is needed; add `FOR UPDATE SKIP LOCKED` if more workers are added.

**Revisit C** above roughly 10 runs per second.

---

## ADR-11: SDK shape

| A: thin semantic layer on `opentelemetry-api` (helpers + constants) | B: full custom tracer and exporter (today) | C: no SDK, documentation only |
|---|---|---|

**Selected: A.**

**Why:** A works inside an existing OTel setup: it uses the global provider, spans nest with auto-instrumented HTTP and DB spans, and no vendor lock-in is created. C works but is error-prone; the contract has about 12 rules to remember. B breaks existing setups.

**Trade-off:** applications must configure a provider. `autopsy_sdk.configure()` does it for greenfield apps.

---

## ADR-12: How checks are transported

| A: span events named `pipeline.check` | B: zero-duration child spans with role `check` | C: OTel log records (log-based events) |
|---|---|---|

**Selected: A now. The ingestion normalizer also accepts C later (X7.4).**

**Why:** span events are lightweight, travel with the span (sampling-consistent), already work end to end (probe 3), and the Python SDK supports them today. The 2026 deprecation plan (OTEP 4430) keeps existing span-event data valid and adds log-to-span-event transforms.

**Risk accepted:** watch the Python SDK changelog (issue #4561).

---

## ADR-13: Attribute naming

| A: keep v1 un-namespaced names (`stage.name`, `execution.id`, `input.artifact_ids`) | B: own namespace `pipeline.*` + standard semconv where one exists |
|---|---|

**Selected: B.**

**Why:** OTel guidance is to use a namespace you own and never squat on generic names. Only unused helpers emit v1 today, so the switch costs almost nothing now and much more later. Standard keys are used where they fit: `error.type`, `service.*`, `deployment.environment.name`, `gen_ai.*`, `http.*`.

**Compatibility:** ingestion maps v1 names to v3 (C1.2).

---

## ADR-14: Modelling one claim with several documents

| A: one claim-level stage per step; documents are operations inside it | B: separate trace per document | C: **stage instances per item** (`pipeline.stage.item_id`), manifest `scope: item|run`, control edges via `requires` |
|---|---|---|

**Selected: C.**

**Why:** a bad hospital bill must not implicate the policy or the discharge summary. Policy-gate blocking must appear as "not executed because of the policy", not as a failure. Prototype 8/8 passes (`reference/test_fanout.py`).

**Trade-off:** the core gains an expansion step (about 80 lines). Covered by tests.

---

## ADR-15: Autopsy UI technology

| A: React + Vite + TypeScript, hand-written SVG graph | B: vanilla JS served by FastAPI | C: React + React Flow / Cytoscape |
|---|---|---|

**Selected: A.**

**Why:** it is the same stack you already use in the insurance frontend (one thing to learn). The graph is small (6 stage types × a few documents), laid out deterministically (columns = manifest order, rows = documents), so plain SVG is enough.

**Revisit C** if graphs exceed about 50 nodes or need panning and zooming.

---

## ADR-16: Database migrations (Autopsy)

| A: numbered SQL files applied at startup with a `schema_migrations` table | B: Alembic | C: `create_all()` (today) |
|---|---|---|

**Selected: A.**

**Why:** it is the same pattern as the insurance pipeline (`database/migrations/001–004`), and it is explicit and readable for a beginner. C cannot alter existing tables.

**Revisit B** if migrations become frequent or need autogeneration.

---

## ADR-17: Authentication in the MVP

| A: one static key `AUTOPSY_API_KEY`, required by default | B: per-project keys (existing `credential_service`) |
|---|---|

**Selected: A now, B in X7.2.**

**Do not block B:** keep a `project_id` column on executions (default `"default"`), and resolve the project from the key.

---

## ADR-18: How the insurance claim run executes

| A: one synchronous request runs all stages | B: background job with a status endpoint |
|---|---|

**Selected: A for the MVP**, matching today's behaviour. The trace boundary is the run, not the HTTP request, so B can be added later without contract changes.

---

## ADR-19: Insurance adjudication logic

| A: deterministic, versioned rules over validated facts | B: an LLM decides |
|---|---|

**Selected: A.**

**Why:** business decisions must be explainable and testable (brief section 6). LLMs stay confined to classification and extraction.

---

## ADR-20: Raw trace viewer

| A: Jaeger, optional | B: Arize Phoenix | C: none |
|---|---|---|

**Selected: A, as a compose profile.**

**Why:** it was already configured in the old stack and it is the standard OSS viewer. Autopsy links to it, and it is never on the diagnosis path.
